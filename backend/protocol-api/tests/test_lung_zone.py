"""ทดสอบระยะฟรีของเข็ม (ก่อนเจาะ 10 mm / หลังทะลุเยื่อหุ้มปอด 8 mm), ชั้นปอด และ Trig Protocol 4 (lung_hit)"""
import os
import tempfile
import unittest
from unittest import mock

import requests

from tests.helpers import load_schemas, offline_client
from tests.telemetry_utils import high_resolution, make_line, theta_for_depth
from tissue_model import TissueResistanceModel

MM = 0.001


def make_model():
    model = TissueResistanceModel()
    model.client = offline_client()
    return high_resolution(model)


class LayoutTests(unittest.TestCase):
    def test_default_distances(self):
        m = make_model()
        self.assertAlmostEqual(m.free_before, 10 * MM)
        self.assertAlmostEqual(m.free_after, 8 * MM)
        self.assertAlmostEqual(m.x_pleura + m.delta2, 26 * MM)  # ผิว → ทะลุเยื่อหุ้มปอด = 26 mm
        self.assertAlmostEqual(m.x_lung, 34 * MM)               # เริ่มโดนปอด
        self.assertLess(m.free_before + m.x_lung, m.needle_stroke)  # 44 mm < 50 mm

    def test_layout_exceeding_stroke_rejected(self):
        m = make_model()
        m.free_after = 0.020
        with self.assertRaises(ValueError):
            m.apply_age(1)

    def test_depth_mapping(self):
        m = make_model()
        self.assertAlmostEqual(m.depth_from_s(m.calculate_kinematics(0.0)[0]), -10 * MM)
        for x in (-5 * MM, 0.0, 2 * MM, 26 * MM, 34 * MM):
            with self.subTest(x=x):
                s, _ = m.calculate_kinematics(theta_for_depth(m, x))
                self.assertAlmostEqual(m.depth_from_s(s), x, places=6)


class FreeZoneForceTests(unittest.TestCase):
    def test_no_force_before_skin_contact(self):
        m = make_model()
        for v in (0.0, 0.05, -0.05):
            with self.subTest(v=v):
                self.assertEqual(m.calculate_f_total(-5 * MM, v, 0.0), 0.0)

    def test_friction_only_in_free_zone_after_pleura(self):
        m = make_model()
        v = 0.1
        expected = m.b_fric * v + m.c_fric
        self.assertAlmostEqual(m.calculate_f_total(30 * MM, v, 30 * MM), expected)

    def test_cavity_friction_can_be_disabled(self):
        m = make_model()
        m.cavity_friction = False
        self.assertEqual(m.calculate_f_total(30 * MM, 0.1, 30 * MM), 0.0)

    def test_lung_force_starts_beyond_34mm(self):
        m = make_model()
        at_boundary = m.calculate_f_total(34 * MM, 0.0, 34 * MM)
        self.assertEqual(at_boundary, 0.0)  # ยังไม่เกิน → ไม่มีแรงปอด (v=0 → ไม่มีเสียดทาน)
        inside = m.calculate_f_total(36 * MM, 0.0, 36 * MM)
        self.assertAlmostEqual(inside, m.k_lung * 2 * MM)

    def test_lung_retract_uses_hysteresis(self):
        m = make_model()
        spring = m.k_lung * 2 * MM
        v = -0.05
        pull = m.calculate_f_total(36 * MM, v, 36 * MM)
        # ถอยเข็ม: แรงสปริงเหลือ gamma_lung เท่า + แรงเสียดทานขาออก
        self.assertAlmostEqual(pull, m.gamma_lung * spring + m.f_fric_out(36 * MM, v))


class LungFlagTests(unittest.TestCase):
    def run_depths(self, model, depths):
        for x in depths:
            model._test_ts = getattr(model, "_test_ts", 0) + 10  # timestamp เดินหน้าทีละ 10 ms
            model.process_telemetry(make_line(model, theta_for_depth(model, x), model._test_ts))

    def test_threshold_between_33_and_35mm(self):
        m = make_model()
        with mock.patch.object(m, "_notify_lung") as notify:
            self.run_depths(m, [-5 * MM, 10 * MM, 25 * MM, 33.9 * MM])
            notify.assert_not_called()
            self.assertFalse(m.lung_hit)
            self.run_depths(m, [34.1 * MM])
            notify.assert_called_once_with(True)
            self.assertTrue(m.lung_hit)

    def test_sends_only_on_state_change_and_clears_on_retract(self):
        m = make_model()
        with mock.patch.object(m, "_notify_lung") as notify:
            self.run_depths(m, [35 * MM, 35.5 * MM, 36 * MM])  # อยู่ในปอดต่อเนื่อง
            self.assertEqual(notify.call_args_list, [mock.call(True)])
            self.run_depths(m, [30 * MM, 20 * MM])  # ถอยออก
            self.assertEqual(notify.call_args_list, [mock.call(True), mock.call(False)])

    def test_reset_clears_flag_for_api(self):
        m = make_model()
        with mock.patch.object(m, "_notify_lung") as notify:
            self.run_depths(m, [36 * MM])
            notify.reset_mock()
            m.reset_state()
            notify.assert_called_once_with(False)

    def test_first_sample_has_zero_velocity(self):
        m = make_model()
        first = m.process_telemetry(make_line(m, theta_for_depth(m, 2 * MM), 1000))
        # ตัวอย่างแรก v = 0 → Kv = 0.5 พอดี (ไม่พุ่งผิดปกติ)
        self.assertAlmostEqual(float(first.split(";")[1]), 0.5)

    def test_post_sends_protocol4_value(self):
        m = make_model()
        with mock.patch("tissue_model.requests.post") as post:
            m._post_lung_flag(True)
            m._post_lung_flag(False)
        urls = [c.args[0] for c in post.call_args_list]
        self.assertEqual(urls, ["http://127.0.0.1:8000/protocols/trig_protocol_4/ingest"] * 2)
        self.assertEqual([c.kwargs["json"] for c in post.call_args_list], [{"value": 1}, {"value": 0}])

    def test_post_failure_does_not_raise(self):
        m = make_model()
        with mock.patch("tissue_model.requests.post", side_effect=requests.ConnectionError("down")):
            m._post_lung_flag(True)  # ต้องไม่ throw (ไม่ให้ลูปฮาร์ดแวร์ล้ม)

    def test_notify_runs_in_daemon_thread(self):
        m = make_model()
        with mock.patch("tissue_model.threading.Thread") as thread:
            m._notify_lung(True)
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()


class Protocol4SchemaTests(unittest.TestCase):
    def setUp(self):
        self.client = offline_client()

    def test_decode_and_encode(self):
        self.assertEqual(self.client.decode_bitfield("trig_protocol_4", 0), {"lung_hit": 0})
        self.assertEqual(self.client.decode_bitfield("trig_protocol_4", 1), {"lung_hit": 1})
        self.assertEqual(self.client.encode_bitfield("trig_protocol_4", {"lung_hit": 1}), 1)

    def test_values_outside_one_bit_rejected(self):
        for bad in (-1, 2, 3, 127):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.client.decode_bitfield("trig_protocol_4", bad)


def _api_available():
    try:
        import fastapi.testclient  # noqa: F401
        import pydantic
        return int(pydantic.VERSION.split(".")[0]) >= 2
    except Exception:
        return False


@unittest.skipUnless(_api_available(), "ต้องติดตั้ง fastapi, httpx และ pydantic>=2 เพื่อทดสอบ API")
class Protocol4ApiTests(unittest.TestCase):
    def setUp(self):
        import main
        from fastapi.testclient import TestClient

        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(main, "DB_FILE", os.path.join(self.tmp.name, "protocols.json")),
            mock.patch.object(main, "SESSIONS_FILE", os.path.join(self.tmp.name, "sessions.json")),
            mock.patch.dict(main.protocols_db, load_schemas(), clear=True),
            mock.patch.object(main, "sessions_db", []),
        ]
        for p in self.patches:
            p.start()
        self.http = TestClient(main.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_ingest_1_and_0(self):
        for value in (1, 0):
            r = self.http.post("/protocols/trig_protocol_4/ingest", json={"value": value})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["settings"], {"lung_hit": value})
        sessions = self.http.get("/sessions").json()
        self.assertEqual([s["settings"]["lung_hit"] for s in sessions], [1, 0])
        self.assertTrue(all(s["protocol_id"] == "trig_protocol_4" for s in sessions))

    def test_ingest_2_rejected_without_session(self):
        r = self.http.post("/protocols/trig_protocol_4/ingest", json={"value": 2})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.http.get("/sessions").json(), [])

    def test_protocol4_does_not_disturb_latest_protocol1_session(self):
        self.http.post("/protocols/trig_protocol_1/ingest", json={"value": 41})
        self.http.post("/protocols/trig_protocol_4/ingest", json={"value": 1})
        p1 = [s for s in self.http.get("/sessions").json() if s["protocol_id"] == "trig_protocol_1"]
        self.assertEqual(p1[-1]["settings"]["age"], 1)


if __name__ == "__main__":
    unittest.main()