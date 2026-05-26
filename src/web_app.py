import asyncio
import json
import os
import sys
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.reader_module import ReaderManager
from src.middleware import Middleware

app = FastAPI()

# Setup static files and templates
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Global State
middleware = Middleware()
reader_manager = ReaderManager(port="COM3")
current_read_point = "PACKAGING_LINE"
is_monitoring = False
periodic_task = None

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

# --- HELPER FUNCTIONS ---
def get_kpis():
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

async def send_state_update():
    state = {
        "type": "state_update",
        "read_point": current_read_point,
        "is_monitoring": is_monitoring,
        "is_connected": reader_manager.is_connected,
        "kpis": get_kpis(),
        "events": middleware.get_all_events()[-50:] # Send last 50 events
    }
    await manager.broadcast(json.dumps(state))

def handle_async_read(tag_payload):
    epc = tag_payload[0] if isinstance(tag_payload, tuple) else tag_payload
    results = middleware.process_reads([epc], current_read_point)
    
    # Broadcast results and new state
    asyncio.run(manager.broadcast(json.dumps({
        "type": "scan_results",
        "results": results
    })))
    asyncio.run(send_state_update())

async def periodic_scan_loop():
    while is_monitoring and current_read_point in ["SMART_TRUCK", "SMART_CABINET"]:
        raw_tags = reader_manager.read_tags()
        if raw_tags:
            results = middleware.process_reads(raw_tags, current_read_point)
            await manager.broadcast(json.dumps({
                "type": "scan_results",
                "results": results
            }))
            await send_state_update()
        await asyncio.sleep(3)

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/connect")
async def toggle_connection(data: dict):
    port = data.get("port", "COM3")
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
    global current_read_point, is_monitoring
    current_read_point = data.get("read_point", "PACKAGING_LINE")
    
    # Stop monitoring on context switch
    is_monitoring = False
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
