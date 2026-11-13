"""สถานะเอนโค้ดเดอร์แยกตามผู้ใช้ สำหรับเว็บจริง (เบราว์เซอร์ของแต่ละคนอ่านบอร์ดผ่าน Web Serial แล้วส่งค่ามาที่ /encoder/ingest)

- ใช้ตรรกะเดิมของ EncoderService (config / Set Zero / state) แต่ไม่เปิดพอร์ตฝั่งเซิร์ฟเวอร์
- config (encoder_id, ppr, offset) ของแต่ละบัญชีเก็บในตาราง encoder_configs จึงอยู่ถาวร
- ค่า raw ล่าสุดเก็บในหน่วยความจำ (ผู้ใช้ปิดเบราว์เซอร์ = ค่าเก่าค้างจน age_ms เกิน 1.5 วินาที หน้า Simulation ถือว่าไม่สด)
- แต่ละคนมีโมเดลคำนวณท่าเข็มของตัวเอง ไม่ปนกัน
"""
import json
import threading
import time
from typing import Any, Dict, Optional

from db import Database
from encoder_service import EncoderService
from tissue_model import TissueResistanceModel

WEB_SERIAL_LABEL = "Web Serial"
IDLE_EVICT_SECONDS = 3600
MAX_ENTRIES = 200


class DbEncoderService(EncoderService):
    def __init__(self, db: Database, user_id: str):
        self.db, self.user_id = db, user_id          # ต้องตั้งก่อน super().__init__ เพราะ _load() ใช้
        super().__init__(config_file="")
        self.sim_model = TissueResistanceModel()
        self.sim_lock = threading.Lock()
        self.created = time.monotonic()

    # ---------- config เก็บใน DB ----------
    def _load(self) -> Dict[str, Dict[str, Any]]:
        row = self.db.query_one("SELECT data FROM encoder_configs WHERE user_id = ?", (self.user_id,))
        try:
            loaded = json.loads(row[0]) if row else None
        except ValueError:
            loaded = None
        return self._merge_config(loaded)

    def _save(self, cfg: Dict[str, Dict[str, Any]]):
        self.db.execute(
            "INSERT INTO encoder_configs (user_id, data) VALUES (?, ?) "
            "ON CONFLICT (user_id) DO UPDATE SET data = excluded.data",
            (self.user_id, json.dumps(cfg, ensure_ascii=False)),
        )

    # ---------- รับค่าจากเบราว์เซอร์ ----------
    def ingest(self, timestamp: int, enc1: int, enc2: int, enc3: int,
               bad_lines: Optional[int] = None, last_raw: Optional[str] = None) -> None:
        with self.lock:
            self.raw.update(Enc_1=enc1, Enc_2=enc2, Enc_3=enc3)
            self.timestamp = timestamp
            self.last_rx = time.monotonic()
            self.samples += 1
            self._connected = True
            self.port, self.baud, self.error = WEB_SERIAL_LABEL, None, None
            if bad_lines is not None:
                self.bad_lines = bad_lines
            if last_raw:
                self.last_raw = last_raw[:80]

    def connect(self, port: Optional[str] = None, baud: int = 230400):
        raise RuntimeError("เว็บนี้อ่านบอร์ดผ่านเบราว์เซอร์ (Web Serial) ไม่ใช่ฝั่งเซิร์ฟเวอร์")


class EncoderHub:
    """รวม DbEncoderService ของแต่ละผู้ใช้ (สร้างตอนเรียกครั้งแรก)"""

    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._items: Dict[str, DbEncoderService] = {}

    def get(self, user_id: str) -> DbEncoderService:
        with self._lock:
            svc = self._items.get(user_id)
            if svc is None:
                self._evict_locked()
                svc = self._items[user_id] = DbEncoderService(self.db, user_id)
            return svc

    def _evict_locked(self):
        if len(self._items) < MAX_ENTRIES:
            return
        now = time.monotonic()
        for uid in [u for u, s in self._items.items()
                    if (s.last_rx is not None and now - s.last_rx > IDLE_EVICT_SECONDS)
                    or (s.last_rx is None and now - s.created > IDLE_EVICT_SECONDS)]:
            del self._items[uid]   # config อยู่ใน DB อยู่แล้ว สร้างใหม่ได้