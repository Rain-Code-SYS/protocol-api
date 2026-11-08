"""ทดสอบ Trig Protocol 2 แบบใหม่ (timestamp;enc1;enc2;enc3), EncoderStreamReader และการแปลง counts → มุมในโมเดล"""
import types
import unittest
from unittest import mock

import encoder_reader
from encoder_reader import EncoderStreamReader
from tests.helpers import offline_client
from tests.telemetry_utils import high_resolution, make_line, theta_for_depth
from tissue_model import AxisCalibration, TissueResistanceModel

MM = 0.001


def make_model():
    model = TissueResistanceModel()
    model.client = offline_client()
    return high_resolution(model)


class Protocol2SchemaTests(unittest.TestCase):
    def setUp(self):
        self.client = offline_client()

    def test_schema_layout(self):
        schema = self.client.get_schema("trig_protocol_2")
        self.assertEqual(schema["format_type"], "delimited")
        self.assertEqual(schema["delimiter"], ";")
        self.assertEqual([f["name"] for f in schema["fields"]], ["timestamp", "enc1", "enc2", "enc3"])
        self.assertTrue(all(f["data_type"] == "int" for f in schema["fields"]))

    def test_parse_valid_and_negative_counts(self):
        self.assertEqual(
            self.client.parse_message("trig_protocol_2", "15230;1024;-512;3071"),
            {"timestamp": 15230, "enc1": 1024, "enc2": -512, "enc3": 3071},
        )

    def test_wrong_field_count_rejected(self):
        for bad in ("1;2;3", "1;2;3;4;5", ""):
            with self.subTest(line=bad):
                with self.assertRaises(ValueError):
                    self.client.parse_message("trig_protocol_2", bad)

    def test_non_integer_rejected(self):
        for bad in ("1000;1.5;0;0", "abc;0;0;0", "1000;0;0;x"):
            with self.subTest(line=bad):
                with self.assertRaises(ValueError):
                    self.client.parse_message("trig_protocol_2", bad)

    def test_old_float_format_rejected(self):
        with self.assertRaises(ValueError):
            self.client.parse_message("trig_protocol_2", "0.0;15.0;10.0;1")


class ReaderParseLineTests(unittest.TestCase):
    def test_valid_lines(self):
        for line, expected in [
            ("15230;1024;-512;3071", (15230, 1024, -512, 3071)),
            ("15230;1024;-512;3071\r\n", (15230, 1024, -512, 3071)),
            ("  0;0;0;0  ", (0, 0, 0, 0)),
        ]:
            with self.subTest(line=line):
                self.assertEqual(EncoderStreamReader.parse_line(line), expected)

    def test_invalid_lines_return_none(self):
        for line in ("", "\n", "1;2;3", "1;2;3;4;5", "a;b;c;d", "1;2;3;4.5", "1,2,3,4"):
            with self.subTest(line=line):
                self.assertIsNone(EncoderStreamReader.parse_line(line))


class FakeSerial:
    def __init__(self, lines=()):
        self.lines = list(lines)
        self.is_open = True
        self.reset_called = False

    def readline(self):
        return self.lines.pop(0) if self.lines else b""  # หมดเวลา → bytes ว่าง

    def reset_input_buffer(self):
        self.reset_called = True

    def close(self):
        self.is_open = False


class ReaderSerialTests(unittest.TestCase):
    def test_defaults_match_sample(self):
        r = EncoderStreamReader()
        self.assertEqual((r.port, r.baud_rate, r.timeout), ("COM16", 230400, 1))

    def test_read_data(self):
        r = EncoderStreamReader()
        r.ser = FakeSerial([b"1000;1;2;3\n", b"1010;4;5;6\r\n"])
        self.assertEqual(r.read_data(), (1000, 1, 2, 3))
        self.assertEqual(r.read_data(), (1010, 4, 5, 6))

    def test_read_data_timeout_and_garbage(self):
        r = EncoderStreamReader()
        r.ser = FakeSerial([b"", b"garbage\n", b"\xff1000;1;2;3\n"])
        self.assertIsNone(r.read_data())            # timeout
        self.assertIsNone(r.read_data())            # บรรทัดเสีย
        self.assertEqual(r.read_data(), (1000, 1, 2, 3))  # ไบต์ไม่ใช่ utf-8 ถูกข้าม

    def test_read_data_without_connection(self):
        r = EncoderStreamReader()
        self.assertIsNone(r.read_data())
        r.ser = FakeSerial()
        r.ser.is_open = False
        self.assertIsNone(r.read_data())

    def test_connect_success(self):
        fake = FakeSerial()
        fake_serial_module = types.SimpleNamespace(Serial=mock.Mock(return_value=fake), SerialException=OSError)
        with mock.patch.object(encoder_reader, "serial", fake_serial_module), \
                mock.patch.object(encoder_reader.time, "sleep") as sleep:
            r = EncoderStreamReader(port="COM7", baud_rate=115200)
            self.assertTrue(r.connect())
        fake_serial_module.Serial.assert_called_once_with("COM7", 115200, timeout=1)
        sleep.assert_called_once_with(2)
        self.assertTrue(fake.reset_called)

    def test_connect_failure(self):
        fake_serial_module = types.SimpleNamespace(Serial=mock.Mock(side_effect=OSError("busy")), SerialException=OSError)
        with mock.patch.object(encoder_reader, "serial", fake_serial_module):
            self.assertFalse(EncoderStreamReader().connect())

    def test_connect_without_pyserial(self):
        with mock.patch.object(encoder_reader, "serial", None):
            self.assertFalse(EncoderStreamReader().connect())

    def test_close(self):
        r = EncoderStreamReader()
        r.ser = FakeSerial()
        r.close()
        self.assertFalse(r.ser.is_open)
        r.close()  # ปิดซ้ำต้องไม่ error


class AxisCalibrationTests(unittest.TestCase):
    def test_to_deg(self):
        self.assertAlmostEqual(AxisCalibration("enc1").to_deg(1024), 90.0)
        self.assertAlmostEqual(AxisCalibration("enc1", zero_counts=100).to_deg(1124), 90.0)
        self.assertAlmostEqual(AxisCalibration("enc1", sign=-1).to_deg(1024), -90.0)
        self.assertAlmostEqual(AxisCalibration("enc1", counts_per_rev=1000).to_deg(250), 90.0)

    def test_default_channel_mapping(self):
        m = TissueResistanceModel()
        self.assertEqual(m.encoders_to_angles(1024, 2048, 3072), (90.0, 180.0, 270.0))

    def test_unequal_counts_per_rev_per_encoder(self):
        """เอนโค้ดเดอร์ 3 ตัวมี counts/รอบไม่เท่ากัน: แต่ละแกนใช้ค่าของตัวเอง"""
        m = TissueResistanceModel()
        m.axes["pitch"].counts_per_rev = 2000
        m.axes["yaw"].counts_per_rev = 4096
        m.axes["theta2"].counts_per_rev = 8192
        # counts เท่ากัน แต่ความละเอียดต่างกัน → มุมต่างกัน
        pitch, yaw, theta2 = m.encoders_to_angles(1000, 1000, 1000)
        self.assertAlmostEqual(pitch, 180.0)
        self.assertAlmostEqual(yaw, 1000 * 360.0 / 4096)
        self.assertAlmostEqual(theta2, 1000 * 360.0 / 8192)
        # ครึ่งรอบของแต่ละตัว (counts ต่างกัน) → ทุกแกนได้ 180°
        self.assertEqual(m.encoders_to_angles(1000, 2048, 4096), (180.0, 180.0, 180.0))

    def test_custom_mapping(self):
        m = TissueResistanceModel()
        m.axes["theta2"].channel = "enc1"
        m.axes["pitch"].channel = "enc3"
        pitch, yaw, theta2 = m.encoders_to_angles(1024, 2048, 3072)
        self.assertEqual((pitch, yaw, theta2), (270.0, 180.0, 90.0))

    def test_unknown_channel_rejected(self):
        m = TissueResistanceModel()
        m.axes["yaw"].channel = "enc9"
        with self.assertRaises(KeyError):
            m.encoders_to_angles(0, 0, 0)


class ProcessEncoderTests(unittest.TestCase):
    def kv(self, out):
        return float(out.split(";")[1])

    def test_process_encoder_matches_process_telemetry(self):
        a, b = make_model(), make_model()
        line = make_line(a, theta_for_depth(a, 5 * MM), 1000)
        ts, e1, e2, e3 = EncoderStreamReader.parse_line(line)
        self.assertEqual(a.process_telemetry(line), b.process_encoder(ts, e1, e2, e3))

    def test_reader_tuple_can_be_unpacked(self):
        m = make_model()
        sample = EncoderStreamReader.parse_line(make_line(m, theta_for_depth(m, 5 * MM), 1000))
        self.assertEqual(len(m.process_encoder(*sample).split(";")), 4)

    def test_velocity_uses_encoder_timestamps(self):
        m = make_model()
        m.process_telemetry(make_line(m, theta_for_depth(m, 2 * MM), 1000))
        out = m.process_telemetry(make_line(m, theta_for_depth(m, 3 * MM), 1010))
        # ลึกขึ้น 1 mm ใน 10 ms = 0.1 m/s → Kv = 0.1*2.5 + 0.5 (ไม่ขึ้นกับเวลาจริงของเครื่อง)
        self.assertAlmostEqual(self.kv(out), 0.75, places=4)

    def test_same_millisecond_keeps_last_velocity(self):
        m = make_model()
        m.process_telemetry(make_line(m, theta_for_depth(m, 2 * MM), 1000))
        m.process_telemetry(make_line(m, theta_for_depth(m, 3 * MM), 1010))
        out = m.process_telemetry(make_line(m, theta_for_depth(m, 3.2 * MM), 1010))
        self.assertAlmostEqual(self.kv(out), 0.75, places=4)

    def test_clock_reset_restarts_velocity(self):
        m = make_model()
        m.process_telemetry(make_line(m, theta_for_depth(m, 2 * MM), 5000))
        out = m.process_telemetry(make_line(m, theta_for_depth(m, 3 * MM), 20))  # บอร์ดรีเซ็ต
        self.assertAlmostEqual(self.kv(out), 0.5)

    def test_touch_controls_brake_flags(self):
        m = make_model()
        line = make_line(m, theta_for_depth(m, 5 * MM), 1000)
        ts, e1, e2, e3 = EncoderStreamReader.parse_line(line)
        self.assertEqual(m.process_encoder(ts, e1, e2, e3).split(";")[2:], ["0", "0"])           # ค่าเริ่มต้น = ต้านแรง
        self.assertEqual(m.process_encoder(ts + 10, e1, e2, e3, touch=0).split(";")[2:], ["1", "1"])
        m.touch = 0
        self.assertEqual(m.process_encoder(ts + 20, e1, e2, e3).split(";")[2:], ["1", "1"])


if __name__ == "__main__":
    unittest.main()