"""ตัวช่วยสร้างข้อความเอนโค้ดเดอร์ 'timestamp;enc1;enc2;enc3' สำหรับเทสต์"""

MM_PER_COUNT_HI_RES = 0.0001   # ความละเอียดสูงของระยะเข็มในเทสต์ฟิสิกส์ (mm ต่อ 1 count)


def high_resolution(model, counts_per_rev=3_600_000):
    """ตั้งความละเอียดสูงเพื่อตัดผลของ quantization ออกจากเทสต์ฟิสิกส์

    - มุมของแต่ละแกน: 0.0001°/count
    - ระยะเข็ม z = 3CD/400: ปรับ Pulley PD (D) ให้ 1 count = 0.0001 mm (D = 400/3 * 0.0001 mm)
    """
    for axis in model.axes.values():
        axis.counts_per_rev = counts_per_rev
    model.pulley_pd_mm = 400.0 / 3.0 * MM_PER_COUNT_HI_RES
    return model


def deg_to_counts(model, axis_name, deg):
    axis = model.axes[axis_name]
    return round(axis.zero_counts + axis.sign * deg * axis.counts_per_rev / 360.0)


def make_line(model, slider_counts, ts_ms, yaw_deg=0.0, pitch_deg=0.0):
    """สร้างบรรทัดตาม Trig Protocol 2 โดยจับคู่ช่องตาม model.axes

    slider_counts = C (counts เอนโค้ดเดอร์สไลด์หลังหักศูนย์ ใช้ในสูตร z = 3CD/400) แปลงกลับเป็นค่า raw = zero + sign * C
    """
    slider = model.axes["theta2"]
    values = {
        model.axes["pitch"].channel: deg_to_counts(model, "pitch", pitch_deg),
        model.axes["yaw"].channel: deg_to_counts(model, "yaw", yaw_deg),
        slider.channel: slider.zero_counts + slider.sign * int(slider_counts),
    }
    return f"{ts_ms};{values['enc1']};{values['enc2']};{values['enc3']}"


def slider_counts_for_depth(model, x):
    """หา counts สไลด์ C ที่ทำให้เข็มอยู่ลึก x (เมตร) จากผิวหนัง: ย้อนสูตร z = 3CD/400 (ปัดเป็นจำนวนเต็ม)"""
    z_mm = (x + model.free_before) * 1000.0
    c = round(z_mm * 400.0 / (3.0 * model.pulley_pd_mm))
    while model.depth_from_counts(c) < x:   # กัน floating-point ปัดให้ลึกน้อยกว่า x นิดเดียว (เทสต์ที่ x = x_p พอดีจะข้ามชั้นผิดด้าน)
        c += 1
    return c


def expected_voltage(model, enc, v, x_max):
    """แรงดัน V ที่ควรได้จากตัวอย่าง enc=(enc1, enc2, enc3) เมื่อความเร็ว = v (m/s) และความลึกสูงสุดก่อนหน้า = x_max (m)
    คำนวณซ้ำจากฟังก์ชันของโมเดลโดยตรง (ไม่แตะสถานะของโมเดล) ใช้เทียบกับ process_encoder"""
    import math
    import tissue_model

    _pitch, yaw, theta2 = model.encoders_to_angles(*enc)
    _s, j = model.calculate_kinematics(theta2)
    x = model.depth_from_counts(model.slider_counts(*enc))
    f = model.calculate_f_total(x, v, max(x_max, x))
    tau = (f + model.M1 * model.G * math.sin(math.radians(yaw))) * j
    return min(tissue_model.V_MAX, abs(tau) / tissue_model.TAU_FULL_SCALE * tissue_model.V_MAX)