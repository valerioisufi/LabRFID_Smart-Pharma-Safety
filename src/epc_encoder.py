def encode_sgtin96(gtin: str, serial: int, prefix_length: int = 7) -> str:
    """
    Converte un codice GS1 GTIN-14 e un numero seriale in una stringa esadecimale EPC SGTIN a 96 bit.
    
    Argomenti:
        gtin: Stringa GTIN a 14 cifre. Se più corta, verrà riempita con zeri a sinistra.
        serial: Numero seriale intero (massimo 38 bit).
        prefix_length: Lunghezza del prefisso aziendale GS1 (da 6 a 12).
        
    Ritorna:
        Una stringa esadecimale di 24 caratteri maiuscoli che rappresenta l'EPC a 96 bit.
    """
    gtin = str(gtin).zfill(14)
    
    # Formato del GTIN-14: Indicatore (1 cifra) + Prefisso Aziendale (L) + Riferimento Articolo (12-L) + Cifra di Controllo (1)
    indicator = gtin[0]
    company_prefix = gtin[1:1+prefix_length]
    item_ref_part = gtin[1+prefix_length:13]
    item_reference = indicator + item_ref_part
    
    # Tabella di partizione GS1 (Lunghezza Prefisso -> Valore di Partizione)
    # Serve per indicare al lettore come decodificare l'EPC per capire dove finisce il prefisso azienda e inizia l'articolo
    partitions: dict[int, int] = {
        12: 0, 11: 1, 10: 2, 9: 3, 8: 4, 7: 5, 6: 6
    }
    partition: int = partitions.get(prefix_length, 5)
    
    # Numero di bit assegnati per (Bit del Prefisso Aziendale, Bit del Riferimento Articolo) in base alla partizione
    bits: dict[int, tuple[int, int]] = {
        0: (40, 4), 1: (37, 7), 2: (34, 10), 3: (30, 14),
        4: (27, 17), 5: (24, 20), 6: (20, 24)
    }
    cp_bits, ir_bits = bits[partition]
    
    # Intestazione e Filtro fissi per lo standard SGTIN-96
    header = 0x30 # 8 bit (Indica che si tratta di un tag SGTIN-96)
    filter_val = 1 # 3 bit (1 = Articolo destinato al punto vendita/Point of Sale)
    
    cp_int = int(company_prefix)
    ir_int = int(item_reference)
    
    # Costruisce l'intero a 96 bit usando operazioni bit a bit (shift a sinistra ed OR)
    # L'ordine è: Header (8) | Filtro (3) | Partizione (3) | Prefisso Azienda (var) | Riferimento Articolo (var) | Seriale (38)
    epc = (header << 88) | (filter_val << 85) | (partition << 82)
    epc |= (cp_int << (82 - cp_bits))
    epc |= (ir_int << (82 - cp_bits - ir_bits))
    epc |= serial
    
    return f"{epc:024X}"

if __name__ == "__main__":
    # Test di codifica base per verificare che l'algoritmo funzioni correttamente
    gtin = "00800123456789" # Prefisso Azienda: 0800123 (7), Rif. Articolo: 45678
    serial = 12345
    print(f"GTIN: {gtin}, Serial: {serial}")
    print(f"EPC Hex: {encode_sgtin96(gtin, serial, prefix_length=7)}")
