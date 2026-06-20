"""
Test del LOCK dell'EPC con password sul reader Tertium RE40.

Verifica, su un tag reale, se la firmware del lettore supporta il lock dell'EPC
*risbloccabile con password* (payload 0C020F) e non solo il permalock. La sequenza:

  0) baseline: riscrive lo stesso EPC SENZA lock           -> deve RIUSCIRE (tag scrivibile)
  1) imposta una access password (banco Reserved)
  2) blocca l'EPC con password (payload 0C020F)
  3) prova a riscrivere l'EPC SENZA password               -> deve FALLIRE (lock attivo)
  4) prova a riscrivere l'EPC CON password                 -> deve RIUSCIRE (=> risbloccabile)
  5) ripristino: sblocca l'EPC (0C000F) e riporta la password a 0

Le scritture riscrivono sempre lo STESSO EPC, quindi il contenuto del tag non cambia:
servono solo a misurare se la scrittura è consentita o bloccata.

ATTENZIONE: se la firmware interpreta 0C020F come PERMALOCK (il manuale è ambiguo),
il banco EPC potrebbe restare bloccato per sempre. Usa un TAG SACRIFICABILE.

Uso:
    python scripts/lock_test.py --port /dev/cu.usbserial-XXXX
    python scripts/lock_test.py --port COM3 --password A1B2C3D4 --yes
"""
import sys
import pathlib
import time
import logging
import argparse

# Aggiunge la root del progetto al path per importare il package src.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from src.tertium_serial_handler import TertiumReader, TertiumError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("lock_test")

ZERO_PWD = "00000000"


def find_tag(reader, attempts=10):
    """Cerca un tag nel campo e ne ritorna l'EPC (pulito, senza PC), oppure None."""
    for _ in range(attempts):
        tags = reader.inventory(timeout_ms=500)
        for t in tags:
            epc = t[0] if isinstance(t, tuple) else t
            if epc:
                return epc
        time.sleep(0.2)
    return None


def write_same_epc(reader, epc, password=""):
    """Riscrive lo stesso EPC nel banco EPC. Ritorna '00' se la scrittura è consentita, altrimenti None."""
    block_num = f"{len(epc) // 4:02X}"
    return reader.write_memory(
        epc, data=epc, mem_bank="01", address="02",
        block_num=block_num, timeout_ms=1500, acc_password=password,
    )


def main():
    ap = argparse.ArgumentParser(description="Test del lock EPC con password sul Tertium RE40.")
    ap.add_argument("--port", required=True, help="Porta seriale (es. /dev/cu.usbserial-XXXX o COM3)")
    ap.add_argument("--password", default="A1B2C3D4", help="Access password a 8 hex usata per il test (default A1B2C3D4)")
    ap.add_argument("--yes", action="store_true", help="Salta la conferma interattiva")
    args = ap.parse_args()

    pwd = args.password.upper()
    if len(pwd) != 8 or any(c not in "0123456789ABCDEF" for c in pwd):
        log.error("La password deve essere esattamente 8 cifre esadecimali.")
        return

    print("=" * 74)
    print(" TEST LOCK EPC CON PASSWORD — Tertium RE40")
    print("=" * 74)
    print(" Su un tag nel campo verranno eseguiti: set password -> lock EPC (0C020F) ->")
    print(" scrittura senza/con password -> ripristino. L'EPC viene riscritto identico,")
    print(" quindi il contenuto NON cambia.")
    print()
    print(" ⚠️  Se la firmware tratta 0C020F come PERMALOCK, il banco EPC potrebbe")
    print("     restare bloccato PER SEMPRE. >> USA UN TAG SACRIFICABILE, non un farmaco. <<")
    print("=" * 74)
    if not args.yes:
        if input(" Procedere? scrivi 'si' per continuare: ").strip().lower() not in ("si", "sì", "s", "y", "yes"):
            print(" Annullato.")
            return

    try:
        with TertiumReader(port=args.port, rssi_enabled=False) as reader:
            reader.set_operation_mode(local="01", id_format="02")  # come l'app: EPC con prefisso PC
            reader.set_led(green_status="FF")

            if not reader.get_status():
                log.warning("Il reader non ha risposto al ping (get_status). Provo comunque l'inventario...")

            log.info("Cerco un tag nel campo...")
            epc = find_tag(reader)
            if not epc:
                log.error("Nessun tag rilevato. Avvicina un tag all'antenna e riprova.")
                return
            log.info(f"Tag trovato: EPC = {epc}")
            tid = reader.read_memory(epc, mem_bank="02", address="00", block_num="06")
            log.info(f"TID = {tid}")

            # STEP 0 — baseline: il tag dev'essere scrivibile in partenza.
            log.info("[0] Baseline: riscrivo lo stesso EPC (nessun lock)...")
            if write_same_epc(reader, epc) != "00":
                log.error("Scrittura di base FALLITA: il tag potrebbe essere gia' bloccato o non "
                          "scrivibile. Interrompo prima di toccare password/lock.")
                return
            log.info("    OK: il tag e' scrivibile in partenza.")

            pwd_set = False
            epc_locked = False
            try:
                # STEP 1 — imposta la access password.
                log.info(f"[1] Imposto la access password = {pwd} (banco Reserved)...")
                if reader.write_access_password(epc, pwd) != "00":
                    log.error("Impossibile impostare la access password (banco Reserved non scrivibile?). Interrompo.")
                    return
                pwd_set = True
                log.info("    OK: access password impostata.")

                # STEP 2 — blocca l'EPC con password (risbloccabile).
                log.info("[2] Blocco l'EPC con password (payload 0C020F)...")
                if reader.lock_epc(epc, acc_password=pwd) != "00":
                    log.error("Comando LOCK rifiutato dal reader/tag: la firmware potrebbe non supportarlo.")
                    return
                epc_locked = True
                log.info("    OK: comando LOCK accettato.")

                # STEP 3 — scrittura SENZA password: deve fallire.
                log.info("[3] Riscrivo l'EPC SENZA password (atteso: FALLIMENTO)...")
                blocked = write_same_epc(reader, epc, password="") != "00"
                log.info(f"    -> scrittura senza password: {'FALLITA (bloccata)' if blocked else 'RIUSCITA'}")

                # STEP 4 — scrittura CON password: deve riuscire.
                log.info("[4] Riscrivo l'EPC CON password (atteso: SUCCESSO)...")
                allowed = write_same_epc(reader, epc, password=pwd) == "00"
                log.info(f"    -> scrittura con password: {'RIUSCITA' if allowed else 'FALLITA'}")

                # VERDETTO
                print("\n" + "=" * 74)
                if blocked and allowed:
                    print(" ✅ FUNZIONA: lock EPC con password SUPPORTATO e RISBLOCCABILE.")
                    print("    (scrittura bloccata senza password, consentita con password)")
                elif blocked and not allowed:
                    print(" ⚠️  Il lock blocca le scritture ma NON si scrive nemmeno con la password:")
                    print("    la firmware probabilmente tratta 0C020F come PERMALOCK, o la password")
                    print("    non viene applicata. L'EPC potrebbe essere bloccato in modo permanente.")
                else:
                    print(" ❌ Il lock NON ha effetto: la scrittura senza password e' comunque riuscita.")
                    print("    La firmware RE40 sembra ignorare il LOCK dell'EPC.")
                print("=" * 74 + "\n")

            finally:
                # RIPRISTINO (finche' la porta e' ancora aperta): sblocca EPC e azzera la password.
                if epc_locked:
                    log.info("[5] Ripristino: sblocco l'EPC (0C000F)...")
                    log.info(f"    unlock retcode: {reader.unlock_epc(epc, acc_password=pwd)}")
                if pwd_set:
                    log.info("    Ripristino: riporto la access password a 00000000...")
                    log.info(f"    reset password retcode: {reader.write_access_password(epc, ZERO_PWD, acc_password=pwd)}")
                try:
                    reader.set_led(green_status="00", red_status="00")
                except Exception:
                    pass

    except TertiumError as e:
        log.error(f"Errore hardware: {e}")
    except Exception as e:
        log.error(f"Errore inatteso: {e}")


if __name__ == "__main__":
    main()
