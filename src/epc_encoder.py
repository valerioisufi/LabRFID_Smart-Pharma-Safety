import datetime
import logging

logger = logging.getLogger(__name__)

def encode_dsgtin128(gtin: str, serial, expiry_date: datetime.date, filter_value: int = 1,
                     serial_hex_digits: int = 8) -> str:
    """
    Codifica un DSGTIN+ (Date-prioritized SGTIN) a 128 bit.
    Questo formato è ideale per la filiera dei deperibili, in quanto espone la data
    nelle prime porzioni del codice binario permettendo il filtraggio hardware (FEFO).

    Argomenti:
        gtin: Stringa GTIN a 14 cifre.
        serial: Valore numerico del seriale (il contatore). Viene codificato come esadecimale
                maiuscolo a larghezza fissa con zeri iniziali (vedi serial_hex_digits).
        expiry_date: Data di scadenza.
        filter_value: Valore di filtro (default 1 per Point-of-Sale).
        serial_hex_digits: Numero di cifre esadecimali del seriale (default 8 = 32 bit). Con il
                GTIN a 56 bit, 8 cifre producono un EPC di esattamente 128 bit senza padding.

    Ritorna:
        Una stringa esadecimale di 32 caratteri che rappresenta l'EPC a 128 bit.
    """
    gtin = str(gtin).zfill(14)

    # Serial Number: codifica "variable-length upper case hexadecimal" (Encoding Indicator 1 = 001,
    # 4 bit per cifra) con zeri iniziali a larghezza fissa. Il seriale in ingresso è il valore
    # numerico del contatore, reso come esadecimale maiuscolo zero-padded a serial_hex_digits cifre.
    serial_val = int(serial)
    serial = format(serial_val, f"0{serial_hex_digits}X")
    length_ind = len(serial)
    enc_ind = 1
    bits_per_char = 4

    # 1. Header (8 bit) per DSGTIN+ è 11111011 (0xFB)
    epc = 0xFB

    # 2. +AIDC Indicator (1 bit)
    epc = (epc << 1) | 0

    # 3. Filter Value (3 bit)
    epc = (epc << 3) | filter_value

    # 4. Date Indicator (4 bit) - 0100 (4) indica Expiration Date
    epc = (epc << 4) | 4

    # 5. Date (16 bit) - Formato YYMMDD compresso: (Year << 9) | (Month << 5) | Day
    if isinstance(expiry_date, str):
        try:
            expiry_date = datetime.datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            pass
    year = expiry_date.year % 100
    month = expiry_date.month
    day = expiry_date.day
    date_bits = (year << 9) | (month << 5) | day
    epc = (epc << 16) | date_bits

    # 6. GTIN-14 (56 bit) in BCD: ogni cifra decimale è un nibble da 4 bit. Conforme a GS1 TDS 2.0,
    #    che per i "+schemi" (SGTIN+/DSGTIN+) abbandona la partizione e codifica il GTIN-14 a
    #    lunghezza fissa (14 cifre x 4 bit). Niente rischio di overflow: ogni cifra è indipendente.
    gtin_bcd = 0
    for ch in gtin:
        gtin_bcd = (gtin_bcd << 4) | int(ch)
    epc = (epc << 56) | gtin_bcd

    # 7. Encoding Indicator (3 bit)
    epc = (epc << 3) | enc_ind

    # 8. Length Indicator (5 bit)
    epc = (epc << 5) | length_ind

    # 9. Serial Number (variabile)
    epc = (epc << (length_ind * bits_per_char)) | serial_val

    # 10. Padding (riempimento con zeri fino a raggiungere 128 bit, o successivi multipli di 16)
    #     Parte fissa = 8+1+3+4+16+56+3+5 = 96 bit, più il seriale variabile.
    current_bits = 96 + (length_ind * bits_per_char)
    target_bits = max(128, ((current_bits + 15) // 16) * 16)
    padding_bits = target_bits - current_bits

    if padding_bits > 0:
        epc = (epc << padding_bits)

    hex_chars = target_bits // 4
    return f"{epc:0{hex_chars}X}"

if __name__ == "__main__":
    # Test di codifica base per verificare che l'algoritmo funzioni correttamente
    gtin = "00614141999996"
    serial_hex = "00000001"
    exp_date = datetime.date(2022, 7, 24)

    logger.info("--- DSGTIN+ 128-bit ---")
    logger.info(f"GTIN: {gtin}, Serial: {serial_hex}, Expiry: {exp_date}")
    logger.info(f"EPC Hex: {encode_dsgtin128(gtin, serial_hex, exp_date)}")
