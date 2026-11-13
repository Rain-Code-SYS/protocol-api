"""ทดสอบสถานะเอนโค้ดเดอร์แยกตามผู้ใช้ (โหมดเว็บ: เบราว์เซอร์ส่งค่ามา /encoder/ingest) โดยไม่ต้องมีพอร์ตจริง"""
import os
import tempfile
import time
import unittest
from unittest import mock

from auth_service import AuthService
from db import Database
from encoder_remote import DbEncoderService, EncoderHub
from encoder_service import DEFAULT_CONFIG


class RemoteEncoderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database("", sqlite_path=os.path.join(self.tmp.name, "app.db"))
        auth = AuthService(self.db)
        self.alice = auth.verify(auth.register("alice@example.com", "alice", "secret1")["token"])
        self.bob = auth.verify(auth.register("bob@example.com", "bob", "secret1")["token"])
        self.hub = EncoderHub(self.db)

    def test_defaults_and_not_connected_before_any_data(self):
        st = self.hub.get(self.alice).state()
        self.assertEqual(st["config"], DEFAULT_CONFIG)
        self.assertFalse(st["connected"])
        with self.assertRaises(RuntimeError):
            self.hub.get(self.alice).zero("Joint_YAW")   # ยังไม่มีข้อมูลจากบอร์ด

    def test_ingest_marks_connected_and_sets_raw(self):
        svc = self.hub.get(self.alice)
        svc.ingest(100, 10, -20, 30, bad_lines=2, last_raw="x" * 200)
        st = svc.state()
        self.assertTrue(st["connected"])
        self.assertEqual((st["port"], st["timestamp"], st["samples"], st["bad_lines"]), ("Web Serial", 100, 1, 2))
        self.assertEqual(st["raw"], {"Enc_1": 10, "Enc_2": -20, "Enc_3": 30})
        self.assertEqual(len(st["last_raw"]), 80)
        self.assertLess(st["age_ms"], 1500)

    def test_users_are_isolated(self):
        a, b = self.hub.get(self.alice), self.hub.get(self.bob)
        a.ingest(1, 111, 222, 333)
        self.assertEqual(b.state()["raw"], {"Enc_1": 0, "Enc_2": 0, "Enc_3": 0})
        self.assertFalse(b.state()["connected"])
        self.assertIs(self.hub.get(self.alice), a)       # ได้ตัวเดิมทุกครั้ง

    def test_zero_saves_offset_per_user_and_survives_restart(self):
        a = self.hub.get(self.alice)
        a.ingest(1, 5, 6, 7)
        self.assertEqual(a.zero("Joint_PITCH"), 6)
        self.assertEqual(self.hub.get(self.bob).config["Joint_PITCH"]["offset"], 0)
        again = EncoderHub(self.db).get(self.alice)      # รีสตาร์ตเซิร์ฟเวอร์ = สร้างใหม่จาก DB
        self.assertEqual(again.config["Joint_PITCH"]["offset"], 6)

    def test_set_config_persists_and_validates(self):
        a = self.hub.get(self.alice)
        a.set_config({"Joint_YAW": {"encoder_id": "Enc_1", "ppr": 1000}})
        self.assertEqual(EncoderHub(self.db).get(self.alice).config["Joint_YAW"]["ppr"], 1000)
        with self.assertRaises(ValueError):
            a.set_config({"Joint_YAW": {"encoder_id": "Enc_2", "ppr": 10}})   # ซ้ำกับ Pitch
        self.assertEqual(a.config["Joint_YAW"]["ppr"], 1000)

    def test_disconnect_and_server_side_connect(self):
        a = self.hub.get(self.alice)
        a.ingest(1, 1, 1, 1)
        a.disconnect()
        self.assertFalse(a.state()["connected"])
        with self.assertRaises(RuntimeError):
            a.connect("COM3")

    def test_stale_data_is_visible_via_age(self):
        a = self.hub.get(self.alice)
        a.ingest(1, 1, 1, 1)
        with mock.patch("encoder_service.time.monotonic", return_value=time.monotonic() + 5):
            self.assertGreater(a.state()["age_ms"], 1500)

    def test_each_user_has_own_sim_model(self):
        a, b = self.hub.get(self.alice), self.hub.get(self.bob)
        self.assertIsNot(a.sim_model, b.sim_model)
        a.sim_model.apply_encoder_config({**a.state()["config"], "Joint_YAW": {"encoder_id": "Enc_1", "ppr": 1000, "offset": 0}})
        self.assertEqual(b.sim_model.axes["yaw"].counts_per_rev, 2048.0)

    def test_pose_from_ingested_values(self):
        a = self.hub.get(self.alice)
        a.ingest(1, 0, 0, 0)
        st = a.state()
        a.sim_model.apply_encoder_config(st["config"])
        pose = a.sim_model.pose(*[st["raw"][k] for k in ("Enc_1", "Enc_2", "Enc_3")])
        self.assertIn("depth_mm", pose)


def _api_available():
    try:
        import fastapi.testclient  # noqa: F401
        import pydantic
        return int(pydantic.VERSION.split(".")[0]) >= 2
    except Exception:
        return False


@unittest.skipUnless(_api_available(), "ต้องติดตั้ง fastapi, httpx และ pydantic>=2 เพื่อทดสอบ API")
class IngestApiTests(unittest.TestCase):
    def setUp(self):
        import main
        from fastapi.testclient import TestClient

        self.tmp = tempfile.TemporaryDirectory()
        db = Database("", sqlite_path=os.path.join(self.tmp.name, "app.db"))
        self.patches = [mock.patch.object(main, "database", db), mock.patch.object(main, "auth", AuthService(db)),
                        mock.patch.object(main, "encoder_hub", EncoderHub(db))]
        for p in self.patches:
            p.start()
        self.http = TestClient(main.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def signup(self, name):
        r = self.http.post("/auth/register", json={"email": f"{name}@example.com", "username": name, "password": "secret1"})
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_ingest_requires_login_and_validates(self):
        body = {"timestamp": 1, "enc1": 1, "enc2": 2, "enc3": 3}
        self.assertEqual(self.http.post("/encoder/ingest", json=body).status_code, 401)
        h = self.signup("alice")
        self.assertEqual(self.http.post("/encoder/ingest", json={**body, "enc1": 2 ** 40}, headers=h).status_code, 422)
        self.assertEqual(self.http.post("/encoder/ingest", json=body, headers=h).status_code, 200)

    def test_state_pose_and_zero_are_per_user(self):
        a, b = self.signup("alice"), self.signup("bob")
        self.http.post("/encoder/ingest", json={"timestamp": 1, "enc1": 5, "enc2": 6, "enc3": 7}, headers=a)
        self.assertEqual(self.http.get("/encoder/state", headers=a).json()["raw"]["Enc_2"], 6)
        self.assertFalse(self.http.get("/encoder/state", headers=b).json()["connected"])
        self.assertTrue(self.http.get("/simulation/pose", headers=a).json()["connected"])
        self.assertFalse(self.http.get("/simulation/pose", headers=b).json()["connected"])
        self.assertEqual(self.http.post("/encoder/zero/Joint_PITCH", headers=a).json()["offset"], 6)
        self.assertEqual(self.http.post("/encoder/zero/Joint_PITCH", headers=b).status_code, 409)

    def test_static_files_are_served(self):
        js = self.http.get("/static/haptic_model.js")
        self.assertEqual(js.status_code, 200)
        self.assertIn("HapticModel", js.text)
        self.assertEqual(self.http.get("/").status_code, 200)

    def test_bad_token_is_401_but_no_token_uses_machine_wide_state(self):
        self.assertEqual(self.http.get("/encoder/state", headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(self.http.get("/encoder/state").status_code, 200)   # โหมดเครื่องเดียว (บริดจ์/เครื่องแล็บ)


if __name__ == "__main__":
    unittest.main()