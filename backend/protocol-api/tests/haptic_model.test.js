// เทียบ static/haptic_model.js (JavaScript) กับค่าอ้างอิงที่สร้างจาก tissue_model.py (Python)
// รัน (จากโฟลเดอร์ protocol-api):  node --test
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const HapticModel = require(path.join(__dirname, '..', 'static', 'haptic_model.js'));
const vectors = require('./haptic_vectors.json');

const close = (a, b, label) => {
  const tol = 1e-9 * Math.max(1, Math.abs(b));
  assert.ok(Math.abs(a - b) <= tol, `${label}: ${a} != ${b}`);
};

test('pyFloat ตรงกับ str(float) ของ Python ทุกค่า', () => {
  for (const [value, expected] of vectors.floats) assert.equal(HapticModel.pyFloat(value), expected, String(value));
});

for (const c of vectors.cases) {
  test(`โมเดลตรงกับ Python: ${c.name}`, () => {
    const m = new HapticModel();
    let n = 0;
    for (const s of c.steps) {
      if (s.op === 'config') m.applyEncoderConfig(s.config);
      else if (s.op === 'age') m.applyAge(s.code);
      else if (s.op === 'reset') m.resetState();
      else {
        const [e1, e2, e3] = s.e;
        const cmd = m.processEncoder(s.ts, e1, e2, e3, s.touch);
        const got = cmd.split(';'), want = s.cmd.split(';');
        assert.equal(got.length, 4, cmd);
        close(Number(got[0]), Number(want[0]), `Ki @${n}`);
        close(Number(got[1]), Number(want[1]), `Kv @${n}`);
        assert.equal(got[2], want[2], `bp @${n}`);
        assert.equal(got[3], want[3], `by @${n}`);
        const p = m.pose(e1, e2, e3);
        for (const k of Object.keys(s.pose)) close(p[k], s.pose[k], `${k} @${n}`);
        assert.equal(m.lung_hit, s.lung, `lung @${n}`);
        close(m.x_max, s.x_max, `x_max @${n}`);
        n++;
      }
    }
    assert.ok(n > 300);
  });
}

test('คำสั่งมี 4 ฟิลด์เสมอและ Ki/Kv ไม่ติดลบ', () => {
  const m = new HapticModel();
  for (const e3 of [0, 100, 398, 700, 1500, -300]) {
    const f = m.processEncoder(1000 + e3, 0, 0, e3).split(';');
    assert.equal(f.length, 4);
    assert.ok(Number(f[0]) >= 0 && Number(f[1]) >= 0.5);
  }
});

test('ค่าไม่ถูกต้องถูกปฏิเสธและไม่แตะโมเดล', () => {
  const m = new HapticModel();
  assert.throws(() => m.applyAge(3));
  assert.equal(m.age_code, 1);
  const bad = {Joint_YAW: {encoder_id: 'Enc_1', ppr: 10}, Joint_PITCH: {encoder_id: 'Enc_1', ppr: 10}, Slider_MOTOR: {encoder_id: 'Enc_3', ppr: 10}};
  assert.throws(() => m.applyEncoderConfig(bad));                       // เลือกเอนโค้ดเดอร์ซ้ำ
  assert.equal(m.axes.pitch.channel, 'enc2');
  assert.throws(() => m.applyEncoderConfig({}));
});

test('onLungChange ถูกเรียกเฉพาะตอนสถานะเปลี่ยน', () => {
  const m = new HapticModel();
  const events = [];
  m.onLungChange = h => events.push(h);
  // theta2 ที่ทำให้ลึกเกิน 34 mm: ใช้ค่ามุมสูงจนเกินระยะปอด
  let ts = 0;
  for (const e3 of [0, 0, 1500, 1500, 1600, 0]) m.processEncoder(ts += 10, 0, 0, e3);
  assert.deepEqual(events, [true, false]);
});

test('RELEASE_COMMAND เป็นรูปแบบ Trig Protocol 3', () => {
  assert.equal(HapticModel.RELEASE_COMMAND.split(';').length, 4);
});