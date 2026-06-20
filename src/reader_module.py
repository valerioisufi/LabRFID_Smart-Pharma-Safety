import logging
import threading
from typing import Optional, Callable

from src.tertium_serial_handler import TertiumReader

logger = logging.getLogger(__name__)

# Soglia RSSI (dBm) usata al DESK: solo i tag molto vicini (appoggiati sul lettore) la superano,
# così si dispensa solo l'astuccio messo sul piatto e non gli altri articoli nelle vicinanze.
# Più la soglia è vicina a -1, più è selettiva. Valore da tarare sull'hardware reale.
DESK_RSSI_THRESHOLD_DBM = -25

class ReaderManager:
    """Livello di astrazione hardware (HAL) che gestisce la connessione con il lettore RFID."""
    def __init__(self, port: Optional[str] = None) -> None:
        self.port: str = port or ""
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
        """
        Regola il lettore in base all'ambiente fisico.

        Al DESK la discriminazione è di PROSSIMITÀ: si attiva il filtro RSSI hardware
        (comando 1C) con soglia alta, così viene letto solo l'astuccio appoggiato sul lettore
        e non gli altri articoli vicini. Negli altri punti il filtro è disattivato, per leggere
        tutto il campo. Si usa l'RSSI e non la potenza perché il filtro RSSI ha effetto
        immediato, mentre il cambio di potenza (SETPOWER) sul RE40 si applica solo dopo un reset
        del dispositivo: quindi non è adatto a discriminare la distanza a runtime.
        """
        if not self.reader or not self.is_connected:
            return

        self.reader.set_led(green_status="FF")

        if read_point == "DESK":
            self.reader.set_rssi_filter(enabled=True, threshold_dbm=DESK_RSSI_THRESHOLD_DBM)
        else:
            self.reader.set_rssi_filter(enabled=False)

        # Modalità Normale (00): è il Middleware a decidere quando scansionare facendo polling.
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

    def read_tid(self, epc: str) -> Optional[str]:
        """
        Legge il TID (banco 02) del tag indirizzato dall'EPC. Il TID è un identificativo
        univoco scritto in fabbrica e di sola lettura: serve a verificare l'autenticità del tag.
        Ritorna la stringa esadecimale del TID, oppure None se la lettura fallisce.
        """
        if not self.reader or not self.is_connected:
            return None
        return self.reader.read_memory(epc, mem_bank="02", address="00", block_num="06")

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
