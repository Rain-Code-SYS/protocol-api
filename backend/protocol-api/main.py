from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from typing import Dict, List, Literal, Optional
import json
import os

from protocol_sdk.client import ProtocolClient
import threading

from auth_service import AuthError, AuthService
from encoder_service import EncoderService, list_serial_ports
from tissue_model import TissueResistanceModel

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
ATTEMPTS_FILE = "attempts.json"  # ผลการจำลองแต่ละครั้ง (ใช้แสดงในหน้า History)

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

def load_attempts() -> List[dict]:
    if os.path.exists(ATTEMPTS_FILE):
        with open(ATTEMPTS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_attempts(data: List[dict]):
    with open(ATTEMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# โหลดข้อมูลจากไฟล์ JSON ทันทีที่เซิร์ฟเวอร์เริ่มทำงาน
attempts_db: List[dict] = load_attempts()
protocols_db: Dict[str, dict] = load_db()
sessions_db: List[dict] = load_sessions()

# ใช้ SDK สำหรับ decode/encode โดยอ่าน Schema จาก protocols_db ในหน่วยความจำ (ไม่ยิง HTTP กลับมาที่ตัวเอง)
sdk_client = ProtocolClient()

# บัญชีผู้ใช้ (ล็อกอิน) เก็บใน users.json: ประวัติ /attempts แยกตามผู้ใช้
auth = AuthService()

# อ่านเอนโค้ดเดอร์ + config สำหรับหน้า Settings (ไม่เปิดพอร์ตเองจนกว่าจะเรียก /encoder/connect)
encoder_service = EncoderService()

# โมเดลสำหรับคำนวณท่าเข็ม/ความลึกให้หน้า Simulation (ใช้เฉพาะ pose() ที่ไม่มี side effect)
sim_model = TissueResistanceModel()
sim_lock = threading.Lock()

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

# =========================================================================
# เอนโค้ดเดอร์ (หน้า Settings): config, ค่าสด, Set Zero, เชื่อมต่อ Serial
# =========================================================================
class EncoderJointConfig(BaseModel):
    encoder_id: str
    ppr: int = Field(ge=1)

class EncoderConnectBody(BaseModel):
    port: Optional[str] = None                  # ไม่ระบุ = เลือกให้เองเมื่อเครื่องเห็นพอร์ตเดียว
    baud: int = Field(default=230400, ge=1)

@app.get("/encoder/state")
def encoder_state():
    """config (encoder_id/ppr/offset) + ค่า raw ล่าสุดของ Enc_1..3 + สถานะการเชื่อมต่อ"""
    return encoder_service.state()

@app.get("/encoder/ports")
def encoder_ports():
    """พอร์ต Serial ที่เสียบอยู่ตอนนี้ ให้หน้า Settings ใช้เลือกพอร์ต (ไม่ฟิก COM)"""
    return {"ports": list_serial_ports()}

@app.put("/encoder/config")
def encoder_set_config(body: Dict[str, EncoderJointConfig]):
    try:
        cfg = encoder_service.set_config({k: v.model_dump() for k, v in body.items()})
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return {"ok": True, "config": cfg}

@app.post("/encoder/zero/{joint}")
def encoder_zero(joint: str):
    try:
        offset = encoder_service.zero(joint)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"ไม่รู้จักข้อต่อ '{joint}'")
    except RuntimeError as err:
        raise HTTPException(status_code=409, detail=str(err))
    return {"ok": True, "joint": joint, "offset": offset}

@app.post("/encoder/connect")
def encoder_connect(body: EncoderConnectBody):
    try:
        encoder_service.connect(body.port, body.baud)
    except RuntimeError as err:
        raise HTTPException(status_code=503, detail=str(err))
    return {"ok": True, "port": encoder_service.state()["port"]}

@app.post("/encoder/disconnect")
def encoder_disconnect():
    encoder_service.disconnect()
    return {"ok": True}

# =========================================================================
# บัญชีผู้ใช้: สมัคร / ล็อกอิน / ออกจากระบบ (ใช้ Bearer token ใน header Authorization)
# =========================================================================
class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)

def _bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None

def current_user(authorization: Optional[str] = Header(default=None)) -> str:
    """dependency: คืนคีย์ผู้ใช้จาก token ไม่งั้นตอบ 401"""
    user = auth.verify(_bearer(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบ")
    return user

@app.post("/auth/register")
def auth_register(body: Credentials):
    try:
        return auth.register(body.username, body.password)
    except AuthError as err:
        raise HTTPException(status_code=err.status, detail=str(err))

@app.post("/auth/login")
def auth_login(body: Credentials):
    try:
        return auth.login(body.username, body.password)
    except AuthError as err:
        raise HTTPException(status_code=err.status, detail=str(err))

@app.post("/auth/logout")
def auth_logout(authorization: Optional[str] = Header(default=None)):
    auth.logout(_bearer(authorization))
    return {"ok": True}

@app.get("/auth/me")
def auth_me(user: str = Depends(current_user)):
    return {"username": auth.display_name(user)}

class AttemptIn(BaseModel):
    date: int                                   # epoch ms
    procedure: str
    age: str
    difficulty: str
    caseType: str
    mode: str
    score: int = Field(ge=0, le=100)            # คะแนนรวม: สำเร็จ = คะแนนมุมแทง, ไม่สำเร็จ (โดนปอด) = 0
    seconds: float = Field(ge=0)
    result: Literal["success", "failed"]
    angle: int = Field(ge=0, le=100)            # คะแนนมุมแทง ณ ตอนเข็มแตะผิว
    depth_mm: float
    force_feedback: bool = False

@app.post("/attempts")
def save_attempt(body: AttemptIn, user: str = Depends(current_user)):
    attempts_db.append({**body.model_dump(), "user": user})  # ผูกผลกับเจ้าของบัญชี
    save_attempts(attempts_db)
    return {"ok": True, "count": sum(1 for a in attempts_db if a.get("user") == user)}

@app.get("/attempts")
def list_attempts(user: str = Depends(current_user)):
    """ส่งเฉพาะผลของผู้ใช้ที่ล็อกอินอยู่ (ผลเก่าที่ไม่มีเจ้าของจะไม่ถูกส่งให้ใคร)"""
    return [{k: v for k, v in a.items() if k != "user"} for a in attempts_db if a.get("user") == user]

@app.get("/simulation/pose")
def simulation_pose():
    """ท่าเข็มปัจจุบันจากเอนโค้ดเดอร์ล่าสุด: pitch/yaw, depth_mm, pleura_mm, lung_mm + สถานะสตรีม"""
    st = encoder_service.state()
    with sim_lock:
        if sim_model._applied_encoder_config != st["config"]:
            sim_model.apply_encoder_config(st["config"])  # PPR / Set Zero / การสลับเอนโค้ดเดอร์จากหน้า Settings
        raw = st["raw"]
        pose = sim_model.pose(raw["Enc_1"], raw["Enc_2"], raw["Enc_3"])
    live = st["connected"] and st["age_ms"] is not None and st["age_ms"] < 1500
    return {**pose, "connected": st["connected"], "live": live}

@app.on_event("shutdown")
def _close_encoder():
    encoder_service.disconnect()