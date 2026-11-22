"""กันสูตรใน tissue_model.py กับ static/haptic_model.js (JavaScript) แยกทางกัน

tests/haptic_vectors.json สร้างจากโค้ด Python (python -m tests.gen_haptic_vectors) และฝั่ง JS เทียบกับไฟล์นี้ (node --test)
เทสต์นี้สร้างค่าอ้างอิงใหม่จาก Python ตอนนี้แล้วเทียบกับไฟล์ที่เก็บไว้: ถ้าไม่ตรง = แก้ tissue_model.py แล้วยังไม่ได้สร้างไฟล์ใหม่และรัน node --test
"""
import json
import os
import unittest

from tests import gen_haptic_vectors as gen


def close(a, b):
    return abs(a - b) <= 1e-9 * max(1.0, abs(b))


class HapticVectorsUpToDate(unittest.TestCase):
    def test_stored_vectors_match_current_python_model(self):
        with open(gen.OUT, encoding="utf-8") as f:
            stored = json.load(f)
        fresh = [gen.build_case("default-config", gen.DEFAULT_CONFIG, False, 1),
                 gen.build_case("custom-config", gen.CUSTOM_CONFIG, True, 2)]
        for want, got in zip(stored["cases"], fresh):
            self.assertEqual(len(want["steps"]), len(got["steps"]))
            for i, (a, b) in enumerate(zip(want["steps"], got["steps"])):
                with self.subTest(case=want["name"], step=i):
                    if a["op"] != "sample":
                        self.assertEqual(a, b)
                        continue
                    self.assertEqual((a["ts"], a["e"], a["touch"], a["lung"]), (b["ts"], b["e"], b["touch"], b["lung"]))
                    self.assertEqual(a["cmd"], b["cmd"])   # แรงดัน V ปัดทศนิยม 3 ตำแหน่ง: ข้อความต้องตรงกันทุกตัวอักษร
                    for k in a["pose"]:
                        self.assertTrue(close(a["pose"][k], b["pose"][k]), k)

    def test_float_reprs_are_python_str(self):
        with open(gen.OUT, encoding="utf-8") as f:
            for value, text in json.load(f)["floats"]:
                self.assertEqual(str(value), text)


if __name__ == "__main__":
    unittest.main()