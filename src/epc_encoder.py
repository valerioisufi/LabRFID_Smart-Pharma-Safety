def encode_sgtin96(gtin: str, serial: int, prefix_length: int = 7) -> str:
    """
    Converts a GS1 GTIN-14 and a serial number into a 96-bit SGTIN EPC Hex String.
    
    Args:
        gtin: 14-digit GTIN string. If shorter, it will be left-padded with zeros.
        serial: Integer serial number (max 38 bits).
        prefix_length: Length of the GS1 Company Prefix (6 to 12).
        
    Returns:
        24-character uppercase Hex string representing the 96-bit EPC.
    """
    gtin = str(gtin).zfill(14)
    
    # GTIN-14 format: Indicator (1) + Company Prefix (L) + Item Ref (12-L) + Check Digit (1)
    indicator = gtin[0]
    company_prefix = gtin[1:1+prefix_length]
    item_ref_part = gtin[1+prefix_length:13]
    item_reference = indicator + item_ref_part
    
    # GS1 Partition Table (Prefix Length -> Partition Value)
    partitions: dict[int, int] = {
        12: 0, 11: 1, 10: 2, 9: 3, 8: 4, 7: 5, 6: 6
    }
    partition: int = partitions.get(prefix_length, 5)
    
    # Bit lengths for (Company Prefix bits, Item Reference bits)
    bits: dict[int, tuple[int, int]] = {
        0: (40, 4), 1: (37, 7), 2: (34, 10), 3: (30, 14),
        4: (27, 17), 5: (24, 20), 6: (20, 24)
    }
    cp_bits, ir_bits = bits[partition]
    
    # Fixed Header and Filter
    header = 0x30 # 8 bits
    filter_val = 1 # 3 bits (1 = Point of Sale item)
    
    cp_int = int(company_prefix)
    ir_int = int(item_reference)
    
    # Build the 96-bit integer using bitwise operations
    epc = (header << 88) | (filter_val << 85) | (partition << 82)
    epc |= (cp_int << (82 - cp_bits))
    epc |= (ir_int << (82 - cp_bits - ir_bits))
    epc |= serial
    
    return f"{epc:024X}"

if __name__ == "__main__":
    # Test encoding
    gtin = "00800123456789" # Company Prefix: 0800123 (7), Item Ref: 45678
    serial = 12345
    print(f"GTIN: {gtin}, Serial: {serial}")
    print(f"EPC Hex: {encode_sgtin96(gtin, serial, prefix_length=7)}")
