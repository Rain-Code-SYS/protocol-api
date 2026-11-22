"""ทดสอบ Trig Protocol 2 แบบใหม่ (timestamp;enc1;enc2;enc3), EncoderStreamReader และการแปลง counts → มุมในโมเดล"""
import types
import unittest
from unittest import mock

import encoder_reader
from encoder_reader import EncoderStreamReader
from tests.helpers import offline_client
from tests.telemetry_utils import expected_voltage, high_resolution, make_line, slider_counts_for_depth
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
            ("1368950;-24;194;1321;0;0;0", (1368950, -24, 194, 1321)),  # เฟิร์มแวร์ส่งฟิลด์ต่อท้าย: ข้ามส่วนเกิน
        ]:
            with self.subTest(line=line):
                self.assertEqual(EncoderStreamReader.parse_line(line), expected)

    def test_invalid_lines_return_none(self):
        for line in ("", "\n", "1;2;3", "a;b;c;d", "1;2;3;4.5", "1,2,3,4", "1;2;3;x;0;0;0"):
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

    def test_last_raw_keeps_the_unparsed_line(self):
        r = EncoderStreamReader()
        self.assertEqual(r.last_raw, "")
        r.ser = FakeSerial([b"hello\r\n"])
        self.assertIsNone(r.read_data())
        self.assertEqual(r.last_raw, "hello\r\n")

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
    """Trig Protocol 3 = แรงดัน V ค่าเดียว (0 – 3.3 V): ปล่อยแรง (touch = 0) = 0 V"""

    @staticmethod
    def volt(out):
        return float(out)

    def test_process_encoder_matches_process_telemetry(self):
        a, b = make_model(), make_model()
        line = make_line(a, slider_counts_for_depth(a, 5 * MM), 1000)
        ts, e1, e2, e3 = EncoderStreamReader.parse_line(line)
        self.assertEqual(a.process_telemetry(line), b.process_encoder(ts, e1, e2, e3))

    def test_reader_tuple_can_be_unpacked(self):
        m = make_model()
        sample = EncoderStreamReader.parse_line(make_line(m, slider_counts_for_depth(m, 5 * MM), 1000))
        out = m.process_encoder(*sample)
        self.assertEqual(len(out.split(";")), 1)          # ค่าเดียว ไม่มีตัวคั่น
        self.assertTrue(0.0 <= self.volt(out) <= 3.3)

    def test_output_is_voltage_from_torque(self):
        m = make_model()
        enc = EncoderStreamReader.parse_line(make_line(m, slider_counts_for_depth(m, 2 * MM), 1000))[1:]
        want = expected_voltage(m, enc, 0.0, 0.0)   # ตัวอย่างแรก v = 0 ที่ลึก 2 mm = แรงสปริงผิวหนังล้วน
        self.assertGreater(want, 0.0)
        self.assertAlmostEqual(self.volt(m.process_encoder(1000, *enc)), want, delta=0.0006)

    def test_velocity_uses_encoder_timestamps(self):
        m = make_model()
        m.process_telemetry(make_line(m, slider_counts_for_depth(m, 2 * MM), 1000))
        line = make_line(m, slider_counts_for_depth(m, 3 * MM), 1010)
        enc = EncoderStreamReader.parse_line(line)[1:]
        want = expected_voltage(m, enc, 0.1, 3 * MM)   # ลึกขึ้น 1 mm ใน 10 ms = 0.1 m/s (ไม่ขึ้นกับเวลาจริงของเครื่อง)
        self.assertAlmostEqual(self.volt(m.process_telemetry(line)), want, delta=0.01)
        slow = make_model()   # เวลาห่างขึ้น 10 เท่า → ความเร็วน้อยลง → แรงเสียดทานน้อยลง → V ต่างกัน
        slow.process_telemetry(make_line(slow, slider_counts_for_depth(slow, 2 * MM), 1000))
        slow_v = self.volt(slow.process_telemetry(make_line(slow, slider_counts_for_depth(slow, 3 * MM), 1100)))
        self.assertNotAlmostEqual(slow_v, want, delta=0.01)

    def test_same_millisecond_keeps_last_velocity(self):
        m = make_model()
        m.process_telemetry(make_line(m, slider_counts_for_depth(m, 2 * MM), 1000))
        m.process_telemetry(make_line(m, slider_counts_for_depth(m, 3 * MM), 1010))
        line = make_line(m, slider_counts_for_depth(m, 3.2 * MM), 1010)
        enc = EncoderStreamReader.parse_line(line)[1:]
        want = expected_voltage(m, enc, 0.1, 3.2 * MM)   # ms เดียวกัน: ใช้ความเร็วล่าสุด (0.1 m/s)
        self.assertAlmostEqual(self.volt(m.process_telemetry(line)), want, delta=0.01)

    def test_clock_reset_restarts_velocity(self):
        m = make_model()
        m.process_telemetry(make_line(m, slider_counts_for_depth(m, 2 * MM), 5000))
        line = make_line(m, slider_counts_for_depth(m, 3 * MM), 20)   # บอร์ดรีเซ็ตนาฬิกา: v = 0
        enc = EncoderStreamReader.parse_line(line)[1:]
        want = expected_voltage(m, enc, 0.0, 3 * MM)
        self.assertAlmostEqual(self.volt(m.process_telemetry(line)), want, delta=0.01)

    def test_touch_zero_releases_to_zero_volts(self):
        m = make_model()
        line = make_line(m, slider_counts_for_depth(m, 5 * MM), 1000)
        ts, e1, e2, e3 = EncoderStreamReader.parse_line(line)
        self.assertGreater(self.volt(m.process_encoder(ts, e1, e2, e3)), 0.0)      # ค่าเริ่มต้น = ต้านแรง
        self.assertEqual(m.process_encoder(ts + 10, e1, e2, e3, touch=0), "0.0")   # ปล่อยแรง
        m.touch = 0
        self.assertEqual(m.process_encoder(ts + 20, e1, e2, e3), "0.0")

    def test_voltage_is_clamped_and_rounded(self):
        import tissue_model
        vf = TissueResistanceModel.voltage_from_tau
        self.assertEqual(vf(0.0), 0.0)
        self.assertEqual(vf(-0.5 * tissue_model.TAU_FULL_SCALE), 1.65)                       # ใช้ขนาดของแรงบิด (ไม่สนทิศ)
        self.assertEqual(vf(10 * tissue_model.TAU_FULL_SCALE), tissue_model.V_MAX)          # ตัดที่ 3.3 V
        self.assertEqual(vf(1e-9), 0.0)                                                       # ปัดที่ 1 mV: ไม่ออกเลขยกกำลังแบบ 1e-09
        self.assertEqual(len(str(vf(0.123456789 * tissue_model.TAU_FULL_SCALE)).split(".")[1]) <= 3, True)


if __name__ == "__main__":
    unittest.main()