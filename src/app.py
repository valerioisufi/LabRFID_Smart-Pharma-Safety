import streamlit as st
import pandas as pd
import time
import os
import sys

# Add the project root to sys.path so 'src' can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import modules
from src.reader_module import ReaderManager
from src.middleware import Middleware

st.set_page_config(page_title="LabRFID Smart Pharma", layout="wide")

# --- INITIALIZATION ---
@st.cache_resource
def get_middleware():
    return Middleware()

@st.cache_resource
def get_reader_manager():
    return ReaderManager(use_mock=True) # Defaulting to Mock for safety, can be toggled

middleware = get_middleware()
reader_manager = get_reader_manager()

# --- SIDEBAR (Control Panel) ---
st.sidebar.title("Pannello di Controllo")

st.sidebar.subheader("Hardware Reader")
use_mock = st.sidebar.checkbox("Usa Mock Reader (Simulatore)", value=reader_manager.use_mock)
if use_mock != reader_manager.use_mock:
    reader_manager.use_mock = use_mock
    reader_manager.disconnect() # Force reconnect on next try

port = st.sidebar.text_input("Porta COM", value="COM3")
reader_manager.port = port

if not reader_manager.is_connected:
    if st.sidebar.button("Connetti Reader"):
        success = reader_manager.connect()
        if success:
            st.sidebar.success("Connesso!")
        else:
            st.sidebar.error("Errore di connessione.")
else:
    st.sidebar.success("Reader Connesso")
    if st.sidebar.button("Disconnetti"):
        reader_manager.disconnect()

st.sidebar.markdown("---")

st.sidebar.subheader("Scenario / Read Point")
read_points = ["PACKAGING_LINE", "SMART_TRUCK", "SMART_CABINET", "DESK", "WASTE_CONTAINER"]
selected_read_point = st.sidebar.selectbox("Seleziona Read Point Attivo", read_points)

# Configure reader power based on read point
reader_manager.configure_for_read_point(selected_read_point)

st.sidebar.markdown("---")
st.sidebar.subheader("Eventi Esterni (Simulazione)")
if st.sidebar.button("Simula Scatto Mezzanotte (Scadenza)"):
    msg = middleware.trigger_external_event("SIMULATE_MIDNIGHT")
    st.sidebar.warning(msg)
    
if st.sidebar.button("Simula Ritiro Lotto (Blacklist)"):
    msg = middleware.trigger_external_event("WITHDRAW_LOT")
    st.sidebar.error(msg)

# --- MAIN DASHBOARD ---
st.title("🛡️ Smart Pharma Safety - RFID Traceability")
st.markdown("Monitoraggio in tempo reale della filiera farmaceutica tramite tecnologia EPC Gen2.")

# Action trigger
st.subheader(f"📍 Read Point Attuale: {selected_read_point}")
if st.button("📡 Esegui Lettura (Scan)", use_container_width=True, type="primary"):
    with st.spinner("Scansione in corso..."):
        # Perform read
        raw_tags = reader_manager.read_tags()
        
        if not raw_tags:
            if selected_read_point == "PACKAGING_LINE" and reader_manager.use_mock:
                # In mock packaging line, force creation of a new random tag if nothing is read
                import uuid
                raw_tags = [f"PHARMA-{str(uuid.uuid4().int)[:4]}"]
            else:
                st.info("Nessun tag rilevato in questo momento.")
        
        # Process reads
        if raw_tags:
            results = middleware.process_reads(raw_tags, selected_read_point)
            
            # Display results
            st.markdown("### 🏷️ Dettaglio Letture Correnti")
            cols = st.columns(len(results) if len(results) < 4 else 3)
            
            for i, res in enumerate(results):
                col = cols[i % len(cols)]
                with col:
                    asset = res.get('asset')
                    if not asset:
                        st.error(f"❌ EPC non valido o sconosciuto: {res.get('message')}")
                        continue
                        
                    status_color = "🟢" if res['status'] == "OK" else "🔴"
                    
                    with st.container(border=True):
                        st.markdown(f"#### {status_color} {asset['epc']}")
                        st.markdown(f"**Lotto:** `{asset['batch']}`")
                        st.markdown(f"**Scadenza:** `{asset['expiryDate']}`")
                        st.markdown(f"**Stato:** `{asset['currentState']}`")
                        
                        if res['status'] == "ALERT":
                            st.error(res['message'])
                        else:
                            st.success(res['message'])

# --- HISTORY LOG ---
st.markdown("---")
st.subheader("📜 Log di Filiera (Storico Eventi)")

events = middleware.get_all_events()

if events:
    # Reverse events to show newest first
    events_reversed = list(reversed(events))
    
    # Format for DataFrame
    df_data = []
    for e in events_reversed:
        # Format alerts
        alerts_str = ", ".join(e.get("alerts", [])) if e.get("alerts") else "OK"
        
        df_data.append({
            "Timestamp": e["timestamp"],
            "EPC": e["epc"],
            "Read Point": e["readPoint"],
            "Azione": e["action"],
            "Stato": e["newState"],
            "Esito / Alert": alerts_str
        })
        
    df = pd.DataFrame(df_data)
    
    # Highlight rows with alerts
    def highlight_alerts(row):
        if row['Esito / Alert'] != "OK":
            return ['background-color: rgba(255, 0, 0, 0.2)'] * len(row)
        return [''] * len(row)
        
    st.dataframe(df.style.apply(highlight_alerts, axis=1), use_container_width=True)
else:
    st.info("Nessun evento registrato finora.")
