# Codifica EPC e dati del tag

## Codifica EPC — DSGTIN+ a 128 bit
`src/epc_encoder.py → encode_dsgtin128(gtin, serial, expiry_date)`. È un SGTIN *date-prioritized*:
espone la data di scadenza nei bit alti (utile per il filtraggio FEFO). Restituisce una stringa
esadecimale (32 caratteri per 128 bit) scritta nel banco EPC del tag.

| Campo | Bit | Contenuto |
|-------|-----|-----------|
| Header | 8 | `0xFB` (11111011), identifica il DSGTIN+ |
| +AIDC Indicator | 1 | `0` |
| Filter | 3 | filtro GS1 (default `1` = Point-of-Sale) |
| Date Indicator | 4 | `0100` = data di scadenza |
| Date | 16 | `(anno%100 << 9) | (mese << 5) | giorno` |
| GTIN-14 | 56 | le 14 cifre in BCD (4 bit per cifra), conforme a GS1 TDS 2.0 |
| Encoding Indicator | 3 | `001` = upper-case hexadecimal (4 bit/cifra) |
| Length Indicator | 5 | numero di cifre hex del seriale (default 8) |
| Serial | variabile | il contatore in esadecimale maiuscolo, con zeri iniziali a larghezza fissa |
| Padding | — | zeri fino a 128 bit (o successivo multiplo di 16) |

Parte fissa = 96 bit + seriale. Esempio: GTIN `00800123456789`, serial `00000001`, scad. 2027-12-31
→ `FB14379F008001234567892800000001` (essendo BCD, le cifre del GTIN si leggono in chiaro nell'hex).

## Dati del tag nel database
Persistiti in `data/database.json`:
```json
{ "assets": { "<EPC>": { ...asset... } }, "events": [ ...event... ], "serialCounter": 1 }
```

### Asset (`assets[<EPC>]`)
| Campo | Descrizione |
|-------|-------------|
| `epc` | EPC corrente (DSGTIN+ hex) — chiave dell'asset |
| `gtin` | GTIN-14 del prodotto |
| `batch` | numero di lotto |
| `expiryDate` | data di scadenza (`YYYY-MM-DD`) |
| `aic` | codice AIC del farmaco |
| `serialNumber` | progressivo assegnato in commissioning |
| `currentState` | stato del ciclo di vita (vedi [macchina-a-stati.md](macchina-a-stati.md)) |
| `lastUpdate` | timestamp ISO UTC dell'ultima modifica (con suffisso `Z`) |
| `oldEpc` | EPC del tag *prima* del commissioning (tag vergine); usato come fallback se la scrittura fisica era fallita |
| `tid` | TID del chip (read-only di fabbrica), legato all'EPC per verificare l'**autenticità** |

### Evento (`events[]`)
| Campo | Descrizione |
|-------|-------------|
| `eventId` | UUID dell'evento |
| `epc` | EPC interessato |
| `timestamp` | istante (ISO UTC + `Z`) |
| `readPoint` | punto di lettura |
| `action` | azione (`PACK`/`LOAD`/`STORE`/`SELL`/`THROW`/`REMOVE`/`READ`) |
| `newState` | stato risultante |
| `alerts` | lista di alert (vuota se tutto regolare) |

## Altri file dati
- `data/blacklisted_batches.json` — lotti ritirati: `{ "blacklisted_batches": ["B-2026-X", ...] }`.
- La **data simulata** (per testare le scadenze) è un'impostazione di runtime, non salvata nel DB.
