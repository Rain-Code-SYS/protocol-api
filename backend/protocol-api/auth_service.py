"""ระบบบัญชีผู้ใช้ (สมัคร/ล็อกอินด้วยอีเมล) เก็บในฐานข้อมูลผ่าน db.Database

- รหัสผ่านเก็บเป็น PBKDF2-SHA256 + salt ไม่เก็บรหัสจริง (ใช้เฉพาะ standard library)
- token ที่ส่งให้เบราว์เซอร์เป็นสุ่ม 256 บิต ฝั่งเซิร์ฟเวอร์เก็บเฉพาะ SHA-256 ของ token
- อีเมลไม่สนตัวพิมพ์เล็ก/ใหญ่ และอีเมล Gmail จะตัดจุด/+แท็ก ออกก่อนเทียบ (a.b+x@gmail.com = ab@gmail.com)
  จึงสมัครซ้ำด้วยอีเมลเดิมไม่ได้ (ลดจำนวนบัญชีต่อคน)
- ล็อกอินได้ทั้งอีเมลและชื่อผู้ใช้ (ชื่อผู้ใช้ใช้เป็นชื่อที่แสดงบนหน้าเว็บ)
"""
import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from typing import Any, Dict, Optional

from db import Database

PBKDF2_ROUNDS = 200_000
SESSION_DAYS = 30
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MAX_EMAIL = 254
MIN_PASSWORD = 6
MAX_PASSWORD = 128
MAX_FAILS = 5          # ใส่รหัสผิดติดกันกี่ครั้งถึงล็อกชั่วคราว
LOCK_SECONDS = 30
GMAIL_DOMAINS = ("gmail.com", "googlemail.com")


class AuthError(Exception):
    """ข้อผิดพลาดของระบบบัญชี: .status คือรหัส HTTP ที่ควรตอบ, .code ให้หน้าเว็บแปลข้อความเอง"""

    def __init__(self, message: str, status: int = 400, code: str = "error"):
        super().__init__(message)
        self.status = status
        self.code = code


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


def normalize_email(email: str) -> str:
    """อีเมลรูปแบบมาตรฐานสำหรับเทียบความซ้ำ (ตัวพิมพ์เล็ก + กฎ Gmail)"""
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if domain in GMAIL_DOMAINS:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


class AuthService:
    def __init__(self, db: Optional[Database] = None):
        self.db = db if db is not None else Database()
        self.lock = threading.Lock()
        self._fails: Dict[str, Any] = {}   # identifier -> (จำนวนครั้งที่ผิด, เวลาที่ล็อกถึง) เก็บในหน่วยความจำ

    # ---------- ตรวจข้อมูล ----------
    @staticmethod
    def _validate(email: str, username: str, password: str):
        email = (email or "").strip()
        if len(email) > MAX_EMAIL or not EMAIL_RE.match(email):
            raise AuthError("รูปแบบอีเมลไม่ถูกต้อง", 400, "bad_email")
        if not USERNAME_RE.match((username or "").strip()):
            raise AuthError("ชื่อผู้ใช้ต้องยาว 3–32 ตัว ใช้ได้เฉพาะ a-z 0-9 _ . -", 400, "bad_username")
        if not isinstance(password, str) or len(password) < MIN_PASSWORD:
            raise AuthError(f"รหัสผ่านต้องมีอย่างน้อย {MIN_PASSWORD} ตัวอักษร", 400, "bad_password")
        if len(password) > MAX_PASSWORD:
            raise AuthError(f"รหัสผ่านยาวเกิน {MAX_PASSWORD} ตัวอักษร", 400, "bad_password")

    def _purge_expired(self):
        self.db.execute("DELETE FROM sessions WHERE exp < ?", (time.time(),))

    def _new_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO sessions (token_hash, user_id, exp) VALUES (?, ?, ?)",
            (_token_key(token), user_id, time.time() + SESSION_DAYS * 86400),
        )
        return token

    # ---------- การใช้งานหลัก ----------
    def register(self, email: str, username: str, password: str) -> Dict[str, str]:
        """สมัครสมาชิกแล้วล็อกอินให้เลย คืน {"token", "username"}"""
        self._validate(email, username, password)
        email_key = normalize_email(email)
        username = username.strip()
        user_key = username.lower()
        if self.db.query_one("SELECT 1 FROM users WHERE email = ?", (email_key,)):
            raise AuthError("อีเมลนี้ถูกใช้สมัครแล้ว", 409, "email_taken")
        if self.db.query_one("SELECT 1 FROM users WHERE username_key = ?", (user_key,)):
            raise AuthError("ชื่อผู้ใช้นี้ถูกใช้แล้ว", 409, "username_taken")
        user_id = uuid.uuid4().hex
        try:
            self.db.execute(
                "INSERT INTO users (id, email, username, username_key, password, created) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, email_key, username, user_key, _hash_password(password), int(time.time() * 1000)),
            )
        except Exception as err:  # สมัครพร้อมกันสองคำขอ: ชนที่ UNIQUE ของฐานข้อมูล
            if self.db.is_unique_violation(err):
                raise AuthError("อีเมลหรือชื่อผู้ใช้นี้ถูกใช้แล้ว", 409, "email_taken")
            raise
        self._purge_expired()
        return {"token": self._new_session(user_id), "username": username}

    def login(self, identifier: str, password: str) -> Dict[str, str]:
        """identifier = อีเมลหรือชื่อผู้ใช้"""
        ident = (identifier or "").strip()
        lock_key = normalize_email(ident) if "@" in ident else ident.lower()
        with self.lock:
            fails, locked_until = self._fails.get(lock_key, (0, 0.0))
            if locked_until > time.time():
                raise AuthError("ใส่รหัสผ่านผิดหลายครั้ง รอสักครู่แล้วลองใหม่", 429, "locked")
        if "@" in ident:
            row = self.db.query_one("SELECT id, username, password FROM users WHERE email = ?", (normalize_email(ident),))
        else:
            row = self.db.query_one("SELECT id, username, password FROM users WHERE username_key = ?", (ident.lower(),))
        # คำนวณ hash ทุกครั้ง (แม้ไม่มีผู้ใช้) เพื่อไม่ให้เวลาตอบบอกได้ว่าบัญชีนี้มีอยู่หรือไม่
        stored = row[2] if row else _hash_password("x", b"\0" * 16)
        ok = _check_password(password or "", stored) and row is not None
        with self.lock:
            if not ok:
                fails += 1
                if fails >= MAX_FAILS:  # ผิดครบกำหนด: ล็อกชั่วคราวแล้วนับใหม่
                    self._fails[lock_key] = (0, time.time() + LOCK_SECONDS)
                else:
                    self._fails[lock_key] = (fails, 0.0)
                raise AuthError("อีเมล/ชื่อผู้ใช้ หรือรหัสผ่านไม่ถูกต้อง", 401, "bad_login")
            self._fails.pop(lock_key, None)
        self._purge_expired()
        return {"token": self._new_session(row[0]), "username": row[1]}

    def verify(self, token: Optional[str]) -> Optional[str]:
        """คืน user_id ถ้า token ใช้ได้ ไม่งั้นคืน None"""
        if not token:
            return None
        row = self.db.query_one("SELECT user_id, exp FROM sessions WHERE token_hash = ?", (_token_key(token),))
        if not row or row[1] < time.time():
            return None
        return row[0]

    def display_name(self, user_id: str) -> str:
        row = self.db.query_one("SELECT username FROM users WHERE id = ?", (user_id,))
        return row[0] if row else user_id

    def logout(self, token: Optional[str]) -> None:
        if token:
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_key(token),))