# Architettura del Sistema LabRFID

Il progetto è strutturato in moduli separati, ognuno con una responsabilità precisa (Separation of
Concerns). Sotto, cosa fa ogni file in `src/`, più una panoramica del flusso end-to-end.

Codice di produzione: `src/`. Script diagnostici per l'hardware (non parte dell'app): `scripts/`.
Specifiche e note: `docs/`. Dati persistenti: `data/database.json` (asset + eventi) e
`data/blacklisted_batches.json` (lotti ritirati).

---

## 1. `tertium_serial_handler.py` (Livello Hardware / Driver)
Comunica direttamente con il lettore RFID **Tertium UHF Desktop RE40** via porta seriale/USB
(`pyserial`), implementando il protocollo TT-RFID.

**Cosa fa:**
* Apre/chiude la connessione seriale e costruisce i frame del protocollo (`$:` + lunghezza +
  sequence + comando + parametri + CR).
* Espone i comandi: `inventory()` (lettura tag), `read_memory()`/`write_memory()` (banchi di
  memoria), `set_rssi_filter()` (filtro di prossimità, comando 1C, specifico RE40), `set_power()`,
  `set_led()`, `beep()`, `set_operation_mode()`, ecc.
* Fa il parsing delle risposte controllando il **return code** (in posizione `[6:8]` del frame).
* `inventory()` termina appena riceve il frame di fine inventario, senza attendere il timeout a muro.

## 2. `reader_module.py` (Livello di Astrazione del Lettore — HAL)
`ReaderManager` fa da ponte tra il middleware e il driver, semplificando connessione e lettura.

**Cosa fa:**
* `connect()` / `disconnect()`, gestione dello stato di connessione.
* `read_tags()`: una singola scansione di inventario che ritorna una lista di EPC (normalizzando il
  formato, anche quando il filtro RSSI fa ritornare delle tuple).
* `write_new_epc()`: scrive un nuovo EPC su un tag presente nel campo.
* `configure_for_read_point()`: regola il lettore in base al punto di lettura. In particolare, al
  **DESK** attiva il **filtro RSSI** (prossimità: legge solo l'astuccio appoggiato sul lettore),
  perché la potenza (SETPOWER) sul RE40 cambierebbe solo dopo un reset e non è adatta a runtime.

> Nota: il polling NON avviene qui in un thread dedicato. È il middleware a schedularlo
> sull'event loop `asyncio`, eseguendo le chiamate seriali bloccanti in un thread executor.

## 3. `epc_encoder.py` (Codifica RFID)
Converte i dati "umani" (GTIN, seriale, data di scadenza) nell'EPC scritto fisicamente nel tag.

**Cosa fa:**
* `encode_dsgtin128()`: codifica un **DSGTIN+ a 128 bit** (Date-prioritized SGTIN), formato adatto
  alla filiera dei deperibili perché espone la data di scadenza nei bit alti. È l'unico formato
  usato dal progetto.

## 4. `state_machine.py` (Database + Logica di Business)
Il "cervello" del tracciamento: gestisce il ciclo di vita di ogni astuccio e lo storico eventi,
sincronizzati su `data/database.json`.

**Stati del ciclo di vita:**
`PACKED` → `DISTRIBUTING` → `STORED` → `DISPENSED` → `DISPOSED`, più due stati legati all'armadio:
`AWAITING_CHECKOUT` (uscito dall'armadio, in attesa di cassa) e `MISSING` (ammanco). `EXPIRED` non
è uno stato: è **derivato** dalla data di scadenza al volo.

**Come funziona:**
* `READ_POINT_RULES` e `ALLOWED_TRANSITIONS` sono la **fonte di verità** delle transizioni: ogni
  punto di lettura impone (azione, stato obiettivo), e la transizione avviene solo se consentita.
* `process_read()`: valuta una lettura applicando, nell'ordine — controlli di qualità
  (scadenza/lotto ritirato), re-letture idempotenti, **blocco vendita** al DESK per farmaci non
  vendibili, e la tabella delle transizioni. Le transizioni non consentite vengono segnalate senza
  cambiare stato.
* `commission_asset()`: crea l'asset e ne registra la nascita (azione `PACK`).
* `process_removal()`: un articolo che **esce dall'armadio** passa a `AWAITING_CHECKOUT` (nessun
  allarme: tra prelievo e cassa passa del tempo).
* `reconcile_pending_checkouts()`: gli `AWAITING_CHECKOUT` che non passano in cassa entro il grace
  period (`CHECKOUT_GRACE_SECONDS`, default 60s) diventano `MISSING`.
* `_apply()`: punto unico che aggiorna lo stato, registra l'evento e salva (con anti-flood sugli
  eventi duplicati consecutivi).

## 5. `middleware.py` (Coordinatore Centrale)
Sta tra l'hardware che legge a raffica e la logica di business. Decide cosa fare in base al
`current_read_point`.

**Cosa fa:**
* Orchestra il polling con un task `asyncio` (`_periodic_scan_loop`), eseguendo le chiamate seriali
  bloccanti in un thread executor (`run_in_executor`) per non bloccare l'event loop.
* **Packaging Line**: scrive l'EPC sui tag e li commissiona (`PACKED`).
* **Smart Truck / Waste**: aggiorna gli stati via `process_read()`.
* **Smart Cabinet**: monitora la **presenza** con un diff dell'inventario — riconosce nuovi arrivi
  (`STORED`), prelievi (`process_removal()`, con debounce anti-falsi-positivi) e ammanchi
  (`reconcile_pending_checkouts()`).
* **Desk**: legge su richiesta (filtro RSSI di prossimità), dispensa e dà feedback LED dell'esito.

## 6. `web_app.py` (Interfaccia Utente e Server)
Server `FastAPI`. Espone le API REST (`/api/connect`, `/api/monitor`, `/api/start_batch`, …), serve
i file statici e `index.html` (Jinja2), e mantiene una connessione **WebSocket** (`/ws`) per
spingere aggiornamenti in tempo reale al browser (nuovi tag, eventi, log di sistema). Auto-rileva la
prima porta seriale disponibile (cross-platform).

---

### Riassunto del Flusso (Esempio: lettura sul camion)
1. Selezioni "Smart Truck" e avvii il monitoraggio.
2. `web_app.py` fa partire il loop di polling del middleware sull'event loop asyncio.
3. `middleware.py` chiede a `reader_module.py` di scansionare (in un thread executor).
4. `tertium_serial_handler.py` interroga l'hardware e ritorna la lista di EPC.
5. `middleware.py`, sapendo di essere sul camion, chiede a `state_machine.py` la transizione verso
   `DISTRIBUTING`, che applica le guardie e aggiorna `database.json`.
6. L'esito torna a `web_app.py`, che lo invia via WebSocket: il browser aggiorna KPI, log ed eventi
   in tempo reale.
