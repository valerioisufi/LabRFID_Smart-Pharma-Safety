import sys
import pathlib
import logging

# Script diagnostico: aggiunge la root del progetto al path per importare il package src.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from src.tertium_serial_handler import TertiumReader

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - [%(levelname)s] %(message)s')

def main():
    PORTA_SERIALE = "/dev/cu.usbserial-1120"  # Sostituisci con la tua porta

    print("Inizializzazione test SETMODE su RE40...")

    try:
        # Inizializziamo senza far partire script asincroni
        with TertiumReader(port=PORTA_SERIALE, baudrate=38400) as reader:
            print("\n" + "="*50)
            print(" TEST LETTURA CONFIGURAZIONE (SETMODE 0E)")
            print("="*50)

            print("Configurazione iniziale...")
            print(reader.set_current_mode(mode="04"))  # Modalità Normale, Formato ID 02)

            config = reader.get_operation_mode()

            if config:
                print("\n✅ LETTURA SUPPORTATA! L'hardware ha restituito:")
                print(f" - Mode       : {config['mode']} (00=Normal, 01=Time, 02=Input)")
                print(f" - Local      : {config['local']} (Feedback beeper/led)")
                print(f" - ID Format  : {config['id_format']} (00=Full frame, 01=Solo EPC)")
                print(f" - Max Num    : {config['max_num']}")
                print(f" - T Scan     : {config['tscan']} ({int(config['tscan'], 16) * 100} ms)")
                print(f" - T Interval : {config['tinterval']} ({int(config['tinterval'], 16) * 100} ms)")
            else:
                print("\n❌ LETTURA NON SUPPORTATA. Il firmware del modulo Zebra interno")
                print("   ignora le interrogazioni vuote anche per il SETMODE.")

            print(reader.get_current_mode())

    except Exception as e:
        print(f"\n❌ Errore durante il test: {e}")

if __name__ == "__main__":
    main()