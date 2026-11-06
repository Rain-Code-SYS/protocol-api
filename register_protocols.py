import requests

BASE_URL = "http://127.0.0.1:8000"

# กำหนดโครงสร้าง Schema สำหรับ trig_protocol_2 และ 3
protocols = [
    {
        "protocol_id": "trig_protocol_2",
        "name": "Haptic Device Telemetry Input",
        "description": "Telemetry data from haptic hardware",
        "format": "delimited",
        "delimiter": ";",
        "fields": [
            {"name": "pitch", "type": "float"},
            {"name": "yaw", "type": "float"},
            {"name": "theta2", "type": "float"},
            {"name": "touch", "type": "int"}
        ]
    },
    {
        "protocol_id": "trig_protocol_3",
        "name": "Haptic Control Command Output",
        "format": "delimited",
        "delimiter": ";",
        "fields": [
            {"name": "Ki", "type": "float"},
            {"name": "Kv", "type": "float"},
            {"name": "bp", "type": "int"},import requests

BASE_URL = "http://127.0.0.1:8000"

protocols = [
    {
        "protocol_id": "trig_protocol_2",
        "name": "Haptic Device Telemetry Input",
        "version": "1.0.0",
        "format_type": "delimited",
        "delimiter": ";",
        "fields": [
            {"name": "pitch", "data_type": "float"},
            {"name": "yaw", "data_type": "float"},
            {"name": "theta2", "data_type": "float"},
            {"name": "touch", "data_type": "int"}
        ]
    },
    {
        "protocol_id": "trig_protocol_3",
        "name": "Haptic Control Command Output",
        "version": "1.0.0",
        "format_type": "delimited",
        "delimiter": ";",
        "fields": [
            {"name": "Ki", "data_type": "float"},
            {"name": "Kv", "data_type": "float"},
            {"name": "bp", "data_type": "int"},
            {"name": "by", "data_type": "int"}
        ]
    }
]

for p in protocols:
    res = requests.post(f"{BASE_URL}/protocols", json=p)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
]

# ยิง POST Request ส่งข้อมูลเข้าสู่ FastAPI Server
for p in protocols:
    res = requests.post(f"{BASE_URL}/protocols", json=p)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")  # จะแสดงรายละเอียดฟิลด์ที่ Pydantic ตรวจพบปัญหา