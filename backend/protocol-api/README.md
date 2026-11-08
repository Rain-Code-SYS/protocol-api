Markdown
# Hardware & Software Protocol Schema Registry API & SDK

ระบบศูนย์กลางจัดการโครงสร้างโปรโตคอลการสื่อสาร (Schema Registry) ระหว่าง **3D Simulation Software**, **Tissue Resistance Model (Python)** และ **Haptic Device Hardware**

---

## 📌 โครงสร้างโปรเจกต์ (Project Structure)

```text
protocol-api/
├── main.py                # FastAPI Server หลักสำหรับบริหารจัดการ Schema
├── register_protocols.py  # สคริปต์สำหรับลงทะเบียน Trig Protocols (1, 2, 3)
├── tissue_model.py        # โมเดลคำนวณแรงต้านเนื้อเยื่อ (Tissue Resistance Model)
├── protocols.json         # ไฟล์เก็บข้อมูล Schema แบบถาวร (Persistence Data)
├── .gitignore             # กำหนดไฟล์ที่ไม่ต้องการ Push ขึ้น Git
└── protocol_sdk/          # Python Client Library (SDK) สำหรับโมดูลอื่นนำไปเรียกใช้
    ├── protocol_sdk/
    │   ├── __init__.py
    │   └── client.py
    └── setup.py
```
⚙️ การติดตั้งและการรันเซิร์ฟเวอร์ (API Setup)
1. ติดตั้ง Dependencies และเปิดใช้งาน FastAPI Server
```
DOS
# ติดตั้งแพ็กเกจที่จำเป็น
pip install fastapi uvicorn requests setuptools

# เริ่มรันเซิร์ฟเวอร์
uvicorn main:app --reload
```
```
API URL: http://127.0.0.1:8000

Interactive Docs (Swagger UI): http://127.0.0.1:8000/docs
```

2. ลงทะเบียนโปรโตคอลเริ่มต้น (Trig Protocols)
เปิด Terminal หน้าต่างใหม่ แล้วสั่งรันสคริปต์เพื่อบันทึกสคีมาเข้าสู่ระบบ:
```
DOS
python register_protocols.py
```
📦 การติดตั้งและเรียกใช้งาน Client SDK (protocol_sdk)
1. การติดตั้ง SDK
ติดตั้งแบบ Editable (สำหรับพัฒนาในเครื่อง local):
```
DOS
pip install -e ./protocol_sdk
```
ติดตั้งจาก GitHub Repository (สำหรับทีมงานท่านอื่น):
```
DOS
pip install git+[https://github.com/Rain-Code-SYS/protocol-api.git#subdirectory=protocol_sdk](https://github.com/Rain-Code-SYS/protocol-api.git#subdirectory=protocol_sdk)
```
2. ตัวอย่างการนำไปใช้ใน Tissue Resistance Model (tissue_model.py)
```Python
from protocol_sdk.client import ProtocolClient

# 1. เชื่อมต่อกับ FastAPI Server
client = ProtocolClient(base_url="[http://127.0.0.1:8000](http://127.0.0.1:8000)")

# 2. จำลองข้อมูล Telemetry จาก Haptic Device (Trig Protocol 2: pitch;yaw;theta2;touch)
raw_serial_data = "0.0;15.0;10.0;1"

# 3. ถอดรหัสข้อความ String เป็น Dictionary ตาม Schema อัตโนมัติ
telemetry = client.parse_message("trig_protocol_2", raw_serial_data)
print("Parsed Telemetry:", telemetry)
# Output: {'pitch': 0.0, 'yaw': 15.0, 'theta2': 10.0, 'touch': 1}

# 4. นำค่าพิกัด/มุมไปคำนวณใน Tissue Resistance Model
theta2 = telemetry["theta2"]
touch = telemetry["touch"]

# ตัวอย่างการคำนวณค่าแรงต้านและ Control Gains
force = 15.0 * theta2 + 0.5 if touch == 1 else 0.0

# 5. แปลงข้อมูลคำสั่งเป็น String (Trig Protocol 3: Ki;Kv;bp;by) เพื่อส่งกลับฮาร์ดแวร์
command_data = {
    "Ki": round(force * 0.1, 4),
    "Kv": 12.0,
    "bp": 1 if force > 10.0 else 0,
    "by": 0
}
command_string = client.build_message("trig_protocol_3", command_data)
print("Command String:", command_string)
# Output: "1.505;12.0;0;0"
```

📋 สรุปรายการโปรโตคอลในระบบ (Protocol Reference)

Protocol ID : [trig_protocol_1,trig_protocol_2,trig_protocol_3]
ชื่อโปรโตคอล : [Simulation Practice Settings,Haptic Device Telemetry,Haptic Control Command]
รูปแบบ (Format) : [JSON,Delimited,Delimited]
Delimiter : [-,;,;]
รายละเอียดฟิลด์ : [[age, difficulty, case_type, practice_mode],[p, y, z, zdot, touch, bp, by],[Ki, Kv, bp, by]]
