import sys
import pathlib
import time
import logging

# Script diagnostico: aggiunge la root del progetto al path per importare il package src.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from src.tertium_serial_handler import TertiumReader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] %(message)s')

def test_inventory(reader, durata_ms=2000):
    start = time.time()
    tags_trovati = set()
    while (time.time() - start) < (durata_ms / 1000):
        tags = reader.inventory(timeout_ms=500)
        if tags:
            for payload in tags:
                epc = payload[0] if isinstance(payload, tuple) else payload
                tags_trovati.add(epc)
    return tags_trovati

def main():
    PORTA_SERIALE = "/dev/cu.usbserial-1110"

    print("Inizializzazione diagnostica hardware RE40...")

    try:
        # Inizializziamo senza forzare l'RSSI per ora
        with TertiumReader(port=PORTA_SERIALE, baudrate=38400, rssi_enabled=False) as reader:

            print("\n" + "="*50)
            print(" TEST 1: LETTURA NORMALE (Nessun Filtro)")
            print("="*50)
            reader.set_rssi_filter(enabled=False)
            tags = test_inventory(reader, 3000)
            print(f"Risultato: Trovati {len(tags)} tag unici.")
            for t in tags: print(f" - {t}")

            if len(tags) == 0:
                print("\nNessun tag nel campo. Avvicina un tag all'antenna e riavvia il test.")
                return

            print("\n" + "="*50)
            print(" TEST 2: FILTRO RSSI ATTIVO (Soglia tollerante: -80 dBm)")
            print("="*50)
            # Attiviamo l'RSSI nel software e nell'hardware
            reader.rssi_enabled = True
            reader.set_rssi_filter(enabled=True, threshold_dbm=-80)
            tags = test_inventory(reader, 3000)
            print(f"Risultato: Trovati {len(tags)} tag unici.")

            print("\n" + "="*50)
            print(" TEST 3: FILTRO RSSI ESTREMO (Soglia altissima: -20 dBm)")
            print(" Il tag dovrebbe scomparire a meno che non tocchi l'antenna.")
            print("="*50)
            reader.set_rssi_filter(enabled=True, threshold_dbm=-20)
            tags = test_inventory(reader, 3000)
            print(f"Risultato: Trovati {len(tags)} tag unici.")
            if len(tags) == 0:
                print(">> DIAGNOSI: Il filtro RSSI hardware FUNZIONA! I tag deboli vengono scartati.")
                print(">> CONCLUSIONE: Il firmware RE40 filtra i tag, ma non accoda il byte RSSI al payload seriale.")
            else:
                print(">> DIAGNOSI: Il tag viene letto ugualmente.")
                print(">> CONCLUSIONE: Il comando 1C sembra essere completamente ignorato dal motore Zebra interno.")

    except Exception as e:
        print(f"\n❌ Errore durante il test: {e}")

if __name__ == "__main__":
    main()