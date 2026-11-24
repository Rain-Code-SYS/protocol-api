// ทดสอบผังห้องทำหัตถการ (static/procedure_room.js): ขนาด ตำแหน่ง และการสร้างเมชด้วย THREE จำลอง
// รัน (จากโฟลเดอร์ protocol-api):  node --test
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const ProcedureRoom = require(path.join(__dirname, '..', 'static', 'procedure_room.js'));

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
  assert.equal(g.children.filter(c => c.target).length, 1);          // โคมไฟมีเป้าหมาย
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