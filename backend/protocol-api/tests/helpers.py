import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# โฟลเดอร์ที่มี setup.py และแพ็กเกจ protocol_sdk จริงอยู่ข้างใน
SDK_DIR = os.path.join(ROOT, "protocol_sdk")

for path in (ROOT, SDK_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from protocol_sdk.client import ProtocolClient  # noqa: E402


def load_schemas():
    with open(os.path.join(ROOT, "protocols.json"), encoding="utf-8") as f:
        return json.load(f)


def offline_client():
    """ProtocolClient ที่ป้อน Schema เข้า cache เอง ไม่ต้องรัน API (ไม่ยิง HTTP)"""
    client = ProtocolClient()
    client._cache.update(load_schemas())
    return client