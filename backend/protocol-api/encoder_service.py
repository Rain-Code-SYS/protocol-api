"""บริการเอนโค้ดเดอร์ฝั่ง backend สำหรับหน้า Settings (แทนส่วน I/O ของ encoder_debugger.py)

- อ่านสตรีม 'timestamp;enc1;enc2;enc3' (Trig Protocol 2) ด้วย EncoderStreamReader ใน thread แยก เก็บเฉพาะค่าล่าสุด
- เก็บ/โหลด config ของแต่ละข้อต่อ (encoder_id, ppr, offset) ใน encoder_config.json (รูปแบบเดียวกับ debugger เดิม)
- ไม่เปิดพอร์ตเองตอนสตาร์ตเซิร์ฟเวอร์: ต้องสั่ง connect เพราะพอร์ต Serial เปิดได้ทีละโปรแกรม
  (ไม่งั้นจะแย่งพอร์ตกับ serial_bridge.py / encoder_debugger.py)
"""
import copy
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

import encoder_reader
from encoder_reader import EncoderStreamReader

CONFIG_FILE = "encoder_config.json"
ENCODERS = ("Enc_1", "Enc_2", "Enc_3")
# ค่าตั้งต้น (ใช้เมื่อยังไม่มี encoder_config.json) ต้องตรงกับค่าตั้งต้นของ model.axes ใน tissue_model.py (มีเทสต์ตรวจ)
DEFAULT_CONFIG: Dict[str, Dict[str, Any]] = {
    "Joint_YAW": {"encoder_id": "Enc_1", "ppr": 2048, "offset": 0},
    "Joint_PITCH": {"encoder_id": "Enc_2", "ppr": 800, "offset": 0},
    "Slider_MOTOR": {"encoder_id": "Enc_3", "ppr": 4096, "offset": 0},
}


def _port_sort_key(device: str):
    """เรียง COM3 ก่อน COM16 (ตามเลข ไม่ใช่ตามตัวอักษร)"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", device)]


def list_serial_ports() -> List[Dict[str, str]]:
    """พอร์ต Serial ที่เครื่องเห็นอยู่ ณ ตอนนี้ [{device, description}] — คืน [] ถ้าไม่มี pyserial"""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    ports = []
    for p in list_ports.comports():
        desc = p.description if p.description and p.description != "n/a" else ""
        ports.append({"device": p.device, "description": desc})
    return sorted(ports, key=lambda p: _port_sort_key(p["device"]))


class EncoderService:
    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self.lock = threading.Lock()
        self.config = self._load()
        self.raw = {e: 0 for e in ENCODERS}
        self.timestamp = None
        self.last_rx = None  # เวลา (monotonic) ที่ได้รับตัวอย่างล่าสุด
        self.port = None
        self.baud = None
        self.error = None
        self.samples = 0       # จำนวนตัวอย่างที่แกะได้ตั้งแต่เชื่อมต่อ
        self.bad_lines = 0     # จำนวนบรรทัดที่ได้รับแต่แกะไม่ได้
        self.last_raw = None   # บรรทัดที่แกะไม่ได้ล่าสุด (ตัดสั้น)
        self._connected = False
        self._thread = None
        self._stop = None

    # ---------- config ----------
    def _load(self) -> Dict[str, Dict[str, Any]]:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if not os.path.exists(self.config_file):
            return cfg
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError):
            return cfg
        if not isinstance(loaded, dict):
            return cfg
        for key, item in cfg.items():
            src = loaded.get(key)
            if not isinstance(src, dict):
                continue
            if src.get("encoder_id") in ENCODERS:
                item["encoder_id"] = src["encoder_id"]
            ppr = src.get("ppr")
            if isinstance(ppr, (int, float)) and not isinstance(ppr, bool) and ppr >= 1:
                item["ppr"] = int(ppr)
            off = src.get("offset")
            if isinstance(off, (int, float)) and not isinstance(off, bool):
                item["offset"] = int(off)
        return cfg

    def _save(self, cfg: Dict[str, Dict[str, Any]]):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)

    def set_config(self, new: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """ตรวจแล้วบันทึก encoder_id/ppr ของแต่ละข้อต่อ (offset คงเดิม; ถ้าเปลี่ยนเอนโค้ดเดอร์ offset รีเซ็ตเป็น 0)"""
        with self.lock:
            cfg = copy.deepcopy(self.config)
            for key, val in new.items():
                if key not in cfg:
                    raise ValueError(f"ไม่รู้จักข้อต่อ '{key}'")
                enc, ppr = val.get("encoder_id"), val.get("ppr")
                if enc not in ENCODERS:
                    raise ValueError(f"เอนโค้ดเดอร์ '{enc}' ไม่ถูกต้อง (ใช้ได้: {', '.join(ENCODERS)})")
                if not isinstance(ppr, int) or isinstance(ppr, bool) or ppr < 1:
                    raise ValueError(f"PPR ของ '{key}' ต้องเป็นจำนวนเต็ม 1 ขึ้นไป")
                if enc != cfg[key]["encoder_id"]:
                    cfg[key]["offset"] = 0
                cfg[key]["encoder_id"], cfg[key]["ppr"] = enc, ppr
            encs = [c["encoder_id"] for c in cfg.values()]
            if len(set(encs)) != len(encs):
                raise ValueError("เลือกเอนโค้ดเดอร์ซ้ำกันหลายข้อต่อ")
            self._save(cfg)  # เขียนไฟล์สำเร็จก่อนค่อยเปลี่ยนในหน่วยความจำ
            self.config = cfg
            return copy.deepcopy(cfg)

    def zero(self, joint: str) -> int:
        """ตั้งค่า raw ปัจจุบันของเอนโค้ดเดอร์ที่ผูกกับข้อต่อนั้นเป็น offset แล้วบันทึกไฟล์"""
        with self.lock:
            if joint not in self.config:
                raise KeyError(joint)
            if not self._connected or self.last_rx is None:
                raise RuntimeError("ยังไม่มีข้อมูลจากเอนโค้ดเดอร์ (ต้องเชื่อมต่อและได้รับข้อมูลก่อน)")
            cfg = copy.deepcopy(self.config)
            cfg[joint]["offset"] = self.raw[cfg[joint]["encoder_id"]]
            self._save(cfg)
            self.config = cfg
            return cfg[joint]["offset"]

    # ---------- serial ----------
    @staticmethod
    def _resolve_port(port: Optional[str]) -> str:
        """ใช้พอร์ตที่ระบุ ถ้าไม่ระบุจะเลือกให้เองเมื่อเครื่องเห็นพอร์ตเดียวเท่านั้น"""
        if port and port.strip():
            return port.strip()
        found = [p["device"] for p in list_serial_ports()]
        if len(found) == 1:
            return found[0]
        if not found:
            raise RuntimeError("ไม่พบพอร์ต Serial ที่ต่ออยู่ (เสียบสายแล้วกดรีเฟรชรายชื่อพอร์ต)")
        raise RuntimeError(f"พบหลายพอร์ต ({', '.join(found)}) เลือกพอร์ตที่ต้องการก่อน")

    def connect(self, port: Optional[str] = None, baud: int = 230400):
        self.disconnect()
        if encoder_reader.serial is None:
            raise RuntimeError("ไม่พบ pyserial — ติดตั้งด้วย: python -m pip install pyserial")
        port = self._resolve_port(port)
        reader = EncoderStreamReader(port=port, baud_rate=baud)
        if not reader.connect():  # มีหน่วง 2 วินาทีข้างใน จึงทำนอก lock
            raise RuntimeError(f"เปิดพอร์ต {port} ไม่ได้ (ไม่มีพอร์ตนี้ หรือมีโปรแกรมอื่นใช้อยู่)")
        stop = threading.Event()
        thread = threading.Thread(target=self._worker, args=(reader, stop), daemon=True)
        with self.lock:
            self.port, self.baud, self.error = port, baud, None
            self.timestamp = self.last_rx = None
            self.samples = self.bad_lines = 0
            self.last_raw = None
            self._connected, self._thread, self._stop = True, thread, stop
        thread.start()

    def disconnect(self):
        with self.lock:
            thread, stop = self._thread, self._stop
            self._thread = self._stop = None
            self._connected = False
        if stop is not None:
            stop.set()
        if thread is not None:
            thread.join(timeout=3)  # readline() รอได้สูงสุดตาม timeout ของพอร์ต (1 วินาที)

    def _worker(self, reader, stop):
        try:
            while not stop.is_set():
                sample = reader.read_data()
                if sample is None:
                    raw = (getattr(reader, "last_raw", "") or "").strip()
                    if raw:  # มีบรรทัดมาแต่รูปแบบไม่ใช่ timestamp;enc1;enc2;enc3
                        with self.lock:
                            self.bad_lines += 1
                            self.last_raw = raw[:80]
                    continue
                ts, e1, e2, e3 = sample
                with self.lock:
                    self.samples += 1
                    self.raw.update(Enc_1=e1, Enc_2=e2, Enc_3=e3)
                    self.timestamp = ts
                    self.last_rx = time.monotonic()
        except Exception as exc:  # เช่น สายหลุดระหว่างอ่าน
            with self.lock:
                self.error = f"อ่าน Serial ไม่ได้: {exc}"
                self._connected = False
        finally:
            reader.close()

    def state(self) -> Dict[str, Any]:
        with self.lock:
            age = None if self.last_rx is None else int((time.monotonic() - self.last_rx) * 1000)
            return {
                "connected": self._connected,
                "port": self.port,
                "baud": self.baud,
                "error": self.error,
                "timestamp": self.timestamp,
                "age_ms": age,
                "samples": self.samples,
                "bad_lines": self.bad_lines,
                "last_raw": self.last_raw,
                "raw": dict(self.raw),
                "config": copy.deepcopy(self.config),
            }