import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import os
import sys

# Add the project root to sys.path so 'src' can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.reader_module import ReaderManager
from src.middleware import Middleware

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class SmartPharmaApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("LabRFID Smart Pharma - CustomTkinter")
        self.geometry("1100x700")

        self.middleware = Middleware()
        self.reader_manager = ReaderManager()
        
        self.current_read_point = "PACKAGING_LINE"
        self.is_monitoring = False
        self.periodic_timer_id = None

        self._build_ui()
        self._switch_context("PACKAGING_LINE")

    def _build_ui(self):
        # Configure grid layout (1x2)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- SIDEBAR ---
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(6, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="Smart Pharma", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.port_entry = ctk.CTkEntry(self.sidebar_frame, placeholder_text="Porta COM (es. COM3)")
        self.port_entry.insert(0, "COM3")
        self.port_entry.grid(row=1, column=0, padx=20, pady=10)

        self.connect_btn = ctk.CTkButton(self.sidebar_frame, text="Connetti Reader", command=self.toggle_connection)
        self.connect_btn.grid(row=2, column=0, padx=20, pady=10)

        self.read_point_menu = ctk.CTkOptionMenu(
            self.sidebar_frame, 
            values=["PACKAGING_LINE", "SMART_TRUCK", "SMART_CABINET", "DESK", "WASTE_CONTAINER"],
            command=self._switch_context
        )
        self.read_point_menu.grid(row=3, column=0, padx=20, pady=20)

        self.monitor_btn = ctk.CTkButton(self.sidebar_frame, text="▶ Avvia Monitoraggio", command=self.toggle_monitoring, fg_color="green")
        self.monitor_btn.grid(row=4, column=0, padx=20, pady=10)

        # --- MAIN AREA ---
        self.main_container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_container.grid_rowconfigure(1, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)

        # Top area for KPIs and specific context UI
        self.context_frame = ctk.CTkFrame(self.main_container)
        self.context_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 20))

        # Bottom area for log
        self.log_frame = ctk.CTkFrame(self.main_container)
        self.log_frame.grid(row=1, column=0, sticky="nsew")
        self.log_frame.grid_rowconfigure(1, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.log_frame, text="📜 Log Eventi", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=10)
        
        # Setup Treeview for logs
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", rowheight=25, fieldbackground="#2b2b2b")
        style.map('Treeview', background=[('selected', '#1f538d')])
        
        self.tree = ttk.Treeview(self.log_frame, columns=("Time", "EPC", "ReadPoint", "Action", "State", "Alerts"), show="headings")
        self.tree.heading("Time", text="Timestamp")
        self.tree.heading("EPC", text="EPC")
        self.tree.heading("ReadPoint", text="Read Point")
        self.tree.heading("Action", text="Action")
        self.tree.heading("State", text="State")
        self.tree.heading("Alerts", text="Alerts")
        
        self.tree.column("Time", width=150)
        self.tree.column("EPC", width=150)
        self.tree.column("ReadPoint", width=120)
        self.tree.column("Action", width=100)
        self.tree.column("State", width=100)
        self.tree.column("Alerts", width=200)
        
        self.tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.refresh_log()

    def toggle_connection(self):
        if self.reader_manager.is_connected:
            self.stop_monitoring()
            self.reader_manager.disconnect()
            self.connect_btn.configure(text="Connetti Reader")
        else:
            self.reader_manager.port = self.port_entry.get()
            if self.reader_manager.connect():
                self.connect_btn.configure(text="Disconnetti")
                self.reader_manager.configure_for_read_point(self.current_read_point)

    def toggle_monitoring(self):
        if not self.reader_manager.is_connected:
            return

        if self.is_monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        self.is_monitoring = True
        self.monitor_btn.configure(text="⏹ Ferma Monitoraggio", fg_color="red")
        
        # Setup reader mode
        self.reader_manager.configure_for_read_point(self.current_read_point)
        
        if self.current_read_point in ["SMART_TRUCK", "SMART_CABINET"]:
            self.periodic_scan()
        else:
            self.reader_manager.start_async_reading(self.handle_async_read)

    def stop_monitoring(self):
        self.is_monitoring = False
        self.monitor_btn.configure(text="▶ Avvia Monitoraggio", fg_color="green")
        
        if self.periodic_timer_id:
            self.after_cancel(self.periodic_timer_id)
            self.periodic_timer_id = None
            
        self.reader_manager.stop_async_reading()

    def handle_async_read(self, tag_payload):
        # Called from background thread! Use .after to update GUI
        # tag_payload can be tuple (epc, rssi) or just epc
        epc = tag_payload[0] if isinstance(tag_payload, tuple) else tag_payload
        self.after(0, self.process_reads_gui, [epc])

    def periodic_scan(self):
        if not self.is_monitoring:
            return
            
        raw_tags = self.reader_manager.read_tags()
        if raw_tags:
            self.process_reads_gui(raw_tags)
            
        # Schedule next scan
        self.periodic_timer_id = self.after(3000, self.periodic_scan)

    def process_reads_gui(self, raw_epcs):
        results = self.middleware.process_reads(raw_epcs, self.current_read_point)
        self.refresh_log()
        self._render_context_kpis() # Update numbers

    def refresh_log(self):
        # Clear tree
        for i in self.tree.get_children():
            self.tree.delete(i)
            
        events = self.middleware.get_all_events()
        for e in reversed(events):
            alerts = ", ".join(e.get("alerts", [])) if e.get("alerts") else "OK"
            item = self.tree.insert("", "end", values=(
                e["timestamp"], e["epc"], e["readPoint"], e["action"], e["newState"], alerts
            ))
            if alerts != "OK":
                self.tree.item(item, tags=('alert',))
                
        self.tree.tag_configure('alert', background='#ffcccc', foreground='black')

    def _switch_context(self, new_context):
        if self.is_monitoring:
            self.stop_monitoring()
            
        self.current_read_point = new_context
        if self.reader_manager.is_connected:
            self.reader_manager.configure_for_read_point(new_context)
            
        self._render_context_kpis()

    def _render_context_kpis(self):
        # Clear context frame
        for widget in self.context_frame.winfo_children():
            widget.destroy()
            
        assets = self.middleware.state_machine.assets.values()
        
        self.context_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        title = ctk.CTkLabel(self.context_frame, text=f"📍 {self.current_read_point}", font=ctk.CTkFont(size=24, weight="bold"))
        title.grid(row=0, column=0, columnspan=3, pady=10)

        if self.current_read_point == "PACKAGING_LINE":
            packed = sum(1 for a in assets if a.get("currentState") == "PACKED")
            self._create_kpi_box(0, 1, "📦 TOT ASSETS IN DB", len(assets))
            self._create_kpi_box(1, 1, "🟢 PACKED", packed)
            self._create_kpi_box(2, 1, "Mode", "Continuous Async")
        elif self.current_read_point == "SMART_TRUCK":
            in_transit = sum(1 for a in assets if a.get("currentState") == "IN_TRANSIT")
            self._create_kpi_box(0, 1, "🚚 IN TRANSIT", in_transit)
            self._create_kpi_box(1, 1, "Mode", "Periodic Polling")
        elif self.current_read_point == "SMART_CABINET":
            in_cab = sum(1 for a in assets if a.get("currentState") == "IN_CABINET")
            exp = sum(1 for a in assets if self.middleware.state_machine._is_expired(a.get("expiryDate")))
            self._create_kpi_box(0, 1, "🏥 IN CABINET", in_cab)
            self._create_kpi_box(1, 1, "⚠️ EXPIRED", exp)
            self._create_kpi_box(2, 1, "Mode", "Periodic Polling")
        elif self.current_read_point == "DESK":
            disp = sum(1 for a in assets if a.get("currentState") == "DISPENSED")
            self._create_kpi_box(0, 1, "✅ DISPENSED", disp)
            self._create_kpi_box(1, 1, "Mode", "Continuous Async")
        elif self.current_read_point == "WASTE_CONTAINER":
            disp = sum(1 for a in assets if a.get("currentState") == "DISPOSED")
            self._create_kpi_box(0, 1, "🗑️ DISPOSED", disp)
            self._create_kpi_box(1, 1, "Mode", "Continuous Async")

    def _create_kpi_box(self, col, row, title, value):
        frame = ctk.CTkFrame(self.context_frame)
        frame.grid(row=row, column=col, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=14)).pack(pady=(10, 0))
        ctk.CTkLabel(frame, text=str(value), font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(0, 10))

if __name__ == "__main__":
    app = SmartPharmaApp()
    app.mainloop()
