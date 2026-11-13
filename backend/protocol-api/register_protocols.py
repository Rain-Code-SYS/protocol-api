"""ลงทะเบียน Trig Protocol ทั้งหมดจาก protocols.json เข้า API (ใช้เมื่อ Schema ในเซิร์ฟเวอร์ว่าง/ต้องการอัปเดต)

ใช้กับเซิร์ฟเวอร์ในเครื่อง:   python register_protocols.py
ใช้กับเว็บจริง:                BASE_URL=https://ชื่อ.onrender.com ADMIN_KEY=คีย์ที่ตั้งไว้ python register_protocols.py
(protocols.json อยู่ใน Git อยู่แล้ว เซิร์ฟเวอร์โหลดเองตอนสตาร์ต ปกติไม่จำเป็นต้องรันสคริปต์นี้)
"""
import json
import os

import requests

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "protocols.json"), encoding="utf-8") as f:
    protocols = json.load(f)

headers = {"X-Admin-Key": ADMIN_KEY} if ADMIN_KEY else {}
for protocol_id, schema in protocols.items():
    res = requests.post(f"{BASE_URL}/protocols", json=schema, headers=headers, timeout=30)
    print(f"{protocol_id}: {res.status_code} {res.text}")