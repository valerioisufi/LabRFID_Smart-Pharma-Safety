# Guida — LabRFID Smart Pharma Safety

Simulatore di tracciamento farmaceutico con RFID UHF su lettore **Tertium UHF Desktop RE40**.
Ogni astuccio porta un tag: lo si commissiona, lo si segue lungo la filiera (camion → armadio →
cassa → smaltimento) e a ogni passaggio si verificano stato, scadenza, lotto e autenticità.

Documenti collegati: [macchina-a-stati.md](macchina-a-stati.md) · [epc-e-dati.md](epc-e-dati.md) ·
struttura dei moduli in dettaglio: [../ARCHITECTURE.md](../ARCHITECTURE.md).

## Avvio
```bash
pip install -r requirements.txt
python src/web_app.py          # poi apri http://localhost:8000
```
Dal pannello: scegli la porta e **Connect Reader**, scegli il **punto di lettura**, avvia il
monitoraggio. Sulla *Packaging Line* usa **Start Automated Writing** per scrivere/commissionare i
tag; **Reset Simulation** azzera il database.

## Struttura (moduli `src/`)
- **tertium_serial_handler.py** — driver seriale del RE40: comandi del protocollo (inventory, read,
  write, LOCK, RSSI, LED, beep) e parsing delle risposte.
- **reader_module.py** — `ReaderManager`: astrazione del lettore (connessione, `read_tags`,
  `read_tid`, configurazione per punto di lettura con filtro RSSI al DESK).
- **epc_encoder.py** — codifica dell'EPC (DSGTIN+ 128 bit).
- **state_machine.py** — database in memoria (su `data/database.json`) + logica del ciclo di vita.
- **middleware.py** — orchestratore: polling asincrono, scelte per punto di lettura, scrittura e
  protezione dei tag.
- **web_app.py** — server FastAPI + WebSocket (API REST e aggiornamenti in tempo reale alla UI).

Script diagnostici hardware (non parte dell'app): `scripts/`. Dati: `data/`.

## Workflow per punto di lettura
| Punto di lettura | Azione | Stato risultante | Note |
|------------------|--------|------------------|------|
| Packaging Line | PACK | PACKED | scrive EPC, lega il TID, protegge l'EPC (lock con password) |
| Smart Truck | LOAD | DISTRIBUTING | carico sul camion |
| Smart Cabinet | STORE | STORED | monitora la **presenza**: rileva arrivi, prelievi, ammanchi |
| Desk (cassa) | SELL | DISPENSED | verifica scadenza/lotto/**autenticità**; blocca la vendita se non conforme |
| Waste Container | THROW | DISPOSED | smaltimento (sempre consentito) |

## Sicurezza anti-contraffazione (due livelli)
- **Rilevamento (TID):** in commissioning l'EPC viene legato al **TID** del chip (read-only di
  fabbrica). Rileggendo il TID a desk e all'arrivo in armadio, un EPC clonato su un altro chip viene
  scoperto (alert "TAG NON AUTENTICO"; al desk blocca la vendita).
- **Prevenzione (LOCK):** dopo la scrittura, l'EPC viene **bloccato** con una access password di
  sistema (lock risbloccabile, payload `0C020F`): non è più riscrivibile senza la password.
