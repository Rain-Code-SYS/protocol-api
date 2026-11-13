"""ทดสอบ EncoderService (config, Set Zero, อ่านสตรีมใน thread) โดยไม่ต้องมีพอร์ตจริง"""
import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import encoder_service
from encoder_service import DEFAULT_CONFIG, EncoderService


class FakeReader:
    samples = []
    ok = True

    def __init__(self, port="COM16", baud_rate=230400):
        self.lines = list(FakeReader.samples)

    def connect(self):
        return FakeReader.ok

    def read_data(self):
        if self.lines:
            return self.lines.pop(0)
        time.sleep(0.005)
        return None

    def close(self):
        pass


def wait_for(cond, timeout=1.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "encoder_config.json")
        self.svc = EncoderService(self.path)
        FakeReader.samples, FakeReader.ok = [], True
        for p in (mock.patch.object(encoder_service, "EncoderStreamReader", FakeReader),
                  mock.patch.object(encoder_service.encoder_reader, "serial", object())):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.svc.disconnect)
        self.addCleanup(self.tmp.cleanup)

    def test_defaults_without_file(self):
        self.assertEqual(self.svc.config, DEFAULT_CONFIG)

    def test_loads_partial_and_bad_file(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"Joint_YAW": {"encoder_id": "Enc_3", "ppr": 2048, "offset": 7},
                       "Joint_PITCH": {"encoder_id": "Enc_9", "ppr": -1}}, f)
        cfg = EncoderService(self.path).config
        self.assertEqual(cfg["Joint_YAW"], {"encoder_id": "Enc_3", "ppr": 2048, "offset": 7})
        self.assertEqual(cfg["Joint_PITCH"], DEFAULT_CONFIG["Joint_PITCH"])
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(EncoderService(self.path).config, DEFAULT_CONFIG)

    def test_set_config_saves_and_keeps_offset(self):
        self.svc.config["Joint_YAW"]["offset"] = 50
        self.svc.set_config({"Joint_YAW": {"encoder_id": "Enc_1", "ppr": 2048}})
        self.assertEqual(self.svc.config["Joint_YAW"], {"encoder_id": "Enc_1", "ppr": 2048, "offset": 50})
        self.assertEqual(json.load(open(self.path, encoding="utf-8"))["Joint_YAW"]["ppr"], 2048)

    def test_changing_encoder_resets_offset(self):
        self.svc.config["Joint_YAW"]["offset"] = 50
        self.svc.set_config({"Joint_YAW": {"encoder_id": "Enc_1", "ppr": 1024},
                             "Joint_PITCH": {"encoder_id": "Enc_3", "ppr": 1024},
                             "Slider_MOTOR": {"encoder_id": "Enc_2", "ppr": 4096}})
        self.assertEqual(self.svc.config["Joint_PITCH"]["offset"], 0)
        self.assertEqual(self.svc.config["Joint_YAW"]["offset"], 50)

    def test_invalid_config_rejected_and_unchanged(self):
        bad = [{"Nope": {"encoder_id": "Enc_1", "ppr": 10}},
               {"Joint_YAW": {"encoder_id": "Enc_9", "ppr": 10}},
               {"Joint_YAW": {"encoder_id": "Enc_1", "ppr": 0}},
               {"Joint_YAW": {"encoder_id": "Enc_2", "ppr": 10}}]  # ซ้ำกับ Pitch
        for body in bad:
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    self.svc.set_config(body)
        self.assertEqual(self.svc.config, DEFAULT_CONFIG)
        self.assertFalse(os.path.exists(self.path))

    def test_zero_requires_data(self):
        with self.assertRaises(RuntimeError):
            self.svc.zero("Joint_YAW")
        with self.assertRaises(KeyError):
            self.svc.zero("nope")

    def test_stream_state_and_zero(self):
        FakeReader.samples = [(100, 10, -20, 30), (110, 11, -21, 31)]
        self.svc.connect("COM9", 115200)
        self.assertTrue(wait_for(lambda: self.svc.state()["timestamp"] == 110))
        st = self.svc.state()
        self.assertTrue(st["connected"])
        self.assertEqual((st["port"], st["baud"]), ("COM9", 115200))
        self.assertEqual(st["raw"], {"Enc_1": 11, "Enc_2": -21, "Enc_3": 31})
        self.assertEqual(self.svc.zero("Joint_PITCH"), -21)
        self.assertEqual(json.load(open(self.path, encoding="utf-8"))["Joint_PITCH"]["offset"], -21)
        self.svc.disconnect()
        self.assertFalse(self.svc.state()["connected"])

    def test_connect_failure_and_missing_pyserial(self):
        FakeReader.ok = False
        with self.assertRaises(RuntimeError):
            self.svc.connect("COM9")
        self.assertFalse(self.svc.state()["connected"])
        with mock.patch.object(encoder_service.encoder_reader, "serial", None):
            with self.assertRaises(RuntimeError) as ctx:
                self.svc.connect()
        self.assertIn("pyserial", str(ctx.exception))

    def test_read_error_marks_disconnected(self):
        class Broken(FakeReader):
            def read_data(self):
                raise OSError("unplugged")
        with mock.patch.object(encoder_service, "EncoderStreamReader", Broken):
            self.svc.connect("COM9")
            self.assertTrue(wait_for(lambda: not self.svc.state()["connected"]))
        self.assertIn("unplugged", self.svc.state()["error"])


    def test_unparseable_lines_are_counted_and_last_one_kept(self):
        class Garbage(FakeReader):
            last_raw = "hello world\r\n"
        with mock.patch.object(encoder_service, "EncoderStreamReader", Garbage):
            self.svc.connect("COM9")
            self.assertTrue(wait_for(lambda: self.svc.state()["bad_lines"] > 0))
        st = self.svc.state()
        self.assertEqual((st["samples"], st["last_raw"]), (0, "hello world"))

    def test_silent_port_has_no_counts(self):
        self.svc.connect("COM9")
        time.sleep(0.05)
        st = self.svc.state()
        self.assertEqual((st["samples"], st["bad_lines"], st["last_raw"]), (0, 0, None))

    def test_good_samples_are_counted(self):
        FakeReader.samples = [(1, 1, 1, 1), (2, 2, 2, 2)]
        self.svc.connect("COM9")
        self.assertTrue(wait_for(lambda: self.svc.state()["samples"] == 2))

    # ---------- เลือกพอร์ตตามที่เสียบจริง (ไม่ฟิก COM) ----------
    def _ports(self, *devices):
        return mock.patch.object(encoder_service, "list_serial_ports",
                                 return_value=[{"device": d, "description": ""} for d in devices])

    def test_connect_without_port_uses_the_only_port(self):
        with self._ports("COM7"):
            self.svc.connect()
        self.assertEqual(self.svc.state()["port"], "COM7")

    def test_connect_without_port_fails_when_none_or_ambiguous(self):
        for devices in ((), ("COM3", "COM16")):
            with self.subTest(devices=devices), self._ports(*devices):
                with self.assertRaises(RuntimeError):
                    self.svc.connect()
                self.assertFalse(self.svc.state()["connected"])

    def test_explicit_port_is_never_replaced(self):
        with self._ports("COM7"):
            self.svc.connect("COM16")
        self.assertEqual(self.svc.state()["port"], "COM16")


class ListPortsTests(unittest.TestCase):
    @staticmethod
    def fake_pyserial(*items):
        ports = [types.SimpleNamespace(device=d, description=desc) for d, desc in items]
        list_ports = types.SimpleNamespace(comports=lambda: ports)
        return mock.patch.dict(sys.modules, {"serial": types.ModuleType("serial"),
                                             "serial.tools": types.SimpleNamespace(list_ports=list_ports)})

    def test_sorted_by_com_number_and_cleans_description(self):
        with self.fake_pyserial(("COM16", "STM32 Virtual ComPort"), ("COM3", "n/a"), ("COM4", "")):
            got = encoder_service.list_serial_ports()
        self.assertEqual([p["device"] for p in got], ["COM3", "COM4", "COM16"])
        self.assertEqual(got[0]["description"], "")
        self.assertEqual(got[2]["description"], "STM32 Virtual ComPort")

    def test_without_pyserial_returns_empty_list(self):
        with mock.patch.dict(sys.modules, {"serial": None}):
            self.assertEqual(encoder_service.list_serial_ports(), [])


if __name__ == "__main__":
    unittest.main()