# Lab RFID - Smart Pharma Safety

Sistema di tracciamento farmaceutico tramite RFID.

## Prerequisiti
1. Assicurati di avere Python installato.
2. Collega il lettore RFID al computer via USB.

## Installazione
Installa le librerie necessarie (ti consigliamo di usare un ambiente virtuale):
```bash
pip install -r requirements.txt
```

## Avvio
Per avviare l'applicazione e l'interfaccia web:
```bash
python src/web_app.py
```

## Utilizzo
1. Apri il browser all'indirizzo [http://localhost:8000](http://localhost:8000).
2. Dal pannello di controllo laterale, assicurati che la porta corretta sia selezionata e clicca su **Connect Reader** per collegare il lettore fisico.
3. Seleziona il punto di lettura desiderato (es. *Packaging Line*, *Smart Truck*, *Smart Cabinet*).
4. Clicca su **Start Monitoring** (oppure usa "Start Batch" per avviare la scrittura dei tag) per interagire con i tag RFID.