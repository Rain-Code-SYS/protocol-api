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

    def parse_message(self, protocol_id: str, raw_message: Any) -> Dict[str, Any]:
        """แกะข้อความดิบเป็น Dictionary ตาม Schema

        - format_type == "bitfield": raw_message เป็น int (เช่น Trig Protocol 1) แกะด้วย decode_bitfield
        - อื่นๆ (delimited): raw_message เป็น string คั่นด้วย delimiter (เช่น '10.5;2.0;1.2;1')
        """
        schema = self.get_schema(protocol_id)
        if str(schema.get("format_type", "")).lower() == "bitfield":
            return self.decode_bitfield(protocol_id, int(raw_message))

        raw_string = raw_message
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

    def decode_bitfield(self, protocol_id: str, value: int) -> Dict[str, Any]:
        """แกะจำนวนเต็มแบบอัดบิต (เช่น Trig Protocol 1 เลข 7 บิต 0bAADDCMM) เป็น Dictionary ตาม Schema

        แต่ละฟิลด์ใน Schema ต้องระบุ bit_offset และ bit_width. ถ้ามี max_value จะใช้ตรวจขอบเขต
        (ไว้กันค่าที่อยู่นอกช่วง enum เช่น 0b11 ของฟิลด์ที่มีค่าที่ถูกต้องสูงสุดแค่ 2)
        """
        schema = self.get_schema(protocol_id)
        fields = schema.get("fields", [])
        total_width = schema.get("bit_width")

        if total_width is not None and not (0 <= value < (1 << total_width)):
            raise ValueError(
                f"ค่าต้องอยู่ในช่วง 0 ถึง {(1 << total_width) - 1} สำหรับ {total_width} บิต (ได้รับ {value})"
            )

        parsed_data: Dict[str, Any] = {}
        for field in fields:
            name = field["name"]
            offset = field.get("bit_offset")
            width = field.get("bit_width")
            if offset is None or width is None:
                raise ValueError(f"ฟิลด์ '{name}' ขาด bit_offset/bit_width ใน Schema แบบ bitfield")

            raw = (value >> offset) & ((1 << width) - 1)
            max_value = field.get("max_value")
            if max_value is not None and raw > max_value:
                raise ValueError(
                    f"ฟิลด์ '{name}' มีค่า {raw} ซึ่งเกินค่าสูงสุดที่ถูกต้อง ({max_value})"
                )
            parsed_data[name] = raw

        return parsed_data

    def encode_bitfield(self, protocol_id: str, data: Dict[str, Any]) -> int:
        """แปลง Dictionary กลับเป็นจำนวนเต็มแบบอัดบิต (ส่วนกลับของ decode_bitfield)"""
        schema = self.get_schema(protocol_id)
        fields = schema.get("fields", [])

        value = 0
        for field in fields:
            name = field["name"]
            if name not in data:
                raise KeyError(f"ข้อมูลขาดฟิลด์ '{name}' ตามที่ระบุใน Schema")
            offset = field.get("bit_offset")
            width = field.get("bit_width")
            if offset is None or width is None:
                raise ValueError(f"ฟิลด์ '{name}' ขาด bit_offset/bit_width ใน Schema แบบ bitfield")

            raw = int(data[name])
            max_value = field.get("max_value")
            upper = max_value if max_value is not None else (1 << width) - 1
            if not (0 <= raw <= upper):
                raise ValueError(f"ฟิลด์ '{name}' มีค่า {raw} ซึ่งอยู่นอกช่วง 0 ถึง {upper}")
            value |= (raw & ((1 << width) - 1)) << offset

        return value