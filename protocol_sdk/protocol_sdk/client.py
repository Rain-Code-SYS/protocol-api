import requests
from typing import Dict, Any, Optional

class ProtocolClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")
        self._cache: Dict[str, dict] = {}  # เก็บ Cache ใน Memory เพื่อลดการยิง Request ถี่ๆ

    def get_schema(self, protocol_id: str, force_refresh: bool = False) -> dict:
        """ดึง Schema จาก FastAPI Server"""
        if protocol_id in self._cache and not force_refresh:
            return self._cache[protocol_id]
        
        response = requests.get(f"{self.base_url}/protocols/{protocol_id}")
        if response.status_code == 200:
            schema = response.json()
            self._cache[protocol_id] = schema
            return schema
        else:
            raise ValueError(f"ไม่พบ Protocol ID '{protocol_id}' บนเซิร์ฟเวอร์ ({response.status_code})")

    def parse_message(self, protocol_id: str, raw_string: str) -> Dict[str, Any]:
        """แกะสายอักขระ (เช่น '10.5;2.0;1.2;0.5;1;0;0') เป็น Dictionary ตาม Schema"""
        schema = self.get_schema(protocol_id)
        delimiter = schema.get("delimiter") or ";"
        fields = schema.get("fields", [])
        
        values = raw_string.strip().split(delimiter)
        if len(values) != len(fields):
            raise ValueError(f"จำนวนฟิลด์ไม่ตรงกับ Schema: คาดหวัง {len(fields)} ได้รับ {len(values)}")
        
        parsed_data = {}
        for field, val_str in zip(fields, values):
            name = field["name"]
            data_type = field["data_type"].lower()
            
            # แปลง Data Type ตามที่ระบุใน Schema
            if data_type in ["float", "double"]:
                parsed_data[name] = float(val_str)
            elif data_type in ["int", "uint8", "int16", "int32"]:
                parsed_data[name] = int(val_str)
            else:
                parsed_data[name] = str(val_str)
                
        return parsed_data

    def build_message(self, protocol_id: str, data: Dict[str, Any]) -> str:
        """แปลง Dictionary กลับเป็น String คั่นด้วย Delimiter เพื่อส่งกลับไปยังฮาร์ดแวร์"""
        schema = self.get_schema(protocol_id)
        delimiter = schema.get("delimiter") or ";"
        fields = schema.get("fields", [])
        
        value_list = []
        for field in fields:
            name = field["name"]
            if name not in data:
                raise KeyError(f"ข้อมูลขาดฟิลด์ '{name}' ตามที่ระบุใน Schema")
            value_list.append(str(data[name]))
            
        return delimiter.join(value_list)