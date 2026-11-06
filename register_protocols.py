import requests

BASE_URL = "http://127.0.0.1:8000"

protocols = [
    {
        "protocol_id": "trig_protocol_2",
        "name": "Haptic Device Telemetry Input",
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
            {"name": "bp", "type": "int"},
            {"name": "by", "type": "int"}
        ]
    }
]

for p in protocols:
    res = requests.post(f"{BASE_URL}/protocols", json=p)
    print(f"Register {p['protocol_id']}:", res.json())