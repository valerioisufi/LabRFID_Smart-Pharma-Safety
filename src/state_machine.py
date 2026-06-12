import json
import os
from pathlib import Path
import datetime
import uuid
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "database.json")

class StateMachine:
    """
    Gestisce lo stato del ciclo di vita dei farmaci (Asset) e mantiene lo storico degli eventi.
    Agisce come un database in memoria sincronizzato su un file JSON.
    """
    def __init__(self) -> None:
        self.assets: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.serial_counter: int = 1
        self.load_db()

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
        return self.assets.get(epc)

    def process_read(self, epc: str, read_point: str) -> dict[str, Any]:
        """
        Logica centrale della Macchina a Stati. Valuta la lettura e applica le regole di business.
        Ritorna un dizionario con: {'status': 'OK'/'ALERT', 'message': '...', 'asset': asset_dict}
        """
        asset = self.get_asset(epc)
        
        if not asset:
            return {
                "status": "ALERT",
                "message": f"Asset sconosciuto ({epc}). Forse un tag non commissionato?",
                "asset": None
            }

        # Il farmaco esiste. Verifico le regole di validità (es. scadenza o ritiri).
        current_state = asset.get("currentState")
        is_expired = self._is_expired(asset.get("expiryDate"))
        is_blacklisted = asset.get("batch") == "B-BLACKLISTED" # Regola mock per simulare un lotto ritirato
        
        alert_msgs = []
        if is_expired:
            alert_msgs.append("FARMACO SCADUTO!")
        if is_blacklisted:
            alert_msgs.append("LOTTO RITIRATO (BLACKLIST)!")

        # Determina il nuovo stato logico in base al punto in cui è avvenuta la lettura fisica
        new_state = current_state
        action = "READ"

        if read_point == "PACKAGING_LINE":
            new_state = "PACKED"
            action = "COMMISSIONING"
            
        elif read_point == "SMART_TRUCK":
            new_state = "IN_TRANSIT"
            action = "DISTRIBUTE"
            if current_state not in ["PACKED", "IN_CABINET"]:
                alert_msgs.append("Transizione anomala: Camion senza imballaggio.")
                
        elif read_point == "SMART_CABINET":
            new_state = "IN_CABINET"
            action = "STORE"
            if current_state not in ["IN_TRANSIT", "PACKED", "IN_CABINET"]:
                alert_msgs.append("Transizione anomala: Arrivato in armadio senza transito.")

        elif read_point == "DESK":
            new_state = "DISPENSED"
            action = "DISPENSE"
            if current_state != "IN_CABINET":
                alert_msgs.append("ATTENZIONE: Prelevato senza passare per lo Smart Cabinet!")
                
        elif read_point == "WASTE_CONTAINER":
            new_state = "DISPOSED"
            action = "DISPOSE"

        # Update asset
        asset["currentState"] = new_state
        asset["lastUpdate"] = datetime.datetime.utcnow().isoformat() + "Z"
        self.assets[epc] = asset
        
        # Log event
        self._log_event(epc, read_point, action, new_state, alert_msgs)
        self.save_db()

        status = "ALERT" if alert_msgs else "OK"
        message = " | ".join(alert_msgs) if alert_msgs else "Transizione corretta."

        return {
            "status": status,
            "message": message,
            "asset": asset
        }

    def set_serial_counter(self, offset):
        try:
            self.serial_counter = int(offset)
            self.save_db()
        except ValueError:
            pass

    def commission_asset(self, epc, gtin, batch, expiry_date, aic, old_epc=None):
        """Official Commissioning with SGTIN-96 encoding and GS1 metadata."""
        new_asset = {
            "epc": epc,
            "gtin": gtin,
            "batch": batch,
            "expiryDate": expiry_date,
            "aic": aic,
            "serialNumber": self.serial_counter,
            "currentState": "PACKED",
            "lastUpdate": datetime.datetime.utcnow().isoformat() + "Z",
            "oldEpc": old_epc
        }
        
        self.assets[epc] = new_asset
        self.serial_counter += 1
        self._log_event(epc, "PACKAGING_LINE", "COMMISSIONING", "PACKED", [])
        self.save_db()
        return {
            "status": "OK",
            "message": "Asset commissionato e registrato su RFID fisico.",
            "asset": new_asset
        }

    def _log_event(self, epc, read_point, action, new_state, alert_msgs):
        event = {
            "eventId": str(uuid.uuid4()),
            "epc": epc,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "readPoint": read_point,
            "action": action,
            "newState": new_state,
            "alerts": alert_msgs
        }
        self.events.append(event)

    def _is_expired(self, expiry_date_str):
        if not expiry_date_str:
            return False
        try:
            expiry_date = datetime.datetime.strptime(expiry_date_str, "%Y-%m-%d")
            return datetime.datetime.now() > expiry_date
        except:
            return False
