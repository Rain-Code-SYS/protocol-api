"""ทดสอบระบบล็อกอิน (AuthService) และการแยกประวัติ /attempts ตามผู้ใช้"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import auth_service
from auth_service import AuthError, AuthService


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "users.json")
        self.svc = AuthService(self.path)

    def test_register_logs_in_and_verify_returns_lowercase_key(self):
        r = self.svc.register("Alice", "secret1")
        self.assertEqual(r["username"], "Alice")
        self.assertEqual(self.svc.verify(r["token"]), "alice")
        self.assertEqual(self.svc.display_name("alice"), "Alice")

    def test_password_is_not_stored_in_plain_text(self):
        self.svc.register("alice", "secret1")
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("secret1", text)
        self.assertIn("pbkdf2_sha256$", text)

    def test_token_is_stored_only_as_hash(self):
        token = self.svc.register("alice", "secret1")["token"]
        with open(self.path, encoding="utf-8") as f:
            self.assertNotIn(token, f.read())

    def test_duplicate_username_is_case_insensitive(self):
        self.svc.register("Alice", "secret1")
        with self.assertRaises(AuthError) as ctx:
            self.svc.register("ALICE", "another1")
        self.assertEqual(ctx.exception.status, 409)

    def test_invalid_username_or_password_rejected(self):
        for name, pw in (("ab", "secret1"), ("has space", "secret1"), ("ok_name", "12345"), ("ok_name", "x" * 200), ("", "secret1")):
            with self.subTest(name=name, pw=len(pw)):
                with self.assertRaises(AuthError) as ctx:
                    self.svc.register(name, pw)
                self.assertEqual(ctx.exception.status, 400)

    def test_login_success_and_wrong_password(self):
        self.svc.register("alice", "secret1")
        self.assertEqual(self.svc.login("ALICE", "secret1")["username"], "alice")
        for name, pw in (("alice", "wrong"), ("nobody", "secret1")):
            with self.subTest(name=name):
                with self.assertRaises(AuthError) as ctx:
                    self.svc.login(name, pw)
                self.assertEqual(ctx.exception.status, 401)

    def test_repeated_failures_lock_temporarily(self):
        self.svc.register("alice", "secret1")
        for _ in range(auth_service.MAX_FAILS):
            with self.assertRaises(AuthError):
                self.svc.login("alice", "wrong")
        with self.assertRaises(AuthError) as ctx:
            self.svc.login("alice", "secret1")  # รหัสถูกก็ยังถูกล็อกอยู่
        self.assertEqual(ctx.exception.status, 429)
        with mock.patch.object(auth_service.time, "time", return_value=time.time() + auth_service.LOCK_SECONDS + 1):
            self.assertEqual(self.svc.login("alice", "secret1")["username"], "alice")

    def test_logout_revokes_only_that_token(self):
        self.svc.register("alice", "secret1")
        t1 = self.svc.login("alice", "secret1")["token"]
        t2 = self.svc.login("alice", "secret1")["token"]
        self.svc.logout(t1)
        self.assertIsNone(self.svc.verify(t1))
        self.assertEqual(self.svc.verify(t2), "alice")

    def test_bad_or_missing_token(self):
        for tok in (None, "", "nonsense"):
            self.assertIsNone(self.svc.verify(tok))
        self.svc.logout(None)  # ต้องไม่ error

    def test_expired_session_rejected(self):
        token = self.svc.register("alice", "secret1")["token"]
        with mock.patch.object(auth_service.time, "time", return_value=time.time() + (auth_service.SESSION_DAYS + 1) * 86400):
            self.assertIsNone(self.svc.verify(token))

    def test_users_and_sessions_survive_restart(self):
        token = self.svc.register("alice", "secret1")["token"]
        again = AuthService(self.path)
        self.assertEqual(again.verify(token), "alice")
        self.assertEqual(again.login("alice", "secret1")["username"], "alice")

    def test_corrupt_file_starts_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(AuthService(self.path).data, {"users": {}, "sessions": {}})


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
        legacy = {**ATTEMPT, "score": 55}  # ผลเก่าก่อนมีระบบล็อกอิน (ไม่มี user)
        self.patches = [
            mock.patch.object(main, "auth", AuthService(os.path.join(self.tmp.name, "users.json"))),
            mock.patch.object(main, "ATTEMPTS_FILE", os.path.join(self.tmp.name, "attempts.json")),
            mock.patch.object(main, "attempts_db", [legacy]),
        ]
        for p in self.patches:
            p.start()
        self.http = TestClient(main.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def signup(self, name):
        r = self.http.post("/auth/register", json={"username": name, "password": "secret1"})
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
        self.assertTrue(all("user" not in x for x in a + b))

    def test_legacy_attempts_are_hidden_from_everyone(self):
        alice = self.signup("alice")
        self.assertEqual(self.http.get("/attempts", headers=alice).json(), [])

    def test_attempts_are_saved_to_file_with_owner(self):
        alice = self.signup("alice")
        self.http.post("/attempts", json=ATTEMPT, headers=alice)
        with open(os.path.join(self.tmp.name, "attempts.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved[-1]["user"], "alice")

    def test_me_and_logout(self):
        alice = self.signup("Alice")
        self.assertEqual(self.http.get("/auth/me", headers=alice).json(), {"username": "Alice"})
        self.assertEqual(self.http.post("/auth/logout", headers=alice).status_code, 200)
        self.assertEqual(self.http.get("/auth/me", headers=alice).status_code, 401)

    def test_login_errors_map_to_http_status(self):
        self.signup("alice")
        self.assertEqual(self.http.post("/auth/login", json={"username": "alice", "password": "nope12"}).status_code, 401)
        self.assertEqual(self.http.post("/auth/register", json={"username": "alice", "password": "secret1"}).status_code, 409)
        self.assertEqual(self.http.post("/auth/register", json={"username": "x", "password": "secret1"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()