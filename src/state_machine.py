import json
import os
from pathlib import Path
import datetime
import uuid
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "database.json")
BLACKLIST_PATH = str(Path(__file__).resolve().parent.parent / "data" / "blacklisted_batches.json")

# Ogni punto di lettura impone un'azione e lo stato obiettivo che la lettura tenta di assegnare.
READ_POINT_RULES: dict[str, tuple[str, str]] = {
    "PACKAGING_LINE":  ("PACK",  "PACKED"),
    "SMART_TRUCK":     ("LOAD",  "DISTRIBUTING"),
    "SMART_CABINET":   ("STORE", "STORED"),
    "DESK":            ("SELL",  "DISPENSED"),
    "WASTE_CONTAINER": ("THROW", "DISPOSED"),
}

# Stati raggiungibili a partire da ciascuno stato corrente (fonte di verità per le transizioni
# guidate dai PUNTI DI LETTURA, cioè process_read). Lo smaltimento (DISPOSED) è sempre lecito.
# Due transizioni NON passano dai punti di lettura e quindi non compaiono qui:
#   STORED -> AWAITING_CHECKOUT  (uscita dall'armadio, gestita da process_removal)
#   AWAITING_CHECKOUT -> MISSING (grace period scaduto, gestita da reconcile_pending_checkouts)
# AWAITING_CHECKOUT e MISSING possono tornare a STORED (rimessi in armadio) o essere venduti.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "PACKED":            {"DISTRIBUTING", "DISPOSED"},
    "DISTRIBUTING":      {"STORED", "DISPOSED"},
    "STORED":            {"DISPENSED", "DISPOSED"},
    "AWAITING_CHECKOUT": {"STORED", "DISPENSED", "DISPOSED"},
    "MISSING":           {"STORED", "DISPENSED", "DISPOSED"},
    "DISPENSED":         {"DISPOSED"},
    "DISPOSED":          set(),
}

# Tempo concesso tra l'uscita dall'armadio (AWAITING_CHECKOUT) e il passaggio in cassa, oltre il
# quale l'articolo viene considerato un ammanco (MISSING). Tiene conto del fatto che dal prelievo
# alla cassa trascorre del tempo: evita falsi allarmi sulle vendite regolari.
CHECKOUT_GRACE_SECONDS = 60


class StateMachine:
    """
    Gestisce lo stato del ciclo di vita dei farmaci (Asset) e mantiene lo storico degli eventi.
    Agisce come un database in memoria sincronizzato su un file JSON.
    """
    def __init__(self) -> None:
        self.assets: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.serial_counter: int = 1
        self.simulated_date: Optional[str] = None
        self.blacklisted_batches: set[str] = set()
        self.load_db()
        self.load_blacklist()

    def load_blacklist(self) -> None:
        if not os.path.exists(BLACKLIST_PATH):
            self.blacklisted_batches = set()
            return
        try:
            with open(BLACKLIST_PATH, "r") as f:
                data = json.load(f)
                self.blacklisted_batches = set(data.get("blacklisted_batches", []))
        except Exception as e:
            logger.error(f"Errore nel caricamento della blacklist: {e}")
            self.blacklisted_batches = set()

    def save_blacklist(self) -> None:
        try:
            os.makedirs(os.path.dirname(BLACKLIST_PATH), exist_ok=True)
            with open(BLACKLIST_PATH, "w") as f:
                json.dump({
                    "blacklisted_batches": list(self.blacklisted_batches)
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Errore nel salvataggio della blacklist: {e}")

    def set_simulation_settings(self, date_str: Optional[str], batches: list[str]) -> None:
        self.simulated_date = date_str if date_str else None
        self.blacklisted_batches = set(batches)
        self.save_blacklist()

    def load_db(self) -> None:
        if not os.path.exists(DB_PATH):
            self.assets = {}
            self.events = []
            return

        try:
            with open(DB_PATH, "r") as f:
                data = json.load(f)
                self.assets = data.get("assets", {})
                self.events = data.get("events", [])
                self.serial_counter = data.get("serialCounter", 1)
        except Exception as e:
            logger.error(f"Errore nel caricamento del database: {e}")
            self.assets = {}
            self.events = []
            self.serial_counter = 1

    def save_db(self) -> None:
        try:
            # Assicura che la cartella 'data' esista prima di salvare
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            with open(DB_PATH, "w") as f:
                json.dump({
                    "assets": self.assets,
                    "events": self.events,
                    "serialCounter": self.serial_counter
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Errore nel salvataggio del database: {e}")

    def get_asset(self, epc: str) -> Optional[dict[str, Any]]:
        # Cerca prima per EPC primario (quello nuovo commissionato)
        asset = self.assets.get(epc)
        if asset:
            return asset

        # Fallback: cerca se questo EPC è l'oldEpc di qualche asset.
        # Questo accade se la scrittura fisica sul tag RFID è fallita ma il db ha registrato il nuovo EPC.
        for a in self.assets.values():
            if a.get("oldEpc") == epc:
                return a

        return None

    def process_read(self, epc: str, read_point: str, tid: Optional[str] = None) -> dict[str, Any]:
        """
        Logica centrale della macchina a stati. Valuta una lettura applicando, nell'ordine:
        controlli di qualità (scadenza/lotto ritirato), re-letture idempotenti, blocco della
        vendita al DESK e la tabella delle transizioni consentite (ALLOWED_TRANSITIONS).

        Ritorna sempre un dizionario {'status': 'OK'|'ALERT', 'message': str, 'asset': dict|None}.
        """
        asset = self.get_asset(epc)
        logger.debug(f"Processing read for EPC {epc} at {read_point}. Asset found: {bool(asset)}")

        if not asset:
            return self._result("ALERT", f"Asset sconosciuto ({epc}). Forse un tag non commissionato?", None)

        rule = READ_POINT_RULES.get(read_point)
        if rule is None:
            return self._result("ALERT", f"Punto di lettura non gestito: {read_point}.", asset)
        action, target = rule

        current = asset.get("currentState")
        quality_alerts = self._quality_alerts(asset)

        # Autenticità: l'EPC deve corrispondere al TID (read-only di fabbrica) legato in
        # commissioning. Se è stato riletto un TID e non combacia, l'EPC è stato clonato su un
        # altro chip. Si comporta come gli altri alert di qualità: blocca la vendita al DESK.
        if tid and asset.get("tid") and tid != asset.get("tid"):
            quality_alerts.append("TAG NON AUTENTICO: TID non corrisponde (possibile EPC clonato)")

        # (1) Re-lettura confermativa: l'asset è già nello stato che questo punto imporrebbe.
        #     Nessuna transizione e nessun evento registrato: gli eventuali alert di qualità
        #     vengono solo mostrati a video, per non intasare lo storico durante il polling.
        if target == current:
            message = " | ".join(quality_alerts) if quality_alerts else "Lettura confermata (stato invariato)."
            return self._result("ALERT" if quality_alerts else "OK", message, asset)

        # (2) Verifica se la lettura va BLOCCATA (stato invariato) e perché.
        block_reason = None
        if read_point == "DESK" and quality_alerts:
            # Blocco vendita: non si dispensa un farmaco scaduto o di un lotto ritirato.
            block_reason = "VENDITA BLOCCATA: farmaco non vendibile"
        elif target not in ALLOWED_TRANSITIONS.get(current, set()):
            # Transizione non prevista dal ciclo di vita (passaggio saltato, ritorno indietro,
            # asset già smaltito, vendita senza passare per lo Smart Cabinet, ...).
            block_reason = f"Transizione non consentita: {current} -> {target}"

        if block_reason:
            alerts = quality_alerts + [block_reason]
            # Lo stato NON cambia; l'evento viene registrato come semplice READ con la motivazione.
            self._apply(asset, epc, read_point, "READ", current, alerts)
            return self._result("ALERT", " | ".join(alerts), asset)

        # (3) Transizione valida: applica azione e nuovo stato.
        self._apply(asset, epc, read_point, action, target, quality_alerts)
        message = " | ".join(quality_alerts) if quality_alerts else "Transizione corretta."
        return self._result("ALERT" if quality_alerts else "OK", message, asset)

    def commission_asset(self, epc, gtin, batch, expiry_date, aic, old_epc=None, tid=None):
        """
        Commissioning: crea l'asset con i metadati GS1 e ne registra la nascita.
        L'evento viene loggato come azione PACK (stato PACKED), coerente con la linea.
        Il TID (identificativo read-only di fabbrica del chip) viene legato all'EPC: servirà a
        verificare in seguito che il tag sia autentico e che l'EPC non sia stato clonato.
        """
        new_asset = {
            "epc": epc,
            "gtin": gtin,
            "batch": batch,
            "expiryDate": expiry_date,
            "aic": aic,
            "serialNumber": self.serial_counter,
            "currentState": "PACKED",
            "lastUpdate": self._now(),
            "oldEpc": old_epc,
            "tid": tid
        }
        self.assets[epc] = new_asset
        self.serial_counter += 1
        self._apply(new_asset, epc, "PACKAGING_LINE", "PACK", "PACKED", [])
        return self._result("OK", "Asset commissionato e registrato su RFID fisico.", new_asset)

    def process_removal(self, epc: str, read_point: str) -> Optional[dict[str, Any]]:
        """
        Valuta la SCOMPARSA di un tag dal campo dello Smart Cabinet. A differenza di
        process_read, qui l'evento è "il tag non c'è più".

        Uscire dall'armadio NON è (ancora) un furto: tra il prelievo e la cassa passa del
        tempo. Quindi un articolo STORED che sparisce passa allo stato transitorio
        AWAITING_CHECKOUT ("uscito, in attesa di cassa"), senza allarme. Sarà
        reconcile_pending_checkouts() a promuoverlo ad ammanco (MISSING) se non passa in
        cassa entro il grace period. Se l'articolo è già DISPENSED, il prelievo è legittimo.
        """
        asset = self.get_asset(epc)
        if not asset:
            return None

        current = asset.get("currentState")
        if current == "STORED":
            self._apply(asset, epc, read_point, "REMOVE", "AWAITING_CHECKOUT", [])
            return self._result("OK", "Articolo uscito dall'armadio, in attesa di cassa.", asset)

        return self._result("OK", "Articolo prelevato dall'armadio.", asset)

    def reconcile_pending_checkouts(self, grace_seconds: int = CHECKOUT_GRACE_SECONDS) -> list[dict[str, Any]]:
        """
        Promuove ad ammanco (MISSING) gli articoli usciti dall'armadio (AWAITING_CHECKOUT) che
        non sono passati in cassa entro grace_seconds. Va richiamata periodicamente (dal loop
        dello Smart Cabinet). Ritorna i risultati dei soli articoli appena segnalati.
        """
        results = []
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        for epc, asset in list(self.assets.items()):
            if asset.get("currentState") != "AWAITING_CHECKOUT":
                continue
            removed_at = self._parse_ts(asset.get("lastUpdate"))
            if removed_at is None:
                continue
            if (now - removed_at).total_seconds() >= grace_seconds:
                alerts = ["AMMANCO: uscito dall'armadio senza passare per la cassa"]
                self._apply(asset, epc, "SMART_CABINET", "REMOVE", "MISSING", alerts)
                results.append(self._result("ALERT", alerts[0], asset))
        return results

    def _apply(self, asset: dict[str, Any], epc: str, read_point: str,
               action: str, new_state: str, alerts: list[str]) -> None:
        """
        Punto unico in cui l'esito di una lettura diventa persistente: aggiorna lo stato
        dell'asset, registra l'evento nello storico e salva su disco. È usato sia da
        process_read sia da commission_asset, così il logging resta una responsabilità
        della StateMachine (e non viene duplicato nei chiamatori).

        Anti-flood: non registra un evento identico all'ultimo già presente per lo stesso
        EPC. Durante il polling continuo, una lettura bloccata ripetuta non riempie lo storico.
        """
        if self._is_duplicate_event(epc, read_point, action, new_state, alerts):
            return
        asset["currentState"] = new_state
        asset["lastUpdate"] = self._now()
        self.assets[epc] = asset
        self._log_event(epc, read_point, action, new_state, alerts)
        self.save_db()

    def _is_duplicate_event(self, epc: str, read_point: str, action: str,
                            new_state: str, alerts: list[str]) -> bool:
        """True se l'ultimo evento registrato per questo EPC è identico a quello in arrivo."""
        for event in reversed(self.events):
            if event.get("epc") == epc:
                return (event.get("readPoint") == read_point
                        and event.get("action") == action
                        and event.get("newState") == new_state
                        and event.get("alerts") == alerts)
        return False

    def _quality_alerts(self, asset: dict[str, Any]) -> list[str]:
        """Alert di qualità validi a qualsiasi punto di lettura: scadenza e lotto ritirato."""
        alerts = []
        if self._is_expired(asset.get("expiryDate")):
            alerts.append("FARMACO SCADUTO!")
        if asset.get("batch") in self.blacklisted_batches:
            alerts.append("LOTTO RITIRATO!")
        return alerts

    @staticmethod
    def _result(status: str, message: str, asset: Optional[dict[str, Any]]) -> dict[str, Any]:
        return {"status": status, "message": message, "asset": asset}

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    @staticmethod
    def _parse_ts(ts: Optional[str]) -> Optional[datetime.datetime]:
        """Converte un timestamp prodotto da _now() (ISO + 'Z') in datetime naive UTC."""
        if not ts:
            return None
        try:
            return datetime.datetime.fromisoformat(ts[:-1] if ts.endswith("Z") else ts)
        except ValueError:
            return None

    def set_serial_counter(self, offset):
        try:
            self.serial_counter = int(offset)
            self.save_db()
        except ValueError:
            pass

    def reset(self) -> None:
        """
        Azzera il database della simulazione: cancella tutti gli asset e lo storico eventi e
        riporta il contatore seriale a 1. Le impostazioni di simulazione (data simulata e lotti
        in blacklist) NON vengono toccate.
        """
        self.assets = {}
        self.events = []
        self.serial_counter = 1
        self.save_db()
        logger.info("Database della simulazione azzerato.")

    def _log_event(self, epc, read_point, action, new_state, alerts):
        event = {
            "eventId": str(uuid.uuid4()),
            "epc": epc,
            "timestamp": self._now(),
            "readPoint": read_point,
            "action": action,
            "newState": new_state,
            "alerts": alerts
        }
        self.events.append(event)

    def _is_expired(self, expiry_date_str):
        if not expiry_date_str:
            return False
        try:
            expiry_date = datetime.datetime.strptime(expiry_date_str, "%Y-%m-%d")

            if self.simulated_date:
                current_eval_date = datetime.datetime.strptime(self.simulated_date, "%Y-%m-%d")
            else:
                current_eval_date = datetime.datetime.now()

            return current_eval_date > expiry_date
        except:
            return False

    def get_kpis(self) -> dict[str, int]:
        """Calcola e restituisce i KPI attuali del sistema."""
        assets_list = self.assets.values()
        return {
            "total_assets": len(assets_list),
            "packed": sum(1 for a in assets_list if a.get("currentState") == "PACKED"),
            "distributing": sum(1 for a in assets_list if a.get("currentState") == "DISTRIBUTING"),
            "in_cabinet": sum(1 for a in assets_list if a.get("currentState") == "STORED"),
            "awaiting_checkout": sum(1 for a in assets_list if a.get("currentState") == "AWAITING_CHECKOUT"),
            "missing": sum(1 for a in assets_list if a.get("currentState") == "MISSING"),
            "dispensed": sum(1 for a in assets_list if a.get("currentState") == "DISPENSED"),
            "disposed": sum(1 for a in assets_list if a.get("currentState") == "DISPOSED"),
            "expired": sum(1 for a in assets_list if self._is_expired(a.get("expiryDate")))
        }

    def get_epcs_by_batch(self, batch_name: str) -> set[str]:
        """Restituisce un set con tutti gli EPC appartenenti a un determinato lotto, inclusi i vecchi EPC se presenti."""
        epcs = set()
        for epc, asset in self.assets.items():
            if asset.get("batch") == batch_name:
                epcs.add(epc)
                if asset.get("oldEpc"):
                    epcs.add(asset.get("oldEpc"))
        return epcs
