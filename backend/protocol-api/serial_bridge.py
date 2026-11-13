"""Serial bridge: รับสตรีมเอนโค้ดเดอร์จาก STM32 แล้วแกะด้วย SDK ตาม Trig Protocol 2

แต่ละบรรทัดจากบอร์ด:  timestamp;enc1;enc2;enc3   (จำนวนเต็มทั้ง 4 ค่า, timestamp หน่วย ms)
ตัวอย่าง:             15230;1024;-512;3071
"""
import os
import time
from typing import Optional

import requests

from protocol_sdk.client import ProtocolClient
from tissue_model import TissueResistanceModel

try:
    import serial  # pyserial
except ImportError:  # ยังไม่ได้ติดตั้ง pyserial: ยังใช้ parse_telemetry_line() ได้ แต่ run_bridge() จะแจ้งให้ติดตั้ง
    serial = None

SERIAL_PORT = 'COM3'   # ปรับเปลี่ยนตามพอร์ตที่ต่อกับ STM32
BAUD_RATE = 230400
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")  # FastAPI backend (ตั้ง API_URL=https://ชื่อ.onrender.com เพื่อชี้ไปเว็บจริง)
PRINT_EVERY = 10        # สตรีมเร็ว: แสดงผลทุกๆ N ตัวอย่าง กันหน้าจอกวาดช้าจนอ่านไม่ทัน
SEND_COMMANDS = True    # ส่งคำสั่ง Trig Protocol 3 (Ki;Kv;bp;by + \n) กลับบอร์ดทางพอร์ตเดียวกัน ปิดได้ถ้าเฟิร์มแวร์ยังไม่รองรับ
SYNC_ENCODER_CONFIG = True  # ใช้ config เอนโค้ดเดอร์จากหน้า Settings (ผ่าน API) และซิงก์ต่อเนื่องระหว่างรัน
CONFIG_SYNC_INTERVAL = 1.0  # วินาที
LEGACY_PREFIX = "$TRIG2"  # ถ้าเฟิร์มแวร์ยังใส่คำนำหน้านี้มา จะตัดทิ้งก่อนแกะ (ไม่ใส่ก็ได้)

client = ProtocolClient(base_url=API_URL)


def make_model() -> TissueResistanceModel:
    """สร้างโมเดลที่ใช้ client ตัวเดียวกับบริดจ์ (แชร์ API_URL และ Schema cache)"""
    model = TissueResistanceModel(api_url=API_URL)
    model.client = client
    return model


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

    model = make_model()
    if SYNC_ENCODER_CONFIG:
        try:
            model.apply_encoder_config_from_api()
            print("[Bridge] ใช้ config เอนโค้ดเดอร์จากหน้า Settings (ซิงก์ต่อเนื่อง)")
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[Bridge] ดึง config เอนโค้ดเดอร์ไม่ได้ ใช้ค่าตั้งต้นของโมเดลไปก่อน: {e}")
        model.start_encoder_config_sync(CONFIG_SYNC_INTERVAL)

    ser = None
    received = 0
    skipped = 0
    model_errors = 0
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
            command = None
            try:
                command = model.process_encoder(
                    telemetry["timestamp"], telemetry["enc1"], telemetry["enc2"], telemetry["enc3"])
            except (ValueError, KeyError, ArithmeticError) as e:
                model_errors += 1
                if model_errors <= 5 or model_errors % 100 == 0:
                    print(f"[Bridge] โมเดลประมวลผลตัวอย่างไม่ได้ (รวม {model_errors}): {e!r}")
            if command is not None and SEND_COMMANDS:
                ser.write((command + "\n").encode("ascii"))  # Trig Protocol 3: Ki;Kv;bp;by

            if received % PRINT_EVERY == 1:
                print(f"Encoder Telemetry Received: {telemetry} -> {command}")
            if max_samples is not None and received >= max_samples:
                break

    except serial.SerialException as e:
        print(f"Serial Error: {e}")
    except KeyboardInterrupt:
        print("Bridge stopped by user.")
    finally:
        model.stop_encoder_config_sync()
        if ser is not None and ser.is_open:
            ser.close()


if __name__ == "__main__":
    run_bridge()