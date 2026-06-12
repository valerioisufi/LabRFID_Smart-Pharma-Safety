import asyncio
from typing import Any, Optional, Callable, Dict, Union, Tuple
from src.state_machine import StateMachine
from src.reader_module import ReaderManager
from src.epc_encoder import encode_dsgtin128

class Middleware:
    """
    Motore degli Eventi (Middleware) / App Controller.
    Agisce da ponte tra l'hardware (ReaderManager) e la logica di business (StateMachine).
    Gestisce anche le logiche di batch e monitoraggio.
    """
    def __init__(self, port: str = "COM3") -> None:
        self.state_machine: StateMachine = StateMachine()
        self.reader_manager: ReaderManager = ReaderManager(port=port)
        
        self.current_read_point: str = "PACKAGING_LINE"
        self.is_monitoring: bool = False
        self.periodic_task: Optional[asyncio.Task[Any]] = None
        self.active_batch_config: Optional[Dict[str, Any]] = None
        self.processed_in_batch: set[str] = set()
        
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
        if self.reader_manager.is_connected:
            self.reader_manager.configure_for_read_point(self.current_read_point)
        self._trigger_state_update()

    def start_monitoring(self):
        if not self.reader_manager.is_connected:
            return False
            
        self.is_monitoring = True
        self.reader_manager.configure_for_read_point(self.current_read_point)
        
        if self.current_read_point in ["SMART_TRUCK", "SMART_CABINET"]:
            if self.main_loop:
                self.periodic_task = self.main_loop.create_task(self._periodic_scan_loop())
        else:
            self.reader_manager.start_async_reading(self._handle_async_read)
            
        self._trigger_state_update()
        return True

    def stop_monitoring(self):
        self.is_monitoring = False
        self.reader_manager.stop_async_reading()
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
        self.reader_manager.stop_async_reading()
        # Force polling mode (00) for continuous safe write
        self.reader_manager.reader.set_current_mode(mode="00")
        
        if self.main_loop:
            self.periodic_task = self.main_loop.create_task(self._periodic_scan_loop())
            
        self._trigger_state_update()
        return True
        
    def stop_batch(self):
        self.active_batch_config = None
        self.is_monitoring = False
        self._trigger_state_update()

    async def _periodic_scan_loop(self):
        while self.is_monitoring:
            if self.current_read_point == "PACKAGING_LINE" and self.active_batch_config:
                raw_tags = self.reader_manager.read_tags()
                if raw_tags:
                    for tag in raw_tags:
                        if tag in self.processed_in_batch:
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
                        
                        retcode = self.reader_manager.reader.write_memory(
                            epc=tag, data=new_epc_hex, mem_bank="01", address="02", block_num="08", timeout_ms=1000
                        )
                        if retcode == "00":
                            self.processed_in_batch.add(tag)
                            self.processed_in_batch.add(new_epc_hex)
                            
                            res = self.state_machine.commission_asset(
                                epc=new_epc_hex, gtin=self.active_batch_config.get("gtin"),
                                batch=self.active_batch_config.get("batch"), expiry_date=self.active_batch_config.get("expiry"),
                                aic=self.active_batch_config.get("aic"), old_epc=tag
                            )
                            if self.on_scan_results:
                                self.on_scan_results([res])
                            self._trigger_state_update()
                await asyncio.sleep(0.5)
            elif self.current_read_point in ["SMART_TRUCK", "SMART_CABINET"]:
                raw_tags = self.reader_manager.read_tags()
                if raw_tags:
                    results = self.process_reads(raw_tags, self.current_read_point)
                    if self.on_scan_results:
                        self.on_scan_results(results)
                    self._trigger_state_update()
                await asyncio.sleep(3)
            else:
                break

    def _handle_async_read(self, tag_payload: Union[str, Tuple[str, Any]]):
        epc = tag_payload[0] if isinstance(tag_payload, tuple) else tag_payload
        if self.main_loop and self.main_loop.is_running():
            self.main_loop.call_soon_threadsafe(
                lambda: self.main_loop.create_task(self._process_and_broadcast_async_read(epc))
            )

    async def _process_and_broadcast_async_read(self, epc: str):
        results = self.process_reads([epc], self.current_read_point)
        if self.on_scan_results:
            self.on_scan_results(results)
        self._trigger_state_update()

    def process_reads(self, raw_epc_list: list[str], read_point: str) -> list[dict[str, Any]]:
        unique_epcs = list(set(raw_epc_list))
        results = []
        for epc in unique_epcs:
            result = self.state_machine.process_read(epc, read_point)
            results.append(result)
        return results

    def get_all_events(self) -> list[dict[str, Any]]:
        self.state_machine.load_db()
        return self.state_machine.events

    def get_kpis(self) -> dict[str, int]:
        return self.state_machine.get_kpis()

    def _trigger_state_update(self):
        if self.on_state_update:
            self.on_state_update()

    def trigger_external_event(self, event_type: str) -> str:
        # todo da sistemare
        if event_type == "SIMULATE_MIDNIGHT":
            asset = self.state_machine.get_asset("PHARMA-0001")
            if asset:
                asset["expiryDate"] = "2020-01-01"
                self.state_machine.save_db()
                self._trigger_state_update()
                return "Midnight simulated: PHARMA-0001 is now expired."
        elif event_type == "WITHDRAW_LOT":
            for key, asset in self.state_machine.assets.items():
                if asset["batch"] == "B-NEW":
                    asset["batch"] = "B-BLACKLISTED"
            self.state_machine.save_db()
            self._trigger_state_update()
            return "Lot withdrawal simulated: B-NEW is now blacklisted."
        return "Unknown event."
