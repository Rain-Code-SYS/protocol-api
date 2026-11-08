"""ทดสอบการเชื่อม Trig Protocol 1 (age) เข้ากับชั้นผิวหนังใน TissueResistanceModel"""
import unittest
from unittest import mock

from tests.helpers import offline_client
from tissue_model import AGE_SKIN_PROFILES, TissueResistanceModel


def make_model():
    model = TissueResistanceModel()
    model.client = offline_client()  # ใช้ Schema จากไฟล์ ไม่ยิง HTTP
    return model


class AgeProfileTests(unittest.TestCase):
    def test_adult_profile_equals_original_defaults(self):
        m = make_model()
        self.assertEqual(m.k_skin, AGE_SKIN_PROFILES[1]["k_skin"])
        self.assertEqual(m.x_p, AGE_SKIN_PROFILES[1]["x_p"])

    def test_apply_age_sets_skin_parameters(self):
        m = make_model()
        for code, profile in AGE_SKIN_PROFILES.items():
            with self.subTest(age=profile["label"]):
                m.apply_age(code)
                self.assertEqual((m.k_skin, m.x_p, m.age_code), (profile["k_skin"], profile["x_p"], code))

    def test_invalid_age_rejected_and_state_unchanged(self):
        m = make_model()
        m.apply_age(0)
        with self.assertRaises(ValueError):
            m.apply_age(3)
        self.assertEqual(m.age_code, 0)
        self.assertEqual(m.k_skin, AGE_SKIN_PROFILES[0]["k_skin"])

    def test_profiles_keep_layers_ordered(self):
        m = make_model()
        for code in AGE_SKIN_PROFILES:
            m.apply_age(code)
            self.assertLess(m.x_p + m.delta1, m.x_trans)
            self.assertLess(m.x_trans, m.x_pleura)


class SkinForceDiffersByAgeTests(unittest.TestCase):
    def skin_force(self, age, x=0.0015):
        m = make_model()
        m.apply_age(age)
        return m.calculate_f_total(x, 0.0, 0.0)  # v=0 → ไม่มีแรงเสียดทาน เหลือแรงสปริงผิวหนัง

    def test_same_depth_gives_different_force(self):
        ped, adult, ger = (self.skin_force(a) for a in (0, 1, 2))
        self.assertAlmostEqual(ped, 800.0 * 0.0015)
        self.assertAlmostEqual(adult, 1200.0 * 0.0015)
        self.assertAlmostEqual(ger, 1000.0 * 0.0015)
        self.assertEqual(len({round(ped, 6), round(adult, 6), round(ger, 6)}), 3)

    def test_puncture_peak_force_matches_profile(self):
        for code, profile in AGE_SKIN_PROFILES.items():
            with self.subTest(age=profile["label"]):
                m = make_model()
                m.apply_age(code)
                self.assertAlmostEqual(m.f_blend1(m.x_p), profile["k_skin"] * profile["x_p"])

    def test_puncture_happens_at_different_depths(self):
        # ลึก 2.2 mm: Pediatric ทะลุผิวหนังแล้ว (อยู่ใน blend zone) แต่ Adult ยังอยู่ในชั้นผิวหนัง
        x = 0.0022
        ped, adult = make_model(), make_model()
        ped.apply_age(0)
        adult.apply_age(1)
        f_ped = ped.calculate_f_total(x, 0.0, x)
        f_adult = adult.calculate_f_total(x, 0.0, x - 1e-6)  # Adult ยังไม่ทะลุ x_max<x_p
        self.assertTrue(ped.x_p <= x < ped.x_p + ped.delta1)
        self.assertTrue(x < adult.x_p)
        self.assertAlmostEqual(f_adult, 1200.0 * x)
        self.assertNotAlmostEqual(f_ped, f_adult)


class Protocol1LinkTests(unittest.TestCase):
    def test_apply_protocol1_value_decodes_and_configures(self):
        m = make_model()
        # age=0 (Pediatric), difficulty=2, case_type=1, practice_mode=1
        value = m.client.encode_bitfield(
            "trig_protocol_1", {"age": 0, "difficulty": 2, "case_type": 1, "practice_mode": 1}
        )
        settings = m.apply_protocol1_value(value)
        self.assertEqual(settings["age"], 0)
        self.assertEqual(m.k_skin, AGE_SKIN_PROFILES[0]["k_skin"])
        self.assertEqual(m.settings["difficulty"], 2)

    def test_127_and_128_rejected_before_changing_model(self):
        m = make_model()
        m.apply_age(2)
        for bad in (127, 128):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    m.apply_protocol1_value(bad)
        self.assertEqual(m.age_code, 2)  # ไม่ถูกแตะ

    def test_apply_settings_resets_motion_state(self):
        m = make_model()
        m.x_max = 0.02
        m.prev_x = 0.03
        m.apply_settings({"age": 1, "difficulty": 0, "case_type": 0, "practice_mode": 0})
        self.assertEqual((m.x_max, m.prev_x), (0.0, None))

    def test_apply_settings_requires_age(self):
        with self.assertRaises(KeyError):
            make_model().apply_settings({"difficulty": 1})

    def test_apply_latest_session_uses_last_trig1_session(self):
        m = make_model()
        fake = mock.Mock()
        fake.json.return_value = [
            {"protocol_id": "trig_protocol_1", "settings": {"age": 0, "difficulty": 0, "case_type": 0, "practice_mode": 0}},
            {"protocol_id": "trig_protocol_1", "settings": {"age": 2, "difficulty": 1, "case_type": 0, "practice_mode": 0}},
        ]
        with mock.patch("tissue_model.requests.get", return_value=fake):
            settings = m.apply_latest_session()
        self.assertEqual(settings["age"], 2)
        self.assertEqual(m.k_skin, AGE_SKIN_PROFILES[2]["k_skin"])

    def test_apply_latest_session_returns_none_when_empty(self):
        m = make_model()
        fake = mock.Mock()
        fake.json.return_value = []
        with mock.patch("tissue_model.requests.get", return_value=fake):
            self.assertIsNone(m.apply_latest_session())


class TelemetryStillWorksTests(unittest.TestCase):
    def test_process_telemetry_returns_protocol3_message(self):
        m = make_model()
        m.apply_age(0)
        out = m.process_telemetry("1000;0;0;398")  # timestamp;enc1;enc2;enc3
        self.assertEqual(len(out.split(";")), 4)


if __name__ == "__main__":
    unittest.main()