# PACKAGING LINE
# scriviamo epc, data di scadenza, lotto, e numero di serie in un tag, e poi leggiamo i dati per verificarli
# stato in codice numerico
# leggiamo TID, facciamo associazione tra TID ed EPC

# SMART TRUCK
# inventory, cambiamo lo stato in DISTRIBUTED, leggiamo il TID e verifichiamo la corrispondenza

# SMART CABINET
# inventory, cambiamo lo stato in STORED, leggiamo il TID e verifichiamo la corrispondenza
# leggiamo la data di scadenza, se è prossima, inviamo un alert -> EXPIRED
# leggiamo il numero di lotto, se è presente in una blacklist, inviamo un alert
# verifica che il farmaco non sia stato prelevato senza passare per la cassa, se è stato prelevato senza passare per la cassa, inviamo un alert

# DESK
# verifica data di scadenza e lotto e nel caso impediamo la vendita del farmaco
# cambia lo stato in DISPENSED

# WASTE CONTAINER
# cestino con piano di appoggio che si apre dopo la lettura del prodotto appoggiato su di esso
# il tag passa allo stato DISPOSED



