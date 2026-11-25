// ทดสอบวัสดุผิวทึบที่มีช่องมองด้านในรอบเข็ม (static/index.html: holeShader / skinMat / glassMat)
// ดึงโค้ดจริงจากไฟล์ไปรันกับ THREE จำลอง และชิ้นส่วน shader รูปแบบเดียวกับ MeshPhongMaterial ของ three.js r128 (ไม่ใช่การตรวจภาพ)
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8').replace(/\r/g, '');
const start = html.indexOf('const skinHole = '), end = html.indexOf('const skinGlass = ');
assert.ok(start > 0 && end > start, 'ไม่พบบล็อกวัสดุผิวใน index.html');
const block = html.slice(start, end);

class V3 { constructor(x, y, z) { this.x = x; this.y = y; this.z = z; } set(x, y, z) { this.x = x; this.y = y; this.z = z; } }
const THREE = {Vector3: V3, DoubleSide: 2, FrontSide: 0, MeshPhongMaterial: class { constructor(o) { Object.assign(this, o); } }};
const sandbox = {THREE};
vm.createContext(sandbox);
vm.runInContext('const mat = (color, opacity, extra) => new THREE.MeshPhongMaterial(Object.assign({color, transparent: opacity < 1, opacity, side: THREE.DoubleSide, shininess: 30}, extra));\n'
  + block + '\nthis.skinMat = skinMat; this.glassMat = glassMat; this.skinHole = skinHole; this.skinHoleR = skinHoleR;', sandbox);

const VERT = 'uniform float x;\n#include <common>\nvoid main() {\n#include <begin_vertex>\n#include <project_vertex>\n}';
const FRAG = '#define PHONG\nuniform vec3 diffuse;\n#include <common>\nvoid main() {\n\t#include <clipping_planes_fragment>\n\tvec4 diffuseColor = vec4( diffuse, opacity );\n\t#include <map_fragment>\n\t#include <alphatest_fragment>\n\t#include <output_fragment>\n}';
const compile = m => { const sh = {uniforms: {}, vertexShader: VERT, fragmentShader: FRAG}; m.onBeforeCompile(sh); return sh; };

test('ผิวทึบแสง: opacity 1, ไม่โปร่งใส, ใช้ shader ตัดช่องรอบจุดเจาะด้วย dither', () => {
  const m = sandbox.skinMat();
  assert.equal(m.opacity, 1); assert.equal(m.transparent, false);
  const sh = compile(m);
  assert.equal(sh.uniforms.uHole, sandbox.skinHole);          // ใช้ uniform ร่วม: อัปเดตที่เดียวทุกชิ้นของผิวเปลี่ยนพร้อมกัน
  assert.equal(sh.uniforms.uHoleR, sandbox.skinHoleR);
  assert.match(sh.vertexShader, /varying vec3 vWPos;[\s\S]*#include <begin_vertex>\nvWPos = \(modelMatrix \* vec4\(transformed, 1\.0\)\)\.xyz;/);
  const i = sh.fragmentShader.indexOf('float hT'), j = sh.fragmentShader.indexOf('if (hT < hN) discard;');
  assert.ok(sh.fragmentShader.indexOf('#include <clipping_planes_fragment>') < i && i < j, 'ต้องคำนวณ hT หลัง clipping และตัดก่อน diffuseColor ถูกใช้');
  assert.ok(j < sh.fragmentShader.indexOf('vec4 diffuseColor'));
  assert.match(sh.fragmentShader, /uniform vec3 uHole;\nuniform float uHoleR;/);
});

test('ผิวใสสีอ่อน: โปร่งใสบางส่วน ไม่เขียน depth หันหน้าเดียว และจางลงตามระยะจากเข็ม', () => {
  const g = sandbox.glassMat();
  assert.equal(g.transparent, true); assert.equal(g.depthWrite, false); assert.equal(g.side, 0);
  assert.ok(g.opacity > 0.2 && g.opacity < 0.5);
  assert.ok(g.color > sandbox.skinMat().color, 'สีอ่อนกว่าผิวทึบ');
  const sh = compile(g);
  assert.ok(!/discard;\n.*hN/.test(sh.fragmentShader) && !sh.fragmentShader.includes('hN'));
  assert.match(sh.fragmentShader, /#include <alphatest_fragment>\ndiffuseColor\.a \*= \(1\.0 - hT\);/);
});

test('ผิวทึบกับผิวใสใช้ program คนละตัว (cache key ต่างกัน) และรัศมีช่องอยู่ที่ราว 5-6 cm', () => {
  assert.notEqual(sandbox.skinMat().customProgramCacheKey(), sandbox.glassMat().customProgramCacheKey());
  assert.ok(sandbox.skinHoleR.value > 0.04 && sandbox.skinHoleR.value < 0.08);
  assert.ok(sandbox.skinHole.value.z < -10, 'ก่อนมีจุดเจาะ ช่องต้องอยู่นอกตัว (ผิวทึบทั้งตัว)');
});