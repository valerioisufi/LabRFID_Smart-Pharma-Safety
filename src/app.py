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
    return ReaderManager(use_mock=True)

middleware = get_middleware()
reader_manager = get_reader_manager()

# --- KPI CALCULATIONS ---
def get_kpis():
    assets = middleware.state_machine.assets.values()
    kpis = {
        "total_assets": len(assets),
        "packed": sum(1 for a in assets if a.get("currentState") == "PACKED"),
        "in_transit": sum(1 for a in assets if a.get("currentState") == "IN_TRANSIT"),
        "in_cabinet": sum(1 for a in assets if a.get("currentState") == "IN_CABINET"),
        "dispensed": sum(1 for a in assets if a.get("currentState") == "DISPENSED"),
        "disposed": sum(1 for a in assets if a.get("currentState") == "DISPOSED"),
        "expired": sum(1 for a in assets if middleware.state_machine._is_expired(a.get("expiryDate")))
    }
    return kpis

# --- RENDER FUNCTIONS ---
def perform_scan(read_point):
    with st.spinner("Scansione in corso..."):
        raw_tags = reader_manager.read_tags()
        if not raw_tags and read_point == "PACKAGING_LINE" and reader_manager.use_mock:
            import uuid
            raw_tags = [f"PHARMA-{str(uuid.uuid4().int)[:4]}"]
        elif not raw_tags:
            st.info("Nessun tag rilevato in questo momento.")
            return []
        
        return middleware.process_reads(raw_tags, read_point)

def display_results(results, cols_count=3):
    if not results: return
    cols = st.columns(cols_count)
    for i, res in enumerate(results):
        col = cols[i % cols_count]
        with col:
            asset = res.get('asset')
            if not asset:
                st.error(f"❌ EPC Sconosciuto: {res.get('message')}")
                continue
                
            status_color = "🟢" if res['status'] == "OK" else "🔴"
            with st.container(border=True):
                st.markdown(f"#### {status_color} {asset['epc']}")
                st.markdown(f"**Lotto:** `{asset['batch']}`")
                st.markdown(f"**Scad:** `{asset['expiryDate']}`")
                st.markdown(f"**Stato:** `{asset['currentState']}`")
                
                if res['status'] == "ALERT":
                    st.error(res['message'])
                else:
                    st.success(res['message'])

def render_packaging_line():
    st.markdown("<h1>⚙️ PACKAGING LINE TERMINAL</h1>", unsafe_allow_html=True)
    st.markdown("---")
    kpis = get_kpis()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("📦 TOT ASSETS IN DB", kpis['total_assets'])
    col2.metric("🟢 PACKED TODAY", kpis['packed'])
    col3.metric("🔌 SYSTEM STATUS", "ONLINE")
    st.markdown("---")
    
    if st.button("▶ EXECUTE COMMISSIONING CYCLE", use_container_width=True, type="primary"):
        results = perform_scan("PACKAGING_LINE")
        display_results(results, 4)

def render_smart_truck():
    st.markdown("<h1>🚛 SMART TRUCK - LOGISTICS DASHBOARD</h1>", unsafe_allow_html=True)
    st.markdown("---")
    kpis = get_kpis()
    
    col1, col2 = st.columns(2)
    col1.metric("📦 BATCHES IN TRANSIT", kpis['in_transit'])
    col2.metric("📍 NEXT STOP", "Central Pharmacy")
    st.markdown("---")
    
    if st.button("📡 SCAN FREIGHT", use_container_width=True, type="primary"):
        results = perform_scan("SMART_TRUCK")
        display_results(results)

def render_smart_cabinet():
    st.markdown("<h1>🏥 SMART CABINET - WARD INVENTORY</h1>", unsafe_allow_html=True)
    st.markdown("---")
    kpis = get_kpis()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("💊 IN CABINET", kpis['in_cabinet'])
    col2.metric("⚠️ EXPIRED", kpis['expired'], delta_color="inverse")
    col3.metric("🔄 LAST SYNC", "Just Now")
    st.markdown("---")
    
    if st.button("🔄 RUN INVENTORY SCAN", use_container_width=True, type="primary"):
        results = perform_scan("SMART_CABINET")
        display_results(results)

def render_desk():
    st.markdown("<h1>⚕️ PHARMACY DESK - POINT OF CARE</h1>", unsafe_allow_html=True)
    st.markdown("---")
    kpis = get_kpis()
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.info("Appoggia il farmaco sul pad RFID per la validazione prima di consegnarlo al paziente.")
    with col2:
        st.metric("✅ Totale Erogati", kpis['dispensed'])
    
    st.markdown("---")
    if st.button("✅ VERIFICA ED EROGA FARMACO", use_container_width=True, type="primary"):
        results = perform_scan("DESK")
        display_results(results, 2)

def render_waste_container():
    st.markdown("<h1>🗑️ WASTE CONTAINER - DISPOSAL</h1>", unsafe_allow_html=True)
    st.markdown("---")
    kpis = get_kpis()
    
    st.metric("☣️ TOTAL DISPOSED", kpis['disposed'])
    st.markdown("---")
    
    if st.button("☣️ SCAN & DISPOSE", use_container_width=True, type="primary"):
        results = perform_scan("WASTE_CONTAINER")
        display_results(results)

# --- SIDEBAR (Control Panel) ---
st.sidebar.title("Pannello di Controllo")

st.sidebar.subheader("Hardware Reader")
use_mock = st.sidebar.checkbox("Usa Mock Reader (Simulatore)", value=reader_manager.use_mock)
if use_mock != reader_manager.use_mock:
    reader_manager.use_mock = use_mock
    reader_manager.disconnect()

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

reader_manager.configure_for_read_point(selected_read_point)

st.sidebar.markdown("---")
st.sidebar.subheader("Eventi Esterni (Simulazione)")
if st.sidebar.button("Simula Scatto Mezzanotte (Scadenza)"):
    msg = middleware.trigger_external_event("SIMULATE_MIDNIGHT")
    st.sidebar.warning(msg)
    
if st.sidebar.button("Simula Ritiro Lotto (Blacklist)"):
    msg = middleware.trigger_external_event("WITHDRAW_LOT")
    st.sidebar.error(msg)


# --- MAIN LOGIC ---
if selected_read_point == "PACKAGING_LINE":
    render_packaging_line()
elif selected_read_point == "SMART_TRUCK":
    render_smart_truck()
elif selected_read_point == "SMART_CABINET":
    render_smart_cabinet()
elif selected_read_point == "DESK":
    render_desk()
elif selected_read_point == "WASTE_CONTAINER":
    render_waste_container()

# --- HISTORY LOG ---
st.markdown("---")
st.subheader("📜 Log di Filiera (Storico Eventi)")

events = middleware.get_all_events()

if events:
    events_reversed = list(reversed(events))
    df_data = []
    for e in events_reversed:
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
    
    def highlight_alerts(row):
        if row['Esito / Alert'] != "OK":
            return ['background-color: rgba(255, 0, 0, 0.2)'] * len(row)
        return [''] * len(row)
        
    st.dataframe(df.style.apply(highlight_alerts, axis=1), use_container_width=True)
else:
    st.info("Nessun evento registrato finora.")
