// สโมคเทสต์การผูกโมเดลร่างกายจริงเข้ากับฉาก 3D ใน static/index.html: ดึงฟังก์ชันจริงจากไฟล์ไปรันกับ THREE จำลอง
// ตรวจว่า simAttachAnatomy สลับฉากครบ จุดเจาะตั้งต้นอยู่ในโซน และปอด/เตียงถูกสร้างตามโมเดลจริง (ไม่ใช่การตรวจภาพ)
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const Anatomy = require(path.join(__dirname, '..', 'static', 'anatomy.js'));

const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8').replace(/\r/g, '');

function extractFunction(name) {
  const start = html.indexOf('function ' + name + '(');
  assert.ok(start >= 0, 'ไม่พบ function ' + name);
  let i = html.indexOf('{', html.indexOf(')', start)), depth = 0;
  for (let j = i; j < html.length; j++) {
    const c = html[j];
    if (c === '{') depth++;
    else if (c === '}' && --depth === 0) return html.slice(start, j + 1);
  }
  throw new Error('วงเล็บไม่สมดุล: ' + name);
}

// ---- THREE จำลอง (เท่าที่ใช้) ----
class V3 {
  constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
  clone() { return new V3(this.x, this.y, this.z); }
  applyQuaternion(q) { return q.rotate(this); }
  copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
  normalize() { const m = Math.hypot(this.x, this.y, this.z) || 1; this.x /= m; this.y /= m; this.z /= m; return this; }
}
class Obj { constructor() { this.children = []; this.visible = true; this.position = new V3(); } add(o) { this.children.push(o); o.parent = this; } remove(o) { this.children = this.children.filter(c => c !== o); }
  traverse(fn) { fn(this); this.children.forEach(c => (c.traverse ? c.traverse(fn) : fn(c))); } }
const RY = -Math.PI / 2;                                   // patient.rotation.y
const rot = (v, s) => new V3(v.x * Math.cos(RY) + s * v.z * Math.sin(RY), v.y, -s * v.x * Math.sin(RY) + v.z * Math.cos(RY));
const quat = {rotate: v => rot(v, 1)};
const THREE = {
  Group: class extends Obj { constructor() { super(); this.quaternion = quat; } localToWorld(v) { return rot(v, 1); } worldToLocal(v) { return rot(v, -1); } updateMatrixWorld() {} },
  Mesh: class extends Obj { constructor(g, m) { super(); this.geometry = g; this.material = m; } },
  BufferGeometry: class { setAttribute() {} setIndex(i) { this.index = i; } computeVertexNormals() {} },
  BufferAttribute: class { constructor(a) { this.array = a; } },
  Float32BufferAttribute: class { constructor(a) { this.array = a; } },
  MeshBasicMaterial: class { constructor(o) { Object.assign(this, o); } },
  MeshPhongMaterial: class { constructor(o) { Object.assign(this, o); } },
  Vector3: V3, DoubleSide: 2,
};

const dir = path.join(__dirname, '..', 'static', 'anatomy');
const A = new Anatomy(JSON.parse(fs.readFileSync(path.join(dir, 'anatomy.json'), 'utf8')), fs.readFileSync(path.join(dir, 'anatomy.bin')));

function makeSandbox() {
  const patient = new THREE.Group(), scene = new THREE.Group();
  const old = n => { const g = new THREE.Group(); g.tag = n; patient.add(g); return g; };
  const mat = (color, opacity) => ({color, opacity});
  const credit = {hidden: true, textContent: ''}, calls = [], roomCalls = [];
  const sandbox = {
    THREE, ANAT: null, console, Math, Float32Array,
    SIM_SITE: Anatomy.SITE,
    $: id => (id === 'simCredit' ? credit : {}),
    simRender: () => calls.push('render'),
    document: {createElement: () => ({getContext: () => ({})})},
    ProcedureRoom: {
      layout: o => { roomCalls.push(o); return {lamp: {}}; },
      build: (T, L, o) => { const g = new T.Group(); g.name = 'room-' + roomCalls.length; g.built = o; return g; },
    },
    simGL: {
      patient, scene, mat, skinMat: () => mat(0xf1c9a8, 1), glassMat: () => mat(0xfff0e2, 0.34), lungMat: mat(0xe58a9a, 0.8), lungMm: 7, userPicked: false,
      skin: old('skin'), body: old('body'), ribs: old('ribs'), zone: old('zone'), lungs: old('lungs'),
      bed: new THREE.Mesh(null, null), ray: {origin: null, dir: null, set(o, d) { this.origin = o; this.dir = d; }, intersectObject(obj) {
        this.picked = obj; return [{point: new V3(this.origin.x + this.dir.x * 0.3, this.origin.y + this.dir.y * 0.3, this.origin.z + this.dir.z * 0.3)}]; }},
    },
    simTarget: null, SIM_PICK_ANYWHERE: true, SIM_DRAPE: true,
  };
  sandbox.tubeGeo = rings => ({rings});
  scene.updateMatrixWorld = () => {};
  vm.createContext(sandbox);
  const code = ['simAttachAnatomy', 'simBuildLungs', 'simSetTarget', 'simHit', 'simBuildRoom']
    .map(extractFunction).join('\n') + '\nfunction simSiteOk(p){ return ANAT.siteOk(p, SIM_SITE); }\nfunction skinNormal(p){ return ANAT.skinNormal(p); }';
  vm.runInContext(code, sandbox);
  return {sandbox, credit, calls, roomCalls};
}

test('simAttachAnatomy สลับฉากเป็นโมเดลจริง: ผิว/กระดูก/อวัยวะ/โซน/เมชเลือกจุด/เตียง/เครดิต', () => {
  const {sandbox, credit, calls} = makeSandbox();
  vm.runInContext('simAttachAnatomy', sandbox)(A);
  const G = sandbox.simGL, P = G.patient;
  assert.equal(vm.runInContext('ANAT', sandbox), A);
  assert.ok(G.skin.geometry && !G.skin.tag);                       // ผิวใหม่ (ไม่ใช่กลุ่มเดิม)
  assert.ok(!P.children.some(c => c.tag), 'ชิ้นส่วนสูตรเดิมต้องถูกถอดออกหมด');
  for (const part of [G.skin, G.body, G.ribs, G.zone, G.lungs, G.pick]) assert.ok(P.children.includes(part));
  assert.equal(G.pick.visible, false);
  assert.equal(G.skin.children.length, 1, 'ผิวใสสีอ่อนเฉพาะรอบเข็มเป็นลูกของผิวทึบ');
  assert.equal(G.skin.children[0].geometry, G.skin.geometry);
  assert.ok(G.skin.castShadow && G.skin.receiveShadow);
  assert.equal(G.zone.children.length, 2);
  assert.equal(G.lungs.children.length, 2);                        // organs + lungsDyn
  assert.equal(G.lungMm, 0);                                       // บังคับสร้างปอดใหม่ในเฟรมถัดไป
  assert.equal(G.bed.position.z, A.landmarks.backX - 0.01);
  assert.equal(credit.hidden, false);
  assert.match(credit.textContent, /BodyParts3D/);
  assert.ok(calls.includes('render'));
});

test('จุดเจาะตั้งต้นหลังสลับโมเดล: ยิงรังสีกับเมชห่อผิว อยู่ในโซน และเวกเตอร์ตั้งฉากเป็นพิกัดโลก', () => {
  const {sandbox} = makeSandbox();
  vm.runInContext('simAttachAnatomy', sandbox)(A);
  const T = vm.runInContext('simTarget', sandbox), G = sandbox.simGL;
  assert.ok(T, 'ต้องมี simTarget');
  assert.equal(T.site, true);
  assert.equal(G.ray.picked, G.pick, 'ต้องยิงกับเมชห่อผิว ไม่ใช่ผิวที่มีแขน');
  assert.ok(Math.abs(Math.hypot(...T.N) - 1) < 1e-9);
  const d = A.defaultSite(-1, 75), S = G.patient.localToWorld(new V3(...d.point));
  assert.ok(Math.hypot(T.S[0] - S.x, T.S[1] - S.y, T.S[2] - S.z) < 1e-9);
  assert.ok(T.S[1] < 0, 'ด้านขวาของผู้ป่วย = -Y ในโลก');
  assert.ok(T.N[2] < 0.6, 'ผนังอกด้านข้าง: ปกติไม่ชี้ขึ้นตรงๆ');
});

test('ไม่เขียนทับจุดเจาะที่ผู้ใช้เลือกไว้แล้ว', () => {
  const {sandbox} = makeSandbox();
  sandbox.simGL.userPicked = true;
  vm.runInContext('simAttachAnatomy', sandbox)(A);
  assert.equal(vm.runInContext('simTarget', sandbox), null);
});

test('simBuildLungs (โมเดลจริง): สร้างปอดซ้าย/ขวาลง lungsDyn และจำค่า mm', () => {
  const {sandbox} = makeSandbox();
  vm.runInContext('simAttachAnatomy', sandbox)(A);
  vm.runInContext('simBuildLungs', sandbox)(34);
  const G = sandbox.simGL;
  assert.equal(G.lungsDyn.children.length, 2);
  assert.equal(G.lungMm, 34);
  vm.runInContext('simBuildLungs', sandbox)(30);
  assert.equal(G.lungsDyn.children.length, 2);                     // ล้างของเดิมก่อนสร้างใหม่
  assert.equal(G.lungMm, 30);
});

test('ห้องทำหัตถการ: สร้างตามหลังผู้ป่วยจริงและโปรไฟล์ขา แทนเตียงเดิม และสร้างใหม่โดยถอดห้องเดิมออก', () => {
  const {sandbox, roomCalls} = makeSandbox();
  const G = sandbox.simGL;
  vm.runInContext('simBuildRoom', sandbox)();                       // ก่อนโหลดโมเดลจริง: ผังตั้งต้น
  assert.equal(roomCalls.length, 1);
  assert.equal(roomCalls[0].backX, undefined);
  assert.equal(G.bed.visible, false, 'เตียงเดิมต้องถูกซ่อน');
  const first = G.room;
  assert.ok(G.scene.children.includes(first));
  vm.runInContext('simAttachAnatomy', sandbox)(A);                  // หลังโหลดโมเดลจริง: สร้างห้องใหม่
  assert.equal(roomCalls.length, 2);
  assert.equal(roomCalls[1].backX, A.landmarks.backX);
  assert.equal(roomCalls[1].env, A.manifest.env);
  assert.ok(roomCalls[1].skinField && roomCalls[1].skinField.top.length > 1000, 'ส่งสนามความสูงผิวจริงให้ผ้าคลุม');
  assert.equal(roomCalls[0].skinField, undefined);
  assert.ok(G.room !== first && G.scene.children.includes(G.room));
  assert.ok(!G.scene.children.includes(first), 'ห้องเดิมต้องถูกถอดออก');
  assert.equal(typeof G.room.built.canvas, 'function');             // ตัวสร้างพื้นผิวภาพ (จอมอนิเตอร์/นาฬิกา/เงา)
});
test('ผ้าคลุมปิดได้ (SIM_DRAPE = false): ไม่ส่งสนามความสูงผิวและสั่งผังไม่สร้างผ้า', () => {
  const {sandbox, roomCalls} = makeSandbox();
  sandbox.SIM_DRAPE = false;
  vm.runInContext('simAttachAnatomy', sandbox)(A);
  const last = roomCalls[roomCalls.length - 1];
  assert.equal(last.drape, false);
  assert.equal(last.skinField, undefined);
  assert.equal(html.match(/const SIM_DRAPE = (\w+);/)[1], 'false', 'ค่าตั้งต้นในหน้าเว็บ = ไม่มีผ้า');
});