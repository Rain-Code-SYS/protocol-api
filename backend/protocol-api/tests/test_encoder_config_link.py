"""ทดสอบการใช้ encoder_config.json (ชุดเดียวกับหน้า Settings) กับ TissueResistanceModel"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import requests

from encoder_service import DEFAULT_CONFIG
from encoder_reader import EncoderStreamReader
from tests.helpers import offline_client
from tests.telemetry_utils import high_resolution, make_line, theta_for_depth
from tissue_model import TissueResistanceModel

CONFIG = {
    "Joint_YAW": {"encoder_id": "Enc_1", "ppr": 2048, "offset": 100},
    "Joint_PITCH": {"encoder_id": "Enc_2", "ppr": 800, "offset": 0},
    "Slider_MOTOR": {"encoder_id": "Enc_3", "ppr": 4096, "offset": 50},
}


def make_model():
    model = TissueResistanceModel()
    model.client = offline_client()
    return model


class ApplyEncoderConfigTests(unittest.TestCase):
    def test_maps_joints_to_axes(self):
        m = make_model()
        m.apply_encoder_config(CONFIG)
        self.assertEqual((m.axes["yaw"].channel, m.axes["yaw"].counts_per_rev, m.axes["yaw"].zero_counts), ("enc1", 2048.0, 100))
        self.assertEqual((m.axes["pitch"].channel, m.axes["pitch"].counts_per_rev, m.axes["pitch"].zero_counts), ("enc2", 800.0, 0))
        self.assertEqual((m.axes["theta2"].channel, m.axes["theta2"].counts_per_rev, m.axes["theta2"].zero_counts), ("enc3", 4096.0, 50))

    def test_angles_match_debugger_formula(self):
        m = make_model()
        m.apply_encoder_config(CONFIG)
        pitch, yaw, theta2 = m.encoders_to_angles(1124, 200, 1074)  # enc1=yaw, enc2=pitch, enc3=slider
        self.assertAlmostEqual(yaw, (1124 - 100) / 2048 * 360)
        self.assertAlmostEqual(pitch, 200 / 800 * 360)
        self.assertAlmostEqual(theta2, (1074 - 50) / 4096 * 360)

    def test_keeps_sign_and_resets_motion_state(self):
        m = make_model()
        m.axes["yaw"].sign = -1
        m.x_max, m.prev_x = 0.02, 0.03
        m.apply_encoder_config(CONFIG)
        self.assertEqual(m.axes["yaw"].sign, -1)
        self.assertEqual((m.x_max, m.prev_x), (0.0, None))

    def test_invalid_config_leaves_model_untouched(self):
        bad_cases = {
            "missing joint": {k: v for k, v in CONFIG.items() if k != "Joint_YAW"},
            "unknown encoder": {**CONFIG, "Joint_YAW": {"encoder_id": "Enc_9", "ppr": 10, "offset": 0}},
            "zero ppr": {**CONFIG, "Joint_YAW": {"encoder_id": "Enc_1", "ppr": 0, "offset": 0}},
            "duplicate encoder": {**CONFIG, "Joint_YAW": {"encoder_id": "Enc_2", "ppr": 10, "offset": 0}},
        }
        for name, cfg in bad_cases.items():
            with self.subTest(case=name):
                m = make_model()
                before = {a: (c.channel, c.counts_per_rev, c.zero_counts) for a, c in m.axes.items()}
                with self.assertRaises((KeyError, ValueError)):
                    m.apply_encoder_config(cfg)
                self.assertEqual(before, {a: (c.channel, c.counts_per_rev, c.zero_counts) for a, c in m.axes.items()})

    def test_defaults_match_settings_page(self):
        """ค่าตั้งต้นของโมเดล = Enc_1 Yaw 2048 / Enc_2 Pitch 800 / Enc_3 Slider 4096 (ตรงกับ encoder_config.json)"""
        m = make_model()
        got = {a: (c.channel, c.counts_per_rev, c.zero_counts) for a, c in m.axes.items()}
        self.assertEqual(got, {"yaw": ("enc1", 2048.0, 0), "pitch": ("enc2", 800.0, 0), "theta2": ("enc3", 4096.0, 0)})


class LoadersTests(unittest.TestCase):
    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "encoder_config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(CONFIG, f)
            m = make_model()
            self.assertEqual(m.load_encoder_config(path), CONFIG)
            self.assertEqual(m.axes["yaw"].zero_counts, 100)

    def test_load_from_api(self):
        m = make_model()
        fake = mock.Mock()
        fake.json.return_value = {"connected": True, "config": CONFIG, "raw": {}}
        with mock.patch("tissue_model.requests.get", return_value=fake) as get:
            m.apply_encoder_config_from_api()
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:8000/encoder/state")
        self.assertEqual(m.axes["theta2"].counts_per_rev, 4096.0)
        self.assertEqual(m.axes["pitch"].channel, "enc2")


class BackendDefaultsTests(unittest.TestCase):
    def test_model_defaults_equal_backend_defaults(self):
        """ไม่มี encoder_config.json ก็ต้องตรงกัน: หน้า Settings (backend) กับค่าตั้งต้นของโมเดล"""
        from tissue_model import ENCODER_CONFIG_AXES
        m = make_model()
        for joint, axis in ENCODER_CONFIG_AXES.items():
            cal, cfg = m.axes[axis], DEFAULT_CONFIG[joint]
            with self.subTest(joint=joint):
                self.assertEqual((cal.channel, cal.counts_per_rev, cal.zero_counts),
                                 (cfg["encoder_id"].lower().replace("_", ""), float(cfg["ppr"]), cfg["offset"]))


class AutoSyncTests(unittest.TestCase):
    @staticmethod
    def api(config):
        resp = mock.Mock()
        resp.json.return_value = {"config": config}
        return mock.patch("tissue_model.requests.get", return_value=resp)

    def test_new_config_is_applied_at_next_sample(self):
        m = make_model()
        self.assertEqual(m.axes["yaw"].zero_counts, 0)
        with self.api(CONFIG):
            self.assertTrue(m.fetch_encoder_config())
        self.assertEqual(m.axes["yaw"].zero_counts, 0)  # ยังไม่เปลี่ยนจนกว่าจะถึงตัวอย่างถัดไป
        m.process_encoder(1000, 0, 0, 0)
        self.assertEqual(m.axes["yaw"].zero_counts, 100)
        with self.api(CONFIG):
            self.assertFalse(m.fetch_encoder_config())  # ไม่เปลี่ยน = ไม่ต้องใช้ซ้ำ (ไม่รีเซ็ตรอบแทงโดยไม่จำเป็น)

    def test_ppr_saved_in_settings_reaches_model(self):
        m = make_model()
        changed = {**CONFIG, "Joint_YAW": {"encoder_id": "Enc_1", "ppr": 1000, "offset": 0}}
        with self.api(changed):
            m.fetch_encoder_config()
        m.process_encoder(1000, 0, 0, 0)
        self.assertEqual(m.axes["yaw"].counts_per_rev, 1000.0)

    def test_api_down_keeps_current_config(self):
        m = make_model()
        with mock.patch("tissue_model.requests.get", side_effect=requests.ConnectionError("down")):
            self.assertFalse(m.fetch_encoder_config())
        m.process_encoder(1000, 0, 0, 0)  # ต้องไม่ throw
        self.assertEqual(m.axes["yaw"].counts_per_rev, 2048.0)

    def test_invalid_config_is_ignored_and_not_retried(self):
        m = make_model()
        bad = {**CONFIG, "Joint_YAW": {"encoder_id": "Enc_9", "ppr": 10, "offset": 0}}
        with self.api(bad):
            self.assertTrue(m.fetch_encoder_config())
        with mock.patch("builtins.print"):
            m.process_encoder(1000, 0, 0, 0)  # ต้องไม่ throw
        self.assertEqual(m.axes["yaw"].channel, "enc1")
        with self.api(bad):
            self.assertFalse(m.fetch_encoder_config())

    def test_background_thread_polls_until_stopped(self):
        m = make_model()
        with mock.patch.object(m, "fetch_encoder_config") as fetch:
            m.start_encoder_config_sync(0.005)
            end = time.time() + 1
            while fetch.call_count < 3 and time.time() < end:
                time.sleep(0.005)
            m.stop_encoder_config_sync()
            time.sleep(0.05)
            count = fetch.call_count
            time.sleep(0.05)
        self.assertGreaterEqual(count, 3)
        self.assertEqual(fetch.call_count, count)  # หยุดแล้วไม่ดึงอีก


class PoseTests(unittest.TestCase):
    def test_pose_reports_depth_angles_and_thresholds(self):
        m = high_resolution(make_model())
        line = make_line(m, theta_for_depth(m, 0.005), 1000, yaw_deg=10, pitch_deg=-4)
        p = m.pose(*EncoderStreamReader.parse_line(line)[1:])
        self.assertAlmostEqual(p["depth_mm"], 5.0, places=2)
        self.assertAlmostEqual(p["yaw_deg"], 10.0, places=3)
        self.assertAlmostEqual(p["pitch_deg"], -4.0, places=3)
        self.assertAlmostEqual(p["pleura_mm"], 26.0)
        self.assertAlmostEqual(p["lung_mm"], 34.0)

    def test_pose_has_no_side_effects(self):
        m = make_model()
        with mock.patch.object(m, "_notify_lung") as notify:
            m.pose(0, 0, 4000)
        notify.assert_not_called()
        self.assertEqual((m.prev_x, m.x_max), (None, 0.0))

    def test_negative_angles_wrap(self):
        m = high_resolution(make_model())
        line = make_line(m, 0.0, 1000, pitch_deg=-30)
        self.assertAlmostEqual(m.pose(*EncoderStreamReader.parse_line(line)[1:])["pitch_deg"], -30.0, places=3)


if __name__ == "__main__":
    unittest.main()