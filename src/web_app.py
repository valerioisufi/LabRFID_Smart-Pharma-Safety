import asyncio
import collections
import json
import logging
import sys
from typing import List, Any, Dict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Aggiunge la root del progetto al path di sistema per permettere gli import assoluti
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.middleware import Middleware
import serial.tools.list_ports

# Handler personalizzato per il logging: cattura i log di sistema per inviarli alla UI Web in tempo reale
class DequeHandler(logging.Handler):
    def __init__(self, maxlen=100):
        super().__init__()
        self.logs = collections.deque(maxlen=maxlen)
        self.main_loop = None

    def emit(self, record):
        try:
            msg = self.format(record)
            self.logs.append(msg)
            if self.main_loop and self.main_loop.is_running():
                self.main_loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(manager.broadcast(json.dumps({
                        "type": "new_system_log",
                        "log": msg,
                        "level": record.levelname
                    })))
                )
        except Exception:
            pass

class AppLogFilter(logging.Filter):
    def filter(self, record):
        if record.name.startswith("src.tertium_serial_handler"):
            return False
        return True

deque_handler = DequeHandler()
formatter = logging.Formatter('%(asctime)s - [%(name)s] %(levelname)s - %(message)s')
deque_handler.setFormatter(formatter)
deque_handler.addFilter(AppLogFilter())

src_logger = logging.getLogger("src")
src_logger.setLevel(logging.DEBUG)
src_logger.addHandler(deque_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup loop on startup
    main_loop = asyncio.get_running_loop()
    deque_handler.main_loop = main_loop
    middleware.set_loop(main_loop)
    yield
    # Cleanup on shutdown se necessario
    middleware.disconnect()


app: FastAPI = FastAPI(lifespan=lifespan)

# Configurazione per servire file statici (CSS, JS) e template HTML (Jinja2)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# Stato Globale dell'Applicazione: auto-rileva la prima porta seriale disponibile (cross-platform),
# così il default funziona su macOS/Linux (/dev/cu.usbserial-*, /dev/ttyUSB*) e non solo su Windows.
default_port: str = next((p.device for p in serial.tools.list_ports.comports()), "")

# Gestore delle connessioni WebSocket (mantiene vive le connessioni con i client web)
class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager: ConnectionManager = ConnectionManager()

# Inizializzazione del Middleware (ora funge da orchestratore centrale)
middleware: Middleware = Middleware(port=default_port)


# --- FUNZIONI DI SUPPORTO (HELPER) ---

def handle_state_update():
    """Callback chiamata dal Middleware quando cambia lo stato."""
    loop = deque_handler.main_loop
    if loop and loop.is_running():
        loop.call_soon_threadsafe(
            lambda: loop.create_task(send_state_update())
        )

def handle_scan_results(results: list[dict[str, Any]]):
    """Callback chiamata dal Middleware quando ci sono risultati di scansione."""
    loop = deque_handler.main_loop
    if loop and loop.is_running():
        loop.call_soon_threadsafe(
            lambda: loop.create_task(manager.broadcast(json.dumps({
                "type": "scan_results",
                "results": results
            })))
        )

# Registra i callback
middleware.on_state_update = handle_state_update
middleware.on_scan_results = handle_scan_results

async def send_state_update() -> None:
    """Invia l'intero stato dell'applicazione alla UI via WebSocket."""
    state: Dict[str, Any] = {
        "type": "state_update",
        "read_point": middleware.current_read_point,
        "is_monitoring": middleware.is_monitoring,
        "is_connected": middleware.is_connected,
        "batch_active": middleware.active_batch_config is not None,
        "kpis": middleware.get_kpis(),
        "events": middleware.get_all_events()[-50:],
        "system_logs": list(deque_handler.logs),
        "simulation_settings": {
            "simulated_date": middleware.state_machine.simulated_date or "",
            "blacklisted_batches": ",".join(middleware.state_machine.blacklisted_batches)
        }
    }
    await manager.broadcast(json.dumps(state))

# --- ROUTES ---

@app.get("/api/ports")
def get_available_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return {"ports": ports}

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    context = {"request": request, "default_port": default_port}
    return templates.TemplateResponse(request=request, name="index.html", context=context)

@app.post("/api/connect")
async def toggle_connection(data: dict):
    port = data.get("port", default_port)
    if middleware.is_connected:
        middleware.disconnect()
    else:
        middleware.connect(port)
    return {"status": "success"}

@app.post("/api/read_point")
async def set_read_point(data: dict):
    read_point = data.get("read_point", "PACKAGING_LINE")
    middleware.set_read_point(read_point)
    return {"status": "success"}

@app.post("/api/monitor")
async def toggle_monitor():
    if not middleware.is_connected:
        return {"status": "error", "message": "Reader not connected"}

    if middleware.is_monitoring:
        middleware.stop_monitoring()
    else:
        middleware.start_monitoring()

    return {"status": "success"}

@app.post("/api/start_batch")
async def start_batch(data: dict):
    if not middleware.is_connected:
        return {"status": "error", "message": "Reader not connected."}
    
    print("Starting batch with config:", data)

    success = middleware.start_batch(data)
    if not success:
        return {"status": "error", "message": "Failed to start batch."}
    return {"status": "success"}

@app.post("/api/stop_batch")
async def stop_batch():
    middleware.stop_batch()
    return {"status": "success"}

@app.post("/api/simulation_settings")
async def simulation_settings(data: dict):
    simulated_date = data.get("simulated_date")
    blacklisted_batches = data.get("blacklisted_batches", "")
    middleware.set_simulation_settings(simulated_date, blacklisted_batches)
    return {"status": "success"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await send_state_update()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
