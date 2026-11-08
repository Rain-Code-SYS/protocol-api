"""อ่านสตรีมจากเอนโค้ดเดอร์ผ่าน Serial — รูปแบบตรงกับ Trig Protocol 2

แต่ละบรรทัด:  timestamp;enc1;enc2;enc3   (จำนวนเต็มทั้ง 4 ค่า, timestamp หน่วย ms, ปิดท้ายด้วย newline)
ตัวอย่าง:      15230;1024;-512;3071
"""
import time
from typing import Optional, Tuple

try:
    import serial  # pyserial
except ImportError:  # ยังไม่ได้ติดตั้ง pyserial: ใช้ parse_line() ได้ แต่ connect() จะแจ้งให้ติดตั้ง
    serial = None

Sample = Tuple[int, int, int, int]


class EncoderStreamReader:
    def __init__(self, port='COM16', baud_rate=230400, timeout=1):
        """
        Constructor สำหรับตั้งค่าพอร์ตการเชื่อมต่อ Serial
        """
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.ser = None

    def connect(self):
        """เปิดการเชื่อมต่อ Serial Port"""
        if serial is None:
            print("[EncoderReader] ไม่พบ pyserial — ติดตั้งด้วย: python -m pip install pyserial")
            return False
        try:
            self.ser = serial.Serial(self.port, self.baud_rate, timeout=self.timeout)
            time.sleep(2)  # หน่วงเวลาให้พอร์ตพร้อม
            self.ser.reset_input_buffer()
            print(f"[EncoderReader] Connected to {self.port} at {self.baud_rate} baud.")
            return True
        except serial.SerialException as e:
            print(f"[EncoderReader] Connection Error: {e}")
            return False

    @staticmethod
    def parse_line(line: str) -> Optional[Sample]:
        """แกะ 1 บรรทัด 'timestamp;enc1;enc2;enc3' → (timestamp, enc1, enc2, enc3)

        คืน None ถ้าบรรทัดว่าง จำนวนฟิลด์ไม่ครบ 4 หรือแปลงเป็นจำนวนเต็มไม่ได้
        """
        line = line.strip()
        if not line:
            return None
        parts = line.split(';')
        if len(parts) != 4:
            return None
        try:
            timestamp, enc1, enc2, enc3 = (int(p) for p in parts)
        except ValueError:
            # กรณีแปลงตัวเลขขัดข้อง
            return None
        return timestamp, enc1, enc2, enc3

    def read_data(self) -> Optional[Sample]:
        """
        อ่านข้อมูล 1 รอบ (Non-blocking หรือรอตาม timeout)
        คืนค่าเป็น tuple: (timestamp, enc1, enc2, enc3) หรือ None ถ้าอ่านไม่สำเร็จ
        """
        if self.ser and self.ser.is_open:
            line = self.ser.readline().decode('utf-8', errors='ignore')
            return self.parse_line(line)
        return None

    def close(self):
        """ปิดการเชื่อมต่อ Serial Port"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[EncoderReader] Serial port closed.")


# สำหรับรันเทสเดี่ยวๆ (Test Script)
if __name__ == "__main__":
    reader = EncoderStreamReader(port='COM16', baud_rate=230400)

    if reader.connect():
        try:
            print("Listening to encoder stream... Press Ctrl+C to stop.\n")
            while True:
                data = reader.read_data()
                if data:
                    ts, e1, e2, e3 = data
                    print(f"Time: {ts} ms | Enc1: {e1} | Enc2: {e2} | Enc3: {e3}")
        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            reader.close()