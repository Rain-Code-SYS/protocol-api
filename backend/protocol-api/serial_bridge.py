"""Serial bridge: รับสตรีมเอนโค้ดเดอร์จาก STM32 แล้วแกะด้วย SDK ตาม Trig Protocol 2

แต่ละบรรทัดจากบอร์ด:  timestamp;enc1;enc2;enc3   (จำนวนเต็มทั้ง 4 ค่า, timestamp หน่วย ms)
ตัวอย่าง:             15230;1024;-512;3071
"""
import time
from typing import Optional

import requests

from protocol_sdk.client import ProtocolClient

try:
    import serial  # pyserial
except ImportError:  # ยังไม่ได้ติดตั้ง pyserial: ยังใช้ parse_telemetry_line() ได้ แต่ run_bridge() จะแจ้งให้ติดตั้ง
    serial = None

SERIAL_PORT = 'COM16'   # ปรับเปลี่ยนตามพอร์ตที่ต่อกับ STM32
BAUD_RATE = 230400
API_URL = "http://127.0.0.1:8000"  # FastAPI backend (ใช้ผ่าน SDK)
PRINT_EVERY = 10        # สตรีมเร็ว: แสดงผลทุกๆ N ตัวอย่าง กันหน้าจอกวาดช้าจนอ่านไม่ทัน
LEGACY_PREFIX = "$TRIG2"  # ถ้าเฟิร์มแวร์ยังใส่คำนำหน้านี้มา จะตัดทิ้งก่อนแกะ (ไม่ใส่ก็ได้)

client = ProtocolClient(base_url=API_URL)


def parse_telemetry_line(line: str) -> Optional[dict]:
    """แกะ 1 บรรทัดเป็น {"timestamp", "enc1", "enc2", "enc3"} ตาม Schema trig_protocol_2

    คืน None ถ้าบรรทัดว่าง จำนวนฟิลด์ไม่ครบ หรือไม่ใช่จำนวนเต็ม
    (บรรทัดแรกหลังเปิดพอร์ตมักขาดครึ่งๆ กลางๆ จึงต้องข้ามได้โดยไม่ให้บริดจ์ล้ม)
    """
    line = line.strip()
    if line.startswith(LEGACY_PREFIX):
        line = line[len(LEGACY_PREFIX):].lstrip(", ")
    if not line:
        return None
    try:
        return client.parse_message("trig_protocol_2", line)
    except ValueError:
        return None


def run_bridge(max_samples: Optional[int] = None):
    """อ่านสตรีมต่อเนื่องจนกด Ctrl+C (หรือครบ max_samples ถ้าระบุ — ใช้ในเทสต์)"""
    if serial is None:
        print("ไม่พบ pyserial — ติดตั้งด้วย: python -m pip install pyserial")
        return

    # ดึง Schema ล่วงหน้า: ถ้า API ยังไม่รันหรือไม่มี trig_protocol_2 จะบอกชัดเจน ไม่ใช่ข้ามทุกบรรทัดเงียบๆ
    try:
        client.get_schema("trig_protocol_2")
    except (ValueError, requests.RequestException) as e:
        print(f"ดึง Schema trig_protocol_2 จาก {API_URL} ไม่ได้ (เปิด FastAPI ก่อนหรือยัง?): {e}")
        return

    ser = None
    received = 0
    skipped = 0
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"Connected to STM32 on {SERIAL_PORT} at {BAUD_RATE} baud")
        time.sleep(2)  # หน่วงเวลาให้พอร์ตพร้อม
        ser.reset_input_buffer()

        while True:
            # readline() รอตาม timeout อยู่แล้ว ไม่ต้อง sleep (sleep จะทำให้อ่านได้ช้ากว่าสตรีม)
            raw = ser.readline().decode('utf-8', errors='ignore').strip()
            if not raw:
                continue

            telemetry = parse_telemetry_line(raw)
            if telemetry is None:
                skipped += 1
                if skipped <= 5 or skipped % 100 == 0:
                    print(f"[Bridge] ข้ามบรรทัดที่รูปแบบไม่ถูกต้อง (รวม {skipped}): {raw!r}")
                continue

            received += 1
            if received % PRINT_EVERY == 1:
                print(f"Encoder Telemetry Received: {telemetry}")
            if max_samples is not None and received >= max_samples:
                break

            # TODO: ส่งต่อให้ TissueResistanceModel ที่นี่ เช่น model.process_encoder(**telemetry)

    except serial.SerialException as e:
        print(f"Serial Error: {e}")
    except KeyboardInterrupt:
        print("Bridge stopped by user.")
    finally:
        if ser is not None and ser.is_open:
            ser.close()


if __name__ == "__main__":
    run_bridge()