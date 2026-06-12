import logging
import threading
from typing import Optional, Callable

from src.tertium_serial_handler import TertiumReader

logger = logging.getLogger(__name__)

class ReaderManager:
    """Livello di astrazione hardware (HAL) che gestisce la connessione con il lettore RFID."""
    def __init__(self, port: Optional[str] = None) -> None:
        if port is None:
            port = "COM3"
        self.port: str = port
        self.reader: Optional[TertiumReader] = None
        self.async_thread: Optional[threading.Thread] = None
        
    def connect(self) -> bool:
            
        self.reader = TertiumReader(port=self.port, rssi_enabled=False)
            
        try:
            self.reader.open()
            self.reader.set_led(red_status="FF") # Red light during connection attempt
            self.reader.set_operation_mode(local="01", id_format="02")
            return True
        except Exception as e:
            logger.error(f"Impossibile connettersi al lettore: {e}")
            return False
            
    def disconnect(self) -> None:
        if self.reader:
            self.reader.close()
            
    @property
    def is_connected(self) -> bool:
        if not self.reader:
            return False
        return self.reader.ser is not None and self.reader.ser.is_open

    def configure_for_read_point(self, read_point: str) -> None:
        """Regola le impostazioni del lettore (potenza e modalità) in base all'ambiente fisico."""
        if not self.reader or not self.is_connected:
            return
            
        self.reader.set_led(green_status="FF")

        if read_point == "DESK":
            self.reader.set_power(0x1B) # Potenza minima
        elif read_point == "SMART_CABINET" or read_point == "SMART_TRUCK":
            self.reader.set_power(0x00) # Potenza massima
        elif read_point == "WASTE_CONTAINER" or read_point == "PACKAGING_LINE":
            self.reader.set_power(0x0A) # Potenza media
            
        # Imposta sempre il lettore in modalità Standard (00)
        # Sarà il Middleware Python a decidere quando scansionare facendo polling.
        self.reader.set_current_mode(mode="00")
            
    def read_tags(self) -> list[str]:
        """Esegue una singola scansione di inventario (Modalità Normale) e ritorna una lista di EPC."""
        if not self.reader or not self.is_connected:
            return []
        

        tags = self.reader.inventory(timeout_ms=500)
        
        # Se il lettore ritorna una lista di tuple (EPC, RSSI), estraiamo solo gli EPC
        if tags and isinstance(tags[0], tuple):
            return [t[0] for t in tags]
        
        logger.debug(f"Tags letti: {tags}")
        return tags

    def write_new_epc(self, new_epc_hex: str) -> tuple[bool, str]:
        """
        Legge il primo tag disponibile nel raggio d'azione e sovrascrive la sua memoria EPC
        con il nuovo codice EPC.
        """
        if not self.reader or not self.is_connected:
            return False, "Lettore non connesso"
            
        # Prima di tutto, cerca un tag fisico nel campo a cui scrivere
        tags = self.read_tags()
        if not tags:
            return False, "Nessun tag fisico rilevato nel raggio d'azione."
            
        target_epc = tags[0]
        
        try:
            # Parametri per write_memory: epc (target), data (nuovo valore), mem_bank="01" (Banco EPC), address="02" (Inizia dalla Word 2 per saltare CRC e PC), block_num="06" (Scrive 6 word = 96 bit)
            retcode = self.reader.write_memory(
                epc=target_epc, 
                data=new_epc_hex, 
                mem_bank="01", 
                address="02", 
                block_num="08", # 1 blocco per ogni word (1 word = 2 byte)
                timeout_ms=2000
            )
            
            if retcode == "00":
                return True, target_epc # Ritorna il vecchio EPC per riferimento visivo
            else:
                return False, f"Errore scrittura (Retcode: {retcode})"
        except Exception as e:
            logger.error(f"Errore in scrittura: {e}")
            return False, str(e)
