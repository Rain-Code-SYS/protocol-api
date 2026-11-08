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

    def Serial(self, port, baud, timeout=1):
        if self._fail_open:
            raise self.SerialException("could not open port")
        outer = self

        class Port:
            is_open = True
            reset_called = False

            def reset_input_buffer(self):
                self.reset_called = True

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


if __name__ == "__main__":
    unittest.main()