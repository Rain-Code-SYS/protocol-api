"""ทดสอบระบบล็อกอินด้วยอีเมล (AuthService + ฐานข้อมูล) และการแยกประวัติ /attempts ตามผู้ใช้"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import auth_service
from auth_service import AuthError, AuthService, normalize_email
from db import Database


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "app.db")
        self.db = Database("", sqlite_path=self.path)
        self.svc = AuthService(self.db)

    def reg(self, email="alice@example.com", name="Alice", pw="secret1"):
        return self.svc.register(email, name, pw)

    def test_register_logs_in_and_verify_returns_user_id(self):
        r = self.reg()
        self.assertEqual(r["username"], "Alice")
        uid = self.svc.verify(r["token"])
        self.assertTrue(uid)
        self.assertEqual(self.svc.display_name(uid), "Alice")

    def test_password_and_token_are_not_stored_in_plain_text(self):
        r = self.reg()
        dump = repr(self.db.query("SELECT * FROM users")) + repr(self.db.query("SELECT * FROM sessions"))
        self.assertNotIn("secret1", dump)
        self.assertNotIn(r["token"], dump)
        self.assertIn("pbkdf2_sha256$", dump)

    def test_duplicate_email_is_case_insensitive_and_409(self):
        self.reg()
        with self.assertRaises(AuthError) as ctx:
            self.reg(email="ALICE@Example.com", name="Other")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "email_taken"))

    def test_gmail_aliases_count_as_same_email(self):
        self.assertEqual(normalize_email("A.B+news@Gmail.com"), "ab@gmail.com")
        self.assertEqual(normalize_email("a.b@example.com"), "a.b@example.com")  # โดเมนอื่นไม่ตัดจุด
        self.reg(email="alice.smith@gmail.com")
        with self.assertRaises(AuthError) as ctx:
            self.reg(email="alicesmith+2@gmail.com", name="Alice2")
        self.assertEqual(ctx.exception.code, "email_taken")

    def test_duplicate_username_is_case_insensitive(self):
        self.reg()
        with self.assertRaises(AuthError) as ctx:
            self.reg(email="b@example.com", name="ALICE")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "username_taken"))

    def test_invalid_input_rejected(self):
        cases = [("not-an-email", "alice", "secret1"), ("a@b", "alice", "secret1"), ("", "alice", "secret1"),
                 ("a@example.com", "ab", "secret1"), ("a@example.com", "has space", "secret1"),
                 ("a@example.com", "alice", "12345"), ("a@example.com", "alice", "x" * 200),
                 ("a" * 250 + "@example.com", "alice", "secret1")]
        for email, name, pw in cases:
            with self.subTest(email=email[:20], name=name, pw=len(pw)):
                with self.assertRaises(AuthError) as ctx:
                    self.svc.register(email, name, pw)
                self.assertEqual(ctx.exception.status, 400)

    def test_login_by_email_or_username(self):
        self.reg()
        for ident in ("alice@example.com", "ALICE@EXAMPLE.COM", "alice", "ALICE"):
            with self.subTest(ident=ident):
                self.assertEqual(self.svc.login(ident, "secret1")["username"], "Alice")

    def test_login_wrong_password_or_unknown_account(self):
        self.reg()
        for ident, pw in (("alice@example.com", "wrong1"), ("nobody@example.com", "secret1"), ("nobody", "secret1")):
            with self.subTest(ident=ident):
                with self.assertRaises(AuthError) as ctx:
                    self.svc.login(ident, pw)
                self.assertEqual(ctx.exception.status, 401)

    def test_repeated_failures_lock_temporarily(self):
        self.reg()
        for _ in range(auth_service.MAX_FAILS):
            with self.assertRaises(AuthError):
                self.svc.login("alice@example.com", "wrong")
        with self.assertRaises(AuthError) as ctx:
            self.svc.login("alice@example.com", "secret1")  # รหัสถูกก็ยังถูกล็อกอยู่
        self.assertEqual(ctx.exception.status, 429)
        with mock.patch.object(auth_service.time, "time", return_value=time.time() + auth_service.LOCK_SECONDS + 1):
            self.assertEqual(self.svc.login("alice@example.com", "secret1")["username"], "Alice")

    def test_logout_revokes_only_that_token(self):
        self.reg()
        t1 = self.svc.login("alice@example.com", "secret1")["token"]
        t2 = self.svc.login("alice@example.com", "secret1")["token"]
        self.svc.logout(t1)
        self.assertIsNone(self.svc.verify(t1))
        self.assertIsNotNone(self.svc.verify(t2))

    def test_bad_or_missing_token(self):
        for tok in (None, "", "nonsense"):
            self.assertIsNone(self.svc.verify(tok))
        self.svc.logout(None)  # ต้องไม่ error

    def test_expired_session_rejected(self):
        token = self.reg()["token"]
        with mock.patch.object(auth_service.time, "time", return_value=time.time() + (auth_service.SESSION_DAYS + 1) * 86400):
            self.assertIsNone(self.svc.verify(token))

    def test_data_survives_restart(self):
        """ปิด-เปิดโปรแกรมใหม่ (ฐานข้อมูลไฟล์เดิม) ผู้ใช้และ session ต้องยังอยู่"""
        token = self.reg()["token"]
        uid = self.svc.verify(token)
        self.db.execute("INSERT INTO attempts (user_id, data) VALUES (?, ?)", (uid, json.dumps({"score": 80})))
        again = AuthService(Database("", sqlite_path=self.path))
        self.assertEqual(again.verify(token), uid)
        self.assertEqual(again.login("alice@example.com", "secret1")["username"], "Alice")
        self.assertEqual(again.db.query("SELECT data FROM attempts WHERE user_id = ?", (uid,))[0][0], '{"score": 80}')

    def test_wipe_users_clears_everything(self):
        uid = self.svc.verify(self.reg()["token"])
        self.db.execute("INSERT INTO attempts (user_id, data) VALUES (?, ?)", (uid, "{}"))
        self.db.wipe_users()
        for table in ("users", "sessions", "attempts"):
            self.assertEqual(self.db.query(f"SELECT COUNT(*) FROM {table}")[0][0], 0)

    def test_deleting_user_cascades_to_attempts_and_sessions(self):
        uid = self.svc.verify(self.reg()["token"])
        self.db.execute("INSERT INTO attempts (user_id, data) VALUES (?, ?)", (uid, "{}"))
        self.db.execute("DELETE FROM users WHERE id = ?", (uid,))
        self.assertEqual(self.db.query("SELECT COUNT(*) FROM attempts")[0][0], 0)
        self.assertEqual(self.db.query("SELECT COUNT(*) FROM sessions")[0][0], 0)


def _api_available():
    try:
        import fastapi.testclient  # noqa: F401
        import pydantic
        return int(pydantic.VERSION.split(".")[0]) >= 2
    except Exception:
        return False


ATTEMPT = {"date": 1794462335516, "procedure": "Thoracentesis", "age": "Adult", "difficulty": "Medium",
           "caseType": "Basic", "mode": "Guide", "score": 80, "seconds": 9.0, "result": "success",
           "angle": 80, "depth_mm": 30.2, "force_feedback": False}


@unittest.skipUnless(_api_available(), "ต้องติดตั้ง fastapi, httpx และ pydantic>=2 เพื่อทดสอบ API")
class AttemptsPerUserApiTests(unittest.TestCase):
    def setUp(self):
        import main
        from fastapi.testclient import TestClient

        self.tmp = tempfile.TemporaryDirectory()
        database = Database("", sqlite_path=os.path.join(self.tmp.name, "app.db"))
        self.patches = [
            mock.patch.object(main, "database", database),
            mock.patch.object(main, "auth", AuthService(database)),
        ]
        for p in self.patches:
            p.start()
        self.http = TestClient(main.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def signup(self, name, email=None):
        r = self.http.post("/auth/register", json={"email": email or f"{name}@example.com", "username": name, "password": "secret1"})
        self.assertEqual(r.status_code, 200)
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_attempts_require_login(self):
        self.assertEqual(self.http.get("/attempts").status_code, 401)
        self.assertEqual(self.http.post("/attempts", json=ATTEMPT).status_code, 401)
        bad = {"Authorization": "Bearer nonsense"}
        self.assertEqual(self.http.get("/attempts", headers=bad).status_code, 401)

    def test_each_user_sees_only_own_attempts(self):
        alice, bob = self.signup("alice"), self.signup("bob")
        self.http.post("/attempts", json=ATTEMPT, headers=alice)
        self.http.post("/attempts", json={**ATTEMPT, "score": 90}, headers=alice)
        self.http.post("/attempts", json={**ATTEMPT, "score": 70}, headers=bob)
        a = self.http.get("/attempts", headers=alice).json()
        b = self.http.get("/attempts", headers=bob).json()
        self.assertEqual([x["score"] for x in a], [80, 90])
        self.assertEqual([x["score"] for x in b], [70])

    def test_attempts_persist_across_logins(self):
        self.signup("alice")
        tok = self.http.post("/auth/login", json={"login": "alice@example.com", "password": "secret1"}).json()["token"]
        h = {"Authorization": "Bearer " + tok}
        self.http.post("/attempts", json=ATTEMPT, headers=h)
        tok2 = self.http.post("/auth/login", json={"login": "alice", "password": "secret1"}).json()["token"]
        self.assertEqual(len(self.http.get("/attempts", headers={"Authorization": "Bearer " + tok2}).json()), 1)

    def test_me_and_logout(self):
        alice = self.signup("Alice")
        self.assertEqual(self.http.get("/auth/me", headers=alice).json(), {"username": "Alice"})
        self.assertEqual(self.http.post("/auth/logout", headers=alice).status_code, 200)
        self.assertEqual(self.http.get("/auth/me", headers=alice).status_code, 401)

    def test_auth_errors_map_to_http_status_and_code(self):
        self.signup("alice")
        r = self.http.post("/auth/login", json={"login": "alice", "password": "nope12"})
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (401, "bad_login"))
        r = self.http.post("/auth/register", json={"email": "alice@example.com", "username": "other", "password": "secret1"})
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (409, "email_taken"))
        r = self.http.post("/auth/register", json={"email": "x@example.com", "username": "alice", "password": "secret1"})
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (409, "username_taken"))
        r = self.http.post("/auth/register", json={"email": "bad", "username": "carol", "password": "secret1"})
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (400, "bad_email"))


if __name__ == "__main__":
    unittest.main()