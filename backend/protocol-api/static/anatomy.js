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

    /** สร้างเมชของผิว / กระดูก / อวัยวะ: mats = {skin, bone, cart, heart, vessel, liver, stomach, diaphragm, airway, esoph}
     *  คืน {skin: Mesh, bones: Group, organs: Group} (วัสดุที่ไม่ได้ส่งมาใช้ mats.default) */
    build(THREE, mats) {
      const bones = new THREE.Group(), organs = new THREE.Group();
      let skin = null;
      for (const m of this.manifest.meshes) {
        const d = this.meshData(m), g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(d.positions, 3));
        g.setIndex(new THREE.BufferAttribute(d.indices, 1));
        g.computeVertexNormals();
        const mat = mats[m.group] || mats[BONE_GROUPS.includes(m.group) ? 'bone' : 'default'] || mats.default;
        const mesh = new THREE.Mesh(g, mat);
        mesh.name = m.name;
        if (m.group === 'skin') skin = mesh;
        else (BONE_GROUPS.includes(m.group) ? bones : organs).add(mesh);
      }
      return {skin, bones, organs};
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
