"""
Reset dei tag usati nella simulazione: sblocca il banco EPC, azzera la access password e
riscrive un EPC a 96 bit "vergine".

Per ogni tag nel campo (di default solo quelli con header DSGTIN+ = 0xFB, cioè i tag commissionati
dal simulatore) esegue, indirizzando il tag col suo EPC attuale a 128 bit:
  1. unlock_epc()            -> sblocca il banco EPC (presenta la password di sistema)
  2. write_access_password() -> riporta la access password a 00000000
  3. write_memory() su EPC   -> scrive un nuovo EPC a 96 bit (24 hex = 6 word)

Risultato: tag sbloccati, senza password, con un EPC a 96 bit univoco. Operazione idempotente:
dopo il reset i tag non hanno più header FB e non vengono riprocessati.

ATTENZIONE: modifica fisicamente i tag (sovrascrive l'EPC, sblocca, azzera la password).

Uso:
    python scripts/reset_tags.py --port /dev/cu.usbserial-XXXX
    python scripts/reset_tags.py --port COM3 --epc-base 000000000000000000000100 --yes
    python scripts/reset_tags.py --port COM3 --all          # processa TUTTI i tag, non solo i DSGTIN+
"""
import sys
import pathlib
import time
import logging
import argparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from src.tertium_serial_handler import TertiumReader, TertiumError
from src.middleware import EPC_ACCESS_PASSWORD   # password di sistema usata in commissioning

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("reset_tags")

ZERO_PWD = "00000000"


def collect_tags(reader, seconds=2.0, only_dsgtin=True):
    """Raccoglie gli EPC unici visti nel campo per qualche secondo."""
    seen = set()
    start = time.time()
    while time.time() - start < seconds:
        for t in reader.inventory(timeout_ms=500):
            epc = t[0] if isinstance(t, tuple) else t
            if epc:
                seen.add(epc.upper())
        time.sleep(0.1)
    if only_dsgtin:
        seen = {e for e in seen if e.startswith("FB")}   # header DSGTIN+ = 0xFB
    return sorted(seen)


def main():
    ap = argparse.ArgumentParser(description="Reset dei tag della simulazione: sblocca e riporta l'EPC a 96 bit.")
    ap.add_argument("--port", required=True, help="Porta seriale (es. /dev/cu.usbserial-XXXX o COM3)")
    ap.add_argument("--password", default=EPC_ACCESS_PASSWORD, help="Access password di sistema (8 hex)")
    ap.add_argument("--epc-base", default="000000000000000000000001",
                    help="EPC a 96 bit di partenza (24 hex); ai tag successivi viene assegnato base+1, base+2, ...")
    ap.add_argument("--all", action="store_true", help="processa tutti i tag, non solo i DSGTIN+ (header FB)")
    ap.add_argument("--yes", action="store_true", help="salta la conferma interattiva")
    args = ap.parse_args()

    pwd = args.password.upper()
    base_hex = args.epc_base.upper()
    if len(base_hex) != 24 or any(c not in "0123456789ABCDEF" for c in base_hex):
        log.error("--epc-base deve essere 24 cifre esadecimali (96 bit).")
        return
    if len(pwd) != 8 or any(c not in "0123456789ABCDEF" for c in pwd):
        log.error("La password deve essere 8 cifre esadecimali.")
        return
    base = int(base_hex, 16)

    try:
        with TertiumReader(port=args.port, rssi_enabled=False) as reader:
            reader.set_operation_mode(local="01", id_format="02")
            reader.set_led(green_status="FF")

            log.info("Cerco i tag nel campo...")
            tags = collect_tags(reader, 2.0, only_dsgtin=not args.all)
            if not tags:
                log.error("Nessun tag da resettare trovato. (Senza --all considero solo i DSGTIN+ con header FB.)")
                return

            print("\nVerranno resettati questi tag (sblocco + password a 0 + EPC a 96 bit):")
            for i, t in enumerate(tags):
                print(f"   {t}  ->  {base + i:024X}")
            print()
            if not args.yes:
                if input(" Procedere? scrivi 'si' per continuare: ").strip().lower() not in ("si", "sì", "s", "y", "yes"):
                    print(" Annullato.")
                    return

            for i, cur in enumerate(tags):
                new_epc = f"{base + i:024X}"
                log.info(f"[{i+1}/{len(tags)}] {cur} -> {new_epc}")

                # 1. sblocca il banco EPC (presenta la password di sistema)
                r_unlock = reader.unlock_epc(cur, acc_password=pwd)
                # 2. azzera la access password (banco Reserved, non lockato)
                r_pwd = reader.write_access_password(cur, ZERO_PWD, acc_password=pwd)
                # 3. scrive il nuovo EPC a 96 bit: ora il banco è sbloccato e la password è 0
                r_write = reader.write_memory(cur, new_epc, mem_bank="01", address="02",
                                              block_num="06", timeout_ms=1500, acc_password="")

                ok = (r_write == "00")
                log.info(f"      unlock={r_unlock}  reset-pwd={r_pwd}  write-EPC={r_write}  -> {'OK' if ok else 'FALLITO'}")
                if not ok:
                    log.warning(f"      Tag {cur} non resettato: l'EPC potrebbe essere ancora a 128 bit. "
                                f"Verifica la password (--password) o che il tag sia rimasto nel campo.")
                reader.beep(freq_hz=2000, duration_ms=80)

            # Verifica: rileggo tutto il campo e mostro gli EPC risultanti
            log.info("Verifica: rileggo i tag nel campo...")
            after = collect_tags(reader, 2.0, only_dsgtin=False)
            print("\nEPC presenti ora nel campo:")
            for e in after:
                print(f"   {e}  ({len(e)*4} bit)")
            residui = [e for e in after if e.startswith("FB")]
            print()
            if residui:
                log.warning(f"Restano {len(residui)} tag con header FB (non resettati): {residui}")
            else:
                log.info("Nessun tag DSGTIN+ residuo: reset completato.")

            reader.set_led(green_status="00", red_status="00")

    except TertiumError as e:
        log.error(f"Errore hardware: {e}")
    except Exception as e:
        log.error(f"Errore inatteso: {e}")


if __name__ == "__main__":
    main()
