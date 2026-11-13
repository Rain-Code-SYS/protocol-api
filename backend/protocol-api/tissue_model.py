import copy
import json
import math
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests

from protocol_sdk.client import ProtocolClient

# =============================================================================
# 👶🧑👴 โปรไฟล์ชั้นผิวหนังตามกลุ่มอายุ (ค่าของฟิลด์ `age` ใน Trig Protocol 1)
#   0 = Pediatric, 1 = Adult, 2 = Geriatric
#
# ⚠️ ค่า Pediatric / Geriatric เป็น "ค่าตั้งต้นสำหรับทดลอง" (placeholder) เพื่อให้เห็นความต่างของแต่ละเคส
#    ยังไม่ได้อ้างอิงงานวิจัยหรือการวัดจริง ควรปรับตามข้อมูลทางคลินิก/การ calibrate ฮาร์ดแวร์
#    ส่วน Adult เท่ากับค่าเดิมของโมเดล (k_skin=1200 N/m, x_p=3 mm)
#   - k_skin : ความแข็งผิวหนัง (N/m)
#   - x_p    : ระยะที่ผิวหนังถูกยืดจนเข็มทะลุ (m) → แรงสูงสุดก่อนทะลุ = k_skin * x_p
# =============================================================================
AGE_SKIN_PROFILES: Dict[int, Dict[str, Any]] = {
    0: {"label": "Pediatric", "k_skin": 800.0,  "x_p": 0.0020},
    1: {"label": "Adult",     "k_skin": 1200.0, "x_p": 0.0030},
    2: {"label": "Geriatric", "k_skin": 1000.0, "x_p": 0.0025},
}

@dataclass
class AxisCalibration:
    """การแปลงค่านับ (counts) ของเอนโค้ดเดอร์ 1 ช่อง → มุมของแกน (องศา)

    deg = sign * (counts - zero_counts) * 360 / counts_per_rev

    ⚠️ counts_per_rev = 4096 เป็นค่า placeholder ต้องตั้งให้ตรงกับเอนโค้ดเดอร์จริง
       (ถ้าเป็นแบบ quadrature ให้นับหลังคูณ 4 แล้ว)
    """
    channel: str                     # "enc1" | "enc2" | "enc3" ตามฟิลด์ใน Trig Protocol 2
    counts_per_rev: float = 4096.0   # จำนวน counts ต่อ 1 รอบของแกน
    zero_counts: int = 0             # ค่า counts ที่ตำแหน่งอ้างอิง (มุม 0°)
    sign: int = 1                    # +1 / -1 กลับทิศทางการหมุน

    def to_deg(self, counts: int) -> float:
        return self.sign * (counts - self.zero_counts) * 360.0 / self.counts_per_rev


# ข้อต่อใน encoder_config.json (ไฟล์ที่หน้า Settings / backend แก้) → แกนใน model.axes
ENCODER_CONFIG_AXES = {"Joint_YAW": "yaw", "Joint_PITCH": "pitch", "Slider_MOTOR": "theta2"}


class TissueResistanceModel:
    def __init__(self, api_url="http://127.0.0.1:8000"):
        self.client = ProtocolClient(base_url=api_url)
        
        # =========================================================================
        # ⚙️ 1. กำหนดพารามิเตอร์ของชั้นเนื้อเยื่อ (สามารถปรับแก้ค่าได้ง่ายตรงนี้)
        # =========================================================================
        # --- ขอบเขตความลึกของแต่ละชั้น (หน่วย: เมตร) ---
        self.x_p = 0.003       # ระยะแทงทะลุชั้นผิวหนัง Skin Puncture Depth (3 mm)
        self.delta1 = 0.001    # ช่วงระยะ Blend หลังผิวหนังขาด (1 mm)
        self.x_trans = 0.012   # จุดเปลี่ยนจากชั้นไขมันเข้าสู่ชั้นกล้ามเนื้อ (12 mm)
        self.x_pleura = 0.025  # ระยะจุดทะลุผ่านชั้นเยื่อหุ้มปอด Pleura (25 mm)
        self.delta2 = 0.001    # ช่วงระยะ Blend หลังเยื่อหุ้มปอดขาด (1 mm)

        # --- ค่ายืดหยุ่นและความแข็ง (Stiffness / Elastic Modulus) ---
        self.k_skin = 1200.0   # ความแข็งชั้นผิวหนัง (N/m)
        self.k_muscle = 800.0  # ความแข็งชั้นกล้ามเนื้อ (N/m)

        # --- แรงตัดขาดและแรงเสียดทาน (Cutting Force & Friction) ---
        self.f_cut_fat = 1.2   # แรงตัดผ่านชั้นไขมัน (N)
        self.f_cut_pleura = 2.5# แรงตัดผ่านชั้นเยื่อหุ้มปอด (N)
        self.b_fric = 5.0      # ค่าความหนืดแรงเสียดทาน Viscous Friction Coefficient (N·s/m)
        self.c_fric = 0.5      # ค่าแรงเสียดทานจลน์คงที่ Coulomb Friction (N)

        # --- ค่าสัมพรรธ์คลายตัวตอนถอยเข็ม (Hysteresis Factors) ---
        self.gamma_h = 0.35    # สัดส่วนแรงเหลือเมื่อถอยเข็มออกจากชั้นผิวหนัง (0.0 - 1.0)
        self.gamma_hm = 0.45   # สัดส่วนแรงเหลือเมื่อถอยเข็มออกจากชั้นกล้ามเนื้อ (0.0 - 1.0)

        # --- พารามิเตอร์ทางกลไก Slider-Crank ---
        self.R1 = 0.031        # ความยาวแขนมอเตอร์ (m)
        self.R2 = 0.028        # ความยาวก้านส่งกำลัง (m)
        self.M1 = 0.016768     # มวลรวมก้อนสไลด์ (kg)
        self.G = 9.81          # Gravity (m/s^2)

        # --- ระยะฟรีของเข็มและโซนปอด (หน่วย: เมตร) ---
        # แกนความลึก x = 0 คือ "ผิวหนังด้านบนสุดที่เข็มเริ่มแตะ"  (x < 0 = เข็มยังลอยอยู่ในอากาศ)
        #   [ฟรีก่อนเจาะ 10 mm] → [ผิวหนัง..ทะลุเยื่อหุ้มปอด 26 mm] → [ฟรีหลังทะลุ 8 mm] → [ปอด]
        self.needle_stroke = 0.050   # ระยะกดสูงสุดของเข็มจริง (50 mm)
        self.free_before = 0.010     # ระยะฟรีก่อนเข็มแตะผิว (10 mm) แรงต้าน = 0
        self.free_after = 0.008      # ระยะฟรีหลังทะลุเยื่อหุ้มปอด (8 mm) เกินจากนี้ = โดนปอด
        self.cavity_friction = True  # True = ในช่วงฟรีหลังทะลุยังมีแรงเสียดทานจากผนังอก (ตามโมเดลเดิม)
        self.theta_home_deg = 0.0    # มุม theta2 ที่ตำแหน่งเข็มถอยสุด (travel = 0)

        # --- ชั้นปอด (⚠️ ค่า placeholder ยังไม่ได้ calibrate) ---
        self.k_lung = 400.0          # ความแข็งเนื้อปอด (N/m)
        self.gamma_lung = 0.5        # สัดส่วนแรงเหลือเมื่อถอยเข็มออกจากปอด (0.0 - 1.0)

        # --- เอนโค้ดเดอร์ (Trig Protocol 2: timestamp;enc1;enc2;enc3) → มุมของแต่ละแกน ---
        # ค่าตั้งต้นตรงกับหน้า Settings / encoder_config.json: Enc_1 = Yaw (2048 PPR), Enc_2 = Pitch (800 PPR),
        # Enc_3 = Slider = theta2 (4096 PPR), ศูนย์ = 0
        # ถ้าแก้ค่าในหน้า Settings (PPR, Set Zero, สลับเอนโค้ดเดอร์) ให้เรียก apply_encoder_config_from_api() ซิงก์ให้ตรงกัน
        self.axes: Dict[str, AxisCalibration] = {
            "pitch": AxisCalibration("enc2", counts_per_rev=800.0),
            "yaw": AxisCalibration("enc1", counts_per_rev=2048.0),
            "theta2": AxisCalibration("enc3", counts_per_rev=4096.0),
        }
        # Touch ไม่ได้มาจากเอนโค้ดเดอร์อีกแล้ว: 1 = สัมผัส/ต้านแรง (ค่าเดิมตอนใช้งาน), 0 = ไม่สัมผัส/ปลดล็อก
        # ถ้ามีเซนเซอร์แยก ให้ส่งค่าผ่านพารามิเตอร์ touch ของ process_encoder() หรือเซ็ต model.touch
        self.touch = 1

        # ตัวแปรเก็บสถานะการเคลื่อนที่ (เวลาอ้างอิงจาก timestamp ของเอนโค้ดเดอร์ หน่วย ms)
        self.prev_x: Optional[float] = None  # ความลึกครั้งก่อน (None = ยังไม่มีตัวอย่างแรก)
        self.prev_ts_ms: Optional[int] = None
        self.prev_v = 0.0
        self.x_max = 0.0       # ความลึกสูงสุดที่เคยแทงเข้าไปได้
        self.lung_hit = False  # สถานะล่าสุดที่ส่งให้ API (Trig Protocol 4)

        self._validate_layout(self.x_p)

        # --- การตั้งค่าเคสจาก Trig Protocol 1 (ค่าเริ่มต้น = Adult ตรงกับค่าคงที่ด้านบน) ---
        self.age_code = 1
        self.settings: Dict[str, int] = {}

        # ซิงก์ config เอนโค้ดเดอร์อัตโนมัติ (ดู start_encoder_config_sync)
        self._applied_encoder_config: Optional[Dict[str, Any]] = None
        self._pending_encoder_config: Optional[Dict[str, Any]] = None
        self._sync_stop = threading.Event()
        self._sync_thread: Optional[threading.Thread] = None

    # =========================================================================
    # 🔗 1.1 เชื่อม Trig Protocol 1 → พารามิเตอร์ของโมเดล
    # =========================================================================
    @property
    def x_lung(self):
        """ความลึกที่เริ่มสัมผัสปอด = ทะลุเยื่อหุ้มปอดครบ (x_pleura + delta2 = 26 mm) + ระยะฟรี 8 mm = 34 mm"""
        return self.x_pleura + self.delta2 + self.free_after

    def _validate_layout(self, x_p: float):
        """ตรวจว่าชั้นเนื้อเยื่อเรียงถูกและเข็มกดไปถึงปอดได้จริง"""
        if x_p + self.delta1 >= self.x_trans:
            raise ValueError("x_p + delta1 ต้องน้อยกว่า x_trans")
        if self.x_trans >= self.x_pleura:
            raise ValueError("x_trans ต้องน้อยกว่า x_pleura")
        if self.free_before + self.x_lung >= self.needle_stroke:
            raise ValueError("ระยะฟรี + ชั้นเนื้อเยื่อ เกินระยะกดสูงสุดของเข็ม")

    def reset_state(self):
        """เริ่มรอบการแทงใหม่: ล้างตำแหน่ง/เวลาก่อนหน้า ความลึกสูงสุด และสถานะปอด"""
        self.prev_x = None
        self.prev_ts_ms = None
        self.prev_v = 0.0
        self.x_max = 0.0
        self._set_lung_state(False)

    # =========================================================================
    # 🫁 1.2 สถานะโดนปอด → ส่ง Trig Protocol 4 ให้ API (ส่งเฉพาะตอนสถานะเปลี่ยน)
    # =========================================================================
    def _set_lung_state(self, hit: bool):
        if hit != self.lung_hit:
            self.lung_hit = hit
            self._notify_lung(hit)

    def _notify_lung(self, hit: bool):
        """ส่งใน thread แยก เพื่อไม่ให้การยิง HTTP ไปบล็อกลูปคำนวณแรง"""
        threading.Thread(target=self._post_lung_flag, args=(hit,), daemon=True).start()

    def _post_lung_flag(self, hit: bool):
        value = self.client.encode_bitfield("trig_protocol_4", {"lung_hit": int(hit)})
        try:
            requests.post(
                f"{self.client.base_url}/protocols/trig_protocol_4/ingest",
                json={"value": value},
                timeout=1.0,
            )
        except requests.RequestException as err:
            print(f"[Lung] ส่งค่า lung_hit={int(hit)} ไปที่ API ไม่สำเร็จ: {err}")

    def apply_age(self, age_code: int):
        """ตั้งค่าชั้นผิวหนังตามกลุ่มอายุ (0=Pediatric, 1=Adult, 2=Geriatric)"""
        if age_code not in AGE_SKIN_PROFILES:
            raise ValueError(f"age code {age_code} ไม่ถูกต้อง (ต้องเป็น {sorted(AGE_SKIN_PROFILES)})")
        profile = AGE_SKIN_PROFILES[age_code]

        # กันตั้งค่าที่ทำให้ชั้นเนื้อเยื่อซ้อนกัน (ตรวจก่อนเขียนค่า จะได้ไม่ค้างสถานะครึ่งๆ กลางๆ)
        self._validate_layout(profile["x_p"])

        self.k_skin = profile["k_skin"]
        self.x_p = profile["x_p"]
        self.age_code = age_code

    def apply_settings(self, settings: Dict[str, int]):
        """รับ dict ที่แกะจาก Trig Protocol 1 แล้ว (age, difficulty, case_type, practice_mode)

        ตอนนี้ใช้เฉพาะ `age` กับชั้นผิวหนัง ส่วน difficulty/case_type/practice_mode เก็บไว้ใน
        self.settings เพื่อให้ขยายต่อได้ภายหลัง
        """
        if "age" not in settings:
            raise KeyError("settings ขาดฟิลด์ 'age'")
        self.apply_age(int(settings["age"]))
        self.settings = dict(settings)
        self.reset_state()

    def apply_protocol1_value(self, value: int):
        """รับเลข 7 บิตดิบของ Trig Protocol 1 → แกะด้วย SDK (ตรวจ 127/128 ให้) → ตั้งค่าโมเดล"""
        settings = self.client.parse_message("trig_protocol_1", value)
        self.apply_settings(settings)
        return settings

    def apply_latest_session(self):
        """ดึง session ล่าสุดของ trig_protocol_1 จาก API (GET /sessions) แล้วตั้งค่าโมเดล

        คืนค่า settings ที่ใช้ หรือ None ถ้ายังไม่มี session
        """
        resp = requests.get(f"{self.client.base_url}/sessions", timeout=5)
        resp.raise_for_status()
        sessions = [s for s in resp.json() if s.get("protocol_id") == "trig_protocol_1"]
        if not sessions:
            return None
        settings = sessions[-1]["settings"]
        self.apply_settings(settings)
        return settings

    # =========================================================================
    # 🎛️ 1.3 ใช้ config เอนโค้ดเดอร์ชุดเดียวกับหน้า Settings (encoder_config.json)
    #   Joint_YAW→yaw, Joint_PITCH→pitch, Slider_MOTOR→theta2 | encoder_id→channel, ppr→counts_per_rev, offset→zero_counts
    #   ค่าตั้งต้นใน self.axes ตรงกับ config ปัจจุบันอยู่แล้ว แต่ไม่ได้ซิงก์อัตโนมัติ: เรียกเมธอดเหล่านี้เมื่อแก้ในหน้า Settings (เช่น Set Zero ใหม่)
    #   sign ไม่มีใน config จึงคงค่าเดิมของแต่ละแกน
    # =========================================================================
    def apply_encoder_config(self, config: Dict[str, Dict[str, Any]]):
        """ตั้ง channel / counts_per_rev / zero_counts ของ model.axes จาก dict รูปแบบ encoder_config.json

        ตรวจครบทุกข้อต่อก่อนค่อยเปลี่ยน (ผิดข้อเดียว = ไม่แตะโมเดลเลย) แล้วเริ่มรอบการแทงใหม่ เพราะศูนย์เปลี่ยนแล้ว
        """
        updates = {}
        for joint, axis in ENCODER_CONFIG_AXES.items():
            item = config.get(joint)
            if not isinstance(item, dict):
                raise KeyError(f"encoder config ขาดข้อต่อ '{joint}'")
            channel = str(item.get("encoder_id", "")).lower().replace("_", "")  # "Enc_1" → "enc1"
            if channel not in ("enc1", "enc2", "enc3"):
                raise ValueError(f"'{joint}' ใช้ encoder_id '{item.get('encoder_id')}' ซึ่งไม่มี (ใช้ได้: Enc_1, Enc_2, Enc_3)")
            ppr = item.get("ppr")
            if isinstance(ppr, bool) or not isinstance(ppr, (int, float)) or ppr <= 0:
                raise ValueError(f"PPR ของ '{joint}' ต้องมากกว่า 0")
            updates[axis] = (channel, float(ppr), int(item.get("offset", 0)))
        channels = [u[0] for u in updates.values()]
        if len(set(channels)) != len(channels):
            raise ValueError("encoder config เลือกเอนโค้ดเดอร์ซ้ำกันหลายข้อต่อ")
        for axis, (channel, ppr, offset) in updates.items():
            cal = self.axes[axis]
            cal.channel, cal.counts_per_rev, cal.zero_counts = channel, ppr, offset
        self._applied_encoder_config = copy.deepcopy(config)
        self.reset_state()

    def load_encoder_config(self, path: str = "encoder_config.json"):
        """อ่านไฟล์ encoder_config.json แล้วใช้กับโมเดล (ต้องเป็นไฟล์ที่ backend เขียน ไม่ใช่สำเนาเก่า)"""
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self.apply_encoder_config(config)
        return config

    def apply_encoder_config_from_api(self):
        """ดึง config ล่าสุดจาก backend (GET /encoder/state) แล้วใช้กับโมเดล — ไม่ต้องรู้ที่อยู่ไฟล์"""
        resp = requests.get(f"{self.client.base_url}/encoder/state", timeout=5)
        resp.raise_for_status()
        config = resp.json()["config"]
        self.apply_encoder_config(config)
        return config

    # --- ซิงก์อัตโนมัติ: thread คอยดึง config จาก API แล้วฝากไว้เป็น pending ---
    #     การเปลี่ยนค่าแกนจริงทำในลูปอ่านเอนโค้ดเดอร์ (ต้นของ process_encoder) ค่าจึงไม่เปลี่ยนกลางการคำนวณตัวอย่างเดียวกัน
    def fetch_encoder_config(self) -> bool:
        """ดึง config ล่าสุดจาก API (GET /encoder/state) ถ้าต่างจากที่ใช้อยู่จะเก็บเป็น pending แล้วคืน True
        ติดต่อ API ไม่ได้ = คืน False และใช้ค่าเดิมต่อ (ไม่ให้ลูปฮาร์ดแวร์ล้ม)"""
        try:
            resp = requests.get(f"{self.client.base_url}/encoder/state", timeout=2)
            resp.raise_for_status()
            config = resp.json()["config"]
        except (requests.RequestException, ValueError, KeyError):
            return False
        if config == self._applied_encoder_config:
            return False
        self._pending_encoder_config = config
        return True

    def _apply_pending_encoder_config(self):
        pending, self._pending_encoder_config = self._pending_encoder_config, None
        if pending is None:
            return
        try:
            self.apply_encoder_config(pending)
        except (KeyError, ValueError) as err:
            self._applied_encoder_config = copy.deepcopy(pending)  # จำไว้ว่าชุดนี้ใช้ไม่ได้ จะได้ไม่ลองซ้ำทุกรอบ
            print(f"[TissueModel] config เอนโค้ดเดอร์จาก API ใช้ไม่ได้ คงค่าเดิมไว้: {err}")

    def start_encoder_config_sync(self, interval: float = 1.0):
        """เริ่ม thread (daemon) ดึง config จาก API ทุก interval วินาที: แก้ PPR / Set Zero / สลับเอนโค้ดเดอร์ในหน้า Settings แล้วโมเดลจะใช้ค่าใหม่เอง"""
        if self._sync_thread is not None and self._sync_thread.is_alive():
            return
        self._sync_stop.clear()

        def loop():
            while not self._sync_stop.wait(interval):
                self.fetch_encoder_config()

        self._sync_thread = threading.Thread(target=loop, daemon=True)
        self._sync_thread.start()

    def stop_encoder_config_sync(self):
        self._sync_stop.set()

    # =========================================================================
    # 🧮 2. ฟังก์ชันย่อยสำหรับคำนวณส่วนประกอบของแรง (Sub-Force Calculations)
    # =========================================================================
    def f_skin(self, x):
        """แรงต้านการยืดของผิวหนัง"""
        return self.k_skin * x

    def f_muscle(self, x):
        """แรงต้านการยืดของชั้นกล้ามเนื้อ"""
        return self.k_muscle * (x - self.x_trans)

    def f_fric_in(self, x, v):
        """แรงเสียดทานขณะแทงเข็มเข้า (v >= 0)"""
        return self.b_fric * v + (self.c_fric if v > 0 else 0.0)

    def f_fric_out(self, x, v):
        """แรงเสียดทานขณะดึงเข็มออก (v < 0)"""
        return self.b_fric * abs(v) + self.c_fric

    def f_blend1(self, x):
        """ช่วงทรานซิชันเปลี่ยนผ่านหลังผิวหนังขาด (Transition Zone 1)"""
        ratio = (x - self.x_p) / self.delta1
        f_skin_max = self.f_skin(self.x_p)
        return (1.0 - ratio) * f_skin_max + ratio * self.f_cut_fat

    def f_blend2(self, x):
        """ช่วงทรานซิชันเปลี่ยนผ่านหลังเยื่อหุ้มปอดขาด (Transition Zone 2)"""
        ratio = (x - (self.x_pleura)) / self.delta2
        return (1.0 - ratio) * self.f_cut_pleura + ratio * 0.0

    # =========================================================================
    # 🎯 3. สมการแรงต้านรวม F_total(x, v, x_max) ตาม Piecewise Model
    # =========================================================================
    def calculate_f_total(self, x, v, x_max):
        """คำนวณแรงต้านรวมตามตำแหน่งความลึก (x), ความเร็ว (v) และ ความลึกสูงสุด (x_max)"""
        
        # 0. ระยะฟรีก่อนเจาะ: เข็มยังไม่แตะผิว (x < 0) ไม่มีแรงต้าน
        if x < 0:
            return 0.0

        # 1. ชั้นผิวหนัง (Skin Layer: 0 <= x < x_p)
        if 0 <= x < self.x_p and x_max < self.x_p:
            if v >= 0:
                return self.f_skin(x) + self.f_fric_in(x, v)
            else:
                return self.gamma_h * self.f_skin(x) + self.f_fric_out(x, v)

        # 2. ช่วงรอยต่อหลังผิวหนังขาด (Skin Puncture Blend Zone: x_p <= x < x_p + delta1)
        elif self.x_p <= x < (self.x_p + self.delta1) and v >= 0:
            return self.f_blend1(x) + self.f_fric_in(x, v)

        # 3. ชั้นไขมันใต้ผิวหนัง (Subcutaneous Fat Layer: x_p + delta1 <= x < x_trans)
        elif (self.x_p + self.delta1) <= x < self.x_trans and v >= 0:
            return self.f_cut_fat + self.f_fric_in(x, v)

        # 4. ชั้นกล้ามเนื้อ (Muscle Layer: x_trans <= x < x_pleura)
        elif self.x_trans <= x < self.x_pleura:
            if v >= 0:
                return self.f_cut_fat + self.f_muscle(x) + self.f_fric_in(x, v)
            else:
                return self.gamma_hm * self.f_muscle(x) + self.f_fric_out(x, v)

        # 5. ช่วงรอยต่อหลังเยื่อหุ้มปอดขาด (Pleura Puncture Blend Zone: x_pleura <= x < x_pleura + delta2)
        elif self.x_pleura <= x < (self.x_pleura + self.delta2) and v >= 0:
            return self.f_blend2(x) + self.f_fric_in(x, v)

        # 6. ชั้นปอด (Lung: x > x_lung) แรงสปริงเนื้อปอด + แรงเสียดทาน
        elif x > self.x_lung:
            lung_spring = self.k_lung * (x - self.x_lung)
            if v >= 0:
                return lung_spring + self.f_fric_in(x, v)
            else:
                return self.gamma_lung * lung_spring + self.f_fric_out(x, v)

        # 7. ระยะฟรีหลังทะลุเยื่อหุ้มปอด (x_pleura + delta2 <= x <= x_lung) / กรณีอื่นๆ
        else:
            if not self.cavity_friction:
                return 0.0
            if v >= 0:
                return self.f_fric_in(x, v)
            else:
                return self.f_fric_out(x, v)

    # =========================================================================
    # 🔄 4. คำนวณ Kinematics & ลูปหลัก
    # =========================================================================
    def pose(self, enc1: int, enc2: int, enc3: int) -> Dict[str, float]:
        """ท่าของเข็มจากเอนโค้ดเดอร์ (ไม่มี side effect: ไม่แตะสถานะความเร็ว/ปอด/API) สำหรับหน้า Simulation

        คืนมุม pitch/yaw (องศา, -180..180), ความลึก depth_mm จากผิว (ลบ = ยังไม่แตะ) และระยะที่ทะลุเยื่อหุ้มปอด/เริ่มโดนปอด (mm)
        """
        pitch, yaw, theta2 = self.encoders_to_angles(enc1, enc2, enc3)
        wrap = lambda a: (a + 180.0) % 360.0 - 180.0
        x = self.depth_from_s(self.calculate_kinematics(theta2)[0])
        return {"pitch_deg": wrap(pitch), "yaw_deg": wrap(yaw), "depth_mm": x * 1000.0,
                "pleura_mm": (self.x_pleura + self.delta2) * 1000.0, "lung_mm": self.x_lung * 1000.0}

    def calculate_kinematics(self, theta2_deg):
        theta2_rad = math.radians(theta2_deg)
        sin_t2 = math.sin(theta2_rad)
        cos_t2 = math.cos(theta2_rad)
        
        sqrt_term = math.sqrt(max(0.0, self.R2**2 - (self.R1 * sin_t2)**2))
        s = self.R1 * cos_t2 + sqrt_term  # ระยะการกระจัด S (เมตร)
        
        if sqrt_term != 0:
            j_theta2 = -self.R1 * sin_t2 - ((self.R1**2 * sin_t2 * cos_t2) / sqrt_term) # Jacobian
        else:
            j_theta2 = 0.0
            
        return s, j_theta2

    def depth_from_s(self, s):
        """แปลงระยะกระจัด s ของสไลด์ → ความลึก x ของเข็มวัดจากผิวหนัง

        travel = s_home - s  (ระยะที่เข็มเคลื่อนจากตำแหน่งถอยสุด; แทงเข้า = theta2 เพิ่ม = s ลด
                              ตรงกับเครื่องหมายของ Jacobian ที่ใช้คำนวณแรงบิดเดิม)
        x      = travel - free_before   (x = 0 เมื่อเข็มแตะผิวหนังพอดี)
        """
        s_home, _ = self.calculate_kinematics(self.theta_home_deg)
        return (s_home - s) - self.free_before

    def encoders_to_angles(self, enc1: int, enc2: int, enc3: int) -> Tuple[float, float, float]:
        """แปลง counts ของ enc1..enc3 → (pitch, yaw, theta2) เป็นองศา ตามค่า self.axes"""
        counts = {"enc1": enc1, "enc2": enc2, "enc3": enc3}
        angles = []
        for axis in ("pitch", "yaw", "theta2"):
            channel = self.axes[axis].channel
            if channel not in counts:
                raise KeyError(f"แกน '{axis}' ชี้ไปที่ช่อง '{channel}' ซึ่งไม่มี (ใช้ได้: enc1, enc2, enc3)")
            angles.append(self.axes[axis].to_deg(counts[channel]))
        return tuple(angles)

    def _velocity(self, x: float, timestamp_ms: int) -> float:
        """ความเร็วเข็ม (m/s) จากผลต่างความลึกและผลต่าง timestamp ของเอนโค้ดเดอร์"""
        # ตัวอย่างแรก หรือนาฬิกาบอร์ดรีเซ็ต (timestamp ถอยหลัง) → เริ่มอ้างอิงใหม่ v = 0 (กัน Ki/Kv พุ่ง)
        if self.prev_ts_ms is None or timestamp_ms < self.prev_ts_ms:
            v = 0.0
        # ตัวอย่างอยู่ใน ms เดียวกัน (dt = 0) → ใช้ความเร็วล่าสุด ไม่หารศูนย์
        elif timestamp_ms == self.prev_ts_ms:
            return self.prev_v
        else:
            v = (x - self.prev_x) / ((timestamp_ms - self.prev_ts_ms) / 1000.0)

        self.prev_x = x
        self.prev_ts_ms = timestamp_ms
        self.prev_v = v
        return v

    def process_telemetry(self, raw_serial_str):
        """รับข้อความดิบ 'timestamp;enc1;enc2;enc3' (Trig Protocol 2) แล้วคืนคำสั่ง Trig Protocol 3"""
        # 1. ถอดรหัสข้อความจากเอนโค้ดเดอร์ผ่าน SDK (ฟิลด์ไม่ครบหรือไม่ใช่จำนวนเต็ม → ValueError)
        t = self.client.parse_message("trig_protocol_2", raw_serial_str)
        return self.process_encoder(t["timestamp"], t["enc1"], t["enc2"], t["enc3"])

    def process_encoder(self, timestamp_ms: int, enc1: int, enc2: int, enc3: int, touch: Optional[int] = None):
        """ประมวลผลตัวอย่างเอนโค้ดเดอร์ 1 ชุด (รูปแบบเดียวกับที่ EncoderStreamReader.read_data() คืนมา)

        ใช้ได้ตรงๆ:  cmd = model.process_encoder(*reader.read_data())
        """
        self._apply_pending_encoder_config()  # ใช้ config ใหม่ (ถ้ามี) ก่อนแปลง counts → มุมของตัวอย่างนี้

        if touch is None:
            touch = self.touch

        # 2. แปลง counts → มุม แล้วคำนวณ Kinematics และ Update ความลึกสูงสุด (x_max)
        _pitch, yaw_deg, theta2_deg = self.encoders_to_angles(enc1, enc2, enc3)

        s, j_theta2 = self.calculate_kinematics(theta2_deg)
        x = self.depth_from_s(s)
        v = self._velocity(x, timestamp_ms)
        self.x_max = max(self.x_max, x)

        # เกินระยะฟรีหลังทะลุเยื่อหุ้มปอด = โดนปอด → แจ้ง API (1 = โดนปอด, 0 = ไม่โดน)
        self._set_lung_state(x > self.x_lung)

        # 3. คำนวณแรงต้านรวม F_total และ แรงบิดรวม tau_total
        f_total = self.calculate_f_total(x, v, self.x_max)
        yaw_rad = math.radians(yaw_deg)

        tau_total = (f_total + self.M1 * self.G * math.sin(yaw_rad)) * j_theta2

        # 4. แปลงแรงบิดเป็น Gain สำหรับ Gimbal Motor (Ki, Kv)
        ki = abs(tau_total) * 10.0
        kv = abs(v) * 2.5 + 0.5

        # 5. กำหนดสถานะ Touch Sensor (0 = ไม่สัมผัส, 1 = สัมผัส)
        if touch == 0:
            bp, by = 1, 1  # ปลดล็อก
        else:
            bp, by = 0, 0  # ต้านแรง

        # 6. สร้างข้อความ Command ผ่าน SDK ส่งกลับฮาร์ดแวร์
        command_data = {"Ki": ki, "Kv": kv, "bp": bp, "by": by}
        return self.client.build_message("trig_protocol_3", command_data)

# --- ทดสอบจำลองการทำงาน ---
if __name__ == "__main__":
    model = TissueResistanceModel()

    # ตัวอย่างทดสอบ: ข้อความจากเอนโค้ดเดอร์ "timestamp(ms);enc1;enc2;enc3"
    # enc3 = 398 counts (ที่ 4096 counts/รอบ ≈ 35° → เข็มลึกกว่าผิว ~2 mm) เป็นเพียงค่าตัวอย่าง
    # ค่าจริงต้องตั้ง counts_per_rev / zero_counts ใน model.axes ให้ตรงกับฮาร์ดแวร์ก่อน
    test_input = "1000;0;0;398"
    output_cmd = model.process_telemetry(test_input)

    print(f"📥 Input (timestamp;enc1;enc2;enc3): {test_input}")
    print(f"📤 Output Command (Ki;Kv;bp;by): {output_cmd}")