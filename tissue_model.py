import math
import time
from protocol_sdk import ProtocolClient

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

        # ตัวแปรเก็บสถานะการเคลื่อนที่
        self.prev_s = 0.0
        self.prev_time = time.time()
        self.x_max = 0.0       # ความลึกสูงสุดที่เคยแทงเข้าไปได้

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

        # 6. กรณีอื่นๆ / แทงพ้นทะลุช่องอกแล้ว (Otherwise)
        else:
            if v >= 0:
                return self.f_fric_in(x, v)
            else:
                return self.f_fric_out(x, v)

    # =========================================================================
    # 🔄 4. คำนวณ Kinematics & ลูปหลัก
    # =========================================================================
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

    def process_telemetry(self, raw_serial_str):
        # 1. ถอดรหัสข้อความจาก Haptic Telemetry ผ่าน SDK
        telemetry = self.client.parse_message("trig_protocol_2", raw_serial_str)
        
        pitch = telemetry["pitch"]
        yaw_deg = telemetry["yaw"]
        theta2_deg = telemetry["theta2"]
        touch = telemetry["touch"]

        # คำนวณ delta_t สำหรับหาความเร็ว v
        curr_time = time.time()
        dt = max(0.0001, curr_time - self.prev_time)
        
        # 2. คำนวณ Kinematics และ Update ความลึกสูงสุด (x_max)
        s, j_theta2 = self.calculate_kinematics(theta2_deg)
        v = (s - self.prev_s) / dt
        
        self.prev_s = s
        self.prev_time = curr_time
        self.x_max = max(self.x_max, s)

        # 3. คำนวณแรงต้านรวม F_total และ แรงบิดรวม tau_total
        f_total = self.calculate_f_total(s, v, self.x_max)
        yaw_rad = math.radians(yaw_deg)
        
        tau_total = (f_total + self.M1 * self.G * math.sin(yaw_rad)) * j_theta2

        # 4. แปลงแรงบิดเป็น Gain สำหรับ Gimbal Motor (Ki, Kv)
        ki = abs(tau_total) * 10.0
        kv = abs(v) * 2.5 + 0.5

        # 5. กำหนดสถานะ Touch Sensor (0 = ไม่สัมผัส, 1 = สัมผัส)
        if touch == 0:
            bp, by = 1, 1  # ปลดล็อก[cite: 4]
        else:
            bp, by = 0, 0  # ต้านแรง[cite: 4]

        # 6. สร้างข้อความ Command ผ่าน SDK ส่งกลับฮาร์ดแวร์
        command_data = {"Ki": ki, "Kv": kv, "bp": bp, "by": by}
        return self.client.build_message("trig_protocol_3", command_data)


# --- ทดสอบจำลองการทำงาน ---
if __name__ == "__main__":
    model = TissueResistanceModel()
    
    # ตัวอย่างทดสอบแทงเข้าชั้นผิวหนัง: theta2 = 10 องศา, yaw = 15 องศา, touch = 1
    test_input = "0.0;15.0;10.0;1"
    output_cmd = model.process_telemetry(test_input)
    
    print(f"📥 Input: {test_input}")
    print(f"📤 Output Command (Ki;Kv;bp;by): {output_cmd}")