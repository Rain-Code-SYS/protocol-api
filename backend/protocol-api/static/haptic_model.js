/*
 * HapticModel: พอร์ต JavaScript ของ TissueResistanceModel (tissue_model.py) สำหรับคำนวณแรงต้านเนื้อเยื่อ
 * ในเครื่องผู้ใช้ (ไม่ผ่านเซิร์ฟเวอร์) เพื่อให้ลูป "อ่านเอนโค้ดเดอร์ -> คำนวณ Ki;Kv -> เขียนกลับบอร์ด" หน่วงน้อยที่สุด
 *
 * - ไม่แตะ DOM / เครือข่าย / Web Serial เลย: ใช้ได้ทั้งในเบราว์เซอร์ (<script>), Web Worker (importScripts), Node และแอปเดสก์ท็อป (Electron/Tauri)
 * - สูตรต้องตรงกับ tissue_model.py เสมอ: tests/haptic_vectors.json สร้างจากโค้ด Python แล้ว tests/haptic_model.test.js เทียบผล
 *   ถ้าแก้ tissue_model.py ให้รัน  python tests/gen_haptic_vectors.py  แล้ว  node --test
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.HapticModel = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ค่าตั้งต้นสำหรับทดลอง (placeholder) เหมือน AGE_SKIN_PROFILES ใน tissue_model.py
  const AGE_SKIN_PROFILES = {
    0: {label: 'Pediatric', k_skin: 800.0, x_p: 0.0020},
    1: {label: 'Adult', k_skin: 1200.0, x_p: 0.0030},
    2: {label: 'Geriatric', k_skin: 1000.0, x_p: 0.0025},
  };
  const ENCODER_CONFIG_AXES = {Joint_YAW: 'yaw', Joint_PITCH: 'pitch', Slider_MOTOR: 'theta2'};
  const RAD = Math.PI / 180;

  /** ข้อความตัวเลขแบบเดียวกับ str(float) ของ Python ("12.0", "1e-05") เพื่อให้คำสั่งที่ส่งบอร์ดเหมือน serial_bridge.py ทุกไบต์ */
  function pyFloat(x) {
    if (Number.isNaN(x)) return 'nan';
    if (!Number.isFinite(x)) return x > 0 ? 'inf' : '-inf';
    if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
    const sign = x < 0 ? '-' : '';
    const [mant, expStr] = Math.abs(x).toExponential().split('e');   // ตัวเลขนัยสำคัญสั้นที่สุดที่คืนค่าเดิมได้ (เหมือน repr)
    const digits = mant.replace('.', '');
    const e = parseInt(expStr, 10);
    if (e >= -4 && e < 16) {
      if (e >= digits.length - 1) return sign + digits + '0'.repeat(e - (digits.length - 1)) + '.0';
      if (e >= 0) return sign + digits.slice(0, e + 1) + '.' + digits.slice(e + 1);
      return sign + '0.' + '0'.repeat(-e - 1) + digits;
    }
    const m = digits.length > 1 ? digits[0] + '.' + digits.slice(1) : digits;
    const ae = Math.abs(e);
    return sign + m + 'e' + (e < 0 ? '-' : '+') + (ae < 10 ? '0' + ae : String(ae));
  }

  class HapticModel {
    constructor() {
      // --- ขอบเขตความลึกของแต่ละชั้น (เมตร) ---
      this.x_p = 0.003;
      this.delta1 = 0.001;
      this.x_trans = 0.012;
      this.x_pleura = 0.025;
      this.delta2 = 0.001;
      // --- ความแข็ง ---
      this.k_skin = 1200.0;
      this.k_muscle = 800.0;
      // --- แรงตัด / เสียดทาน ---
      this.f_cut_fat = 1.2;
      this.f_cut_pleura = 2.5;
      this.b_fric = 5.0;
      this.c_fric = 0.5;
      // --- hysteresis ---
      this.gamma_h = 0.35;
      this.gamma_hm = 0.45;
      // --- Slider-Crank ---
      this.R1 = 0.031;
      this.R2 = 0.028;
      this.M1 = 0.016768;
      this.G = 9.81;
      // --- ระยะฟรีและปอด ---
      this.needle_stroke = 0.050;
      this.free_before = 0.010;
      this.free_after = 0.008;
      this.cavity_friction = true;
      this.theta_home_deg = 0.0;
      this.k_lung = 400.0;
      this.gamma_lung = 0.5;
      // --- เอนโค้ดเดอร์ (ตรงกับค่าตั้งต้นหน้า Settings) ---
      this.axes = {
        pitch: {channel: 'enc2', counts_per_rev: 800.0, zero_counts: 0, sign: 1},
        yaw: {channel: 'enc1', counts_per_rev: 2048.0, zero_counts: 0, sign: 1},
        theta2: {channel: 'enc3', counts_per_rev: 4096.0, zero_counts: 0, sign: 1},
      };
      this.touch = 1;            // 1 = ต้านแรง, 0 = ปลดล็อก
      this.prev_x = null;
      this.prev_ts_ms = null;
      this.prev_v = 0.0;
      this.x_max = 0.0;
      this.lung_hit = false;
      this.onLungChange = null;  // ฟังก์ชัน (hit:boolean) เรียกเมื่อสถานะโดนปอดเปลี่ยน (ใช้ส่งต่อให้ซิมูเลชันภายนอก/แอป)
      this.age_code = 1;
      this._validateLayout(this.x_p);
    }

    get x_lung() { return this.x_pleura + this.delta2 + this.free_after; }

    _validateLayout(x_p) {
      if (x_p + this.delta1 >= this.x_trans) throw new Error('x_p + delta1 ต้องน้อยกว่า x_trans');
      if (this.x_trans >= this.x_pleura) throw new Error('x_trans ต้องน้อยกว่า x_pleura');
      if (this.free_before + this.x_lung >= this.needle_stroke) throw new Error('ระยะฟรี + ชั้นเนื้อเยื่อ เกินระยะกดสูงสุดของเข็ม');
    }

    /** เริ่มรอบการแทงใหม่: ล้างตำแหน่ง/เวลาก่อนหน้า ความลึกสูงสุด และสถานะปอด */
    resetState() {
      this.prev_x = null;
      this.prev_ts_ms = null;
      this.prev_v = 0.0;
      this.x_max = 0.0;
      this._setLungState(false);
    }

    _setLungState(hit) {
      if (hit !== this.lung_hit) {
        this.lung_hit = hit;
        if (typeof this.onLungChange === 'function') this.onLungChange(hit);
      }
    }

    /** 0 = Pediatric, 1 = Adult, 2 = Geriatric */
    applyAge(code) {
      const profile = AGE_SKIN_PROFILES[code];
      if (!profile) throw new Error('age code ' + code + ' ไม่ถูกต้อง (ต้องเป็น 0, 1 หรือ 2)');
      this._validateLayout(profile.x_p);
      this.k_skin = profile.k_skin;
      this.x_p = profile.x_p;
      this.age_code = code;
    }

    /** config รูปแบบเดียวกับ encoder_config.json / GET /encoder/state: ตรวจครบก่อนค่อยเปลี่ยน แล้วเริ่มรอบใหม่ */
    applyEncoderConfig(config) {
      const updates = {};
      for (const joint of Object.keys(ENCODER_CONFIG_AXES)) {
        const item = config && config[joint];
        if (!item || typeof item !== 'object') throw new Error("encoder config ขาดข้อต่อ '" + joint + "'");
        const channel = String(item.encoder_id === undefined ? '' : item.encoder_id).toLowerCase().replace(/_/g, '');
        if (!['enc1', 'enc2', 'enc3'].includes(channel)) throw new Error("'" + joint + "' ใช้ encoder_id '" + item.encoder_id + "' ซึ่งไม่มี");
        const ppr = item.ppr;
        if (typeof ppr !== 'number' || !(ppr > 0)) throw new Error("PPR ของ '" + joint + "' ต้องมากกว่า 0");
        updates[ENCODER_CONFIG_AXES[joint]] = [channel, ppr, Math.trunc(Number(item.offset === undefined ? 0 : item.offset))];
      }
      const channels = Object.values(updates).map(u => u[0]);
      if (new Set(channels).size !== channels.length) throw new Error('encoder config เลือกเอนโค้ดเดอร์ซ้ำกันหลายข้อต่อ');
      for (const axis of Object.keys(updates)) {
        const cal = this.axes[axis];
        [cal.channel, cal.counts_per_rev, cal.zero_counts] = updates[axis];
      }
      this.resetState();
    }

    // ---------- ส่วนประกอบของแรง ----------
    f_skin(x) { return this.k_skin * x; }
    f_muscle(x) { return this.k_muscle * (x - this.x_trans); }
    f_fric_in(x, v) { return this.b_fric * v + (v > 0 ? this.c_fric : 0.0); }
    f_fric_out(x, v) { return this.b_fric * Math.abs(v) + this.c_fric; }
    f_blend1(x) {
      const ratio = (x - this.x_p) / this.delta1;
      return (1.0 - ratio) * this.f_skin(this.x_p) + ratio * this.f_cut_fat;
    }
    f_blend2(x) {
      const ratio = (x - this.x_pleura) / this.delta2;
      return (1.0 - ratio) * this.f_cut_pleura + ratio * 0.0;
    }

    /** แรงต้านรวมตามความลึก x, ความเร็ว v, ความลึกสูงสุด x_max (Piecewise Model เดียวกับ Python) */
    calculateFTotal(x, v, x_max) {
      if (x < 0) return 0.0;
      if (x >= 0 && x < this.x_p && x_max < this.x_p) {
        return v >= 0 ? this.f_skin(x) + this.f_fric_in(x, v) : this.gamma_h * this.f_skin(x) + this.f_fric_out(x, v);
      } else if (this.x_p <= x && x < this.x_p + this.delta1 && v >= 0) {
        return this.f_blend1(x) + this.f_fric_in(x, v);
      } else if (this.x_p + this.delta1 <= x && x < this.x_trans && v >= 0) {
        return this.f_cut_fat + this.f_fric_in(x, v);
      } else if (this.x_trans <= x && x < this.x_pleura) {
        return v >= 0 ? this.f_cut_fat + this.f_muscle(x) + this.f_fric_in(x, v)
                      : this.gamma_hm * this.f_muscle(x) + this.f_fric_out(x, v);
      } else if (this.x_pleura <= x && x < this.x_pleura + this.delta2 && v >= 0) {
        return this.f_blend2(x) + this.f_fric_in(x, v);
      } else if (x > this.x_lung) {
        const spring = this.k_lung * (x - this.x_lung);
        return v >= 0 ? spring + this.f_fric_in(x, v) : this.gamma_lung * spring + this.f_fric_out(x, v);
      }
      if (!this.cavity_friction) return 0.0;
      return v >= 0 ? this.f_fric_in(x, v) : this.f_fric_out(x, v);
    }

    // ---------- Kinematics ----------
    calculateKinematics(theta2_deg) {
      const t = theta2_deg * RAD;
      const sin_t2 = Math.sin(t), cos_t2 = Math.cos(t);
      const sqrt_term = Math.sqrt(Math.max(0.0, this.R2 * this.R2 - (this.R1 * sin_t2) * (this.R1 * sin_t2)));
      const s = this.R1 * cos_t2 + sqrt_term;
      const j = sqrt_term !== 0
        ? -this.R1 * sin_t2 - ((this.R1 * this.R1 * sin_t2 * cos_t2) / sqrt_term)
        : 0.0;
      return [s, j];
    }

    depthFromS(s) {
      const s_home = this.calculateKinematics(this.theta_home_deg)[0];
      return (s_home - s) - this.free_before;
    }

    /** counts ของ enc1..enc3 -> [pitch, yaw, theta2] (องศา) ตาม this.axes */
    encodersToAngles(enc1, enc2, enc3) {
      const counts = {enc1, enc2, enc3};
      const out = [];
      for (const name of ['pitch', 'yaw', 'theta2']) {
        const ax = this.axes[name];
        if (!(ax.channel in counts)) throw new Error("แกน '" + name + "' ชี้ไปที่ช่อง '" + ax.channel + "' ซึ่งไม่มี");
        out.push(ax.sign * (counts[ax.channel] - ax.zero_counts) * 360.0 / ax.counts_per_rev);
      }
      return out;
    }

    /** ท่าของเข็มจากเอนโค้ดเดอร์ (ไม่มี side effect) สำหรับวาดหน้า Simulation */
    pose(enc1, enc2, enc3) {
      const [pitch, yaw, theta2] = this.encodersToAngles(enc1, enc2, enc3);
      const wrap = a => (((a + 180.0) % 360.0) + 360.0) % 360.0 - 180.0;
      const x = this.depthFromS(this.calculateKinematics(theta2)[0]);
      return {
        pitch_deg: wrap(pitch), yaw_deg: wrap(yaw), depth_mm: x * 1000.0,
        pleura_mm: (this.x_pleura + this.delta2) * 1000.0, lung_mm: this.x_lung * 1000.0,
      };
    }

    _velocity(x, timestamp_ms) {
      let v;
      if (this.prev_ts_ms === null || timestamp_ms < this.prev_ts_ms) v = 0.0;      // ตัวอย่างแรก/บอร์ดรีเซ็ตนาฬิกา
      else if (timestamp_ms === this.prev_ts_ms) return this.prev_v;               // ms เดียวกัน: ใช้ความเร็วล่าสุด
      else v = (x - this.prev_x) / ((timestamp_ms - this.prev_ts_ms) / 1000.0);
      this.prev_x = x;
      this.prev_ts_ms = timestamp_ms;
      this.prev_v = v;
      return v;
    }

    /** ประมวลผลตัวอย่าง 1 ชุด คืนตัวเลขดิบ {ki, kv, bp, by, x, v, f_total} */
    step(timestamp_ms, enc1, enc2, enc3, touch) {
      if (touch === undefined || touch === null) touch = this.touch;
      const [, yaw_deg, theta2_deg] = this.encodersToAngles(enc1, enc2, enc3);
      const [s, j_theta2] = this.calculateKinematics(theta2_deg);
      const x = this.depthFromS(s);
      const v = this._velocity(x, timestamp_ms);
      this.x_max = Math.max(this.x_max, x);
      this._setLungState(x > this.x_lung);
      const f_total = this.calculateFTotal(x, v, this.x_max);
      const tau_total = (f_total + this.M1 * this.G * Math.sin(yaw_deg * RAD)) * j_theta2;
      const ki = Math.abs(tau_total) * 10.0;
      const kv = Math.abs(v) * 2.5 + 0.5;
      const released = touch === 0;
      return {ki, kv, bp: released ? 1 : 0, by: released ? 1 : 0, x, v, f_total};
    }

    /** คำสั่ง Trig Protocol 3 ("Ki;Kv;bp;by") พร้อมส่งบอร์ด (ต่อท้ายด้วย \n เอง) */
    processEncoder(timestamp_ms, enc1, enc2, enc3, touch) {
      const r = this.step(timestamp_ms, enc1, enc2, enc3, touch);
      return pyFloat(r.ki) + ';' + pyFloat(r.kv) + ';' + r.bp + ';' + r.by;
    }
  }

  HapticModel.AGE_SKIN_PROFILES = AGE_SKIN_PROFILES;
  HapticModel.pyFloat = pyFloat;
  /** คำสั่งปล่อยแรง: Ki=0, Kv ต่ำสุด, ปลดล็อก (bp=by=1) ใช้ตอนหยุดแรงสะท้อนกลับ/ตัดการเชื่อมต่อ */
  HapticModel.RELEASE_COMMAND = '0.0;0.5;1;1';
  return HapticModel;
});