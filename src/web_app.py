import asyncio
import collections
import json
import logging
import sys
from typing import List, Any, Optional, Dict, Tuple, Union
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Aggiunge la root del progetto al path di sistema per permettere gli import assoluti
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.reader_module import ReaderManager
from src.middleware import Middleware


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


deque_handler = DequeHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
deque_handler.setFormatter(formatter)
logging.getLogger("src.reader_module").addHandler(deque_handler)
logging.getLogger("src.tertium_serial_handler").addHandler(deque_handler)
logging.getLogger("src.reader_module").setLevel(logging.INFO)
logging.getLogger("src.tertium_serial_handler").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    deque_handler.main_loop = asyncio.get_running_loop()
    yield


app: FastAPI = FastAPI(lifespan=lifespan)

# Configurazione per servire file statici (CSS, JS) e template HTML (Jinja2)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# Stato Globale dell'Applicazione
default_port: str = "/dev/cu.usbserial-1110" if sys.platform == "darwin" else "COM3"
middleware: Middleware = Middleware()
reader_manager: ReaderManager = ReaderManager(port=default_port)
current_read_point: str = "PACKAGING_LINE"
is_monitoring: bool = False
periodic_task: Optional[asyncio.Task[Any]] = None
active_batch_config: Optional[Dict[str, Any]] = None
processed_in_batch: set[str] = set()


# Gestore delle connessioni WebSocket (mantiene vive le connessioni con i client web)
class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass


manager: ConnectionManager = ConnectionManager()


# --- FUNZIONI DI SUPPORTO (HELPER) ---
def get_kpis() -> Dict[str, int]:
    assets = middleware.state_machine.assets.values()
    return {
        "total_assets": len(assets),
        "packed": sum(1 for a in assets if a.get("currentState") == "PACKED"),
        "in_transit": sum(1 for a in assets if a.get("currentState") == "IN_TRANSIT"),
        "in_cabinet": sum(1 for a in assets if a.get("currentState") == "IN_CABINET"),
        "dispensed": sum(1 for a in assets if a.get("currentState") == "DISPENSED"),
        "disposed": sum(1 for a in assets if a.get("currentState") == "DISPOSED"),
        "expired": sum(1 for a in assets if middleware.state_machine._is_expired(a.get("expiryDate")))
    }


async def send_state_update() -> None:
    state: Dict[str, Any] = {
        "type": "state_update",
        "read_point": current_read_point,
        "is_monitoring": is_monitoring,
        "is_connected": reader_manager.is_connected,
        "batch_active": active_batch_config is not None,
        "kpis": get_kpis(),
        "events": middleware.get_all_events()[-50:],  # Invia solo gli ultimi 50 eventi per non appesantire la UI
        "system_logs": list(deque_handler.logs)  # Invia il buffer circolare dei log di sistema
    }
    await manager.broadcast(json.dumps(state))


async def process_and_broadcast_async_read(epc: str) -> None:
    results = middleware.process_reads([epc], current_read_point)
    await manager.broadcast(json.dumps({
        "type": "scan_results",
        "results": results
    }))
    await send_state_update()


def handle_async_read(tag_payload: Union[str, Tuple[str, Any]]) -> None:
    epc = tag_payload[0] if isinstance(tag_payload, tuple) else tag_payload

    # Programma l'esecuzione dell'aggiornamento in modo sicuro sull'event loop principale (dato che veniamo chiamati da un thread in background)
    loop = deque_handler.main_loop
    if loop and loop.is_running():
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(process_and_broadcast_async_read(epc))
        )


from src.epc_encoder import encode_sgtin96


async def periodic_scan_loop():
    global processed_in_batch
    while is_monitoring:
        if current_read_point == "PACKAGING_LINE" and active_batch_config:
            raw_tags = reader_manager.read_tags()
            if raw_tags:
                for tag in raw_tags:
                    # Skip if this tag has already been processed in the current batch run
                    if tag in processed_in_batch:
                        continue

                    # Also skip if the tag already contains an EPC that is registered in our DB for this batch
                    asset = middleware.state_machine.get_asset(tag)
                    if asset and asset.get("batch") == active_batch_config.get("batch"):
                        processed_in_batch.add(tag)
                        continue

                    serial = middleware.state_machine.serial_counter
                    new_epc_hex = encode_sgtin96(
                        active_batch_config.get("gtin", ""),
                        serial, prefix_length=7
                    )
                    # Scrittura fisica
                    retcode = reader_manager.reader.write_memory(
                        epc=tag, data=new_epc_hex, mem_bank="01", address="02", block_num="06", timeout_ms=1000
                    )
                    if retcode == "00":
                        # Mark both the old and new EPCs as processed to prevent loop writing
                        processed_in_batch.add(tag)
                        processed_in_batch.add(new_epc_hex)

                        res = middleware.state_machine.commission_asset(
                            epc=new_epc_hex, gtin=active_batch_config.get("gtin"),
                            batch=active_batch_config.get("batch"), expiry_date=active_batch_config.get("expiry"),
                            aic=active_batch_config.get("aic"), old_epc=tag
                        )
                        await manager.broadcast(json.dumps({"type": "scan_results", "results": [res]}))
                        await send_state_update()
            await asyncio.sleep(0.5)  # Polling veloce per il nastro trasportatore

        elif current_read_point in ["SMART_TRUCK", "SMART_CABINET"]:
            raw_tags = reader_manager.read_tags()
            if raw_tags:
                results = middleware.process_reads(raw_tags, current_read_point)
                await manager.broadcast(json.dumps({
                    "type": "scan_results",
                    "results": results
                }))
                await send_state_update()
            await asyncio.sleep(3)  # Polling lento per l'inventario
        else:
            break


import serial.tools.list_ports


@app.get("/api/ports")
def get_available_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return {"ports": ports}


@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    context = {"request": request, "default_port": default_port}

    # Starlette >= 0.28.0 (FastAPI >= 0.100.0)
    return templates.TemplateResponse(request=request, name="index.html", context=context)

@app.post("/api/connect")
async def toggle_connection(data: dict):
    port = data.get("port", default_port)
    if reader_manager.is_connected:
        global is_monitoring
        is_monitoring = False
        reader_manager.stop_async_reading()
        reader_manager.disconnect()
    else:
        reader_manager.port = port
        reader_manager.connect()
    await send_state_update()
    return {"status": "success"}


@app.post("/api/read_point")
async def set_read_point(data: dict):
    global current_read_point, is_monitoring, active_batch_config
    current_read_point = data.get("read_point", "PACKAGING_LINE")

    # Stop monitoring on context switch
    is_monitoring = False
    active_batch_config = None
    reader_manager.stop_async_reading()
    if reader_manager.is_connected:
        reader_manager.configure_for_read_point(current_read_point)

    await send_state_update()
    return {"status": "success"}


@app.post("/api/monitor")
async def toggle_monitor():
    global is_monitoring, periodic_task

    if not reader_manager.is_connected:
        return {"status": "error", "message": "Reader not connected"}

    is_monitoring = not is_monitoring

    if is_monitoring:
        reader_manager.configure_for_read_point(current_read_point)
        if current_read_point in ["SMART_TRUCK", "SMART_CABINET"]:
            periodic_task = asyncio.create_task(periodic_scan_loop())
        else:
            reader_manager.start_async_reading(handle_async_read)
    else:
        reader_manager.stop_async_reading()
        # periodic_task will stop on its next loop due to `is_monitoring == False`

    await send_state_update()
    return {"status": "success"}


@app.post("/api/start_batch")
async def start_batch(data: dict):
    global active_batch_config, is_monitoring, periodic_task, processed_in_batch

    if not reader_manager.is_connected:
        return {"status": "error", "message": "Reader not connected."}

    active_batch_config = data
    offset = data.get("serial_offset")
    if offset:
        middleware.state_machine.set_serial_counter(offset)

    # Reset processed tags set and populate with existing ones in DB for the same batch
    processed_in_batch = set()
    batch_name = data.get("batch")
    if batch_name:
        for epc, asset in middleware.state_machine.assets.items():
            if asset.get("batch") == batch_name:
                processed_in_batch.add(epc)
                if asset.get("oldEpc"):
                    processed_in_batch.add(asset.get("oldEpc"))

    is_monitoring = True
    reader_manager.stop_async_reading()
    # Force polling mode (00) for continuous safe write
    reader_manager.reader.set_current_mode(mode="00")

    periodic_task = asyncio.create_task(periodic_scan_loop())
    await send_state_update()
    return {"status": "success"}


@app.post("/api/stop_batch")
async def stop_batch():
    global active_batch_config, is_monitoring
    active_batch_config = None
    is_monitoring = False
    await send_state_update()
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
