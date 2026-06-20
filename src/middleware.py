import asyncio
from functools import partial
from typing import Any, Optional, Callable, Dict, Union, Tuple
from src.state_machine import StateMachine
from src.reader_module import ReaderManager
from src.epc_encoder import encode_dsgtin128
import logging

logger = logging.getLogger(__name__)

class Middleware:
    """
    Motore degli Eventi (Middleware) / App Controller.
    Agisce da ponte tra l'hardware (ReaderManager) e la logica di business (StateMachine).
    Gestisce anche le logiche di batch e monitoraggio.
    """

    # Smart Cabinet: ogni quanti secondi rifare l'inventario e dopo quante scansioni
    # consecutive senza vedere un tag dichiararlo "prelevato" (debounce anti-falsi positivi,
    # perché una lettura RFID può saltare un tag presente).
    CABINET_POLL_SECONDS = 2
    CABINET_ABSENT_THRESHOLD = 2

    def __init__(self, port: str = "") -> None:
        self.state_machine: StateMachine = StateMachine()
        self.reader_manager: ReaderManager = ReaderManager(port=port)
        
        self.current_read_point: str = "PACKAGING_LINE"
        self.is_monitoring: bool = False
        self.periodic_task: Optional[asyncio.Task[Any]] = None
        self.active_batch_config: Optional[Dict[str, Any]] = None
        self.processed_in_batch: set[str] = set()
        # Smart Cabinet: presenza dei tag tra una scansione e l'altra (EPC -> n. scansioni mancate)
        self.cabinet_presence: dict[str, int] = {}

        # Callbacks for web UI communication
        self.on_state_update: Optional[Callable[[], None]] = None
        self.on_scan_results: Optional[Callable[[list[dict[str, Any]]], None]] = None
        
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_connected(self) -> bool:
        return self.reader_manager.is_connected

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.main_loop = loop

    def connect(self, port: str) -> bool:
        if self.reader_manager.is_connected:
            self.stop_monitoring()
            self.reader_manager.disconnect()
        self.reader_manager.port = port
        success = self.reader_manager.connect()
        self._trigger_state_update()
        return success

    def disconnect(self):
        self.stop_monitoring()
        self.reader_manager.disconnect()
        self._trigger_state_update()

    def set_read_point(self, read_point: str):
        self.current_read_point = read_point
        self.stop_monitoring()
        self.active_batch_config = None
        self.cabinet_presence = {}
        if self.reader_manager.is_connected:
            self.reader_manager.configure_for_read_point(self.current_read_point)
        self._trigger_state_update()

    def start_monitoring(self):
        if not self.reader_manager.is_connected:
            return False
            
        self.is_monitoring = True
        self.cabinet_presence = {}
        self.reader_manager.configure_for_read_point(self.current_read_point)

        # Use Python Software Polling for ALL contexts
        if self.main_loop:
            self.periodic_task = self.main_loop.create_task(self._periodic_scan_loop())
            
        self._trigger_state_update()
        return True

    def stop_monitoring(self):
        self.is_monitoring = False
        # Cancella il task di scansione per evitare loop sovrapposti con start/stop ravvicinati.
        # Se a chiamare è il loop stesso (es. il ramo DESK che si auto-ferma) non lo si cancella,
        # perché sta già uscendo da solo con un break.
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        task = self.periodic_task
        if task and not task.done() and task is not current:
            task.cancel()
            self.periodic_task = None
        self._trigger_state_update()

    def start_batch(self, data: dict):
        if not self.reader_manager.is_connected:
            return False
            
        self.active_batch_config = data
        offset = data.get("serial_offset")
        if offset:
            self.state_machine.set_serial_counter(offset)
            
        batch_name = data.get("batch")
        self.processed_in_batch = self.state_machine.get_epcs_by_batch(batch_name) if batch_name else set()
        
        self.is_monitoring = True
        
        if self.main_loop:
            self.periodic_task = self.main_loop.create_task(self._periodic_scan_loop())
            
        self._trigger_state_update()
        return True
        
    def stop_batch(self):
        self.active_batch_config = None
        self.is_monitoring = False
        self._trigger_state_update()

    def reset_simulation(self) -> None:
        """Ferma il monitoraggio e azzera il database (asset + eventi), riportando l'app pulita."""
        self.stop_monitoring()
        self.active_batch_config = None
        self.processed_in_batch = set()
        self.cabinet_presence = {}
        self.state_machine.reset()
        self._trigger_state_update()

    async def _run_blocking(self, func, *args, **kwargs):
        """
        Esegue una chiamata seriale bloccante (inventory, scrittura, beep) in un thread
        separato, così l'event loop resta libero di servire WebSocket e richieste HTTP.
        Le operazioni vengono comunque eseguite una alla volta (sono tutte await-ate in
        sequenza nel loop di scansione), quindi la porta seriale non viene mai usata in
        concorrenza.
        """
        loop = self.main_loop or asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def _periodic_scan_loop(self):
        while self.is_monitoring:
            if self.current_read_point == "PACKAGING_LINE" and self.active_batch_config:
                raw_tags = await self._run_blocking(self.reader_manager.read_tags)
                if raw_tags:
                    for tag in raw_tags:
                        logger.debug(f"Scanned EPC: {tag}")
                        if tag in self.processed_in_batch:
                            logger.debug(f"Tag {tag} already processed in this batch, skipping.")
                            continue
                            
                        asset = self.state_machine.get_asset(tag)
                        if asset and asset.get("batch") == self.active_batch_config.get("batch"):
                            self.processed_in_batch.add(tag)
                            continue
                            
                        serial = self.state_machine.serial_counter
                        new_epc_hex = encode_dsgtin128(
                            self.active_batch_config.get("gtin", ""),
                            serial,
                            self.active_batch_config.get("expiry"),
                        )
                        
                        retcode = await self._run_blocking(
                            self.reader_manager.reader.write_memory,
                            epc=tag, data=new_epc_hex, mem_bank="01", address="02", block_num="08", timeout_ms=1000
                        )
                        await self._run_blocking(self.reader_manager.reader.beep)
                        logger.info(f"Attempting to write new EPC {new_epc_hex} to tag {tag}, write response: {retcode}")

                        if retcode == "00":
                            self.processed_in_batch.add(tag)
                            self.processed_in_batch.add(new_epc_hex)

                            # Legge il TID (read-only di fabbrica) e lo lega all'EPC appena scritto.
                            tid = await self._run_blocking(self.reader_manager.read_tid, new_epc_hex)
                            res = self.state_machine.commission_asset(
                                epc=new_epc_hex, gtin=self.active_batch_config.get("gtin"),
                                batch=self.active_batch_config.get("batch"), expiry_date=self.active_batch_config.get("expiry"),
                                aic=self.active_batch_config.get("aic"), old_epc=tag, tid=tid
                            )
                            if self.on_scan_results:
                                self.on_scan_results([res])
                            self._trigger_state_update()
                await asyncio.sleep(0.5)
            
            elif self.current_read_point == "SMART_CABINET":
                # Lo Smart Cabinet monitora la PRESENZA: confronta l'inventario corrente con
                # quello precedente per accorgersi sia dei nuovi arrivi sia dei prelievi.
                seen = set(await self._run_blocking(self.reader_manager.read_tags))
                results = []

                # Nuovi arrivi: processati una sola volta (immagazzinamento -> STORED).
                for epc in seen:
                    if epc not in self.cabinet_presence:
                        # Nuovo arrivo: rilegge il TID per verificare l'autenticità del tag.
                        tid = await self._run_blocking(self.reader_manager.read_tid, epc)
                        results.append(self.state_machine.process_read(epc, "SMART_CABINET", tid=tid))
                    self.cabinet_presence[epc] = 0

                # Prelievi: un tag sparito per CABINET_ABSENT_THRESHOLD scansioni è stato rimosso.
                for epc in list(self.cabinet_presence):
                    if epc in seen:
                        continue
                    self.cabinet_presence[epc] += 1
                    if self.cabinet_presence[epc] >= self.CABINET_ABSENT_THRESHOLD:
                        del self.cabinet_presence[epc]
                        res = self.state_machine.process_removal(epc, "SMART_CABINET")
                        if res:
                            results.append(res)

                # Riconciliazione: gli articoli usciti dall'armadio e non passati in cassa
                # entro il grace period diventano ammanchi (MISSING).
                results.extend(self.state_machine.reconcile_pending_checkouts())

                if results:
                    if self.on_scan_results:
                        self.on_scan_results(results)
                    self._trigger_state_update()
                await asyncio.sleep(self.CABINET_POLL_SECONDS)
            
            elif self.current_read_point == "DESK":
                raw_tags = await self._run_blocking(self.reader_manager.read_tags)
                if raw_tags:
                    # Prima della vendita si verifica l'autenticità: per ogni tag si rilegge il TID.
                    results = []
                    for epc in set(raw_tags):
                        tid = await self._run_blocking(self.reader_manager.read_tid, epc)
                        results.append(self.state_machine.process_read(epc, "DESK", tid=tid))
                    if self.on_scan_results:
                        self.on_scan_results(results)
                    self._trigger_state_update()
                    # Feedback visivo dell'esito sul lettore: rosso se c'è un alert, verde se ok.
                    has_alert = any(r["status"] == "ALERT" for r in results)
                    await self._run_blocking(
                        self.reader_manager.reader.set_led,
                        red_status="FF" if has_alert else "00",
                        green_status="00" if has_alert else "FF",
                    )
                    # Desk reads only ON DEMAND and stops after one successful read event.
                    self.stop_monitoring()
                    break
                await asyncio.sleep(1) # Fast poll until tag is placed
            
            elif self.current_read_point == "SMART_TRUCK" or self.current_read_point == "WASTE_CONTAINER":
                raw_tags = await self._run_blocking(self.reader_manager.read_tags)
                if raw_tags:
                    results = self.process_reads(raw_tags, self.current_read_point)
                    if self.on_scan_results:
                        self.on_scan_results(results)
                    self._trigger_state_update()
                await asyncio.sleep(1)
            else:
                break

    def process_reads(self, raw_epc_list: list[str], read_point: str) -> list[dict[str, Any]]:
        unique_epcs = list(set(raw_epc_list))
        results = []
        for epc in unique_epcs:
            result = self.state_machine.process_read(epc, read_point)
            results.append(result)
        return results

    def get_all_events(self) -> list[dict[str, Any]]:
        # Gli eventi sono già in memoria e sempre aggiornati: non serve rileggere il DB da disco
        # (lo si faceva a ogni broadcast WebSocket, con spreco e rischio di race con save_db).
        return self.state_machine.events

    def get_kpis(self) -> dict[str, int]:
        return self.state_machine.get_kpis()

    def _trigger_state_update(self):
        if self.on_state_update:
            self.on_state_update()

    def set_simulation_settings(self, date_str: Optional[str], batches_str: str) -> None:
        batches = [b.strip() for b in batches_str.split(',')] if batches_str.strip() else []
        self.state_machine.set_simulation_settings(date_str, batches)
        self._trigger_state_update()
