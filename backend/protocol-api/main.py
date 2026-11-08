from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from typing import Dict, List, Optional
import json
import os

from protocol_sdk.client import ProtocolClient

app = FastAPI(
    title="Hardware/Software Protocol Schema API",
    description="API สำหรับจัดการและแชร์โครงสร้าง JSON Protocol Schemas",
    version="1.1.0"
)

# อนุญาตให้ UI (ที่เสิร์ฟจาก Flask :5000 หรือเปิดไฟล์ตรงๆ) ยิง request ข้าม origin มาที่ backend นี้ได้
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "null",  # กรณีเปิด index.html จากไฟล์โดยตรง (file://)
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "protocols.json"
SESSIONS_FILE = "sessions.json"

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

def load_sessions() -> List[dict]:
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_sessions(data: List[dict]):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# โหลดข้อมูลจากไฟล์ JSON ทันทีที่เซิร์ฟเวอร์เริ่มทำงาน
protocols_db: Dict[str, dict] = load_db()
sessions_db: List[dict] = load_sessions()

# ใช้ SDK สำหรับ decode/encode โดยอ่าน Schema จาก protocols_db ในหน่วยความจำ (ไม่ยิง HTTP กลับมาที่ตัวเอง)
sdk_client = ProtocolClient()

def decode_with_schema(protocol_id: str, value: int) -> Dict[str, int]:
    if protocol_id not in protocols_db:
        raise HTTPException(status_code=404, detail=f"Protocol '{protocol_id}' not found")
    # ป้อน Schema ล่าสุดเข้า cache ของ SDK เพื่อเลี่ยงการเรียก HTTP กลับมาที่ตัวเอง
    sdk_client._cache[protocol_id] = protocols_db[protocol_id]
    return sdk_client.decode_bitfield(protocol_id, value)

class FieldSchema(BaseModel):
    name: str
    data_type: str
    byte_length: Optional[int] = None
    description: Optional[str] = None
    # --- เฉพาะ format_type == "bitfield" ---
    bit_offset: Optional[int] = Field(default=None, ge=0)
    bit_width: Optional[int] = Field(default=None, ge=1)
    max_value: Optional[int] = Field(default=None, ge=0)

class ProtocolSchema(BaseModel):
    protocol_id: str
    name: str
    version: str
    format_type: str
    delimiter: Optional[str] = ";"
    bit_width: Optional[int] = Field(default=None, ge=1)  # ความกว้างรวมของ bitfield (เช่น 7)
    fields: List[FieldSchema]

    @model_validator(mode="after")
    def validate_bitfield(self):
        """ตรวจความถูกต้องของ Schema แบบ bitfield ก่อนบันทึก (ผิดจะตอบ 422)"""
        if self.format_type.lower() != "bitfield":
            return self

        if self.bit_width is None:
            raise ValueError("bitfield schema ต้องระบุ bit_width รวม")

        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("ชื่อฟิลด์ซ้ำกันใน bitfield schema")

        used = 0  # bitmask ของบิตที่ถูกใช้ไปแล้ว ไว้ตรวจการทับซ้อน
        for f in self.fields:
            if f.bit_offset is None or f.bit_width is None:
                raise ValueError(f"ฟิลด์ '{f.name}' ต้องระบุ bit_offset และ bit_width")
            if f.bit_offset + f.bit_width > self.bit_width:
                raise ValueError(
                    f"ฟิลด์ '{f.name}' ล้นความกว้างรวม {self.bit_width} บิต"
                )
            if f.max_value is not None and f.max_value > (1 << f.bit_width) - 1:
                raise ValueError(
                    f"ฟิลด์ '{f.name}' มี max_value {f.max_value} เกินที่ {f.bit_width} บิตเก็บได้"
                )
            mask = ((1 << f.bit_width) - 1) << f.bit_offset
            if used & mask:
                raise ValueError(f"ฟิลด์ '{f.name}' ใช้บิตทับกับฟิลด์อื่น")
            used |= mask
        return self

def schema_to_dict(schema: ProtocolSchema) -> dict:
    """แปลงเป็น dict สำหรับเก็บลง protocols.json (ตัดคีย์ bit_* ที่ไม่เกี่ยวข้องกับ delimited ออก)"""
    data = schema.model_dump()
    if data["format_type"].lower() != "bitfield":
        data.pop("bit_width", None)
        for f in data["fields"]:
            for key in ("bit_offset", "bit_width", "max_value"):
                f.pop(key, None)
    return data

@app.get("/")
def read_root():
    return {"status": "online", "message": "Protocol Schema API Ready"}

@app.post("/protocols")
def save_protocol(schema: ProtocolSchema):
    protocols_db[schema.protocol_id] = schema_to_dict(schema)
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

# =========================================================================
# รับข้อมูลจริง (runtime) จาก UI — Trig Protocol 1 (INT 7 บิตแบบอัดบิต)
# =========================================================================
class Trig1Ingest(BaseModel):
    value: int
    procedure: Optional[str] = None

@app.post("/protocols/trig_protocol_1/ingest")
def ingest_trig1(body: Trig1Ingest):
    """รับค่าที่ UI ส่งมา (เช่น {"value": 41, "procedure": "thoracentesis"}),
    แกะบิตตาม Schema trig_protocol_1 แล้วเก็บเป็น session"""
    try:
        settings = decode_with_schema("trig_protocol_1", body.value)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    session = {
        "protocol_id": "trig_protocol_1",
        "raw_value": body.value,
        "procedure": body.procedure,
        "settings": settings,
    }
    sessions_db.append(session)
    save_sessions(sessions_db)

    print(f"[Trig1] 0b{body.value:07b} ({body.value}) proc={body.procedure} -> {settings}")
    return {"ok": True, "settings": settings, "procedure": body.procedure}

# =========================================================================
# รับสถานะโดนปอดจาก tissue_model — Trig Protocol 4 (bitfield 1 บิต: 1 = โดนปอด, 0 = ไม่โดน)
# =========================================================================
class Trig4Ingest(BaseModel):
    value: int

@app.post("/protocols/trig_protocol_4/ingest")
def ingest_trig4(body: Trig4Ingest):
    """รับ {"value": 1} หรือ {"value": 0} แล้วแกะตาม Schema trig_protocol_4 เก็บเป็น session"""
    try:
        settings = decode_with_schema("trig_protocol_4", body.value)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    session = {
        "protocol_id": "trig_protocol_4",
        "raw_value": body.value,
        "settings": settings,
    }
    sessions_db.append(session)
    save_sessions(sessions_db)

    print(f"[Trig4] lung_hit={settings['lung_hit']}")
    return {"ok": True, "settings": settings}

@app.get("/sessions")
def list_sessions():
    return sessions_db