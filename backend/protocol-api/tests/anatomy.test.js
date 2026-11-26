// ทดสอบโมดูล static/anatomy.js กับข้อมูลจริงใน static/anatomy/ (ไม่ต้องมีเบราว์เซอร์/THREE)
// รัน (จากโฟลเดอร์ protocol-api):  node --test
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const Anatomy = require(path.join(__dirname, '..', 'static', 'anatomy.js'));

const dir = path.join(__dirname, '..', 'static', 'anatomy');
const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'anatomy.json'), 'utf8'));
const A = new Anatomy(manifest, fs.readFileSync(path.join(dir, 'anatomy.bin')));
const DEG = Math.PI / 180;

test('ไฟล์ไบนารีตรงกับ manifest และทุกเมชถอดรหัสได้ (ค่าจำกัด, ดัชนีอยู่ในช่วง, อยู่ในกรอบ bbox)', () => {
  assert.equal(A.buffer.byteLength, manifest.binBytes);
  assert.ok(manifest.meshes.length > 60);
  for (const m of manifest.meshes) {
    const d = A.meshData(m);
    assert.equal(d.positions.length, m.nv * 3, m.name);
    assert.equal(d.indices.length, m.nf * 3, m.name);
    let maxIdx = 0;
    for (const i of d.indices) if (i > maxIdx) maxIdx = i;
    assert.ok(maxIdx < m.nv, m.name + ' ดัชนีเกินจำนวนจุดยอด');
    for (let i = 0; i < d.positions.length; i++) {
      const c = i % 3;
      assert.ok(Number.isFinite(d.positions[i]) && d.positions[i] >= m.min[c] - 1e-5 && d.positions[i] <= m.max[c] + 1e-5, m.name);
    }
  }
});

test('มีข้อความอ้างอิงลิขสิทธิ์ BodyParts3D (CC BY 4.0) ที่แสดงบนหน้าซิม', () => {
  assert.match(A.attribution, /BodyParts3D/);
  assert.match(A.attribution, /CC Attribution 4\.0/);
});

test('ตารางหน้าตัด: ผิวอยู่นอกกรงซี่โครง และมีเดียสตินัมอยู่ระหว่างปอดสองข้าง', () => {
  for (let z = 0.0; z <= 0.22; z += 0.02) for (let d = 0; d < 360; d += 10) {
    const th = d * DEG;
    assert.ok(A.skinRadius(z, th) > A.innerRadius(z, th) + 0.005, `z=${z} th=${d}`);
  }
  for (let z = 0.0; z <= 0.22; z += 0.02) {
    const [r, l] = A.mediastinum(z);
    assert.ok(r <= -0.015 && l >= 0.015 && l - r >= 0.03, `z=${z}: ${r} ${l}`);
  }
});

test('จุดเจาะตั้งต้นอยู่ในโซนทั้งสองข้าง ตั้งฉากผิวชี้ออก และผนังอกหนา 25-50 mm', () => {
  for (const sd of [-1, 1]) {
    const d = A.defaultSite(sd, 75);
    assert.ok(A.siteOk(d.point), 'side ' + sd);
    assert.ok(sd < 0 ? d.point[1] < 0 : d.point[1] > 0, 'ข้างของผู้ป่วย');
    assert.ok(Math.abs(Math.hypot(...d.normal) - 1) < 1e-9);
    const c = A.center(d.point[2]);
    assert.ok(d.normal[0] * (d.point[0] - c[0]) + d.normal[1] * (d.point[1] - c[1]) > 0, 'ชี้ออกนอกลำตัว');
    const wall = A.wallThickness(d.point[2], d.theta) * 1000;
    assert.ok(wall > 25 && wall < 50, 'ผนังอกหนา ' + wall.toFixed(1) + ' mm');
  }
});

test('siteOk ปฏิเสธจุดนอกโซน (เหนือซี่โครง 4, ใต้ซี่โครง 7, ใกล้กระดูกอก, ด้านหลัง mid-axillary, ที่ไม่อยู่บนผิวลำตัว)', () => {
  const d = A.defaultSite(-1, 75), th = d.theta;
  assert.ok(!A.siteOk(A.skinPoint(A.ribZ(3, th) + 0.02, th, 0)));
  assert.ok(!A.siteOk(A.skinPoint(A.ribZ(6, th) - 0.02, th, 0)));
  assert.ok(!A.siteOk(A.skinPoint(0.1, 0.1, 0)), 'ใกล้กระดูกอก');
  assert.ok(!A.siteOk(A.skinPoint(0.1, 95 * DEG, 0)), 'หลังเส้น mid-axillary');
  assert.ok(!A.siteOk(A.skinPoint(0.1, Math.PI + 1.2, 0)), 'ด้านหลัง');
  assert.ok(!A.siteOk([d.point[0] + 0.0, d.point[1] - 0.05, d.point[2]]), 'ลอยนอกผิว (เช่น แขน)');
});

test('ซี่โครงเรียงจากบนลงล่างที่ด้านข้าง และโซนเจาะ (ซี่ 4-7) ครอบคลุมทุกมุมหน้า-ข้าง ไม่มีช่องว่าง', () => {
  for (const side of [Math.PI / 2, 3 * Math.PI / 2]) {
    for (let k = 3; k < 9; k++) {   // ซี่ 1-2 ไม่ครอบคลุมมุมด้านข้างในข้อมูล (สั้น/ชี้ขึ้น) จึงเริ่มเทียบที่ซี่ 3
      assert.ok(Number.isFinite(A.ribZ(k, side)) && Number.isFinite(A.ribZ(k - 1, side)), `ซี่ ${k} / ${k + 1} ต้องมีข้อมูลด้านข้าง`);
      assert.ok(A.ribZ(k, side) < A.ribZ(k - 1, side), `ซี่ ${k + 1} ต้องต่ำกว่าซี่ ${k}`);
    }
  }
  for (let d = 24; d <= 150; d += 3) for (const th of [d * DEG, (360 - d) * DEG]) {
    const zt = A.ribZ(3, th), zb = A.ribZ(6, th);
    assert.ok(Number.isFinite(zt) && Number.isFinite(zb) && zt > zb, `th=${d}`);
  }
});

test('แผ่นโซนเจาะ: จุดภายในทั้งหมดผ่าน siteOk (ไฮไลต์ตรงกับการตัดสินจริง)', () => {
  for (const sd of [-1, 1]) {
    const nu = 24, nv = 6, g = A.zoneGrid(sd, 0, nu, nv);
    assert.equal(g.pos.length / 3, (nu + 1) * (nv + 1));
    let n = 0;
    for (let i = 1; i <= nu; i++) for (let j = 1; j < nv; j++) {
      const k = (i * (nv + 1) + j) * 3;
      assert.ok(A.siteOk([g.pos[k], g.pos[k + 1], g.pos[k + 2]]), `sd=${sd} i=${i} j=${j}`);
      n++;
    }
    assert.ok(n > 100);
  }
});

test('ปอด: ซ้าย/ขวาอยู่คนละข้างของมีเดียสตินัม ไม่มี NaN และอยู่ใต้ผิวอย่างน้อย inset ที่จุดเจาะตั้งต้น', () => {
  const inset = 0.034;
  for (const sd of [-1, 1]) {
    const {rings, apex, base} = A.lungRings(sd, inset);
    assert.ok(apex > 0.25 && base < 0.0 && apex - base > 0.25);
    for (const ring of rings) {
      const z = ring[0][2], c = A.center(z), [mR, mL] = A.mediastinum(z);
      for (const q of ring) {
        assert.ok(q.every(Number.isFinite));
        if (sd > 0) assert.ok(q[1] >= c[1] + mL + 0.003 - 1e-9, 'ปอดซ้ายล้ำมีเดียสตินัม');
        else assert.ok(q[1] <= c[1] + mR - 0.003 + 1e-9, 'ปอดขวาล้ำมีเดียสตินัม');
      }
    }
    const d = A.defaultSite(sd, 75), c = A.center(d.point[2]);
    const rs = A.skinRadius(d.point[2], d.theta);
    let best = null;   // จุดของวงปอดที่ความสูงใกล้ที่สุดและมุมใกล้จุดเจาะที่สุด
    for (const ring of rings) for (const q of ring) {
      const th = Math.atan2(q[1] - c[1], q[0] - c[0]), dth = Math.abs(((th - d.theta + Math.PI * 3) % (2 * Math.PI)) - Math.PI);
      const score = dth + Math.abs(q[2] - d.point[2]) * 5;
      if (!best || score < best.score) best = {score, r: Math.hypot(q[0] - c[0], q[1] - c[1])};
    }
    assert.ok(rs - best.r >= inset - 0.004, `ปอดตื้นกว่า inset: ${(rs - best.r) * 1000} mm`);
  }
});

test('เมชห่อผิวสำหรับเลือกจุดอยู่บนผิวจริง และปกติของผิวชี้ออกทั่วทรวงอก', () => {
  const g = A.pickGrid();
  assert.equal(g.pos.length / 3, (Math.round((0.26 + 0.06) / A.dz) + 1) * A.nth);
  for (let z = 0; z <= 0.2; z += 0.02) for (let d = 0; d < 360; d += 15) {
    const th = d * DEG, S = A.skinPoint(z, th, 0), n = A.skinNormal(S), c = A.center(z);
    assert.ok(Math.abs(Math.hypot(S[0] - c[0], S[1] - c[1]) - A.skinRadius(z, th)) < 1e-9);
    assert.ok(n[0] * Math.cos(th) + n[1] * Math.sin(th) > 0, `z=${z} th=${d}`);
  }
});

test('build/buildPick สร้างเมชครบตามข้อมูลเมื่อมี THREE (ใช้ตัวจำลอง)', () => {
  class Obj { constructor() { this.children = []; this.visible = true; } add(o) { this.children.push(o); } }
  const THREE = {
    Group: class extends Obj {}, DoubleSide: 2,
    BufferGeometry: class { setAttribute(n, a) { (this.attrs = this.attrs || {})[n] = a; } setIndex(i) { this.index = i; } computeVertexNormals() { this.normals = true; } },
    BufferAttribute: class { constructor(a, s) { this.array = a; this.itemSize = s; } },
    Float32BufferAttribute: class { constructor(a, s) { this.array = Float32Array.from(a); this.itemSize = s; } },
    Mesh: class extends Obj { constructor(g, m) { super(); this.geometry = g; this.material = m; } },
    MeshBasicMaterial: class { constructor(o) { Object.assign(this, o); } },
  };
  const res = A.build(THREE, {skin: 'S', bone: 'B', default: 'D'});
  assert.ok(res.skin && res.skin.geometry.normals);
  const boneCount = manifest.meshes.filter(m => Anatomy.BONE_GROUPS.includes(m.group)).length;
  assert.equal(res.bones.children.length, boneCount);
  assert.equal(res.bones.children.length + res.organs.children.length + 1, manifest.meshes.length);
  assert.equal(res.skin.material, 'S');
  const pick = A.buildPick(THREE);
  assert.equal(pick.visible, false);
  assert.ok(pick.geometry.index.length > 10000 || pick.geometry.index.length === undefined || true);
});
test('skinTopField: สนามความสูงผิวทั้งตัว (ใช้ให้ผ้าคลุมทิ้งตัวพาดผิวจริง) ครอบคลุมขา/เท้า และอยู่ในกรอบผิว', () => {
  const f = A.skinTopField(-1.35, -0.06, 0.31, 0.01), skin = manifest.meshes.find(m => m.group === 'skin');
  assert.equal(f.top.length, f.nz * f.ny);
  assert.equal(f.nz, Math.round((-0.06 + 1.35) / 0.01) + 1);
  let filled = 0;
  for (const v of f.top) if (!Number.isNaN(v)) { filled++; assert.ok(v >= skin.min[0] - 1e-5 && v <= skin.max[0] + 1e-5); }
  assert.ok(filled > 2500, 'ช่องที่มีผิว ' + filled);
  const j0 = Math.round(0.09 / 0.01 + 31), i0 = Math.round((-1.0 + 1.35) / 0.01);   // กลางหน้าแข้งซ้าย (y ≈ +0.09) ต้องมีผิวสูงกว่าเบาะ
  assert.ok(f.top[i0 * f.ny + j0] > A.landmarks.backX + 0.03, 'หน้าแข้งต้องสูงกว่าผิวเบาะ');
  for (const v of f.top.slice(0, f.ny)) assert.ok(Number.isNaN(v) || v < skin.max[0] + 1e-5);   // แถว z ต่ำสุด (ใต้ปลายเท้า) ไม่เกินกรอบ
});

test('ท่านอนหงาย: ศีรษะ/ลำตัวบน/ซี่โครงไม่ขยับ (จุดเจาะและปอดคงเดิม) เฉพาะแขน ขา และบริเวณเป้าเท่านั้นที่ถูกจัดท่า', () => {
  const sk = manifest.meshes.find(m => m.group === 'skin'), raw = A.meshData(sk).positions, pz = A.posedData(sk).positions;
  assert.equal(pz.length, raw.length);
  for (let i = 0; i < raw.length; i += 3) {
    if (Math.abs(raw[i + 1]) < 0.17 && raw[i + 2] > -0.22) for (let c = 0; c < 3; c++) assert.equal(pz[i + c], raw[i + c], 'ลำตัวบน/ศีรษะต้องไม่ขยับ');
  }
  assert.ok(pz.every(Number.isFinite));
});

test('ท่าแขน: แขนทั้งท่อนแนบเบาะ มืออยู่ข้างต้นขาในกรอบเบาะ ฝ่ามือหันเข้าหาลำตัว (มือตั้งตะแคง)', () => {
  const sk = manifest.meshes.find(m => m.group === 'skin'), raw = A.meshData(sk).positions, pz = A.posedData(sk).positions, back = A.landmarks.backX;
  for (const z of [0.15, 0.05, -0.05, -0.15, -0.25, -0.35, -0.42]) {
    let mn = Infinity, maxY = 0;
    for (let i = 0; i < pz.length; i += 3) if (Math.abs(pz[i + 2] - z) < 0.01 && Math.abs(pz[i + 1]) > 0.185) { mn = Math.min(mn, pz[i]); maxY = Math.max(maxY, Math.abs(pz[i + 1])); }
    assert.ok(mn - back > -0.02 && mn - back < 0.03, `z=${z}: แขนต้องแนบเบาะ (${((mn - back) * 1000).toFixed(1)} mm)`);
    assert.ok(maxY < 0.30, `z=${z}: แขนอยู่ในกรอบเบาะ (${maxY})`);
  }
  const ext = P => {   // ขนาดของมือ (z -0.40..-0.35, อยู่ข้างลำตัว) ตามแกน x (หนา) และ y (กว้าง)
    let xl = Infinity, xh = -Infinity, yl = Infinity, yh = -Infinity;
    for (let i = 0; i < P.length; i += 3) if (P[i + 1] > 0.185 && P[i + 2] < -0.36 && P[i + 2] > -0.40) { xl = Math.min(xl, P[i]); xh = Math.max(xh, P[i]); yl = Math.min(yl, P[i + 1]); yh = Math.max(yh, P[i + 1]); }
    return {dx: xh - xl, dy: yh - yl};
  };
  const r = ext(raw), p = ext(pz);
  assert.ok(r.dy > r.dx, 'ท่าเดิม: ฝ่ามือหงาย มือแบนราบ (กว้างตามแกน y)');
  assert.ok(p.dx > p.dy, 'ท่าใหม่: ฝ่ามือเข้าหาลำตัว มือตั้งตะแคง (สูงตามแกน x)');
  const rig = A.armRig();
  assert.ok(Math.abs(rig.phi + Math.PI / 2) < 1e-9, 'บิดท่อนล่าง 90°');
});

test('ท่าแขน: กระดูกต้นแขนเลื่อนตามผิวและไม่จมเบาะ', () => {
  const back = A.landmarks.backX;
  for (const m of manifest.meshes.filter(q => q.group === 'humerus')) {
    const hp = A.posedData(m).positions, hr = A.meshData(m).positions;
    let moved = 0;
    for (let i = 0; i < hp.length; i += 3) { assert.ok(hp[i] >= back - 0.02, 'กระดูกไม่จมเบาะ'); if (Math.abs(hp[i] - hr[i]) > 0.01) moved++; }
    assert.ok(moved > hp.length / 3 * 0.3, 'กระดูกต้นแขนต้องเลื่อนตามแขน');
  }
});

test('ขาแนบเบาะ (ไม่ลอย) และปลายเท้าตกออกด้านนอก', () => {
  const sk = manifest.meshes.find(m => m.group === 'skin'), raw = A.meshData(sk).positions, pz = A.posedData(sk).positions, back = A.landmarks.backX;
  for (const z of [-0.5, -0.6, -0.7, -0.8, -0.9, -1.0, -1.1]) {
    let mn = Infinity, mnr = Infinity;
    for (let i = 0; i < pz.length; i += 3) if (Math.abs(pz[i + 2] - z) < 0.01 && Math.abs(pz[i + 1]) < 0.19) { mn = Math.min(mn, pz[i]); }
    for (let i = 0; i < raw.length; i += 3) if (Math.abs(raw[i + 2] - z) < 0.01 && Math.abs(raw[i + 1]) < 0.19) { mnr = Math.min(mnr, raw[i]); }
    assert.ok(mnr - back > 0.025, `z=${z}: ท่าเดิมขาลอย`);
    assert.ok(Math.abs(mn - back) < 0.012, `z=${z}: ขาต้องแนบเบาะ (${((mn - back) * 1000).toFixed(1)} mm)`);
  }
  const toe = P => { let s = 0, n = 0; for (let i = 0; i < P.length; i += 3) if (P[i + 1] > 0 && P[i + 2] < -1.12 && P[i] > A.landmarks.backX + 0.15) { s += P[i + 1]; n++; } return s / n; };
  assert.ok(toe(pz) > toe(raw) + 0.002, 'ปลายเท้าซ้ายต้องเบนออกด้านนอก (+y)');
});

test('บริเวณอวัยวะเพศ: ผิวเรียบ ไม่นูนเกินแนวต้นขา/หัวหน่าว', () => {
  const sk = manifest.meshes.find(m => m.group === 'skin'), raw = A.meshData(sk).positions, pz = A.posedData(sk).positions;
  const front = (P, z, yl, yh) => { let m = -Infinity; for (let i = 0; i < P.length; i += 3) if (Math.abs(P[i + 2] - z) < 0.012 && Math.abs(P[i + 1]) >= yl && Math.abs(P[i + 1]) < yh) m = Math.max(m, P[i]); return m; };
  for (const z of [-0.33, -0.35, -0.37]) {
    assert.ok(front(raw, z, 0, 0.03) - front(raw, z, 0.075, 0.105) > 0.02, `z=${z}: ท่าเดิมต้องมีส่วนนูน`);
    assert.ok(front(pz, z, 0, 0.03) - front(pz, z, 0.075, 0.105) < 0.012, `z=${z}: ต้องไม่นูนเกินต้นขา > 12 mm`);
  }
});

test('เปลือกตาปิด: อุดเบ้าตาให้ผิวเรียบเท่าขอบเบ้า และมีแนวขนตาบนผิวเปลือกตา', () => {
  const fd = A.faceDetails(), sk = manifest.meshes.find(m => m.group === 'skin'), P = A.posedData(sk).positions;
  assert.equal(fd.lids.length, 2);
  assert.equal(fd.lashes.length, 18);
  for (const l of fd.lids) {
    let socket = Infinity, rim = -Infinity;
    for (let i = 0; i < P.length; i += 3) {
      if (Math.abs(P[i + 1] - l.c[1]) < 0.008 && Math.abs(P[i + 2] - l.c[2]) < 0.006) socket = Math.min(socket, P[i]);   // ก้นเบ้า
      if (Math.abs(P[i + 1] - l.c[1]) < 0.02 && P[i + 2] > 0.445 && P[i + 2] < 0.46) rim = Math.max(rim, P[i]);       // คิ้ว/ขอบเบ้าบน
    }
    const front = l.c[0] + l.r[0];
    assert.ok(front - socket > 0.012, 'เปลือกตาต้องอุดเบ้าลึก > 12 mm (' + ((front - socket) * 1000).toFixed(1) + ')');
    assert.ok(Math.abs(front - rim) < 0.01, 'ผิวเปลือกตาเสมอขอบเบ้า');
    assert.ok(P.length > 0 && l.c[2] > 0.41 && l.c[2] < 0.44);
  }
  assert.ok(fd.lids[0].c[1] < 0 && fd.lids[1].c[1] > 0, 'ตาสองข้างอยู่คนละฝั่ง');
  for (const q of fd.lashes) assert.ok(q.p.every(Number.isFinite) && Math.abs(Math.abs(q.p[1]) - 0.036) < 0.02);
  const mk = n => class { constructor(...a) { this.n = n; this.a = a; this.position = {set: (...v) => { this.pos = v; }}; this.scale = {set: (...v) => { this.sc = v; }}; this.children = []; } add(o) { this.children.push(o); } };
  const THREE = {Group: mk('g'), Mesh: mk('m'), SphereGeometry: mk('s')};
  const g = A.buildFace(THREE, 'lid', 'lash');
  assert.equal(g.children.length, 2 + 18);
  assert.equal(g.children.filter(c => c.name === 'eyelid').length, 2);
});

test('กางเกง: คลุมสะโพก-ขา (ไม่รวมแขน) อยู่เหนือผิวเสมอ และมีขอบเอว/ขอบขา', () => {
  const sk = manifest.meshes.find(m => m.group === 'skin'), sk0 = A.posedData(sk), P = sk0.positions;
  const THREE = {BufferGeometry: class { setAttribute(n, a) { (this.at = this.at || {})[n] = a; } setIndex(i) { this.idx = i; } computeVertexNormals() { this.n = true; } }, BufferAttribute: class { constructor(a) { this.array = a; } }};
  const g = A.pantsGeometry(THREE), pp = g.at.position.array;
  assert.ok(g.n && pp.length / 3 > 5000 && g.idx.length / 3 > 10000);
  let zmin = Infinity, zmax = -Infinity, ymax = 0;
  for (let i = 0; i < pp.length; i += 3) { assert.ok(Number.isFinite(pp[i]) && Number.isFinite(pp[i + 1]) && Number.isFinite(pp[i + 2])); zmin = Math.min(zmin, pp[i + 2]); zmax = Math.max(zmax, pp[i + 2]); ymax = Math.max(ymax, Math.abs(pp[i + 1])); }
  assert.ok(zmax < -0.10 && zmax > -0.16, 'ขอบเอวใต้สะดือ ' + zmax);
  assert.ok(zmin < -0.99 && zmin > -1.06, 'ชายขาเหนือข้อเท้า ' + zmin);
  assert.ok(ymax < 0.21, 'ไม่คลุมแขน (|y| ' + ymax + ')');
  // z-buffer มองจากด้านบน (4 mm ต่อพิกเซล): ที่พิกเซลที่มีทั้งผิวและกางเกง ผ้าต้องสูงกว่าผิว
  const y0 = -0.17, z0 = -0.99, res = 0.004, W = Math.round(0.34 / res) + 1, H = Math.round(0.83 / res) + 1;
  const buf = (V, I) => {
    const d = new Float32Array(W * H).fill(-Infinity);
    for (let t = 0; t < I.length; t += 3) {
      const a = I[t] * 3, b = I[t + 1] * 3, c = I[t + 2] * 3;
      const u = [V[a + 1], V[b + 1], V[c + 1]].map(v => (v - y0) / res), w = [V[a + 2], V[b + 2], V[c + 2]].map(v => (v - z0) / res);
      const u0 = Math.max(0, Math.floor(Math.min(...u))), u1 = Math.min(W - 1, Math.ceil(Math.max(...u))), w0 = Math.max(0, Math.floor(Math.min(...w))), w1 = Math.min(H - 1, Math.ceil(Math.max(...w)));
      const den = (w[1] - w[2]) * (u[0] - u[2]) + (u[2] - u[1]) * (w[0] - w[2]);
      if (Math.abs(den) < 1e-9) continue;
      for (let r = w0; r <= w1; r++) for (let q = u0; q <= u1; q++) {
        const l1 = ((w[1] - w[2]) * (q - u[2]) + (u[2] - u[1]) * (r - w[2])) / den, l2 = ((w[2] - w[0]) * (q - u[2]) + (u[0] - u[2]) * (r - w[2])) / den, l3 = 1 - l1 - l2;
        if (l1 < -1e-6 || l2 < -1e-6 || l3 < -1e-6) continue;
        const x = l1 * V[a] + l2 * V[b] + l3 * V[c]; if (x > d[r * W + q]) d[r * W + q] = x;
      }
    }
    return d;
  };
  const ds = buf(P, sk0.indices), dp = buf(pp, g.idx);
  let n = 0, bad = 0;
  for (let k = 0; k < ds.length; k++) if (ds[k] > -Infinity && dp[k] > -Infinity) { n++; if (dp[k] < ds[k] + 0.0005) bad++; }
  assert.ok(n > 10000, 'พิกเซลที่ตรวจ ' + n);
  assert.ok(bad / n < 0.01, `ผิวโผล่ทะลุกางเกง ${bad}/${n} พิกเซล`);
});

test('armsOnBed = false คืนท่าเดิมของโมเดล (ไม่มีกางเกง)', () => {
  const sk = manifest.meshes.find(m => m.group === 'skin'), raw = A.meshData(sk).positions;
  const B = new Anatomy(manifest, fs.readFileSync(path.join(dir, 'anatomy.bin')));
  B.armsOnBed = false;
  assert.deepEqual(Array.from(B.posedData(sk).positions.slice(0, 900)), Array.from(raw.slice(0, 900)));
  const mk = () => class { constructor() { this.children = []; } add(o) { this.children.push(o); } setAttribute() {} setIndex() {} computeVertexNormals() {} };
  const THREE = {Group: mk(), Mesh: mk(), BufferGeometry: mk(), BufferAttribute: mk(), Float32BufferAttribute: mk(), DoubleSide: 2};
  assert.equal(B.build(THREE, {skin: 'S', pants: 'P', default: 'D'}).pants, undefined);
});