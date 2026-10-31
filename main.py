from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
import json
import os

app = FastAPI(
    title="Hardware/Software Protocol Schema API",
    description="API สำหรับจัดการและแชร์โครงสร้าง JSON Protocol Schemas",
    version="1.0.0"
)

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

# โหลดข้อมูลจากไฟล์ JSON ทันทีที่เซิร์ฟเวอร์เริ่มทำงาน
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

@app.get("/")
def read_root():
    return {"status": "online", "message": "Protocol Schema API Ready"}

@app.post("/protocols")
def save_protocol(schema: ProtocolSchema):
    protocols_db[schema.protocol_id] = schema.dict()
    save_db(protocols_db)  # บันทึกลงไฟล์ protocols.json ถาวร
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
    save_db(protocols_db)  # บันทึกการอัปเดตลงไฟล์ protocols.json
    return {"status": "success", "message": f"Protocol '{protocol_id}' deleted"}