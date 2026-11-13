"""ระบบบัญชีผู้ใช้แบบ local (ใช้เฉพาะ standard library ไม่ต้องติดตั้งแพ็กเกจเพิ่ม)

- เก็บผู้ใช้และ session ใน users.json (รหัสผ่านเก็บเป็น PBKDF2-SHA256 + salt ไม่เก็บรหัสจริง)
- token ที่ส่งให้เบราว์เซอร์เป็นสุ่ม 256 บิต ฝั่งเซิร์ฟเวอร์เก็บเฉพาะ SHA-256 ของ token
- ชื่อผู้ใช้ไม่สนตัวพิมพ์เล็ก/ใหญ่ (Alice = alice)
"""
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from typing import Any, Dict, Optional

USERS_FILE = "users.json"
PBKDF2_ROUNDS = 200_000
SESSION_DAYS = 30
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD = 6
MAX_PASSWORD = 128
MAX_FAILS = 5          # ใส่รหัสผิดติดกันกี่ครั้งถึงล็อกชั่วคราว
LOCK_SECONDS = 30


class AuthError(Exception):
    """ข้อผิดพลาดของระบบบัญชี: .status คือรหัส HTTP ที่ควรตอบ"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _hash_password(password: str, salt: Optional[bytes] = None, rounds: int = PBKDF2_ROUNDS) -> str:
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def _check_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, users_file: str = USERS_FILE):
        self.users_file = users_file
        self.lock = threading.Lock()
        self._fails: Dict[str, Any] = {}   # username -> (จำนวนครั้งที่ผิด, เวลาที่ล็อกถึง) เก็บในหน่วยความจำ
        self.data = self._load()

    # ---------- ไฟล์ ----------
    def _load(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"users": {}, "sessions": {}}
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    if isinstance(loaded.get("users"), dict):
                        data["users"] = loaded["users"]
                    if isinstance(loaded.get("sessions"), dict):
                        data["sessions"] = loaded["sessions"]
            except (OSError, json.JSONDecodeError):
                pass
        return data

    def _save(self):
        tmp = self.users_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.users_file)  # เขียนไฟล์ชั่วคราวก่อนแล้วสลับ กันไฟล์พังถ้าปิดโปรแกรมกลางคัน

    # ---------- ตรวจข้อมูล ----------
    @staticmethod
    def _norm(username: str) -> str:
        return (username or "").strip().lower()

    def _validate(self, username: str, password: str):
        if not USERNAME_RE.match((username or "").strip()):
            raise AuthError("ชื่อผู้ใช้ต้องยาว 3–32 ตัว ใช้ได้เฉพาะ a-z 0-9 _ . -", 400)
        if not isinstance(password, str) or len(password) < MIN_PASSWORD:
            raise AuthError(f"รหัสผ่านต้องมีอย่างน้อย {MIN_PASSWORD} ตัวอักษร", 400)
        if len(password) > MAX_PASSWORD:
            raise AuthError(f"รหัสผ่านยาวเกิน {MAX_PASSWORD} ตัวอักษร", 400)

    def _purge_expired(self):
        now = time.time()
        stale = [k for k, s in self.data["sessions"].items() if s.get("exp", 0) < now]
        for k in stale:
            del self.data["sessions"][k]

    def _new_session(self, key: str) -> str:
        token = secrets.token_urlsafe(32)
        self.data["sessions"][_token_key(token)] = {
            "user": key,
            "exp": time.time() + SESSION_DAYS * 86400,
        }
        return token

    # ---------- การใช้งานหลัก ----------
    def register(self, username: str, password: str) -> Dict[str, str]:
        """สมัครสมาชิกแล้วล็อกอินให้เลย คืน {"token", "username"}"""
        self._validate(username, password)
        key = self._norm(username)
        with self.lock:
            if key in self.data["users"]:
                raise AuthError("ชื่อผู้ใช้นี้ถูกใช้แล้ว", 409)
            self.data["users"][key] = {
                "username": username.strip(),
                "password": _hash_password(password),
                "created": int(time.time() * 1000),
            }
            self._purge_expired()
            token = self._new_session(key)
            self._save()
            return {"token": token, "username": username.strip()}

    def login(self, username: str, password: str) -> Dict[str, str]:
        key = self._norm(username)
        with self.lock:
            fails, locked_until = self._fails.get(key, (0, 0.0))
            if locked_until > time.time():
                raise AuthError("ใส่รหัสผ่านผิดหลายครั้ง รอสักครู่แล้วลองใหม่", 429)
            user = self.data["users"].get(key)
            # คำนวณ hash ทุกครั้ง (แม้ไม่มีผู้ใช้) เพื่อไม่ให้เวลาตอบบอกได้ว่าชื่อนี้มีอยู่หรือไม่
            stored = user["password"] if user else _hash_password("x", b"\0" * 16)
            ok = _check_password(password or "", stored) and user is not None
            if not ok:
                fails += 1
                if fails >= MAX_FAILS:  # ผิดครบกำหนด: ล็อกชั่วคราวแล้วนับใหม่
                    self._fails[key] = (0, time.time() + LOCK_SECONDS)
                else:
                    self._fails[key] = (fails, 0.0)
                raise AuthError("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", 401)
            self._fails.pop(key, None)
            self._purge_expired()
            token = self._new_session(key)
            self._save()
            return {"token": token, "username": user["username"]}

    def verify(self, token: Optional[str]) -> Optional[str]:
        """คืนคีย์ผู้ใช้ (ชื่อตัวพิมพ์เล็ก) ถ้า token ใช้ได้ ไม่งั้นคืน None"""
        if not token:
            return None
        with self.lock:
            s = self.data["sessions"].get(_token_key(token))
            if not s or s.get("exp", 0) < time.time() or s.get("user") not in self.data["users"]:
                return None
            return s["user"]

    def display_name(self, key: str) -> str:
        with self.lock:
            return self.data["users"].get(key, {}).get("username", key)

    def logout(self, token: Optional[str]) -> None:
        if not token:
            return
        with self.lock:
            if self.data["sessions"].pop(_token_key(token), None) is not None:
                self._save()