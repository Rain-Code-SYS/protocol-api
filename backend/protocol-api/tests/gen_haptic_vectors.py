"""สร้าง tests/haptic_vectors.json จาก tissue_model.py (Python) เป็นค่าอ้างอิงให้ static/haptic_model.js (JavaScript)

รัน (จากโฟลเดอร์ protocol-api):  python -m tests.gen_haptic_vectors
แล้วตรวจฝั่ง JS:                 node --test
แก้สูตรใน tissue_model.py เมื่อไร ให้รันสองคำสั่งนี้ซ้ำ (test_haptic_vectors.py จะเตือนถ้าไฟล์ JSON ไม่ตรงกับโค้ด Python)
"""
import json
import math
import os
import random

from tests.helpers import offline_client
from tissue_model import TissueResistanceModel

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "haptic_vectors.json")

CUSTOM_CONFIG = {
    "Joint_YAW": {"encoder_id": "Enc_3", "ppr": 1000, "offset": 40},
    "Joint_PITCH": {"encoder_id": "Enc_1", "ppr": 2000, "offset": -30},
    "Slider_MOTOR": {"encoder_id": "Enc_2", "ppr": 8192, "offset": 667},
}
DEFAULT_CONFIG = {
    "Joint_YAW": {"encoder_id": "Enc_1", "ppr": 2048, "offset": 0},
    "Joint_PITCH": {"encoder_id": "Enc_2", "ppr": 800, "offset": 0},
    "Slider_MOTOR": {"encoder_id": "Enc_3", "ppr": 4096, "offset": 0},
}
FLOATS = [0.0, 0.5, 12.0, 1.505, 0.1 + 0.2, 1e-5, 2.5e-5, 0.0001, 0.00012345, 1.5e-7, 5e-324, 100.0,
          123456789.125, 1e15, 999999999999999.9, 1e16, 1.2345678901234567e17, 1e22, 1.7976931348623157e308]


def make_model():
    m = TissueResistanceModel()
    m.client = offline_client()
    m._notify_lung = lambda hit: None        # ไม่ยิง HTTP ไป API ตอนสร้างค่าอ้างอิง
    return m


def counts(config, joint, deg):
    c = config[joint]
    return round(deg / 360.0 * c["ppr"]) + c["offset"]


def sample_values(config, theta2_deg, yaw_deg, pitch_deg):
    vals = {config[j]["encoder_id"]: counts(config, j, d) for j, d in
            (("Slider_MOTOR", theta2_deg), ("Joint_YAW", yaw_deg), ("Joint_PITCH", pitch_deg))}
    return vals["Enc_1"], vals["Enc_2"], vals["Enc_3"]


def build_case(name, config, apply_config, seed):
    rng = random.Random(seed)
    model = make_model()
    steps = []
    if apply_config:
        model.apply_encoder_config(config)
        steps.append({"op": "config", "config": config})
    ts = 1000
    theta = -5.0
    direction = 1
    for i in range(400):
        if i in (0, 130, 260):                      # เปลี่ยนกลุ่มอายุ + เริ่มรอบใหม่
            age = (i // 130) % 3
            model.apply_age(age)
            model.reset_state()
            steps.append({"op": "age", "code": age})
            steps.append({"op": "reset"})
        if i == 200:
            model.reset_state()
            steps.append({"op": "reset"})
        theta += direction * rng.uniform(0.0, 3.0)
        if theta > 85:
            direction = -1
        if theta < -12:
            direction = 1
        step_ms = rng.choice([0, 1, 1, 2, 5, 10, 10, 20])
        ts += step_ms
        if i == 330:
            ts = 20                                  # บอร์ดรีเซ็ตนาฬิกา
        yaw, pitch = rng.uniform(-200, 200), rng.uniform(-60, 60)
        e1, e2, e3 = sample_values(config, theta, yaw, pitch)
        touch = rng.choice([None, None, None, 1, 0])
        cmd = model.process_encoder(ts, e1, e2, e3, touch=touch)
        pose = model.pose(e1, e2, e3)
        steps.append({"op": "sample", "ts": ts, "e": [e1, e2, e3], "touch": touch, "cmd": cmd, "pose": pose,
                      "lung": model.lung_hit, "x_max": model.x_max})
    return {"name": name, "steps": steps}


def main():
    data = {
        "floats": [[f, str(f)] for f in FLOATS] + [[f, str(f)] for f in
                 (random.Random(7).uniform(0, 1) * 10 ** random.Random(i).randint(-8, 20) for i in range(60))],
        "cases": [build_case("default-config", DEFAULT_CONFIG, False, 1),
                  build_case("custom-config", CUSTOM_CONFIG, True, 2)],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"เขียน {OUT}: {sum(len(c['steps']) for c in data['cases'])} ขั้น")


if __name__ == "__main__":
    main()