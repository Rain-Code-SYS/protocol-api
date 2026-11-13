"""ทดสอบ serial_bridge.py กับสตรีมแบบ Trig Protocol 2 (timestamp;enc1;enc2;enc3) โดยไม่ต้องมีพอร์ตจริง"""
import unittest
from unittest import mock

from tests.helpers import offline_client

import serial_bridge


class FakeSerialModule:
    class SerialException(Exception):
        pass

    def __init__(self, lines, fail_open=False):
        self._lines = list(lines)
        self._fail_open = fail_open
        self.instance = None
        self.written = []

    def Serial(self, port, baud, timeout=1):
        if self._fail_open:
            raise self.SerialException("could not open port")
        outer = self

        class Port:
            is_open = True
            reset_called = False

            def reset_input_buffer(self):
                self.reset_called = True

            def write(self, data):
                outer.written.append(data)

            def readline(self):
                if not outer._lines:
                    raise KeyboardInterrupt
                return outer._lines.pop(0)

            def close(self):
                self.is_open = False

        self.instance = Port()
        self.port, self.baud = port, baud
        return self.instance


class ParseLineTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(serial_bridge, "client", offline_client())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_valid_line(self):
        self.assertEqual(
            serial_bridge.parse_telemetry_line("15230;1024;-512;3071\r\n"),
            {"timestamp": 15230, "enc1": 1024, "enc2": -512, "enc3": 3071},
        )

    def test_legacy_prefix_is_stripped(self):
        self.assertEqual(
            serial_bridge.parse_telemetry_line("$TRIG2, 1;2;3;4")["enc3"], 4
        )

    def test_bad_lines_return_none(self):
        for bad in ("", "   ", "1;2;3", "1;2;3;4;5", "a;b;c;d", "1;2;3;4.5", "0.0;15.0;10.0;1"):
            with self.subTest(line=bad):
                self.assertIsNone(serial_bridge.parse_telemetry_line(bad))


class RunBridgeTests(unittest.TestCase):
    def setUp(self):
        for p in (
            mock.patch.object(serial_bridge, "client", offline_client()),
            mock.patch.object(serial_bridge.time, "sleep"),
            mock.patch.object(serial_bridge, "SYNC_ENCODER_CONFIG", False),
        ):
            p.start()
            self.addCleanup(p.stop)

    def run_with(self, lines, **kw):
        fake = FakeSerialModule(lines)
        with mock.patch.object(serial_bridge, "serial", fake), mock.patch("builtins.print") as pr:
            serial_bridge.run_bridge(**kw)
        return fake, [str(c.args[0]) for c in pr.call_args_list]

    def test_uses_stm32_port_settings_and_resets_buffer(self):
        fake, _ = self.run_with([b"1;1;1;1\n"], max_samples=1)
        self.assertEqual((fake.port, fake.baud), ("COM16", 230400))
        self.assertTrue(fake.instance.reset_called)
        self.assertFalse(fake.instance.is_open)  # ปิดพอร์ตเสมอ

    def test_garbage_does_not_crash_and_valid_lines_are_received(self):
        lines = [b"\xff\xfe junk\n", b"12;5\n", b"\n", b"100;1;2;3\n", b"101;4;5;6\n"]
        _, out = self.run_with(lines, max_samples=2)
        self.assertEqual(sum("Encoder Telemetry Received" in o for o in out), 1)  # PRINT_EVERY = 10
        self.assertTrue(any("ข้ามบรรทัด" in o for o in out))

    def test_keyboard_interrupt_is_handled(self):
        _, out = self.run_with([b"1;2;3;4\n"])
        self.assertIn("Bridge stopped by user.", out)

    def test_serial_open_failure_reported(self):
        fake = FakeSerialModule([], fail_open=True)
        with mock.patch.object(serial_bridge, "serial", fake), mock.patch("builtins.print") as pr:
            serial_bridge.run_bridge()
        self.assertTrue(any("Serial Error" in str(c.args[0]) for c in pr.call_args_list))

    def test_missing_pyserial_gives_install_hint(self):
        with mock.patch.object(serial_bridge, "serial", None), mock.patch("builtins.print") as pr:
            serial_bridge.run_bridge()
        self.assertIn("pyserial", str(pr.call_args.args[0]))

    def test_api_down_is_reported_not_swallowed(self):
        import requests
        from protocol_sdk.client import ProtocolClient

        down = ProtocolClient()  # cache ว่าง → ต้องยิง HTTP
        with mock.patch.object(serial_bridge, "client", down), \
             mock.patch("protocol_sdk.client.requests.get", side_effect=requests.ConnectionError("down")), \
             mock.patch.object(serial_bridge, "serial", FakeSerialModule([b"1;2;3;4\n"])), \
             mock.patch("builtins.print") as pr:
            serial_bridge.run_bridge()
        self.assertTrue(any("ดึง Schema" in str(c.args[0]) for c in pr.call_args_list))

    def test_samples_are_processed_and_commands_written_back(self):
        fake, _ = self.run_with([b"100;0;0;0\n", b"110;0;0;0\n"], max_samples=2)
        self.assertEqual(len(fake.written), 2)
        for data in fake.written:
            self.assertTrue(data.endswith(b"\n"))
            self.assertEqual(len(data.decode().strip().split(";")), 4)  # Ki;Kv;bp;by

    def test_send_commands_can_be_disabled(self):
        with mock.patch.object(serial_bridge, "SEND_COMMANDS", False):
            fake, _ = self.run_with([b"100;0;0;0\n"], max_samples=1)
        self.assertEqual(fake.written, [])

    def test_model_error_does_not_stop_bridge(self):
        model_cls = serial_bridge.TissueResistanceModel
        with mock.patch.object(model_cls, "process_encoder", side_effect=[ValueError("bad"), "1;2;0;0"]):
            fake, out = self.run_with([b"100;0;0;0\n", b"110;0;0;0\n"], max_samples=2)
        self.assertEqual(fake.written, [b"1;2;0;0\n"])
        self.assertTrue(any("โมเดลประมวลผล" in o for o in out))

    def test_config_sync_starts_and_stops_when_enabled(self):
        model_cls = serial_bridge.TissueResistanceModel
        with mock.patch.object(serial_bridge, "SYNC_ENCODER_CONFIG", True), \
             mock.patch.object(model_cls, "apply_encoder_config_from_api") as apply_cfg, \
             mock.patch.object(model_cls, "start_encoder_config_sync") as start, \
             mock.patch.object(model_cls, "stop_encoder_config_sync") as stop:
            self.run_with([b"1;1;1;1\n"], max_samples=1)
        apply_cfg.assert_called_once()
        start.assert_called_once()
        stop.assert_called_once()

    def test_config_fetch_failure_falls_back_to_defaults(self):
        import requests
        model_cls = serial_bridge.TissueResistanceModel
        with mock.patch.object(serial_bridge, "SYNC_ENCODER_CONFIG", True), \
             mock.patch.object(model_cls, "apply_encoder_config_from_api", side_effect=requests.ConnectionError("down")), \
             mock.patch.object(model_cls, "start_encoder_config_sync"), \
             mock.patch.object(model_cls, "stop_encoder_config_sync"):
            fake, out = self.run_with([b"100;0;0;0\n"], max_samples=1)
        self.assertTrue(any("ค่าตั้งต้น" in o for o in out))
        self.assertEqual(len(fake.written), 1)  # บริดจ์ยังทำงานต่อด้วยค่าตั้งต้น


if __name__ == "__main__":
    unittest.main()