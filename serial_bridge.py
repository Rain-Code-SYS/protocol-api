import serial
import time
import requests

SERIAL_PORT = 'COM3'  # ปรับเปลี่ยนตามพอร์ตที่ต่อกับ Arduino
BAUD_RATE = 115200
API_URL = "http://127.0.0.1:8000/api/v1/protocols/trig_protocol_1/build"

def run_bridge():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"Connected to Arduino on {SERIAL_PORT}")
        time.sleep(2)

        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8').strip()
                print(f"[Arduino Raw]: {line}")
                
                # หากได้รับโปรโตคอลแจ้งเตือนสถานะจาก Arduino
                if line.startswith("$TRIG2"):
                    print(f"Haptic Feedback Status Received: {line}")

            time.sleep(0.01)

    except serial.SerialException as e:
        print(f"Serial Error: {e}")
    except KeyboardInterrupt:
        print("Bridge stopped by user.")

if __name__ == "__main__":
    run_bridge()