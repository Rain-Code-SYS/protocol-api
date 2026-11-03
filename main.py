import os
import json
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# โหลด Protocol SDK Client
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

# 1. ตั้งค่า CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 2. Schema API Database & Models (ส่วนจัดการ Protocol Schema)
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
# 3. Trig Protocol 1 Model & Endpoint (ส่วนสื่อสารกับ UI)
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
# 4. Schema API Routes
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
# 5. UI Static Files Mounting & Root Route
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

if UI_DIR:
    # Mount ที่ root ("/") พร้อม html=True เพื่อให้เบราว์เซอร์อ่าน index.html, style.css, app.js และโฟลเดอร์ assets ได้ทันที
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
else:
    @app.get("/")
    def read_root():
        return {"status": "online", "message": "Protocol Schema API Ready (UI directory not found)"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)