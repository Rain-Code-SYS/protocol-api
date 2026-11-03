import math
import time
from protocol_sdk.client import ProtocolClient

class TissueResistanceModel:
    def __init__(self, api_url="http://127.0.0.1:8000"):
        self.client = ProtocolClient(base_url=api_url)

        # ==========================================
        # 1. พารามิเตอร์ทางกายภาพของระบบ (Physical Parameters)
        # ==========================================
        self.R1 = 0.031          # ความยาวแขนมอเตอร์ Crank Radius (m)
        self.R2 = 0.028          # ความยาวก้านส่งกำลัง Connecting Rod (m)
        self.m1 = 0.016768       # มวลรวมของก้อนสไลด์และหัวจับเข็ม (kg)
        self.g  = 9.81           # แรงโน้มถ่วงโลก (m/s^2)

        # คำนวณระยะเริ่มต้น s(0) เมื่อ theta2 = 0 deg (ระยะยืดสูงสุด)
        self.s0 = self.R1 + self.R2  # 0.031 + 0.028 = 0.059 m (59 mm)

        # ==========================================
        # 2. พารามิเตอร์ชั้นเนื้อเยื่อ (Tissue Layer Boundaries)
        # ==========================================
        self.x_p = 0.003         # ระยะแทงทะลุผิวหนัง Skin Puncture (3 mm)
        self.delta1 = 0.001      # ช่วง Blend 1 (1 mm)
        self.x_trans = 0.012     # จุดเปลี่ยนจากไขมันเข้ากล้ามเนื้อ (12 mm)
        self.x_pleura = 0.025    # ระยะแทงทะลุเยื่อหุ้มปอด (25 mm)
        self.delta2 = 0.001      # ช่วง Blend 2 (1 mm)

        # ค่าความแข็งและความต้านทาน
        self.k_skin = 1200.0     # (N/m)
        self.k_muscle = 800.0    # (N/m)
        self.f_cut_fat = 1.5     # แรงตัดชั้นไขมัน (N)
        self.f_fric_in = 0.8     # แรงเสียดทานตอนแทงเข้า (N)
        self.f_fric_out = 0.5    # แรงเสียดทานตอนถอนออก (N)
        self.gamma_h = 0.3       # สัมประสิทธิ์ Hysteresis ผิวหนัง
        self.gamma_hm = 0.4      # สัมประสิทธิ์ Hysteresis กล้ามเนื้อ

        # สถานะติดตามความลึกสูงสุด (State Tracking)
        self.x_max = 0.0
        self.last_x = 0.0
        self.last_time = time.time()

    def calculate_kinematics(self, theta1_deg: float, theta2_deg: float):
        """
        คำนวณระยะการกระจัดเชิงเส้น s(theta2), Insertion Depth (x), 
        Insertion Speed (v) และ Jacobian J(theta2)
        """
        # แปลงมุมเป็น Radian
        th1 = math.radians(theta1_deg) # yaw angle (มุมเอียงของราง)
        th2 = math.radians(theta2_deg) # motor rotation angle (0 - 60 deg)

        # 1. ระยะการกระจัด s(theta2) ตามสมการ Slider-Crank
        sin_th2 = math.sin(th2)
        cos_th2 = math.cos(th2)
        
        sqrt_term = math.sqrt(max(0, self.R2**2 - (self.R1 * sin_th2)**2))
        s = self.R1 * cos_th2 + sqrt_term

        # 2. คำนวณระยะแทง x (Insertion Depth: 0 - 36 mm)
        # เมื่อ theta2 = 0 deg -> x = 0 mm, เมื่อ theta2 = 60 deg -> x = 35.58 mm (~36 mm)
        x = self.s0 - s  

        # 3. คำนวณความเร็ว v = dx/dt (Insertion Speed)
        now = time.time()
        dt = max(1e-4, now - self.last_time)
        v = (x - self.last_x) / dt
        
        self.last_x = x
        self.last_time = now
        if x > self.x_max:
            self.x_max = x

        # 4. คำนวณ Jacobian J(theta2)
        denom = math.sqrt(max(1e-6, self.R2**2 - (self.R1**2) * (sin_th2**2)))
        J = -self.R1 * sin_th2 - ((self.R1**2) * sin_th2 * cos_th2) / denom

        return x, v, th1, J

    def calculate_tissue_force(self, x: float, v: float) -> float:
        """ คำนวณแรงต้านเนื้อเยื่อ F_total(x, v, x_max) """
        if x < 0:
            return 0.0

        # --- 1. ชั้นผิวหนัง (Skin Layer: 0 <= x < x_p) ---
        if x < self.x_p and self.x_max < self.x_p:
            f_skin = self.k_skin * x
            if v >= 0:
                return f_skin + self.f_fric_in
            else:
                return self.gamma_h * f_skin + self.f_fric_out

        # --- 2. ช่วง Blend 1 (x_p <= x < x_p + delta1) ---
        elif x < (self.x_p + self.delta1):
            if v >= 0:
                f_blend1 = self.f_cut_fat * ((x - self.x_p) / self.delta1)
                return f_blend1 + self.f_fric_in
            else:
                return self.f_fric_out

        # --- 3. ชั้นไขมัน (Fat Layer: x_p + delta1 <= x < x_trans) ---
        elif x < self.x_trans:
            if v >= 0:
                return self.f_cut_fat + self.f_fric_in
            else:
                return self.f_fric_out

        # --- 4. ชั้นกล้ามเนื้อ (Muscle Layer: x_trans <= x < x_pleura) ---
        elif x < self.x_pleura:
            f_muscle = self.k_muscle * (x - self.x_trans)
            if v >= 0:
                return self.f_cut_fat + f_muscle + self.f_fric_in
            else:
                return self.gamma_hm * f_muscle + self.f_fric_out

        # --- 5. ช่วง Blend 2 (x_pleura <= x < x_pleura + delta2) ---
        elif x < (self.x_pleura + self.delta2):
            if v >= 0:
                f_blend2 = 2.0 * (1.0 - (x - self.x_pleura) / self.delta2)
                return f_blend2 + self.f_fric_in
            else:
                return self.f_fric_out

        # --- 6. ทะลุเยื่อหุ้มปอด / ทะลุผ่านทั้งหมด ---
        else:
            return self.f_fric_in if v >= 0 else self.f_fric_out

    def process_telemetry(self, raw_telemetry_str: str) -> str:
        """
        รับข้อความ Trig Protocol 2 (pitch;yaw;theta2;touch)
        คำนวณและส่งกลับข้อความ Trig Protocol 3 (Ki;Kv;bp;by)
        """
        # Parse Telemetry
        telemetry = self.client.parse_message("trig_protocol_2", raw_telemetry_str)
        
        yaw = float(telemetry["yaw"])       # theta1 (มุมเอียงของราง)
        theta2 = float(telemetry["theta2"]) # มุมมอเตอร์ Gimbal (0 - 60 deg)
        touch = int(telemetry["touch"])     # สัมผัส (0 หรือ 1)

        # ตรวจสอบ Touch Sensor: ถ้า touch == 0 (ไม่สัมผัส) ให้เบรกทำงานทันที
        if touch == 0:
            command_data = {"Ki": 0.0, "Kv": 0.0, "bp": 1, "by": 1}
            return self.client.build_message("trig_protocol_3", command_data)

        # 1. คำนวณทาง Kinematics
        x, v, th1_rad, J = self.calculate_kinematics(yaw, theta2)

        # 2. คำนวณแรงต้าน F_total
        f_total = self.calculate_tissue_force(x, v)

        # 3. คำนวณแรงบิดรวม tau_total = (F_total + m * g * sin(theta1)) * J(theta2)
        gravity_comp = self.m1 * self.g * math.sin(th1_rad)
        tau_total = (f_total + gravity_comp) * J

        # 4. แปลงแรงบิด tau_total เป็นค่า Gain (Ki, Kv) สำหรับขับ Gimbal Motor
        ki_command = abs(tau_total)
        kv_command = 12.0  # แรงดันควบคุมคงที่ 12V

        command_data = {
            "Ki": round(ki_command, 4),
            "Kv": round(kv_command, 2),
            "bp": 0,  # สัมผัสแล้ว ปลดเบรก
            "by": 0
        }

        return self.client.build_message("trig_protocol_3", command_data)


if __name__ == "__main__":
    model = TissueResistanceModel()
    
    # ทดสอบกรณี Touch = 0 (ไม่สัมผัส)
    out_no_touch = model.process_telemetry("0.0;15.0;10.0;0")
    print(f"🚫 No Touch Output -> {out_no_touch}")
    
    # ทดสอบกรณี Touch = 1 (กดลงไป theta2 = 30 องศา)
    out_touch = model.process_telemetry("0.0;15.0;30.0;1")
    print(f"🎯 Touch Active Output -> {out_touch}")