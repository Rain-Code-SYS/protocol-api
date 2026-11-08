"""ทดสอบ Trig Protocol 1 (bitfield 7 บิต 0bAADDCMM): decode/encode, validation 127/128 และ API ingest"""
import os
import tempfile
import unittest
from unittest import mock

from tests.helpers import ROOT, load_schemas, offline_client


class DecodeBitfieldTests(unittest.TestCase):
    def setUp(self):
        self.client = offline_client()

    def decode(self, value):
        return self.client.decode_bitfield("trig_protocol_1", value)

    def test_known_value_41(self):
        # 41 = 0b0101001 -> Adult / Medium / Basic / Guide
        self.assertEqual(
            self.decode(41),
            {"age": 1, "difficulty": 1, "case_type": 0, "practice_mode": 1},
        )

    def test_min_and_max_valid(self):
        self.assertEqual(self.decode(0), {"age": 0, "difficulty": 0, "case_type": 0, "practice_mode": 0})
        # Geriatric / Hard / Emer / Blind = 0b10_10_1_10 = 86
        self.assertEqual(self.decode(0b1010110), {"age": 2, "difficulty": 2, "case_type": 1, "practice_mode": 2})

    def test_127_rejected_by_field_enum(self):
        # 127 = 0b1111111 อยู่ในช่วง 7 บิต แต่ age=0b11=3 เกิน max_value 2
        with self.assertRaises(ValueError) as ctx:
            self.decode(127)
        self.assertIn("age", str(ctx.exception))

    def test_128_rejected_by_range(self):
        # 128 = 0b10000000 เกิน 7 บิต
        with self.assertRaises(ValueError) as ctx:
            self.decode(128)
        self.assertIn("127", str(ctx.exception))

    def test_other_out_of_range_values(self):
        for bad in (-1, 129, 255, 1000):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.decode(bad)

    def test_each_field_rejects_0b11(self):
        # difficulty = 3, practice_mode = 3 (age ปกติ)
        with self.assertRaises(ValueError) as ctx:
            self.decode(0b00_11_0_00)
        self.assertIn("difficulty", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            self.decode(0b00_00_0_11)
        self.assertIn("practice_mode", str(ctx.exception))

    def test_exactly_54_valid_values(self):
        valid = []
        for v in range(128):
            try:
                self.decode(v)
                valid.append(v)
            except ValueError:
                pass
        self.assertEqual(len(valid), 3 * 3 * 2 * 3)


class EncodeBitfieldTests(unittest.TestCase):
    def setUp(self):
        self.client = offline_client()

    def test_roundtrip_all_valid_combinations(self):
        for age in range(3):
            for diff in range(3):
                for case in range(2):
                    for mode in range(3):
                        data = {"age": age, "difficulty": diff, "case_type": case, "practice_mode": mode}
                        value = self.client.encode_bitfield("trig_protocol_1", data)
                        self.assertTrue(0 <= value < 128)
                        self.assertEqual(self.client.decode_bitfield("trig_protocol_1", value), data)

    def test_encode_rejects_age_3(self):
        with self.assertRaises(ValueError):
            self.client.encode_bitfield(
                "trig_protocol_1", {"age": 3, "difficulty": 0, "case_type": 0, "practice_mode": 0}
            )

    def test_encode_requires_all_fields(self):
        with self.assertRaises(KeyError):
            self.client.encode_bitfield("trig_protocol_1", {"age": 1})


def _api_available():
    try:
        import fastapi.testclient  # noqa: F401
        import pydantic  # noqa: F401
        return int(pydantic.VERSION.split(".")[0]) >= 2
    except Exception:
        return False


@unittest.skipUnless(_api_available(), "ต้องติดตั้ง fastapi, httpx และ pydantic>=2 เพื่อทดสอบ API")
class ApiTests(unittest.TestCase):
    def setUp(self):
        import main
        from fastapi.testclient import TestClient

        self.main = main
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

    def test_ingest_valid_value_creates_session(self):
        r = self.http.post("/protocols/trig_protocol_1/ingest", json={"value": 41, "procedure": "thoracentesis"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["settings"]["age"], 1)
        self.assertEqual(len(self.http.get("/sessions").json()), 1)

    def test_ingest_127_and_128_return_400_and_no_session(self):
        for bad in (127, 128):
            with self.subTest(value=bad):
                r = self.http.post("/protocols/trig_protocol_1/ingest", json={"value": bad})
                self.assertEqual(r.status_code, 400)
        self.assertEqual(self.http.get("/sessions").json(), [])

    def test_post_bitfield_schema_keeps_bit_fields(self):
        schema = load_schemas()["trig_protocol_1"]
        schema["protocol_id"] = "copy_of_p1"
        r = self.http.post("/protocols", json=schema)
        self.assertEqual(r.status_code, 200)
        saved = self.http.get("/protocols/copy_of_p1").json()
        self.assertEqual(saved["bit_width"], 7)
        age = next(f for f in saved["fields"] if f["name"] == "age")
        self.assertEqual((age["bit_offset"], age["bit_width"], age["max_value"]), (5, 2, 2))

    def test_post_overlapping_bitfield_rejected_422(self):
        schema = load_schemas()["trig_protocol_1"]
        schema["protocol_id"] = "bad"
        schema["fields"][1]["bit_offset"] = 4  # difficulty ทับ age (บิต 5)
        self.assertEqual(self.http.post("/protocols", json=schema).status_code, 422)

    def test_post_bitfield_missing_bit_width_rejected_422(self):
        schema = load_schemas()["trig_protocol_1"]
        schema["protocol_id"] = "bad2"
        del schema["bit_width"]
        self.assertEqual(self.http.post("/protocols", json=schema).status_code, 422)

    def test_post_delimited_schema_has_no_bit_keys(self):
        schema = load_schemas()["trig_protocol_2"]
        schema["protocol_id"] = "copy_of_p2"
        self.assertEqual(self.http.post("/protocols", json=schema).status_code, 200)
        saved = self.http.get("/protocols/copy_of_p2").json()
        self.assertNotIn("bit_width", saved)
        self.assertNotIn("bit_offset", saved["fields"][0])


if __name__ == "__main__":
    unittest.main()