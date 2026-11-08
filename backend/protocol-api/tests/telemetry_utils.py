"""ตัวช่วยสร้างข้อความเอนโค้ดเดอร์ 'timestamp;enc1;enc2;enc3' สำหรับเทสต์"""


def high_resolution(model, counts_per_rev=3_600_000):
    """ตั้งความละเอียดเอนโค้ดเดอร์ให้สูง (0.0001°/count) เพื่อตัดผลของ quantization ออกจากเทสต์ฟิสิกส์"""
    for axis in model.axes.values():
        axis.counts_per_rev = counts_per_rev
    return model


def deg_to_counts(model, axis_name, deg):
    axis = model.axes[axis_name]
    return round(axis.zero_counts + axis.sign * deg * axis.counts_per_rev / 360.0)


def make_line(model, theta_deg, ts_ms, yaw_deg=0.0, pitch_deg=0.0):
    """สร้างบรรทัดตาม Trig Protocol 2 โดยจับคู่ช่องตาม model.axes"""
    values = {
        model.axes["pitch"].channel: deg_to_counts(model, "pitch", pitch_deg),
        model.axes["yaw"].channel: deg_to_counts(model, "yaw", yaw_deg),
        model.axes["theta2"].channel: deg_to_counts(model, "theta2", theta_deg),
    }
    return f"{ts_ms};{values['enc1']};{values['enc2']};{values['enc3']}"


def theta_for_depth(model, x):
    """หามุม theta2 ที่ทำให้เข็มอยู่ลึก x (เมตร) จากผิวหนัง (bisection บนช่วงที่ s ลดลงเรื่อยๆ)"""
    import math

    s_home, _ = model.calculate_kinematics(model.theta_home_deg)
    target_travel = x + model.free_before
    lo, hi = 0.0, math.degrees(math.asin(model.R2 / model.R1))
    for _ in range(100):
        mid = (lo + hi) / 2
        s, _ = model.calculate_kinematics(mid)
        if s_home - s < target_travel:
            lo = mid
        else:
            hi = mid
    return lo