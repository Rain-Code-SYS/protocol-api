"""ชั้นฐานข้อมูลบางๆ: ข้อมูลผู้ใช้/session/ประวัติ ต้องอยู่ถาวร

- มีตัวแปรสภาพแวดล้อม DATABASE_URL (postgres://...) -> ใช้ PostgreSQL (เช่น Neon/Supabase/Render Postgres) ข้อมูลไม่หายตอน deploy
- ไม่มี -> ใช้ SQLite ไฟล์ app.db ในเครื่อง (ไว้พัฒนา/เทสต์ ไม่ต้องติดตั้งอะไรเพิ่ม)
- เขียน SQL ด้วยเครื่องหมาย ? แล้วแปลงเป็น %s ให้เองเมื่อใช้ Postgres
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, List, Optional, Sequence

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        username TEXT NOT NULL,
        username_key TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        created BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        exp DOUBLE PRECISION NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS attempts (
        id {serial},
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        data TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS attempts_user_idx ON attempts(user_id, id)",
    """CREATE TABLE IF NOT EXISTS encoder_configs (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        data TEXT NOT NULL
    )""",
]


def _pg_url(url: str) -> str:
    return "postgresql://" + url[len("postgres://"):] if url.startswith("postgres://") else url


class Database:
    def __init__(self, url: Optional[str] = None, sqlite_path: str = "app.db"):
        url = url if url is not None else os.environ.get("DATABASE_URL", "")
        self.is_pg = url.startswith(("postgres://", "postgresql://"))
        self._lock = threading.RLock()
        if self.is_pg:
            import psycopg2.pool  # ติดตั้งผ่าน requirements.txt (psycopg2-binary)
            self._pool = psycopg2.pool.ThreadedConnectionPool(1, 10, _pg_url(url))
        else:
            self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
            self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):
        serial = "BIGSERIAL PRIMARY KEY" if self.is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for stmt in SCHEMA:
            self.execute(stmt.format(serial=serial) if "{serial}" in stmt else stmt)

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_pg else sql

    @contextmanager
    def _cursor(self):
        if self.is_pg:
            conn = self._pool.getconn()
            try:
                if conn.closed:  # โฮสต์ฟรีตัดการเชื่อมต่อที่ว่างนานๆ
                    self._pool.putconn(conn, close=True)
                    conn = self._pool.getconn()
                cur = conn.cursor()
                try:
                    yield cur
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    cur.close()
            finally:
                self._pool.putconn(conn)
        else:
            with self._lock:
                cur = self._conn.cursor()
                try:
                    yield cur
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    raise
                finally:
                    cur.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """รันคำสั่งเขียน คืนจำนวนแถวที่โดน"""
        with self._cursor() as cur:
            cur.execute(self._sql(sql), tuple(params))
            return cur.rowcount

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[tuple]:
        with self._cursor() as cur:
            cur.execute(self._sql(sql), tuple(params))
            return cur.fetchall()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[tuple]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def is_unique_violation(self, err: Exception) -> bool:
        if self.is_pg:
            import psycopg2.errors
            return isinstance(err, psycopg2.errors.UniqueViolation)
        return isinstance(err, sqlite3.IntegrityError)

    def wipe_users(self) -> None:
        """ลบบัญชี/session/ประวัติทั้งหมด (ใช้ตอนรีเซ็ตบัญชีเก่า)"""
        for table in ("attempts", "encoder_configs", "sessions", "users"):
            self.execute(f"DELETE FROM {table}")