import time
import random
import logging

try:
    from src.tertium_serial_handler import TertiumReader
    TERTIUM_AVAILABLE = True
except ImportError:
    TERTIUM_AVAILABLE = False

logger = logging.getLogger(__name__)

class MockReader:
    """Simulates the physical Tertium reader for demo purposes."""
    
    def __init__(self):
        self.connected = False
        self.port = "MOCK_PORT"
        
    def open(self):
        self.connected = True
        logger.info("MockReader connected.")
        
    def close(self):
        self.connected = False
        logger.info("MockReader disconnected.")
        
    def set_power(self, power_val, mode="00"):
        # Power settings: 
        # Desk -> low power
        # Smart Truck / Smart Cabinet -> high power
        logger.info(f"MockReader power set to {power_val} (Mode: {mode})")
        return True
        
    def inventory(self, timeout_ms=500):
        # Simulate taking some time to read
        time.sleep(timeout_ms / 1000.0)
        
        # Simulate different reads based on the context, but since this is just a mock,
        # we will generate some predefined tags or random ones.
        # In a real scenario, the middleware decides the read point.
        # Here we just return a mix of known tags from our mock database.
        
        tags = [
            "PHARMA-0001",
            "PHARMA-0002",
            "PHARMA-0003"
        ]
        
        # Randomly decide how many tags to read
        num_tags = random.randint(1, len(tags))
        return random.sample(tags, num_tags)

class ReaderManager:
    """Hardware Abstraction Layer managing the reader connection."""
    def __init__(self, use_mock=True, port="COM3"):
        self.use_mock = use_mock
        self.port = port
        self.reader = None
        
    def connect(self):
        if self.use_mock or not TERTIUM_AVAILABLE:
            self.reader = MockReader()
        else:
            self.reader = TertiumReader(port=self.port, rssi_enabled=False)
            
        try:
            self.reader.open()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to reader: {e}")
            return False
            
    def disconnect(self):
        if self.reader:
            self.reader.close()
            
    @property
    def is_connected(self):
        if not self.reader:
            return False
        if self.use_mock or not TERTIUM_AVAILABLE:
            return getattr(self.reader, 'connected', False)
        else:
            # Handle actual physical TertiumReader
            return hasattr(self.reader, 'ser') and self.reader.ser is not None and self.reader.ser.is_open

    def configure_for_read_point(self, read_point):
        """Adjusts reader settings based on the physical environment."""
        if not self.reader:
            return
            
        if read_point == "DESK":
            # Very low power for close proximity, avoiding stray reads
            self.reader.set_power(0x1B) # Min power in some Tertium modules
        elif read_point == "SMART_TRUCK" or read_point == "SMART_CABINET":
            # Max power for reading multiple tags
            self.reader.set_power(0x00) # Max power
        elif read_point == "WASTE_CONTAINER":
            self.reader.set_power(0x0A) # Medium power
            
    def read_tags(self):
        """Performs an inventory scan and returns a list of EPCs."""
        if not self.reader:
            return []
            
        tags = self.reader.inventory(timeout_ms=500)
        
        # If it's a list of tuples (EPC, RSSI), extract just the EPCs
        if tags and isinstance(tags[0], tuple):
            return [t[0] for t in tags]
        return tags
