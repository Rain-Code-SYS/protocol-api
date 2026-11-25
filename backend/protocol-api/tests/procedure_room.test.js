// ทดสอบผังห้องทำหัตถการ (static/procedure_room.js): ขนาด ตำแหน่ง และการสร้างเมชด้วย THREE จำลอง
// รัน (จากโฟลเดอร์ protocol-api):  node --test
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const ProcedureRoom = require(path.join(__dirname, '..', 'static', 'procedure_room.js'));
const Anatomy = require(path.join(__dirname, '..', 'static', 'anatomy.js'));

const man = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'static', 'anatomy', 'anatomy.json'), 'utf8'));
const L = ProcedureRoom.layout({backX: man.landmarks.backX, env: man.env});

const bounds = it => {
  if (it.kind === 'box' || it.kind === 'shell') return it.size.map((s, i) => [it.pos[i] - s / 2, it.pos[i] + s / 2]);
  if (it.kind === 'cyl') {
    const half = {x: [it.h / 2, it.r, it.r], y: [it.r, it.h / 2, it.r], z: [it.r, it.r, it.h / 2]}[it.axis];
    return half.map((s, i) => [it.pos[i] - s, it.pos[i] + s]);
  }
  if (it.kind === 'sph') return it.radii.map((s, i) => [it.pos[i] - s, it.pos[i] + s]);
  return null;
};

test('ผังมีชิ้นส่วนครบ ชื่อไม่ซ้ำ และมีของสำคัญของห้องทำหัตถการ', () => {
  const names = L.items.map(i => i.name);
  assert.equal(new Set(names).size, names.length, 'ชื่อซ้ำ');
  assert.ok(L.items.length > 80);
  for (const want of ['table-pad', 'pillow', 'drape', 'lamp-head', 'mayo-tray', 'syringe-20ml', 'antiseptic-bottle', 'iv-pole', 'monitor-screen',
    'counter-top', 'sink-basin', 'door-panel', 'sharps-container', 'biohazard-bin', 'stool-seat', 'floor', 'ceiling', 'room-shell']) assert.ok(names.includes(want), want);
});

test('เตียง: ผิวเบาะอยู่ที่ระดับหลังผู้ป่วย ความสูงเตียงอยู่ในช่วงใช้งานจริง และพื้นอยู่ใต้เตียง', () => {
  const pad = L.items.find(i => i.name === 'table-pad');
  assert.ok(Math.abs(pad.pos[2] + pad.size[2] / 2 - man.landmarks.backX) < 1e-9);
  const height = L.padTop - L.floorZ;
  assert.ok(height > 0.75 && height < 1.0, 'ความสูงเตียง ' + height);
  assert.ok(Math.abs(L.ceilZ - L.floorZ - 2.9) < 1e-9);
  assert.ok(pad.pos[0] - pad.size[0] / 2 < -0.55 && pad.pos[0] + pad.size[0] / 2 > 1.2, 'เตียงยาวครอบศีรษะ-เท้าผู้ป่วย');
});

test('ทุกชิ้นอยู่ในห้อง (ไม่ทะลุพื้น เพดาน ผนัง)', () => {
  const R = L.room, eps = 0.02;
  for (const it of L.items) {
    if (it.name === 'room-shell' || it.name === 'floor' || it.name === 'ceiling') continue;
    const b = bounds(it);
    if (!b) continue;
    assert.ok(b[0][0] >= R.x0 - eps && b[0][1] <= R.x1 + eps, it.name + ' เกินผนัง X');
    assert.ok(b[1][0] >= R.y0 - eps && b[1][1] <= R.y1 + eps, it.name + ' เกินผนัง Y');
    assert.ok(b[2][0] >= L.floorZ - 0.01 && b[2][1] <= L.ceilZ + 0.01, it.name + ' ทะลุพื้น/เพดาน');
  }
});

test('ผ้าคลุมครอบขาจริง: เริ่มใต้ซี่โครงถึงเท้า กว้างกว่าขา และสูงจากเตียงสมเหตุผล', () => {
  const d = L.items.find(i => i.kind === 'drape');
  assert.equal(d.xs.length, man.env.n);
  for (let i = 1; i < d.xs.length; i++) assert.ok(d.xs[i] < d.xs[i - 1], 'เรียงจากเท้าไปเอว');
  assert.ok(d.xs[0] > 1.1 && d.xs[d.xs.length - 1] < 0.1 && d.xs[d.xs.length - 1] > -0.1);
  for (let i = 0; i < d.xs.length; i++) {
    assert.ok(d.halfWidth[i] > 0.05 && d.halfWidth[i] < 0.30, 'ความกว้างผ้า ' + d.halfWidth[i]);
    assert.ok(d.top[i] > d.bottom, 'ผ้าต้องสูงกว่าผิวเบาะ');
    assert.ok(d.top[i] - d.bottom < 0.45);
  }
  assert.equal(d.bottom, man.landmarks.backX);
});

test('ไม่มี env ก็สร้างผังได้ (ไม่มีผ้าคลุม) และหมอนมีความหนาขั้นต่ำ', () => {
  const L2 = ProcedureRoom.layout({});
  assert.ok(!L2.items.some(i => i.kind === 'drape'));
  assert.ok(L2.items.find(i => i.name === 'pillow').radii[2] >= 0.025);
  assert.ok(Math.abs(L2.padTop - ProcedureRoom.DEFAULTS.defaultBackX) < 1e-9);
});

test('โคมผ่าตัดอยู่เหนือหน้าอก ชี้ลงมาที่ตัวผู้ป่วย และไม่ชนระยะกล้องมาตรฐาน', () => {
  assert.ok(L.lamp.pos[2] > L.padTop + 0.8, 'โคมสูงจากเตียงเกิน 0.8 m');
  assert.ok(L.lamp.pos[2] < L.ceilZ);
  assert.ok(Math.abs(L.lamp.target[1]) < 0.2 && L.lamp.target[0] > -0.4 && L.lamp.target[0] < 0.3);
});

test('แท่งเครื่องมืออยู่ด้านขวาของผู้ป่วย (-Y) ใกล้ระดับเตียง และอุปกรณ์อยู่บนถาด', () => {
  const tray = L.items.find(i => i.name === 'mayo-tray');
  assert.ok(tray.pos[1] < -0.6 && Math.abs(tray.pos[0]) < 0.6);
  assert.ok(Math.abs(tray.pos[2] - L.padTop) < 0.3);
  for (const n of ['gauze-1', 'syringe-10ml', 'antiseptic-bottle', 'lidocaine-vial', 'kidney-dish']) {
    const it = L.items.find(i => i.name === n), b = bounds(it);
    assert.ok(b[2][0] >= tray.pos[2] && b[2][0] < tray.pos[2] + 0.1, n + ' ต้องวางบนถาด');
    assert.ok(Math.abs(it.pos[0] - tray.pos[0]) <= tray.size[0] / 2 && Math.abs(it.pos[1] - tray.pos[1]) <= tray.size[1] / 2, n + ' อยู่ในขอบถาด');
  }
});

test('build: สร้างเมชครบทุกชิ้นด้วย THREE จำลอง (กล่อง/กระบอก/ทรงรี/ผ้าคลุม/เงา/จอ) พร้อมแสง', () => {
  class Obj { constructor() { this.children = []; this.position = {set: (x, y, z) => { this.pos = [x, y, z]; }}; this.rotation = {x: 0, y: 0, z: 0, set: (...a) => { this.rot = a; }}; this.scale = {set: (...a) => { this.sc = a; }}; } add(o) { this.children.push(o); } }
  const count = {};
  const geo = k => class { constructor(...a) { count[k] = (count[k] || 0) + 1; this.args = a; } setAttribute() {} setIndex() {} computeVertexNormals() {} };
  const THREE = {
    Group: class extends Obj {}, Mesh: class extends Obj { constructor(g, m) { super(); this.geometry = g; this.material = m; } },
    BoxGeometry: geo('box'), CylinderGeometry: geo('cyl'), SphereGeometry: geo('sph'), PlaneGeometry: geo('plane'), BufferGeometry: geo('buf'),
    Float32BufferAttribute: class {}, CanvasTexture: class {},
    MeshPhongMaterial: class { constructor(p) { Object.assign(this, p); } }, MeshBasicMaterial: class { constructor(p) { Object.assign(this, p); } },
    SpotLight: class extends Obj { constructor() { super(); this.target = new Obj(); } }, HemisphereLight: class extends Obj {},
    BackSide: 1, DoubleSide: 2,
  };
  const g = ProcedureRoom.build(THREE, L, {});
  const meshes = g.children.filter(c => c.geometry);
  assert.equal(meshes.length, L.items.length);
  assert.equal(g.children.filter(c => c.target).length, 3);          // โคมผ่าตัด + ไฟเพดาน 2 ดวง (มีเป้าหมายและเงา)
  assert.ok(count.box >= 60 && count.cyl >= 26 && count.sph >= 2 && count.plane >= 7);   // box รวมเปลือกห้อง 60, plane = เงา 5 + จอ + นาฬิกา
  const shell = meshes.find(m => m.name === 'room-shell');
  assert.equal(shell.material.side, THREE.BackSide);                // เห็นเฉพาะด้านในห้อง (มองจากนอกห้องทะลุได้)
  const drape = meshes.find(m => m.name === 'drape');
  assert.equal(drape.material.side, THREE.DoubleSide);
  const clock = meshes.find(m => m.name === 'wall-clock'), mon = meshes.find(m => m.name === 'monitor-screen');
  assert.deepEqual(mon.rot, [Math.PI / 2, 0, Math.PI / 2]);
  assert.deepEqual(clock.rot, [Math.PI / 2, 0, -Math.PI / 2]);
  assert.equal(meshes.find(m => m.name === 'table-column').rotation.x, Math.PI / 2);          // กระบอกแนวตั้ง (แกน Z ของฉาก)
  assert.equal(meshes.find(m => m.name === 'table-rail-r').rotation.z, Math.PI / 2);          // รางข้างเตียงแนวนอนตามแกน X
});

// ---------- ผ้าคลุมทิ้งตัวพาดผิวจริง ----------
const dirA = path.join(__dirname, '..', 'static', 'anatomy');
const A = new Anatomy(man, fs.readFileSync(path.join(dirA, 'anatomy.bin')));
const FIELD = A.skinTopField(-1.35, -0.06, 0.31, 0.01);
const LC = ProcedureRoom.layout({backX: man.landmarks.backX, env: man.env, skinField: FIELD});
const DR = LC.items.find(i => i.kind === 'drape');
const SF = ProcedureRoom.drapeSurface(DR);
const X0 = SF.pos[SF.endRows * SF.nv * 3], X1 = SF.pos[(SF.endRows + 1) * SF.nv * 3];   // X ของผ้า = -z ผู้ป่วย: แถวแรกของแผ่นบนเตียงคือปลายเท้า
const K = 8, NV = SF.nv, NY = NV - 2 * K, E0 = SF.endRows, NX = SF.nu - E0;   // E0 = แถวชายผ้าห้อยปลายเตียง (ก่อนแถวผ้าบนเตียง)

test('ผ้า (มีผิวจริง): ยังมีข้อมูลโปรไฟล์เดิมครบ และมีสนามความสูงที่ใช้สร้างเมช', () => {
  assert.ok(DR.cloth && DR.cloth.h.length === FIELD.nz * FIELD.ny);
  assert.equal(DR.xs.length, man.env.n);
  assert.equal(DR.bottom, man.landmarks.backX);
  assert.ok(SF.pos.every(Number.isFinite) && SF.uv.every(Number.isFinite));
  assert.equal(SF.pos.length / 3, SF.nu * SF.nv);
  assert.ok(Math.max(...SF.idx) < SF.pos.length / 3);
});

test('ผ้าอยู่เหนือผิวทุกจุดของร่างกายจริง (ขา แขน เท้า สะโพก): ไม่มีส่วนของหุ่นโผล่นอกผ้า', () => {
  const m = man.meshes.find(q => q.group === 'skin'), d = A.meshData(m), P = d.positions, I = d.indices;
  const yE = SF.pos[(E0 * NV + K + NY - 1) * 3 + 1];
  const clothZ = (z, y) => {                                                 // bilinear บนแถวบนของกริดผ้า
    const fi = (-z - X0) / (X1 - X0), j = (y + yE) / (2 * yE) * (NY - 1);
    const i0 = Math.min(NX - 2, Math.max(0, Math.floor(fi))), fu = fi - i0, j0 = Math.min(NY - 2, Math.max(0, Math.floor(j))), fv = j - j0;
    const at = (i, jj) => SF.pos[((E0 + i) * NV + K + jj) * 3 + 2];
    return at(i0, j0) * (1 - fu) * (1 - fv) + at(i0 + 1, j0) * fu * (1 - fv) + at(i0, j0 + 1) * (1 - fu) * fv + at(i0 + 1, j0 + 1) * fu * fv;
  };
  let n = 0, worst = Infinity;
  for (let t = 0; t < I.length; t += 3) {
    const a = I[t] * 3, b = I[t + 1] * 3, c = I[t + 2] * 3;
    for (const [u, v, w] of [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1 / 3, 1 / 3, 1 / 3], [0.5, 0.5, 0], [0, 0.5, 0.5], [0.5, 0, 0.5]]) {
      const x = P[a] * u + P[b] * v + P[c] * w, y = P[a + 1] * u + P[b + 1] * v + P[c + 1] * w, z = P[a + 2] * u + P[b + 2] * v + P[c + 2] * w;
      if (z < -1.30 || z > -0.075 || Math.abs(y) > 0.30) continue;          // เฉพาะช่วงที่ผ้าคลุม (ไม่รวมตัวส่วนบนและด้านนอกขอบเตียง)
      n++; worst = Math.min(worst, clothZ(z, y) - x);
    }
  }
  assert.ok(n > 20000, 'ตัวอย่างผิวที่ตรวจ ' + n);
  assert.ok(worst > 0.002, 'ผ้าต่ำกว่าผิวที่สุด ' + (worst * 1000).toFixed(1) + ' mm');
});

test('ผ้ามีรอยย่น (ผิวไม่เรียบ) แต่ไม่ลึกเกินจริง และราบกับเบาะที่ส่วนปลาย', () => {
  let rough = 0, cnt = 0, maxZ = -Infinity;
  for (let i = 2; i < NX - 2; i++) for (let j = 2; j < NY - 2; j++) {
    const z = (di, dj) => SF.pos[((E0 + i + di) * NV + K + j + dj) * 3 + 2];
    rough += Math.abs(z(1, 0) + z(-1, 0) + z(0, 1) + z(0, -1) - 4 * z(0, 0)); cnt++;   // ค่าโค้งเฉพาะที่ (laplacian)
    maxZ = Math.max(maxZ, z(0, 0));
  }
  assert.ok(rough / cnt > 0.0004, 'ผ้าเรียบเกินไป: ' + rough / cnt);
  assert.ok(rough / cnt < 0.01, 'ผ้าย่นเกินจริง: ' + rough / cnt);
  assert.ok(maxZ - man.landmarks.backX < 0.33 && maxZ - man.landmarks.backX > 0.1);
  const footZ = SF.pos[(K + (NY >> 1)) * 3 + 2], footX = SF.pos[(K + (NY >> 1)) * 3];   // แถวนอกสุดของชายผ้าปลายเตียง: ห้อยต่ำกว่าเบาะและยื่นพ้นปลายเบาะ
  assert.ok(footZ < man.landmarks.backX - 0.1, 'ปลายผ้ายังสูง ' + (footZ - man.landmarks.backX));
  assert.ok(footX > X0 + 0.02, 'ชายผ้าปลายเตียงต้องยื่นพ้นขอบ');
  for (let r = 0; r < E0; r++) for (let v = 0; v < NV; v++) assert.ok(Number.isFinite(SF.pos[(r * NV + v) * 3 + 2]));
});

test('ชายผ้าห้อยลงข้างเตียงทั้งสองด้าน ต่ำกว่าผิวเบาะและพ้นขอบเบาะ', () => {
  for (const [v, sd] of [[0, -1], [NV - 1, 1]]) {
    for (let i = 0; i < SF.nu; i += 7) {
      const q = (i * NV + v) * 3, y = SF.pos[q + 1], z = SF.pos[q + 2];
      assert.ok(sd * y > ProcedureRoom.DEFAULTS.tableHalfWidth, 'ชายผ้าต้องพ้นขอบเบาะ');
      assert.ok(z < man.landmarks.backX - 0.1, 'ชายผ้าต้องห้อยลงต่ำกว่าเบาะ >10 cm');
    }
  }
});

test('ไม่มี skinField ก็ใช้ผ้ารูปแบบเดิม (ไม่มี cloth) และหน้าตัดไม่ตัดมุมขา', () => {
  const L0 = ProcedureRoom.layout({backX: man.landmarks.backX, env: man.env});
  assert.ok(!L0.items.find(i => i.kind === 'drape').cloth);
});

test('build (มี Standard material): ผ้ามี uv + bump, โคมส่องเงา, ชิ้นโครงสร้างไม่ทิ้งเงา, ชิ้นเฟอร์นิเจอร์ทิ้งและรับเงา', () => {
  class Obj { constructor() { this.children = []; this.position = {set: (x, y, z) => { this.pos = [x, y, z]; }}; this.rotation = {x: 0, y: 0, z: 0, set() {}}; this.scale = {set() {}}; } add(o) { this.children.push(o); } }
  const geo = () => class { constructor() { this.attrs = {}; } setAttribute(n, a) { this.attrs[n] = a; } setIndex() {} computeVertexNormals() {} };
  const light = class extends Obj { constructor() { super(); this.target = new Obj(); this.shadow = {mapSize: {set: (a, b) => { this.shadowSize = [a, b]; }}, camera: {}}; } };
  const mk = n => class { constructor(p) { Object.assign(this, p); this.kind = n; } };
  const THREE = {
    Group: class extends Obj {}, Mesh: class extends Obj { constructor(g, m) { super(); this.geometry = g; this.material = m; } },
    BoxGeometry: geo(), CylinderGeometry: geo(), SphereGeometry: geo(), PlaneGeometry: geo(), BufferGeometry: geo(),
    Float32BufferAttribute: class { constructor(a, s) { this.array = a; this.itemSize = s; } },
    CanvasTexture: class { constructor() { this.repeat = {set: (a, b) => { this.rep = [a, b]; }}; } },
    MeshPhongMaterial: mk('phong'), MeshBasicMaterial: mk('basic'), MeshStandardMaterial: mk('std'),
    SpotLight: light, HemisphereLight: class extends Obj {}, BackSide: 1, DoubleSide: 2, RepeatWrapping: 1000,
  };
  const cv = () => ({width: 0, height: 0, getContext: () => new Proxy({}, {get: (t, k) => (k === 'createRadialGradient' ? () => ({addColorStop() {}}) : () => {}), set: () => true})});
  const g = ProcedureRoom.build(THREE, LC, {canvas: cv});
  const by = n => g.children.find(c => c.name === n);
  const drape = by('drape');
  assert.equal(drape.material.kind, 'std');
  assert.ok(drape.material.bumpMap && drape.geometry.attrs.uv.itemSize === 2);
  assert.equal(drape.castShadow, true);
  assert.equal(by('floor').castShadow, false);
  assert.equal(by('floor').receiveShadow, true);
  assert.ok(by('floor').material.map && by('floor').material.map.rep[0] >= 9);
  for (const n of ['room-shell', 'ceiling', 'wainscot-y1']) assert.equal(by(n).castShadow, false, n);
  for (const n of ['table-pad', 'mayo-tray', 'iv-pole', 'stool-seat', 'lamp-head']) assert.equal(by(n).castShadow, true, n);
  const lights = g.children.filter(c => c.target);
  assert.equal(lights.length, 3);
  assert.ok(lights.every(l => l.castShadow === true));
  assert.deepEqual(lights[0].shadowSize, [2048, 2048]);
});