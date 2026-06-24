# Macchina a stati

Definita in `src/state_machine.py`. La fonte di verità sono due tabelle: `READ_POINT_RULES`
(punto di lettura → azione + stato obiettivo) e `ALLOWED_TRANSITIONS` (transizioni lecite).

## Stati
| Stato | Significato |
|-------|-------------|
| `PACKED` | commissionato: EPC scritto, TID legato, EPC protetto in linea |
| `DISTRIBUTING` | caricato sul camion / in transito |
| `STORED` | presente nello Smart Cabinet |
| `AWAITING_CHECKOUT` | uscito dall'armadio, in attesa di cassa (transitorio) |
| `MISSING` | ammanco: uscito e non passato in cassa entro il grace period |
| `DISPENSED` | venduto al desk (terminale) |
| `DISPOSED` | smaltito (terminale) |

`EXPIRED` **non è uno stato**: è un flag *derivato* al volo dalla data di scadenza (vs data
corrente o simulata).

## Ciclo di vita
```
PACKED ──truck──> DISTRIBUTING ──cabinet──> STORED ──(esce)──> AWAITING_CHECKOUT ──desk──> DISPENSED
                                              ^                      │
                                              └──(rimesso a posto)───┤
                                                                     └──(grace 60s scaduto)──> MISSING
DISPOSED  ← (waste container, da qualsiasi stato non terminale)
```
- `STORED → AWAITING_CHECKOUT` e `AWAITING_CHECKOUT → MISSING` **non** passano dai punti di
  lettura: le gestiscono `process_removal` e `reconcile_pending_checkouts` (Smart Cabinet).
- `AWAITING_CHECKOUT`/`MISSING` possono tornare a `STORED` (tag rimesso in armadio).
- Lo smaltimento (`DISPOSED`) è sempre lecito.

## Casi coperti da `process_read(epc, read_point, tid)`
1. **EPC sconosciuto** → `ALERT`, nessuna modifica.
2. **Re-lettura idempotente** (lo stato obiettivo è già quello corrente) → nessuna transizione né
   evento; eventuali alert di qualità sono mostrati a video ma non riloggati.
3. **Blocco vendita al DESK**: se scaduto / lotto ritirato / TID non autentico → stato **invariato**,
   `ALERT` "VENDITA BLOCCATA".
4. **Transizione non consentita** (non in `ALLOWED_TRANSITIONS`, es. salto di passaggi, ritorno
   indietro, asset già smaltito) → **bloccata**, stato invariato, `ALERT` (azione `READ`).
5. **Transizione valida** → applicata con l'azione del punto di lettura.

Smart Cabinet (presenza, in `middleware.py`):
- **prelievo**: un `STORED` che sparisce dal campo → `AWAITING_CHECKOUT` (nessun allarme: tra
  prelievo e cassa passa tempo); con *debounce* anti-falsi-positivi.
- **ammanco**: `reconcile_pending_checkouts` promuove ad `MISSING` gli `AWAITING_CHECKOUT` più
  vecchi di `CHECKOUT_GRACE_SECONDS` (= 60s) non passati in cassa.

`_apply()` rende persistente l'esito (aggiorna stato, logga evento, salva) ed evita di registrare
**eventi duplicati consecutivi** per lo stesso EPC (anti-flood durante il polling).

## Azioni e alert nel log
- **Azioni**: `PACK`, `LOAD`, `STORE`, `SELL`, `THROW`, `REMOVE` (prelievo/ammanco), `READ`
  (re-lettura o tentativo bloccato).
- **Alert di qualità** (bloccano la vendita al desk): `FARMACO SCADUTO!`, `LOTTO RITIRATO!`,
  `TAG NON AUTENTICO` (TID non corrispondente).
