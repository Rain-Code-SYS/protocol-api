/*
 * Anatomy: โมเดลร่างกายจริงของหน้า Simulation (ข้อมูลจาก BodyParts3D แปลงด้วย tools/build_anatomy.py -> static/anatomy/anatomy.json + anatomy.bin)
 *
 * BodyParts3D, © The Database Center for Life Science, licensed under CC Attribution 4.0 International
 * (https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html) ข้อมูลถูกดัดแปลง: แปลงพิกัด ลดโพลีกอน สร้างตารางหน้าตัด
 *
 * พิกัดผู้ป่วย (เมตร): x = หน้า(+)/หลัง(-), y = ซ้ายของผู้ป่วย(+), z = ศีรษะ(+)  (ตรงกับกลุ่ม patient ในฉาก 3D ของ index.html)
 * มุม th รอบแกนลำตัว: 0 = ด้านหน้า (+x), เพิ่มไปทางซ้ายผู้ป่วย (+y): จุด = (cx + r cos th, cy + r sin th)
 *
 * ส่วนที่ไม่แตะ THREE (decode / ตารางหน้าตัด / จุดเจาะ / ปอด) ใช้ได้ใน Node เพื่อเทสต์ ส่วน build() ต้องส่งออบเจ็กต์ THREE เข้ามา
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Anatomy = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const TAU = 2 * Math.PI;
  const SITE = {ribTop: 3, ribBot: 6, minY: 0.07};   // โซนเจาะ: ช่องซี่โครงที่ 4-6 (ระหว่างซี่โครงซี่ที่ 4 กับ 7) หน้า mid-axillary line และห่างกระดูกอก >= 7 cm
  const ARM_Y0 = 0.172, ARM_Y1 = 0.19;   // แขนเริ่มที่ |y| ≈ 0.17-0.19 m (ลำตัวไม่เกิน ~0.17)
  const ARM_ABD = 0.05, ARM_HAND_Y = 0.235;   // กางแขนที่ไหล่ ~3° ; ข้อมือวางที่ |y| = 0.235 m (ข้างต้นขา ในกรอบเบาะ)
  const LEG_TOE_OUT = 0.21;   // ปลายเท้าตกออกด้านนอก ~12°
  const LID = {x: 0.060, y: 0.036, z: 0.4255, rx: 0.0175, ry: 0.0165, rz: 0.0088};   // เปลือกตา: อุดเบ้าตาลึก ~17 mm ของโมเดลให้ผิวเรียบเท่าขอบเบ้า
  const PANTS_TOP = -0.13, PANTS_HEM = -1.02, PANTS_Y = 0.18, PANTS_OFF = 0.0075;   // กางเกง: ใต้สะดือถึงเหนือข้อเท้า, ออฟเซ็ตจากผิว 7.5 mm
  const BONE_GROUPS = ['rib', 'cart', 'sternum', 'clav', 'scap', 'humerus', 'vert', 'sacrum'];
  const SITE_RADIAL_TOL = 0.02;                      // จุดที่ชนต้องอยู่บนผิวลำตัว (ไม่ใช่แขน) ภายใน 2 cm จากรัศมีผิวในตาราง
  const LUNG_WALL_MARGIN = 0.005;                    // ปอดอยู่ลึกกว่าผิวด้านในของกรงซี่โครงอย่างน้อยเท่านี้ (เมตร)
  const MED_MARGIN = 0.003;
  const MED_MIN_HALF = 0.015;                        // ครึ่งความกว้างต่ำสุดของมีเดียสตินัมข้างละ 1.5 cm

  const mod2pi = a => ((a % TAU) + TAU) % TAU;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  class Anatomy {
    /** manifest = JSON ของ anatomy.json, buffer = ArrayBuffer ของ anatomy.bin */
    constructor(manifest, buffer) {
      if (!manifest || !manifest.polar || !manifest.ribs) throw new Error('anatomy manifest ไม่ถูกต้อง');
      this.manifest = manifest;
      this.armsOnBed = true;   // false = ท่าแขนห้อยเดิมของโมเดล
      this.buffer = buffer && buffer.buffer && !(buffer instanceof ArrayBuffer)
        ? buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength) : buffer;
      const P = manifest.polar;
      this.nz = P.nz; this.nth = P.nth; this.z0 = P.z0; this.dz = P.dz;
      const sc = P.scale;
      this.cx = Float64Array.from(P.cx, v => v * sc.cxy);
      this.cy = Float64Array.from(P.cy, v => v * sc.cxy);
      const flat = a => (Array.isArray(a[0]) ? a.flat() : a);   // ตารางหน้าตัดเก็บเป็นแถวต่อชั้น (nz x nth)
      this.rs = Float64Array.from(flat(P.rs), v => v * sc.r);
      this.ri = Float64Array.from(flat(P.ri), v => v * sc.r);
      this.medL = Float64Array.from(P.medL, v => v * sc.med);
      this.medR = Float64Array.from(P.medR, v => v * sc.med);
      this.tissueMedianMm = P.tissueMedianMm;
      const R = manifest.ribs;
      this.ribs = R.z.map(row => Float64Array.from(row, v => v === null ? NaN : v * R.scale));
      this.landmarks = manifest.landmarks;
      this.attribution = manifest.attribution;
    }

    static async load(baseUrl) {
      const base = baseUrl.replace(/\/?$/, '/');
      const [jr, br] = await Promise.all([fetch(base + 'anatomy.json'), fetch(base + 'anatomy.bin')]);
      if (!jr.ok || !br.ok) throw new Error('โหลดไฟล์กายวิภาคไม่สำเร็จ (' + jr.status + '/' + br.status + ')');
      const manifest = await jr.json();
      const buffer = await br.arrayBuffer();
      if (manifest.binBytes && buffer.byteLength !== manifest.binBytes) throw new Error('anatomy.bin ขนาดไม่ตรงกับ anatomy.json');
      return new Anatomy(manifest, buffer);
    }

    // ---------- ตารางหน้าตัด ----------
    _zIndex(z) {
      const f = clamp((z - this.z0) / this.dz, 0, this.nz - 1);
      const i0 = Math.min(Math.floor(f), this.nz - 2);
      return [i0, f - i0];
    }

    center(z) {
      const [i, t] = this._zIndex(z);
      return [this.cx[i] + (this.cx[i + 1] - this.cx[i]) * t, this.cy[i] + (this.cy[i + 1] - this.cy[i]) * t];
    }

    /** ขอบมีเดียสตินัมในแนว y (เมตร จากแกนกลาง): [ขวา(-), ซ้าย(+)] อย่างน้อยข้างละ 1.5 cm (ชุดข้อมูลไม่มีเอออร์ตาส่วนอกขาลง/กระดูกสันหลังส่วนนี้) */
    mediastinum(z) {
      const [i, t] = this._zIndex(z);
      const r = this.medR[i] + (this.medR[i + 1] - this.medR[i]) * t, l = this.medL[i] + (this.medL[i + 1] - this.medL[i]) * t;
      return [Math.min(r, -MED_MIN_HALF), Math.max(l, MED_MIN_HALF)];
    }

    _field(arr, z, th) {
      const [i, t] = this._zIndex(z);
      const f = mod2pi(th) / TAU * this.nth - 0.5, fl = Math.floor(f), s = f - fl;
      const j0 = ((fl % this.nth) + this.nth) % this.nth, j1 = (j0 + 1) % this.nth, n = this.nth;
      const a = arr[i * n + j0] * (1 - s) + arr[i * n + j1] * s;
      const b = arr[(i + 1) * n + j0] * (1 - s) + arr[(i + 1) * n + j1] * s;
      return a + (b - a) * t;
    }

    skinRadius(z, th) { return this._field(this.rs, z, th); }
    innerRadius(z, th) { return this._field(this.ri, z, th); }
    /** ความหนาของผนังอก (ผิว -> ผิวด้านในกรงซี่โครง) ตามแนวรัศมี หน่วยเมตร */
    wallThickness(z, th) { return this.skinRadius(z, th) - this.innerRadius(z, th); }

    theta(p) {
      const c = this.center(p[2]);
      return mod2pi(Math.atan2(p[1] - c[1], p[0] - c[0]));
    }

    /** จุดบนผิวที่ความสูง z มุม th เลื่อนเข้าด้านใน inset เมตร (inset ลบ = ออกนอกผิว) */
    skinPoint(z, th, inset) {
      const c = this.center(z), r = this.skinRadius(z, th) - (inset || 0);
      return [c[0] + r * Math.cos(th), c[1] + r * Math.sin(th), z];
    }

    /** เวกเตอร์ตั้งฉากผิว (ชี้ออกนอกลำตัว, หน่วยความยาว) ที่จุด p (พิกัดผู้ป่วย) จากตารางผิว */
    skinNormal(p) {
      const z = clamp(p[2], this.z0 + 2 * this.dz, this.z0 + (this.nz - 3) * this.dz), th = this.theta(p);
      const hz = 2 * this.dz, ht = 2 * TAU / this.nth;
      const a = this.skinPoint(z + hz, th), b = this.skinPoint(z - hz, th);
      const c = this.skinPoint(z, th + ht), d = this.skinPoint(z, th - ht);
      const tz = [a[0] - b[0], a[1] - b[1], a[2] - b[2]], tt = [c[0] - d[0], c[1] - d[1], c[2] - d[2]];
      let n = [tt[1] * tz[2] - tt[2] * tz[1], tt[2] * tz[0] - tt[0] * tz[2], tt[0] * tz[1] - tt[1] * tz[0]];
      const m = Math.hypot(n[0], n[1], n[2]);
      n = n.map(v => v / m);
      if (n[0] * Math.cos(th) + n[1] * Math.sin(th) < 0) n = n.map(v => -v);   // ชี้ออกนอกลำตัว
      return n;
    }

    // ---------- แนวซี่โครง / โซนเจาะ ----------
    /** ความสูง z ของแนวกลางซี่โครงซี่ที่ k+1 (k = 0..11) ที่มุม th; NaN ถ้าซี่โครงไม่ครอบคลุมมุมนั้น */
    ribZ(k, th) {
      const row = this.ribs[k], n = this.nth;
      const f = mod2pi(th) / TAU * n - 0.5, fl = Math.floor(f), s = f - fl;
      const j0 = ((fl % n) + n) % n, j1 = (j0 + 1) % n;
      const a = row[j0], b = row[j1];
      if (Number.isNaN(a) || Number.isNaN(b)) return NaN;
      return a + (b - a) * s;
    }

    /** p = จุดบนผิว (พิกัดผู้ป่วย) อยู่ในโซนเจาะหรือไม่: ช่องซี่โครงที่ 4-6 หน้า mid-axillary line, ไม่ใช่แขน */
    siteOk(p, site) {
      const s = site || SITE, c = this.center(p[2]);
      if (p[0] - c[0] <= 0 || Math.abs(p[1]) < s.minY) return false;
      const th = this.theta(p);
      const dist = Math.hypot(p[0] - c[0], p[1] - c[1]);
      if (Math.abs(dist - this.skinRadius(p[2], th)) > SITE_RADIAL_TOL) return false;
      const zb = this.ribZ(s.ribBot, th), zt = this.ribZ(s.ribTop, th);
      if (Number.isNaN(zb) || Number.isNaN(zt)) return false;
      return p[2] > zb && p[2] < zt;
    }

    /** จุดเจาะตั้งต้นที่ถูกต้อง: ช่องซี่โครงที่ 5 (ระหว่างซี่ 5 กับ 6) ด้านขวาของผู้ป่วย ห่างจากกระดูกอกไปทางด้านข้าง */
    defaultSite(sideSign, thetaDeg) {
      const sd = sideSign === undefined ? -1 : sideSign;
      const deg = thetaDeg === undefined ? 75 : thetaDeg;
      const th = sd < 0 ? TAU - deg * Math.PI / 180 : deg * Math.PI / 180;
      const z = (this.ribZ(4, th) + this.ribZ(5, th)) / 2;
      const S = this.skinPoint(z, th, 0);
      return {theta: th, point: S, normal: this.skinNormal(S)};
    }

    // ---------- ปอด ----------
    /** ช่วงความสูงของปอด: ยอดปอดเหนือซี่โครงซี่ที่ 1 เล็กน้อย / ฐานปอดที่ระดับซี่โครงซี่ที่ 9 ด้านข้าง */
    lungExtent() {
      let apex = -Infinity;
      for (let j = 0; j < this.nth; j++) if (Number.isFinite(this.ribs[0][j])) apex = Math.max(apex, this.ribs[0][j]);
      const l = this.ribZ(8, Math.PI / 2), r = this.ribZ(8, 3 * Math.PI / 2);
      const base = (l + r) / 2;
      return {apex: apex + 0.012, base};
    }

    /** วงตัดของปอดข้างหนึ่ง (sd = +1 ซ้าย, -1 ขวา) สำหรับ tubeGeo: ผนังด้านนอกลึกจากผิว inset เมตร แต่ไม่ล้ำออกนอกกรงซี่โครง
     *  และหลบมีเดียสตินัม (หัวใจ/หลอดเลือดใหญ่/หลอดลม) คืน {rings: [[x,y,z],...][], apex, base} */
    lungRings(sd, inset, nRings, nPts) {
      const NR = nRings || 18, NP = nPts || 44, a0 = 0.14;
      const {apex, base} = this.lungExtent();
      const zc = (apex + base) / 2, h = (apex - base) / 2, rings = [];
      for (let i = 0; i <= NR; i++) {
        const z = base + 2 * h * i / NR;
        const k = Math.max(0.06, Math.sqrt(Math.max(0, 1 - ((z - zc) / h) ** 2)));
        const c = this.center(z), [mR, mL] = this.mediastinum(z), pts = [];
        for (let j = 0; j <= NP; j++) {
          const f = j / NP;
          const th = sd < 0 ? Math.PI + a0 + (Math.PI - 2 * a0) * f : Math.PI - a0 - (Math.PI - 2 * a0) * f;
          const r = Math.min(this.skinRadius(z, th) - inset, this.innerRadius(z, th) - LUNG_WALL_MARGIN);
          let x = c[0] + r * Math.cos(th), y = c[1] + r * Math.sin(th);
          y = sd > 0 ? Math.max(y, c[1] + mL + MED_MARGIN) : Math.min(y, c[1] + mR - MED_MARGIN);
          pts.push([x, y]);
        }
        const m = pts.reduce((s2, q) => [s2[0] + q[0] / pts.length, s2[1] + q[1] / pts.length], [0, 0]);
        rings.push(pts.map(q => [m[0] + (q[0] - m[0]) * k, m[1] + (q[1] - m[1]) * k, z]));
      }
      return {rings, apex, base};
    }

    // ---------- กริดสำหรับโซนเจาะ / เมชรังสีเลือกจุด ----------
    /** แผ่นไฮไลต์โซนเจาะข้างหนึ่ง: {pos: [x,y,z...], idx} ลอยเหนือผิว lift เมตร */
    zoneGrid(sd, lift, NU, NV) {
      const nu = NU || 24, nv = NV || 6, s = SITE;
      // เริ่มที่มุมแรกที่ |y| >= minY (พ้นกระดูกอก) ที่ระดับกลางโซน และจบก่อนเส้น mid-axillary (x = ศูนย์กลาง) เล็กน้อย
      let th0 = 0.2;
      while (th0 < 1.4) {
        const zm = (this.ribZ(s.ribTop, th0) + this.ribZ(s.ribBot, th0)) / 2, q = this.skinPoint(zm, th0, 0);
        if (Math.abs(q[1]) >= s.minY + 0.002) break;
        th0 += 0.01;
      }
      const th1 = Math.PI / 2 - 0.03, pos = [], idx = [];
      for (let i = 0; i <= nu; i++) {
        const a = th0 + (th1 - th0) * i / nu, th = sd < 0 ? TAU - a : a;
        const zb = this.ribZ(s.ribBot, th), zt = this.ribZ(s.ribTop, th);
        for (let j = 0; j <= nv; j++) pos.push(...this.skinPoint(zb + (zt - zb) * j / nv, th, -(lift === undefined ? 0.0008 : lift)));
      }
      for (let i = 0; i < nu; i++) for (let j = 0; j < nv; j++) { const a = i * (nv + 1) + j, b = a + nv + 1; idx.push(a, b, a + 1, b, b + 1, a + 1); }
      return {pos, idx};
    }

    /** เมชห่อผิวลำตัวช่วงอก (ใช้ยิงรังสีเลือกจุดเจาะ ไม่แสดงผล): ช่วง z ที่ตารางผิวเชื่อถือได้ (ใต้ไหล่) */
    pickGrid(zLo, zHi) {
      const lo = zLo === undefined ? -0.06 : zLo, hi = zHi === undefined ? 0.26 : zHi, NZ = Math.round((hi - lo) / this.dz), n = this.nth;
      const pos = [], idx = [];
      for (let i = 0; i <= NZ; i++) for (let j = 0; j < n; j++) pos.push(...this.skinPoint(lo + (hi - lo) * i / NZ, (j + 0.5) * TAU / n, 0));
      for (let i = 0; i < NZ; i++) for (let j = 0; j < n; j++) {
        const a = i * n + j, b = i * n + (j + 1) % n, c = (i + 1) * n + j, d = (i + 1) * n + (j + 1) % n;
        idx.push(a, b, c, b, d, c);
      }
      return {pos, idx};
    }

    // ---------- เมชจริง (ต้องใช้ THREE) ----------
    /** ข้อมูลเมชที่ถอดรหัสแล้ว: {positions: Float32Array, indices: Uint16Array|Uint32Array, ...meta} */
    meshData(m) {
      const q = new Uint16Array(this.buffer, m.vOff, m.nv * 3), pos = new Float32Array(m.nv * 3);
      for (let i = 0; i < pos.length; i++) {
        const c = i % 3;
        pos[i] = m.min[c] + q[i] / 65535 * (m.max[c] - m.min[c]);
      }
      const indices = m.wide ? new Uint32Array(this.buffer, m.iOff, m.nf * 3) : new Uint16Array(this.buffer, m.iOff, m.nf * 3);
      return Object.assign({positions: pos, indices}, m);
    }

    // ---------- ท่านอนหงายตามธรรมชาติ ----------
    // โมเดลเป็นท่ายืน (แขนห้อย ฝ่ามือหันไปด้านหน้า ขาลอยจากเตียง 3-6 cm อวัยวะเพศนูน) จึงจัดท่าใหม่ตอนสร้างเมช (ข้อมูลไฟล์ไม่ถูกแก้):
    //  - แขน: หมุนแบบโครงกระดูก (ไหล่ + ศอก) ให้ท่อนบน/ท่อนล่างแนบเบาะ บิดท่อนล่างให้ฝ่ามือหันเข้าหาลำตัว มืออยู่ข้างต้นขา
    //  - ขา: ลดลงแนบเบาะตามโปรไฟล์ด้านหลังจริง ปลายเท้าตกออกด้านนอกเล็กน้อย
    //  - ผิวบริเวณอวัยวะเพศ: ปรับให้เรียบ (แล้วใส่กางเกงทับ ดู buildPants)
    //  - ลำตัว ศีรษะ ไม่ถูกแตะ (ซี่โครง/ปอด/จุดเจาะคงตำแหน่งเดิม)
    _rotAbout(p, c, a, th) {
      const x = p[0] - c[0], y = p[1] - c[1], z = p[2] - c[2], co = Math.cos(th), si = Math.sin(th), dot = a[0] * x + a[1] * y + a[2] * z;
      return [c[0] + x * co + (a[1] * z - a[2] * y) * si + a[0] * dot * (1 - co),
        c[1] + y * co + (a[2] * x - a[0] * z) * si + a[1] * dot * (1 - co),
        c[2] + z * co + (a[0] * y - a[1] * x) * si + a[2] * dot * (1 - co)];
    }

    /** โครงแขน (คำนวณครั้งเดียว): ข้อไหล่ S ศอก E ข้อมือ W (แขนซ้าย y>0 ส่วนขวาสะท้อน y) และมุมที่แก้ให้แนบเบาะ */
    armRig() {
      if (this._armRig) return this._armRig;
      const meshes = this.manifest.meshes, skin = meshes.find(q => q.group === 'skin'), hum = meshes.find(q => q.group === 'humerus' && q.min[1] > 0);
      const mean = (P, f) => { let n = 0; const a = [0, 0, 0]; for (let i = 0; i < P.length; i += 3) if (f(P[i], P[i + 1], P[i + 2])) { n++; a[0] += P[i]; a[1] += P[i + 1]; a[2] += P[i + 2]; } return n ? a.map(v => v / n) : null; };
      const H = this.meshData(hum).positions, K = this.meshData(skin).positions;
      const S = mean(H, (x, y, z) => z > 0.20) || [-0.03, 0.16, 0.225], E = mean(H, (x, y, z) => z < -0.045) || [-0.02, 0.22, -0.06];
      const W = mean(K, (x, y, z) => y > ARM_Y1 && z < -0.29 && z > -0.31) || [0, 0.27, -0.30];
      const ax = (() => { const v = [E[0] - W[0], E[1] - W[1], E[2] - W[2]], n = Math.hypot(...v); return v.map(q => q / n); })();
      const rig = {S, E, W, axis: ax, g1: ARM_ABD, b1: 0, g2: 0, b2: 0, phi: -Math.PI / 2, target: this.landmarks.backX - 0.004};
      // ชุดจุดแขนซ้ายที่ใช้แก้มุม: ท่อนบน (ใต้ไหล่ถึงเหนือศอก) / ท่อนล่าง+มือ
      const upper = [], fore = [];
      for (let i = 0; i < K.length; i += 3) {
        if (K[i + 1] < ARM_Y1 + 0.005 || K[i + 2] > 0.17) continue;
        if (K[i + 2] > E[2] + 0.04) upper.push([K[i], K[i + 1], K[i + 2]]); else if (K[i + 2] < E[2] - 0.12 && K[i + 2] > -0.6) fore.push([K[i], K[i + 1], K[i + 2]]);
      }
      const minX = (pts, f) => { let m = Infinity; for (const q of pts) { const r = f(q); if (r[0] < m) m = r[0]; } return m; };
      const bis = (lo, hi, g) => { for (let k = 0; k < 40; k++) { const mid = (lo + hi) / 2; if (g(mid) > rig.target) lo = mid; else hi = mid; } return (lo + hi) / 2; };   // g ลดลงตามมุม
      rig.b1 = bis(0, 0.7, b => { rig.b1 = b; return minX(upper, q => this._armPoint(q, rig, 0, 0)); });
      // ท่อนล่าง: ให้ข้อมืออยู่ที่ y ≈ ARM_HAND_Y (ข้างต้นขา) ก่อน แล้วลดมุมศอกให้แนบเบาะ
      const wy = g2 => { rig.g2 = g2; return this._armPoint(W, rig, 1, 0)[1]; };
      { let lo = -0.5, hi = 0.5; for (let k = 0; k < 40; k++) { const mid = (lo + hi) / 2; if (wy(mid) > ARM_HAND_Y) hi = mid; else lo = mid; } rig.g2 = (lo + hi) / 2; }
      rig.b2 = bis(-0.4, 1.0, b => { rig.b2 = b; return minX(fore, q => this._armPoint(q, rig, 1, this._twistW(q[2], rig))); });
      return (this._armRig = rig);
    }

    _twistW(z, rig) { const t = clamp((rig.E[2] - z) / (rig.E[2] - rig.W[2]), 0, 1); return t * t * (3 - 2 * t); }

    /** จุด v (แขนซ้าย) หลังหมุนโซ่ไหล่→ศอก: f = 0 ท่อนบน, 1 ท่อนล่าง; tw = น้ำหนักการบิดท่อนล่าง (pronation) */
    _armPoint(v, r, f, tw) {
      const chainS = p => this._rotAbout(this._rotAbout(p, r.S, [0, 1, 0], r.b1), r.S, [1, 0, 0], r.g1);
      const up = chainS(v);
      if (f <= 0) return up;
      const t = this._rotAbout(v, r.E, r.axis, r.phi * tw);
      const fo = chainS(this._rotAbout(this._rotAbout(t, r.E, [0, 1, 0], r.b2), r.E, [1, 0, 0], r.g2));
      return f >= 1 ? fo : [up[0] + (fo[0] - up[0]) * f, up[1] + (fo[1] - up[1]) * f, up[2] + (fo[2] - up[2]) * f];
    }

    /** จัดท่าแขน (ผิวและกระดูกต้นแขน) in-place: LBS ระหว่างท่อนบน/ท่อนล่าง น้ำหนักตามระยะห่างจากลำตัว */
    poseArmPts(P) {
      const r = this.armRig(), sstep = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
      for (let i = 0; i < P.length; i += 3) {
        const y = P[i + 1], z = P[i + 2], sg = y < 0 ? -1 : 1, w = sstep(ARM_Y0, ARM_Y1 + 0.005, Math.abs(y)) * (1 - sstep(0.17, 0.26, z));
        if (w <= 0 || z < -0.6) continue;
        const f = 1 - sstep(r.E[2] - 0.03, r.E[2] + 0.03, z), q = this._armPoint([P[i], sg * y, z], r, f, this._twistW(z, r));
        P[i] += w * (q[0] - P[i]); P[i + 1] += w * (sg * q[1] - y); P[i + 2] += w * (q[2] - z);
      }
      return P;
    }

    /** ปรับผิวบริเวณอวัยวะเพศให้เรียบ: ตัดส่วนนูนให้ไม่เกินแนวผิวต้นขา/หัวหน่าว แล้วเกลี่ยเป็นแผ่นต่อเนื่อง */
    fixGroin(P, I) {
      const sstep = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
      const z0 = -0.80, z1 = -0.23, dz = 0.02, n = Math.round((z1 - z0) / dz) + 1, ceil = new Float32Array(n).fill(-Infinity);
      for (let i = 0; i < P.length; i += 3) {
        const y = Math.abs(P[i + 1]), z = P[i + 2];
        if (y < 0.075 || y > 0.105 || z < z0 - dz || z > z1 + dz) continue;   // แนวผิวต้นขา/ข้างหัวหน่าว (นอกบริเวณที่จะปรับ)
        const k = Math.round((z - z0) / dz); if (k >= 0 && k < n && P[i] > ceil[k]) ceil[k] = P[i];
      }
      for (let k = 0; k < n; k++) if (!Number.isFinite(ceil[k])) ceil[k] = k ? ceil[k - 1] : 0.05;
      const cs = Array.from(ceil, (v, k) => (ceil[Math.max(0, k - 1)] + 2 * v + ceil[Math.min(n - 1, k + 1)]) / 4);
      const nV = P.length / 3, wt = new Float32Array(nV);
      for (let v = 0; v < nV; v++) {
        const y = Math.abs(P[v * 3 + 1]), z = P[v * 3 + 2];
        if (z < z0 || z > z1 || y > 0.075) continue;
        const wr = (1 - sstep(0.045, 0.075, y)) * sstep(z1, z1 - 0.05, z) * sstep(z0, z0 + 0.05, z);
        if (wr <= 0) continue;
        wt[v] = wr;
        const f = (z - z0) / dz, k = clamp(Math.floor(f), 0, n - 2), c = cs[k] + (cs[k + 1] - cs[k]) * (f - k);
        if (P[v * 3] > c) P[v * 3] += wr * (c - P[v * 3]);
      }
      const nb = new Map();
      const link = (a, b) => { if (wt[a] > 0) { let l = nb.get(a); if (!l) nb.set(a, l = []); l.push(b); } };
      for (let t = 0; t < I.length; t += 3) for (let e = 0; e < 3; e++) { const a = I[t + e], b = I[t + (e + 1) % 3]; link(a, b); link(b, a); }
      for (let it = 0; it < 60; it++) {
        const nx = new Map();
        for (const [v, l] of nb) { let m = 0; for (const u of l) m += P[u * 3]; nx.set(v, P[v * 3] + 0.6 * wt[v] * (m / l.length - P[v * 3])); }
        for (const [v, x] of nx) P[v * 3] = x;
      }
      return P;
    }

    /** ขาแนบเบาะ: ปลายเท้าตกออกด้านนอก แล้วลดขาตามโปรไฟล์ด้านหลังจริง (ถ่วงน้ำหนักตามความสูงเหนือสะโพก) */
    poseLegs(P) {
      const sstep = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
      const down = (a, b, z) => sstep(0, 1, (a - z) / (a - b)), isLeg = (y, z) => Math.abs(y) < ARM_Y0 && z < -0.28;
      const cen = { '1': [0, 0], '-1': [0, 0] }, cnt = { '1': 0, '-1': 0 };
      for (let i = 0; i < P.length; i += 3) if (P[i + 2] < -0.80 && P[i + 2] > -0.90 && Math.abs(P[i + 1]) > 0.02) { const g = P[i + 1] > 0 ? '1' : '-1'; cen[g][0] += P[i]; cen[g][1] += Math.abs(P[i + 1]); cnt[g]++; }
      for (const g of ['1', '-1']) if (cnt[g]) { cen[g][0] /= cnt[g]; cen[g][1] /= cnt[g]; }
      for (let i = 0; i < P.length; i += 3) {
        const y = P[i + 1], z = P[i + 2];
        if (!isLeg(y, z) || Math.abs(y) < 0.003) continue;
        const wf = down(-0.80, -1.05, z); if (wf <= 0) continue;
        const sg = y < 0 ? -1 : 1, c = cen[String(sg)], q = this._rotAbout([P[i], Math.abs(y), z], [c[0], c[1], 0], [0, 0, 1], LEG_TOE_OUT * wf);
        P[i] = q[0]; P[i + 1] = sg * q[1];
      }
      const z0 = -1.25, z1 = -0.30, dz = 0.02, n = Math.round((z1 - z0) / dz) + 1, back = new Float32Array(n).fill(NaN);
      for (let i = 0; i < P.length; i += 3) {
        if (!isLeg(P[i + 1], P[i + 2]) || P[i + 2] < z0 - dz / 2) continue;
        const k = Math.round((P[i + 2] - z0) / dz); if (k >= 0 && k < n && !(back[k] <= P[i])) back[k] = P[i];
      }
      const target = this.landmarks.backX - 0.004;
      let d = Array.from(back, b => (Number.isFinite(b) ? Math.max(0, b - target) : 0));
      for (let rep = 0; rep < 2; rep++) d = d.map((v, k) => (d[Math.max(0, k - 1)] + 2 * v + d[Math.min(n - 1, k + 1)]) / 4);
      for (let i = 0; i < P.length; i += 3) {
        const y = P[i + 1], z = P[i + 2];
        if (!isLeg(y, z)) continue;
        const f = clamp((z - z0) / dz, 0, n - 1), k = Math.min(n - 2, Math.floor(f));
        P[i] -= down(-0.30, -0.46, z) * (d[k] + (d[k + 1] - d[k]) * (f - k));
      }
      return P;
    }

    /** meshData + ท่านอนหงายตามธรรมชาติ (ผิว: กระดูกต้นแขน: แขน) — เมชอื่นคงเดิม; ผลถูกแคชและใช้ร่วมกัน (ห้ามแก้ค่าในอาร์เรย์) */
    posedData(m) {
      if (!this.armsOnBed || (m.group !== 'skin' && m.group !== 'humerus')) return this.meshData(m);
      this._posed = this._posed || new Map();
      let d = this._posed.get(m.id);
      if (!d) {
        d = this.meshData(m);
        if (m.group === 'skin') { this.fixGroin(d.positions, d.indices); this.poseArmPts(d.positions); this.poseLegs(d.positions); } else this.poseArmPts(d.positions);
        this._posed.set(m.id, d);
      }
      return d;
    }

    /** เปลือกตาปิด + แนวขนตา แทนเบ้าตาที่เป็นหลุมลึก (ข้อมูลล้วน: ทดสอบได้โดยไม่ต้องมี THREE) */
    faceDetails() {
      const lids = [], lashes = [];
      for (const sg of [-1, 1]) {
        const c = [LID.x, sg * LID.y, LID.z], r = [LID.rx, LID.ry, LID.rz];
        lids.push({c, r});
        for (let k = -4; k <= 4; k++) {
          const dy = k * LID.ry * 0.17, dz = -0.0032 - 0.0014 * (1 - (dy / (LID.ry * 0.77)) ** 2), q = 1 - (dy / r[1]) ** 2 - (dz / r[2]) ** 2;
          lashes.push({p: [c[0] + r[0] * Math.sqrt(Math.max(0.05, q)) + 0.0004, c[1] + dy, c[2] + dz], r: 0.0012});
        }
      }
      return {lids, lashes};
    }

    buildFace(THREE, lidMat, lashMat) {
      const g = new THREE.Group(), fd = this.faceDetails();
      for (const l of fd.lids) { const m = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 12), lidMat); m.position.set(...l.c); m.scale.set(...l.r); m.name = 'eyelid'; g.add(m); }
      for (const l of fd.lashes) { const m = new THREE.Mesh(new THREE.SphereGeometry(l.r, 8, 6), lashMat); m.position.set(...l.p); m.name = 'lash'; g.add(m); }
      return g;
    }

    /** กางเกงขายาว (ตามผิวจริงหลังจัดท่า): ผิวเดิมที่ออฟเซ็ตออกตามเส้นตั้งฉาก เกลี่ยเรียบ มีขอบเอวหนาเล็กน้อย
     *  คลุมสะโพก-ขา (ไม่รวมแขน) ตั้งแต่ใต้สะดือถึงเหนือข้อเท้า คืน Mesh หรือ null */
    buildPants(THREE, mat) {
      const sk = this.manifest.meshes.find(q => q.group === 'skin');
      if (!sk) return null;
      const g = this.pantsGeometry(THREE);
      return g ? Object.assign(new THREE.Mesh(g, mat), {name: 'pants'}) : null;
    }

    pantsGeometry(THREE) {
      const sk = this.manifest.meshes.find(q => q.group === 'skin'), d = this.posedData(sk), P = d.positions, I = d.indices, nV = P.length / 3;
      const sstep = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
      const nrm = new Float32Array(P.length);
      for (let t = 0; t < I.length; t += 3) {
        const a = I[t] * 3, b = I[t + 1] * 3, c = I[t + 2] * 3;
        const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2], vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2];
        const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
        for (const q of [a, b, c]) { nrm[q] += nx; nrm[q + 1] += ny; nrm[q + 2] += nz; }
      }
      for (let v = 0; v < nV; v++) { const l = Math.hypot(nrm[v * 3], nrm[v * 3 + 1], nrm[v * 3 + 2]) || 1; nrm[v * 3] /= l; nrm[v * 3 + 1] /= l; nrm[v * 3 + 2] /= l; }
      const sel = new Uint8Array(nV);
      for (let v = 0; v < nV; v++) { const z = P[v * 3 + 2]; sel[v] = z < PANTS_TOP && z > PANTS_HEM && Math.abs(P[v * 3 + 1]) < PANTS_Y ? 1 : 0; }
      const remap = new Int32Array(nV).fill(-1), keep = [], idx = [];
      for (let t = 0; t < I.length; t += 3) {
        if (!(sel[I[t]] && sel[I[t + 1]] && sel[I[t + 2]])) continue;
        for (let e = 0; e < 3; e++) { const v = I[t + e]; if (remap[v] < 0) { remap[v] = keep.length; keep.push(v); } idx.push(remap[v]); }
      }
      if (!keep.length) return null;
      const m = keep.length, pos = new Float32Array(m * 3), orig = new Float32Array(m * 3), nn = new Float32Array(m * 3);
      keep.forEach((v, k) => {
        const z = P[v * 3 + 2], off = PANTS_OFF + 0.0045 * (1 - sstep(PANTS_TOP, PANTS_TOP - 0.035, z));   // ขอบเอวหนากว่า
        for (let c = 0; c < 3; c++) { orig[k * 3 + c] = P[v * 3 + c]; nn[k * 3 + c] = nrm[v * 3 + c]; pos[k * 3 + c] = P[v * 3 + c] + nrm[v * 3 + c] * off; }
      });
      const adj = Array.from({length: m}, () => []);
      for (let t = 0; t < idx.length; t += 3) for (let e = 0; e < 3; e++) { adj[idx[t + e]].push(idx[t + (e + 1) % 3], idx[t + (e + 2) % 3]); }
      for (let it = 0; it < 3; it++) {                                                   // เกลี่ยให้ผ้าเรียบกว่าผิว (กล้ามเนื้อ/รอยย่นเล็กๆ ไม่ขึ้นบนผ้า)
        const nx = new Float32Array(pos);
        for (let k = 0; k < m; k++) { const l = adj[k]; if (!l.length) continue; for (let c = 0; c < 3; c++) { let s = 0; for (const u of l) s += pos[u * 3 + c]; nx[k * 3 + c] = pos[k * 3 + c] + 0.5 * (s / l.length - pos[k * 3 + c]); } }
        pos.set(nx);
      }
      const wc = new Float32Array(m);                                                    // บริเวณเป้า: เกลี่ยเพิ่มให้เป็นผ้าเรียบ ไม่ตามรูปผิวข้างใน
      keep.forEach((v, k) => { wc[k] = (1 - sstep(0.05, 0.075, Math.abs(orig[k * 3 + 1]))) * sstep(-0.18, -0.24, orig[k * 3 + 2]) * sstep(-0.56, -0.50, orig[k * 3 + 2]); });
      for (let it = 0; it < 18; it++) {
        const nx = new Float32Array(pos);
        for (let k = 0; k < m; k++) { if (wc[k] <= 0) continue; const l = adj[k]; for (let c = 0; c < 3; c++) { let s2 = 0; for (const u of l) s2 += pos[u * 3 + c]; nx[k * 3 + c] = pos[k * 3 + c] + 0.7 * wc[k] * (s2 / l.length - pos[k * 3 + c]); } }
        pos.set(nx);
      }
      for (let it = 0; it < 4; it++) for (let k = 0; k < m; k++) {                     // บริเวณเป้า: ผ้าสูงกว่าผิวของจุดข้างเคียงด้วย (กันผิวโผล่ที่ตะเข็บ)
        if (wc[k] <= 0) continue;
        let mx = -Infinity; for (const u of adj[k]) if (orig[u * 3] > mx) mx = orig[u * 3];
        if (pos[k * 3] < mx + 0.004) pos[k * 3] = mx + 0.004;
      }
      for (let k = 0; k < m; k++) {                                                      // ผ้าต้องไม่จมผิว: ห่างจากผิวตามเส้นตั้งฉากอย่างน้อย 3 mm
        const dx = pos[k * 3] - orig[k * 3], dy = pos[k * 3 + 1] - orig[k * 3 + 1], dz = pos[k * 3 + 2] - orig[k * 3 + 2];
        const dn = dx * nn[k * 3] + dy * nn[k * 3 + 1] + dz * nn[k * 3 + 2];
        if (dn < 0.003) for (let c = 0; c < 3; c++) pos[k * 3 + c] += nn[k * 3 + c] * (0.003 - dn);
        if (nn[k * 3] > 0.3 && pos[k * 3] < orig[k * 3] + 0.004) pos[k * 3] = orig[k * 3] + 0.004;   // ด้านบน (หงายหน้า): ผ้าไม่ต่ำกว่าผิวใต้มัน
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      g.setIndex(idx);
      g.computeVertexNormals();
      return g;
    }

    /** สนามความสูงของผิวด้านบน: x สูงสุดของผิวทั้งตัว (ลำตัว ขา แขน) ในแต่ละช่อง (z, y) ขนาด cell เมตร
     *  ใช้ให้ผ้าคลุมทิ้งตัวพาดผิวจริงโดยไม่มีส่วนใดโผล่ (ไม่ต้องใช้ THREE)
     *  คืน {z0, y0, cell, nz, ny, top: Float32Array(nz*ny)}: ช่อง (i, j) อยู่ที่ z = z0 + i*cell, y = y0 + j*cell; NaN = ไม่มีผิว */
    skinTopField(zLo, zHi, yHalf, cell) {
      const m = this.manifest.meshes.find(q => q.group === 'skin');
      if (!m) return null;
      const nz = Math.round((zHi - zLo) / cell) + 1, ny = Math.round(2 * yHalf / cell) + 1;
      const top = new Float32Array(nz * ny).fill(NaN);
      const d = this.posedData(m), P = d.positions, I = d.indices;
      const put = (x, y, z) => {
        const i = Math.round((z - zLo) / cell), j = Math.round((y + yHalf) / cell);
        if (i < 0 || i >= nz || j < 0 || j >= ny) return;
        const k = i * ny + j;
        if (!(top[k] >= x)) top[k] = x;
      };
      for (let t = 0; t < I.length; t += 3) {
        const a = I[t] * 3, b = I[t + 1] * 3, c = I[t + 2] * 3;
        const e = Math.max(Math.hypot(P[a] - P[b], P[a + 1] - P[b + 1], P[a + 2] - P[b + 2]),
          Math.hypot(P[b] - P[c], P[b + 1] - P[c + 1], P[b + 2] - P[c + 2]),
          Math.hypot(P[c] - P[a], P[c + 1] - P[a + 1], P[c + 2] - P[a + 2]));
        const n = clamp(Math.ceil(e / (cell * 0.7)), 1, 14);   // สามเหลี่ยมใหญ่: สุ่มจุดภายในด้วย (กันช่องว่างบนขาที่เมชหยาบ)
        for (let u = 0; u <= n; u++) for (let v = 0; v <= n - u; v++) {
          const w = n - u - v, fu = u / n, fv = v / n, fw = w / n;
          put(P[a] * fw + P[b] * fu + P[c] * fv, P[a + 1] * fw + P[b + 1] * fu + P[c + 1] * fv, P[a + 2] * fw + P[b + 2] * fu + P[c + 2] * fv);
        }
      }
      return {z0: zLo, y0: -yHalf, cell, nz, ny, top};
    }

    /** สร้างเมชของผิว / กระดูก / อวัยวะ: mats = {skin, bone, cart, heart, vessel, liver, stomach, diaphragm, airway, esoph}
     *  คืน {skin: Mesh, bones: Group, organs: Group} (วัสดุที่ไม่ได้ส่งมาใช้ mats.default) */
    build(THREE, mats) {
      const bones = new THREE.Group(), organs = new THREE.Group();
      let skin = null;
      for (const m of this.manifest.meshes) {
        const d = this.posedData(m), g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(d.positions, 3));
        g.setIndex(new THREE.BufferAttribute(d.indices, 1));
        g.computeVertexNormals();
        const mat = mats[m.group] || mats[BONE_GROUPS.includes(m.group) ? 'bone' : 'default'] || mats.default;
        const mesh = new THREE.Mesh(g, mat);
        mesh.name = m.name;
        if (m.group === 'skin') skin = mesh;
        else (BONE_GROUPS.includes(m.group) ? bones : organs).add(mesh);
      }
      const out = {skin, bones, organs};
      if (mats.pants && this.armsOnBed) out.pants = this.buildPants(THREE, mats.pants);          // กางเกง (อยู่ในพิกัดผู้ป่วย เหมือนผิว)
      if (mats.lid && mats.lash && THREE.SphereGeometry) out.face = this.buildFace(THREE, mats.lid, mats.lash);   // เปลือกตาปิด
      return out;
    }

    /** เมชห่อผิวสำหรับยิงรังสี (ซ่อนไว้) */
    buildPick(THREE) {
      const {pos, idx} = this.pickGrid();
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      g.setIndex(idx);
      const mesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial({side: THREE.DoubleSide}));
      mesh.visible = false;
      return mesh;
    }
  }

  Anatomy.SITE = SITE;
  Anatomy.BONE_GROUPS = BONE_GROUPS;
  return Anatomy;
});