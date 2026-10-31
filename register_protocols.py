import requests

BASE_URL = "http://127.0.0.1:8000"

protocols = [
    {
        "protocol_id": "trig_protocol_1",
        "name": "Simulation Practice Settings",
        "version": "1.0",
        "format_type": "JSON",
        "delimiter": None,
        "fields": [
            {"name": "age", "data_type": "int", "description": "Pediatric=0, Adult=1, Geriatric=2"},
            {"name": "difficulty", "data_type": "int", "description": "Easy=0, Medium=1, Hard=2"},
            {"name": "case_type", "data_type": "int", "description": "Basic=0, Emer/Trauma=1"},
            {"name": "practice_mode", "data_type": "int", "description": "Tutorial=0, Guide=1, Blind=2"}
        ]
    },
    {
        "protocol_id": "trig_protocol_2",
        "name": "Haptic Device Telemetry",
        "version": "1.0",
        "format_type": "Delimited",
        "delimiter": ";",
        "fields": [
            {"name": "p", "data_type": "float", "description": "pitch angle"},
            {"name": "y", "data_type": "float", "description": "yaw angle"},
            {"name": "z", "data_type": "float", "description": "insertion depth"},
            {"name": "zdot", "data_type": "float", "description": "insertion speed"},
            {"name": "touch", "data_type": "int", "description": "needle holding state"},
            {"name": "bp", "data_type": "int", "description": "brake state (pitch)"},
            {"name": "by", "data_type": "int", "description": "brake state (yaw)"}
        ]
    },
    {
        "protocol_id": "trig_protocol_3",
        "name": "Haptic Control Command",
        "version": "1.0",
        "format_type": "Delimited",
        "delimiter": ";",
        "fields": [
            {"name": "Ki", "data_type": "float", "description": "Current Constant Value"},
            {"name": "Kv", "data_type": "float", "description": "Voltage Constant Value"},
            {"name": "bp", "data_type": "int", "description": "brake state (pitch)"},
            {"name": "by", "data_type": "int", "description": "brake state (yaw)"}
        ]
    }
]

for proto in protocols:
    res = requests.post(f"{BASE_URL}/protocols", json=proto)
    print(f"Registered {proto['protocol_id']}:", res.json())