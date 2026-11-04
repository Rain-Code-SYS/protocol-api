import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# โหลด Protocol SDK Client (ถ้ามี)
try:
    from protocol_sdk.client import ProtocolClient
    client = ProtocolClient()
except ImportError:
    client = None

app = FastAPI(
    title="Haptic Medical Simulation & Protocol Schema API",
    description="Backend API for Trig Protocols, Schema Management, and UI Integration",
    version="1.0.0"
)

# ---------------------------------------------------------
# 1. ค้นหาโฟลเดอร์ UI สำหรับไฟล์ Static และ HTML
# ---------------------------------------------------------
base_dir = os.path.dirname(__file__)
possible_ui_paths = [
    os.path.join(base_dir, "protocol-api", "ui"),
    os.path.join(base_dir, "ui")
]

UI_DIR = None
for path in possible_ui_paths:
    if os.path.exists(path):
        UI_DIR = path
        break

# ---------------------------------------------------------
# 2. ตั้งค่า CORS Middleware
# ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 3. Schema API Database & Models (จัดการ Protocol Schema)
# ---------------------------------------------------------
DB_FILE = "protocols.json"

def load_db() -> Dict[str, dict]:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_db(data: Dict[str, dict]):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

protocols_db: Dict[str, dict] = load_db()

class FieldSchema(BaseModel):
    name: str
    data_type: str
    byte_length: Optional[int] = None
    description: Optional[str] = None

class ProtocolSchema(BaseModel):
    protocol_id: str
    name: str
    version: str
    format_type: str
    delimiter: Optional[str] = ";"
    fields: List[FieldSchema]

# ---------------------------------------------------------
# 4. Trig Protocol 1 Model & Endpoint (สื่อสารกับ UI)
# ---------------------------------------------------------
class TrigProtocol1Request(BaseModel):
    age: int = Field(..., ge=0, le=2, description="0: Pediatric, 1: Adult, 2: Geriatric")
    difficulty: int = Field(..., ge=0, le=2, description="0: Easy, 1: Medium, 2: Hard")
    case_type: int = Field(..., ge=0, le=1, description="0: Trauma/Basic, 1: Emergency")
    practice_mode: int = Field(..., ge=0, le=2, description="0: Tutorial, 1: Guide, 2: Blind")

@app.post("/api/v1/protocols/trig_protocol_1/build")
async def build_trig_protocol_1(req: TrigProtocol1Request):
    try:
        payload = {
            "age": req.age,
            "difficulty": req.difficulty,
            "case_type": req.case_type,
            "practice_mode": req.practice_mode
        }
        
        raw_message = client.build_message("trig_protocol_1", payload) if client else "CLIENT_NOT_INITIALIZED"
        
        return {
            "status": "success",
            "protocol": "trig_protocol_1",
            "payload": payload,
            "raw_message": raw_message
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---------------------------------------------------------
# 5. Schema API Routes
# ---------------------------------------------------------
@app.post("/protocols")
def save_protocol(schema: ProtocolSchema):
    protocols_db[schema.protocol_id] = schema.dict()
    save_db(protocols_db)
    return {"status": "success", "protocol_id": schema.protocol_id}

@app.get("/protocols")
def list_protocols():
    return list(protocols_db.values())

@app.get("/protocols/{protocol_id}")
def get_protocol(protocol_id: str):
    if protocol_id not in protocols_db:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocols_db[protocol_id]

@app.delete("/protocols/{protocol_id}")
def delete_protocol(protocol_id: str):
    if protocol_id not in protocols_db:
        raise HTTPException(status_code=404, detail="Protocol not found")
    del protocols_db[protocol_id]
    save_db(protocols_db)
    return {"status": "success", "message": f"Protocol '{protocol_id}' deleted"}

# ---------------------------------------------------------
# 6. ระบบบันทึกและอ่านประวัติการฝึกซ้อม (History Data Store)
# ---------------------------------------------------------
HISTORY_FILE = "history.json"

def load_history_db() -> list:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_history_db(data: list):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

history_db = load_history_db()

class SessionRecord(BaseModel):
    procedure: str
    difficulty: str
    mode: str
    score: int

@app.get("/api/v1/history")
async def get_history_data():
    return history_db

@app.post("/api/v1/history")
async def add_history_record(record: SessionRecord):
    new_entry = {
        "id": len(history_db) + 1,
        "date": datetime.now().strftime("%b %d, %Y"),
        "procedure": record.procedure,
        "difficulty": record.difficulty,
        "mode": record.mode,
        "score": record.score
    }
    history_db.insert(0, new_entry)
    save_history_db(history_db)
    return {"status": "success", "record": new_entry}

# ---------------------------------------------------------
# 7. WebSocket Connection Manager (Haptic Telemetry Real-time)
# ---------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

ws_manager = ConnectionManager()

@app.websocket("/ws/simulation")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # รับข้อมูล Telemetry จาก serial_bridge.py / UI
            data = await websocket.receive_text()
            # ส่งกระจายข้อมูลต่อให้ Client ทุกเครื่องที่เปิดหน้าเว็บอยู่
            await ws_manager.broadcast(data)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

# ---------------------------------------------------------
# 8. HTML Page Routes (บริการหน้า Simulation และ History)
# ---------------------------------------------------------
@app.get("/simulation")
async def read_simulation():
    if UI_DIR:
        sim_path = os.path.join(UI_DIR, "simulation.html")
        if os.path.exists(sim_path):
            return FileResponse(sim_path)
    return {"error": "ui/simulation.html not found"}

@app.get("/history")
async def read_history():
    if UI_DIR:
        history_path = os.path.join(UI_DIR, "history.html")
        if os.path.exists(history_path):
            return FileResponse(history_path)
    return {"error": "ui/history.html not found"}

# ---------------------------------------------------------
# 9. UI Static Files Mounting & Root Route
# ---------------------------------------------------------
if UI_DIR:
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
else:
    @app.get("/")
    def read_root():
        return {"status": "online", "message": "Protocol Schema API Ready (UI directory not found)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)