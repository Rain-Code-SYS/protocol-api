from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from typing import Dict, List, Literal, Optional
import json
import os

from protocol_sdk.client import ProtocolClient
import threading

from auth_service import AuthError, AuthService
from db import Database
from encoder_remote import DbEncoderService, EncoderHub
from encoder_service import EncoderService, list_serial_ports
from tissue_model import TissueResistanceModel

app = FastAPI(
    title="Hardware/Software Protocol Schema API",
    description="API สำหรับจัดการและแชร์โครงสร้าง JSON Protocol Schemas",
    version="1.1.0"
)

# อนุญาตให้ UI (ที่เสิร์ฟจาก Flask :5000 หรือเปิดไฟล์ตรงๆ) ยิง request ข้าม origin มาที่ backend นี้ได้
EXTRA_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "null",  # กรณีเปิด index.html จากไฟล์โดยตรง (file://)
        *EXTRA_ORIGINS,
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "protocols.json"
SESSIONS_FILE = "sessions.json"

# Schema/session ของโปรโตคอลยังเก็บเป็นไฟล์ JSON (protocols.json อยู่ใน Git อยู่แล้ว ส่วน sessions.json เป็นแค่ log ชั่วคราว)
protocols_db: Dict[str, dict] = load_db()
sessions_db: List[dict] = load_sessions()

# ใช้ SDK สำหรับ decode/encode โดยอ่าน Schema จาก protocols_db ในหน่วยความจำ (ไม่ยิง HTTP กลับมาที่ตัวเอง)
sdk_client = ProtocolClient()

# ข้อมูลที่ต้องอยู่ถาวร (บัญชีผู้ใช้ + ประวัติ /attempts) เก็บในฐานข้อมูล:
# ตั้ง DATABASE_URL = PostgreSQL บนคลาวด์ / ไม่ตั้ง = SQLite ไฟล์ app.db ในเครื่อง
database = Database()
auth = AuthService(database)

# คีย์ผู้ดูแล: ถ้าตั้ง ADMIN_KEY ไว้ การเพิ่ม/ลบ Schema (POST/DELETE /protocols) ต้องส่ง header X-Admin-Key
# (กันคนแปลกหน้าลบโปรโตคอลบนเว็บสาธารณะ) ไม่ตั้ง = ไม่ตรวจ (ใช้ในเครื่อง)
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

def require_admin(x_admin_key: Optional[str] = Header(default=None)):
    if ADMIN_KEY and x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="ต้องใช้คีย์ผู้ดูแล")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_INDEX = os.path.join(STATIC_DIR, "index.html")
# ไฟล์ฝั่งเบราว์เซอร์ที่หน้าเว็บโหลด เช่น /static/haptic_model.js (โมเดลแรงสะท้อนกลับที่รันในเครื่องผู้ใช้)
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# อ่านเอนโค้ดเดอร์ + config สำหรับหน้า Settings (ไม่เปิดพอร์ตเองจนกว่าจะเรียก /encoder/connect)
encoder_service = EncoderService()           # โหมดเครื่องเดียว: บริดจ์/เครื่องแล็บที่เปิดพอร์ตฝั่งเซิร์ฟเวอร์ (เรียกโดยไม่ล็อกอิน)
encoder_hub = EncoderHub(database)           # โหมดเว็บ: เบราว์เซอร์ของแต่ละบัญชีอ่านบอร์ดเอง (Web Serial) แล้วส่งมา /encoder/ingest

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
    """เสิร์ฟหน้าเว็บ (static/index.html) จากโดเมนเดียวกับ API; ถ้าไม่มีไฟล์ก็ตอบสถานะ"""
    if os.path.exists(STATIC_INDEX):
        return FileResponse(STATIC_INDEX)
    return {"status": "online", "message": "Protocol Schema API Ready"}

@app.get("/health")
def health():
    return {"status": "online"}

@app.post("/protocols", dependencies=[Depends(require_admin)])
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

@app.delete("/protocols/{protocol_id}", dependencies=[Depends(require_admin)])
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

_I32 = 2 ** 31

class EncoderIngest(BaseModel):
    """ค่าที่เบราว์เซอร์อ่านจากบอร์ด (Trig Protocol 2: timestamp;enc1;enc2;enc3)"""
    timestamp: int = Field(ge=-_I32, le=_I32)
    enc1: int = Field(ge=-_I32, le=_I32)
    enc2: int = Field(ge=-_I32, le=_I32)
    enc3: int = Field(ge=-_I32, le=_I32)
    bad_lines: Optional[int] = Field(default=None, ge=0, le=_I32)
    last_raw: Optional[str] = Field(default=None, max_length=200)

def _bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None

def optional_user(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """ไม่ส่ง token = None (โหมดเครื่องเดียวแบบเดิม); ส่ง token ที่ใช้ไม่ได้ = 401"""
    token = _bearer(authorization)
    if token is None:
        return None
    user = auth.verify(token)
    if user is None:
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบ")
    return user

def current_user(authorization: Optional[str] = Header(default=None)) -> str:
    """dependency: คืนคีย์ผู้ใช้จาก token ไม่งั้นตอบ 401"""
    user = auth.verify(_bearer(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบ")
    return user

def _enc(user: Optional[str]) -> EncoderService:
    """ล็อกอินแล้ว = สถานะเอนโค้ดเดอร์ของบัญชีนั้น, ไม่ล็อกอิน = ตัวกลางของเครื่อง (เดิม)"""
    return encoder_hub.get(user) if user else encoder_service

@app.get("/encoder/state")
def encoder_state(user: Optional[str] = Depends(optional_user)):
    """config (encoder_id/ppr/offset) + ค่า raw ล่าสุดของ Enc_1..3 + สถานะการเชื่อมต่อ"""
    return _enc(user).state()

@app.get("/encoder/ports")
def encoder_ports(user: Optional[str] = Depends(optional_user)):
    """พอร์ต Serial ฝั่งเซิร์ฟเวอร์ (โหมดเว็บไม่มี: เบราว์เซอร์เลือกพอร์ตเอง)"""
    return {"ports": [] if user else list_serial_ports()}

@app.put("/encoder/config")
def encoder_set_config(body: Dict[str, EncoderJointConfig], user: Optional[str] = Depends(optional_user)):
    try:
        cfg = _enc(user).set_config({k: v.model_dump() for k, v in body.items()})
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return {"ok": True, "config": cfg}

@app.post("/encoder/zero/{joint}")
def encoder_zero(joint: str, user: Optional[str] = Depends(optional_user)):
    try:
        offset = _enc(user).zero(joint)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"ไม่รู้จักข้อต่อ '{joint}'")
    except RuntimeError as err:
        raise HTTPException(status_code=409, detail=str(err))
    return {"ok": True, "joint": joint, "offset": offset}

@app.post("/encoder/connect")
def encoder_connect(body: EncoderConnectBody, user: Optional[str] = Depends(optional_user)):
    try:
        _enc(user).connect(body.port, body.baud)
    except RuntimeError as err:
        raise HTTPException(status_code=503, detail=str(err))
    return {"ok": True, "port": _enc(user).state()["port"]}

@app.post("/encoder/disconnect")
def encoder_disconnect(user: Optional[str] = Depends(optional_user)):
    _enc(user).disconnect()
    return {"ok": True}

@app.post("/encoder/ingest")
def encoder_ingest(body: EncoderIngest, user: str = Depends(current_user)):
    """เบราว์เซอร์ส่งค่าล่าสุดจากบอร์ดมาเก็บเป็นสถานะของบัญชีนี้ (ใช้กับหน้า Simulation / Set Zero)"""
    encoder_hub.get(user).ingest(body.timestamp, body.enc1, body.enc2, body.enc3, body.bad_lines, body.last_raw)
    return {"ok": True}

# =========================================================================
# บัญชีผู้ใช้: สมัคร / ล็อกอิน / ออกจากระบบ (ใช้ Bearer token ใน header Authorization)
# =========================================================================
class RegisterBody(BaseModel):
    email: str = Field(max_length=254)
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)

class LoginBody(BaseModel):
    login: str = Field(max_length=254)          # อีเมล หรือชื่อผู้ใช้
    password: str = Field(max_length=256)

def _auth_http_error(err: AuthError) -> HTTPException:
    return HTTPException(status_code=err.status, detail={"code": err.code, "message": str(err)})

@app.post("/auth/register")
def auth_register(body: RegisterBody):
    try:
        return auth.register(body.email, body.username, body.password)
    except AuthError as err:
        raise _auth_http_error(err)

@app.post("/auth/login")
def auth_login(body: LoginBody):
    try:
        return auth.login(body.login, body.password)
    except AuthError as err:
        raise _auth_http_error(err)

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
    database.execute(  # ผูกผลกับเจ้าของบัญชี เก็บถาวรในฐานข้อมูล
        "INSERT INTO attempts (user_id, data) VALUES (?, ?)",
        (user, json.dumps(body.model_dump(), ensure_ascii=False)),
    )
    count = database.query_one("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (user,))[0]
    return {"ok": True, "count": count}

@app.get("/attempts")
def list_attempts(user: str = Depends(current_user)):
    """ส่งเฉพาะผลของผู้ใช้ที่ล็อกอินอยู่ (เรียงตามลำดับที่บันทึก)"""
    rows = database.query("SELECT data FROM attempts WHERE user_id = ? ORDER BY id", (user,))
    return [json.loads(r[0]) for r in rows]

@app.get("/simulation/pose")
def simulation_pose(user: Optional[str] = Depends(optional_user)):
    """ท่าเข็มปัจจุบันจากเอนโค้ดเดอร์ล่าสุด: pitch/yaw, depth_mm, pleura_mm, lung_mm + สถานะสตรีม
    ล็อกอินแล้วใช้ค่าและ config ของบัญชีนั้น ไม่ล็อกอินใช้ตัวกลางของเครื่อง (เดิม)"""
    svc = _enc(user)
    model, lock = (svc.sim_model, svc.sim_lock) if isinstance(svc, DbEncoderService) else (sim_model, sim_lock)
    st = svc.state()
    with lock:
        if model._applied_encoder_config != st["config"]:
            model.apply_encoder_config(st["config"])  # PPR / Set Zero / การสลับเอนโค้ดเดอร์จากหน้า Settings
        raw = st["raw"]
        pose = model.pose(raw["Enc_1"], raw["Enc_2"], raw["Enc_3"])
    live = st["connected"] and st["age_ms"] is not None and st["age_ms"] < 1500
    return {**pose, "connected": st["connected"], "live": live}

@app.on_event("shutdown")
def _close_encoder():
    encoder_service.disconnect()