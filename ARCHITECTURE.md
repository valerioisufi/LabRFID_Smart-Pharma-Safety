# Architettura del Sistema LabRFID

Il progetto è strutturato in diversi moduli separati, ognuno con una responsabilità ben precisa. Questo approccio modulare (Separation of Concerns) rende il codice più facile da mantenere e da testare.

Ecco una panoramica dettagliata di cosa fa ogni file all'interno della cartella `src/`.

---

## 1. `tertium_serial_handler.py` (Livello Hardware / Driver)
Questo è il file più "basso" del sistema. Si occupa di comunicare direttamente (fisicamente) con il lettore RFID hardware (prodotto presumibilmente da Tertium Technology) tramite la porta seriale/USB.

**Cosa fa:**
* Stabilisce e mantiene la connessione Seriale (usando la libreria `pyserial`).
* Invia i comandi esadecimali specifici che l'hardware si aspetta (es. comandi per leggere l'inventario dei tag, per scrivere nella memoria di un tag, per cambiare la potenza dell'antenna).
* Riceve la risposta grezza dal lettore, la analizza (parsing) e controlla che non ci siano errori (es. checksum errati o tag non trovati).
* **Funzioni principali:** `connect()`, `inventory()` (per leggere tutti i tag vicini), `write_memory()` (per scrivere fisicamente un nuovo codice EPC nel tag).

## 2. `reader_module.py` (Livello di Astrazione del Lettore)
Questo file fa da "ponte" tra l'applicazione web e il driver hardware (`tertium_serial_handler.py`).

**Cosa fa:**
* Crea un `ReaderManager` che incapsula il lettore fisico in modo da semplificarne l'uso.
* **Gestisce il Multithreading:** Questo è fondamentale. Dato che la lettura seriale può bloccare il programma, questo modulo avvia un "thread in background" (un processo separato) che continua a interrogare il lettore in loop, senza bloccare l'interfaccia web.
* **Filtra i duplicati:** Se un tag viene letto 100 volte in un secondo (cosa normale per l'RFID), questo modulo fa in modo di generare un "evento" pulito per evitare di intasare il sistema.
* Contiene metodi come `start_async_reading()` e `stop_async_reading()` che la Web App usa per far partire/fermare le scansioni continue.

## 3. `epc_encoder.py` (Logica di Codifica RFID)
Nell'industria farmaceutica i tag RFID non contengono stringhe di testo semplici, ma uno standard industriale chiamato SGTIN-96 (Serialized Global Trade Item Number). Questo file gestisce le conversioni matematiche.

**Cosa fa:**
* Prende i dati "umani" (come il GTIN del farmaco e il numero di serie) e li converte in una lunghissima stringa binaria e poi Esadecimale (di 96 bit / 24 caratteri). Questo è il dato che viene effettivamente "scritto" nell'antenna del tag.
* Decodifica: Fa anche l'inverso. Prende il codice esadecimale letto dall'antenna e lo spacchetta per dirti "Questo è il prodotto GTIN XYZ, numero di serie 123".
* **Funzione principale:** `encode_sgtin96()`.

## 4. `state_machine.py` (Il Database e la Logica di Business)
Questo è il "cervello logico" del tracciamento. Gestisce il ciclo di vita (la macchina a stati) di ogni singola scatola di medicinale.

**Cosa fa:**
* Salva e carica i dati da un file `data/assets.json` (che funge da database persistente).
* Definisce gli "stati" che un farmaco può avere (es. `COMMISSIONED`, `PACKED`, `IN_TRANSIT`, `IN_CABINET`, `DISPENSED`, `EXPIRED`).
* Contiene la logica per validare i passaggi di stato. Ad esempio: un farmaco può passare da `IN_TRANSIT` a `IN_CABINET`, ma non può passare direttamente da `COMMISSIONED` a `DISPENSED`. Se succede, genera un "Violation Event".
* Registra tutti gli eventi e l'ora esatta in cui un'azione è avvenuta (chi ha letto cosa, quando e in che stato è passato).

## 5. `middleware.py` (Il Coordinatore Centrale)
Nel mondo RFID, il "Middleware" è il software che sta in mezzo tra l'hardware che legge a raffica e il gestionale aziendale (in questo caso la state_machine).

**Cosa fa:**
* Riceve la lista degli EPC letti grezzi dal `reader_module`.
* Chiede alla `state_machine` "chi sono questi tag?".
* Decide cosa fare in base a *dove* ti trovi (`current_read_point`). Ad esempio:
    * Se sei sulla **Packaging Line**, i tag letti passano allo stato `PACKED`.
    * Se sei sul **Smart Truck**, passano allo stato `IN_TRANSIT`.
    * Se sei sullo **Smart Cabinet**, passano a `IN_CABINET`.
* **Funzione principale:** `process_reads(tags, read_point)`, che esegue questa logica ad alto livello.

## 6. `web_app.py` (L'Interfaccia Utente e il Server)
È il server principale (basato sul framework veloce `FastAPI`). Mette in piedi l'infrastruttura web affinché tu possa vedere le cose nel browser.

**Cosa fa:**
* Espone le **API REST** (es. `/api/connect`, `/api/monitor`, `/api/start_batch`) che la pagina web chiama quando clicchi i bottoni.
* Espone i file statici (`.css`, `.js`) e fa il rendering della pagina `index.html` (usando Jinja2).
* Gestisce una **connessione WebSocket** (`/ws`): I WebSockets permettono al server di inviare dati *in tempo reale* al tuo browser (es. un nuovo tag letto, o un nuovo log di sistema) senza che tu debba ricaricare la pagina.
* Collega insieme tutti gli altri moduli: instanzia il lettore, instanzia il middleware, raccoglie i log e li "pompa" verso il browser.

---

### Riassunto del Flusso (Esempio: Lettura sul Camion)
1. In `web_app.py` selezioni "Smart Truck" e clicchi "Start Monitor".
2. `web_app.py` dice a `reader_module.py` di iniziare a leggere in loop nel thread in background.
3. `reader_module.py` chiede a `tertium_serial_handler.py` di scansionare tramite Seriale.
4. `tertium_serial_handler.py` interroga l'hardware fisico e risponde con una lista di codici EPC.
5. `reader_module.py` pulisce la lista dai duplicati eccessivi e la passa a `middleware.py`.
6. `middleware.py` sa che sei sul "Camion" e dice a `state_machine.py`: "Aggiorna questi EPC allo stato IN_TRANSIT".
7. `state_machine.py` aggiorna il file JSON.
8. `middleware.py` ritorna l'esito a `web_app.py`.
9. `web_app.py` invia un pacchetto dati tramite WebSocket al tuo browser.
10. Il browser aggiorna i numeri e i log a schermo in tempo reale.
