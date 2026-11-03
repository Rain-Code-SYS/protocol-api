import time
import serial
import serial.tools.list_ports
from tissue_model import TissueResistanceModel

def find_arduino_port():
    """ ค้นหาพอร์ต COM ของ Arduino โดยอัตโนมัติ """
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if "Arduino" in port.description or "CH340" in port.description or "USB Serial" in port.description:
            return port.device
    return None

def main():
    # 1. กำหนดพอร์ต COM (ปรับเปลี่ยนตามพอร์ตจริง เช่น 'COM3' หรือให้ระบบค้นหาอัตโนมัติ)
    port_name = find_arduino_port() or "COM3"
    baud_rate = 115200

    print(f"🔌 กำลังเชื่อมต่อกับ Arduino ที่พอร์ต {port_name} ({baud_rate} baud)...")

    try:
        ser = serial.Serial(port_name, baud_rate, timeout=0.1)
        time.sleep(2)  # รอ Arduino Reset ระบบ
        print("✅ เชื่อมต่อ Serial Port สำเร็จ!")
    except Exception as e:
        print(f"❌ ไม่สามารถเปิดพอร์ต {port_name} ได้: {e}")
        print("โปรดตรวจสอบการเชื่อมต่อบอร์ด หรือเปลี่ยนชื่อ COM Port ในไฟล์ serial_bridge.py")
        return

    # 2. เริ่มต้นโมเดล Tissue Resistance
    model = TissueResistanceModel()

    print("🚀 เริ่มต้นระบบ Real-Time Serial Bridge (กด Ctrl+C เพื่อเลิกรัน)")
    
    try:
        while True:
            # อ่านข้อมูล Telemetry (Trig Protocol 2) จาก Arduino
            if ser.in_waiting > 0:
                raw_line = ser.readline().decode('utf-8', errors='ignore').strip()
                
                if raw_line and raw_line.count(';') == 3:
                    # ประมวลผลผ่าน Tissue Model เพื่อสร้างคำสั่ง Trig Protocol 3
                    command_string = model.process_telemetry(raw_line)
                    
                    # ส่งคำสั่งกลับไปยัง Arduino
                    ser.write((command_string + '\n').encode('utf-8'))
                    
                    print(f"[IN] {raw_line}  -->  [OUT] {command_string}")

            time.sleep(0.005)  # Delay 5ms ป้องกัน CPU Overload

    except KeyboardInterrupt:
        print("\nหยุดการทำงานของ Serial Bridge")
    finally:
        ser.close()
        print("ปิดการเชื่อมต่อ Serial Port เรียบร้อย")

if __name__ == "__main__":
    main()