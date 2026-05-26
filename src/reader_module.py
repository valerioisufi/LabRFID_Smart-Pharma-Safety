import time
import logging
import threading

try:
    from src.tertium_serial_handler import TertiumReader
    TERTIUM_AVAILABLE = True
except ImportError:
    TERTIUM_AVAILABLE = False

logger = logging.getLogger(__name__)

class ReaderManager:
    """Hardware Abstraction Layer managing the reader connection."""
    def __init__(self, port=None):
        import sys
        if port is None:
            port = "/dev/cu.usbserial-1110" if sys.platform == "darwin" else "COM3"
        self.port = port
        self.reader = None
        self.async_thread = None
        
    def connect(self):
        if not TERTIUM_AVAILABLE:
            logger.error("TertiumReader module not found.")
            return False
            
        self.reader = TertiumReader(port=self.port, rssi_enabled=False)
            
        try:
            self.reader.open()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to reader: {e}")
            return False
            
    def disconnect(self):
        self.stop_async_reading()
        if self.reader:
            self.reader.close()
            
    @property
    def is_connected(self):
        if not self.reader:
            return False
        return hasattr(self.reader, 'ser') and self.reader.ser is not None and self.reader.ser.is_open

    def configure_for_read_point(self, read_point):
        """Adjusts reader settings based on the physical environment."""
        if not self.reader or not self.is_connected:
            return
            
        if read_point == "DESK":
            self.reader.set_power(0x1B) # Min power
            self.reader.set_current_mode(mode="01") # Time-based auto scan
        elif read_point == "SMART_TRUCK" or read_point == "SMART_CABINET":
            self.reader.set_power(0x00) # Max power
            self.reader.set_current_mode(mode="00") # Normal (manual inventory)
        elif read_point == "WASTE_CONTAINER" or read_point == "PACKAGING_LINE":
            self.reader.set_power(0x0A) # Medium power
            self.reader.set_current_mode(mode="01") # Time-based auto scan

    def start_async_reading(self, callback):
        """Starts a background thread to continuously read tags."""
        if not self.reader or not self.is_connected:
            return
            
        if self.async_thread and self.async_thread.is_alive():
            return # Already running
            
        self.async_thread = threading.Thread(target=self.reader.listen_async, args=(callback,))
        self.async_thread.daemon = True
        self.async_thread.start()
        
    def stop_async_reading(self):
        """Stops the background reading thread."""
        if self.reader and hasattr(self.reader, 'stop_listening'):
            self.reader.stop_listening()
            
    def read_tags(self):
        """Performs a single inventory scan (Normal mode) and returns a list of EPCs."""
        if not self.reader or not self.is_connected:
            return []
            
        tags = self.reader.inventory(timeout_ms=500)
        
        # If it's a list of tuples (EPC, RSSI), extract just the EPCs
        if tags and isinstance(tags[0], tuple):
            return [t[0] for t in tags]
        return tags

    def write_new_epc(self, new_epc_hex: str):
        """
        Reads the first available tag in range, and overwrites its EPC memory
        with the new SGTIN-96 EPC.
        """
        if not self.reader or not self.is_connected:
            return False, "Reader not connected"
            
        # First, find a tag to write to
        tags = self.read_tags()
        if not tags:
            return False, "Nessun tag fisico rilevato nel raggio d'azione."
            
        target_epc = tags[0]
        
        try:
            # write_memory args: epc, data, mem_bank="01" (EPC), address="02" (Word 2), block_num="06" (6 words = 96 bits)
            retcode = self.reader.write_memory(
                epc=target_epc, 
                data=new_epc_hex, 
                mem_bank="01", 
                address="02", 
                block_num="06", 
                timeout_ms=2000
            )
            
            if retcode == "00":
                return True, target_epc # Return the old EPC just for reference
            else:
                return False, f"Errore scrittura (Retcode: {retcode})"
        except Exception as e:
            logger.error(f"Write error: {e}")
            return False, str(e)
