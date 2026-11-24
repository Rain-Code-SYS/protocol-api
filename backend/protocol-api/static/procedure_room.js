/*
 * ProcedureRoom: ห้องทำหัตถการรอบเตียงผู้ป่วยในฉาก 3D ของหน้า Simulation
 *   เตียงหัตถการ + หมอน + ผ้าคลุมช่วงล่าง, โคมผ่าตัดเหนือเตียง, แท่นเครื่องมือ (Mayo stand) พร้อมอุปกรณ์เจาะ, เสาน้ำเกลือ,
 *   จอมอนิเตอร์, เคาน์เตอร์พร้อมอ่างล้างมือ, ตู้ติดผนัง, ประตู, ถังขยะติดเชื้อ/กล่องทิ้งของมีคม, เก้าอี้ผู้ทำหัตถการ, พื้น ผนัง เพดาน และไฟเพดาน
 *
 * - layout() คำนวณผังเป็นข้อมูลล้วน (ไม่แตะ THREE) จึงทดสอบใน Node ได้; build() แปลงผังเป็นเมช
 * - พิกัดโลกของฉาก (หน่วยเมตร): X ไปทางเท้า (ศีรษะอยู่ -X), Y = ซ้ายของผู้ป่วย, Z = ขึ้น ตัวผู้ป่วยนอนหงายหลังแตะเตียงที่ Z = backX
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ProcedureRoom = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const D = {
    padThickness: 0.09, tableHeight: 0.74,          // ความหนาเบาะ / ความสูงจากพื้นถึงใต้เบาะ
    tableX0: -0.65, tableX1: 1.35, tableHalfWidth: 0.31,
    ceilingHeight: 2.9, room: {x0: -2.7, x1: 3.2, y0: -2.3, y1: 2.3},
    defaultBackX: -0.12,
  };
  const C = {
    wall: 0xe4eaec, wainscot: 0xa9cfcb, base: 0x6f8789, floor: 0x8e9aa0, ceiling: 0xf1f4f5, pad: 0x2c5e86,
    steel: 0xb9c0c6, darkSteel: 0x4a5258, white: 0xf3f5f6, drape: 0x2f9a8f, pillow: 0xf2f4f5,
  };

  /**
   * opts: {backX (Z ของหลังผู้ป่วย = ผิวเบาะ), env (จาก anatomy.json: โปรไฟล์ขา/ท้ายทอย, ไม่ใส่ก็ได้)}
   * คืน {floorZ, ceilZ, room, padTop, items: [...], lamp: {pos, target}}
   * item: {name, kind: 'box'|'cyl'|'sph'|'shadow'|'screen'|'clock'|'drape'|'shell', pos, size|r,h,axis|radii, color, ...}
   */
  function layout(opts) {
    const o = opts || {};
    const backX = o.backX === undefined ? D.defaultBackX : o.backX;
    const room = D.room, padTop = backX, padBottom = padTop - D.padThickness;
    const floorZ = padBottom - D.tableHeight, ceilZ = floorZ + D.ceilingHeight;
    const tx = (D.tableX0 + D.tableX1) / 2, tl = D.tableX1 - D.tableX0, tw = 2 * D.tableHalfWidth;
    const items = [];
    const box = (name, pos, size, color, x) => items.push(Object.assign({name, kind: 'box', pos, size, color}, x));
    const cyl = (name, pos, r, h, color, x) => items.push(Object.assign({name, kind: 'cyl', pos, r, h, axis: 'z', color}, x));
    const sph = (name, pos, radii, color, x) => items.push(Object.assign({name, kind: 'sph', pos, radii, color}, x));
    const shadow = (name, pos, w, l, opacity) => items.push({name, kind: 'shadow', pos: [pos[0], pos[1], floorZ + 0.003], size: [w, l], opacity: opacity || 0.35});
    const wy1 = room.y1, wy0 = room.y0, wx0 = room.x0, wx1 = room.x1;

    // ---------- เปลือกห้อง ----------
    items.push({name: 'room-shell', kind: 'shell', pos: [(wx0 + wx1) / 2, (wy0 + wy1) / 2, (floorZ + ceilZ) / 2], size: [wx1 - wx0, wy1 - wy0, ceilZ - floorZ], color: C.wall});
    items.push({name: 'floor', kind: 'box', pos: [(wx0 + wx1) / 2, (wy0 + wy1) / 2, floorZ - 0.005], size: [wx1 - wx0, wy1 - wy0, 0.01], color: C.floor, shininess: 40, specular: 0x333333});
    items.push({name: 'ceiling', kind: 'box', pos: [(wx0 + wx1) / 2, (wy0 + wy1) / 2, ceilZ + 0.005], size: [wx1 - wx0, wy1 - wy0, 0.01], color: C.ceiling});
    // แผงผนังล่าง (wainscot) และบัวพื้น
    const wh = 1.05, t = 0.012;
    box('wainscot-y1', [(wx0 + wx1) / 2, wy1 - t / 2, floorZ + wh / 2], [wx1 - wx0, t, wh], C.wainscot);
    box('wainscot-y0', [(wx0 + wx1) / 2, wy0 + t / 2, floorZ + wh / 2], [wx1 - wx0, t, wh], C.wainscot);
    box('wainscot-x0', [wx0 + t / 2, (wy0 + wy1) / 2, floorZ + wh / 2], [t, wy1 - wy0, wh], C.wainscot);
    box('wainscot-x1', [wx1 - t / 2, (wy0 + wy1) / 2, floorZ + wh / 2], [t, wy1 - wy0, wh], C.wainscot);
    box('baseboard-y1', [(wx0 + wx1) / 2, wy1 - 0.02, floorZ + 0.05], [wx1 - wx0, 0.02, 0.1], C.base);
    box('baseboard-y0', [(wx0 + wx1) / 2, wy0 + 0.02, floorZ + 0.05], [wx1 - wx0, 0.02, 0.1], C.base);
    box('baseboard-x0', [wx0 + 0.02, (wy0 + wy1) / 2, floorZ + 0.05], [0.02, wy1 - wy0, 0.1], C.base);
    box('baseboard-x1', [wx1 - 0.02, (wy0 + wy1) / 2, floorZ + 0.05], [0.02, wy1 - wy0, 0.1], C.base);
    // ไฟเพดาน (เปล่งแสง)
    for (const [i, x] of [-1.3, 1.9].entries()) box('ceiling-light-' + (i + 1), [x, 0, ceilZ - 0.012], [1.2, 0.6, 0.024], 0xffffff, {emissive: 0xffffff, basic: true});

    // ---------- เตียงหัตถการ ----------
    box('table-pad', [tx, 0, padTop - D.padThickness / 2], [tl, tw, D.padThickness], C.pad, {shininess: 25});
    box('table-carriage', [tx, 0, padBottom - 0.035], [0.9, 0.3, 0.07], C.darkSteel);
    cyl('table-column', [tx, 0, floorZ + (padBottom - 0.07 - floorZ) / 2 + 0.03], 0.09, padBottom - 0.07 - floorZ - 0.06, C.steel, {shininess: 60});
    box('table-base', [tx, 0, floorZ + 0.03], [1.1, 0.55, 0.06], C.darkSteel);
    for (const sd of [-1, 1]) cyl('table-rail-' + (sd < 0 ? 'r' : 'l'), [tx, sd * (D.tableHalfWidth + 0.015), padBottom + 0.035], 0.012, tl - 0.1, C.steel, {axis: 'x', shininess: 80});
    shadow('shadow-table', [tx, 0], 1.7, 1.2, 0.4);

    // หมอนรองศีรษะ (ตามระยะห่างท้ายทอยจริงถ้ามีข้อมูล)
    const env = o.env || null;
    const headTopZ = env ? env.headTopZ : 0.548, headBackX = env ? env.headBackX : padTop + 0.02;
    const pillowT = Math.max(0.05, headBackX - padTop + 0.04);
    sph('pillow', [-(headTopZ - 0.09), 0, padTop + pillowT / 2 - 0.01], [0.17, 0.21, pillowT / 2], C.pillow, {shininess: 5});

    // ผ้าคลุมช่วงล่าง (จากโปรไฟล์ขาจริงของผู้ป่วย): เริ่มต่ำกว่าเอวลงไปถึงปลายเท้า
    if (env) {
      const zs = [], hw = [], ant = [];
      for (let i = 0; i < env.n; i++) {
        zs.push(-(env.z0 + i * env.dz));                      // พิกัดโลก X = -z ผู้ป่วย (เรียงจากเท้าไปเอว)
        hw.push(env.halfWidthMm[i] / 1000 + 0.025);
        ant.push(env.anteriorXMm[i] / 1000 + 0.02);
      }
      items.push({name: 'drape', kind: 'drape', xs: zs, halfWidth: hw, top: ant, bottom: padTop, color: C.drape});
    }

    // ---------- โคมผ่าตัดเหนือเตียง ----------
    const lampZ = padTop + 1.12, lampX = -0.15, lampY = 0.95;
    cyl('lamp-stem', [lampX, lampY + 0.35, (lampZ + ceilZ) / 2], 0.022, ceilZ - lampZ, C.steel);
    cyl('lamp-arm', [lampX, lampY + 0.18, lampZ + 0.03], 0.018, 0.36, C.steel, {axis: 'y'});
    cyl('lamp-head', [lampX, lampY, lampZ], 0.3, 0.06, C.white, {shininess: 70});
    cyl('lamp-lens', [lampX, lampY, lampZ - 0.032], 0.22, 0.008, 0xfff6e0, {emissive: 0xfff2cc, basic: true});
    const lamp = {pos: [lampX, lampY, lampZ - 0.05], target: [-0.1, 0, padTop + 0.1]};

    // ---------- แท่งเครื่องมือ (Mayo stand) ด้านขวาของผู้ป่วย พร้อมอุปกรณ์เจาะ ----------
    const mx = 0.18, my = -0.98, trayZ = floorZ + 0.95;
    box('mayo-base', [mx, my, floorZ + 0.025], [0.55, 0.42, 0.05], C.darkSteel);
    cyl('mayo-column', [mx, my, floorZ + 0.5], 0.022, 0.9, C.steel, {shininess: 70});
    box('mayo-tray', [mx, my, trayZ], [0.56, 0.38, 0.02], C.steel, {shininess: 90, specular: 0x666666});
    box('mayo-cloth', [mx, my, trayZ + 0.012], [0.5, 0.33, 0.004], C.drape);
    shadow('shadow-mayo', [mx, my], 0.8, 0.7, 0.3);
    const z0 = trayZ + 0.014;
    box('gauze-1', [mx - 0.18, my + 0.1, z0 + 0.012], [0.1, 0.1, 0.024], C.white);
    box('gauze-2', [mx - 0.18, my + 0.1, z0 + 0.036], [0.1, 0.1, 0.024], C.white);
    cyl('syringe-10ml', [mx + 0.02, my - 0.12, z0 + 0.008], 0.009, 0.12, 0xdcecf5, {axis: 'x', opacity: 0.8});
    cyl('syringe-plunger', [mx + 0.09, my - 0.12, z0 + 0.008], 0.004, 0.06, 0xf0f0f0, {axis: 'x'});
    cyl('syringe-20ml', [mx + 0.02, my - 0.08, z0 + 0.011], 0.012, 0.15, 0xdcecf5, {axis: 'x', opacity: 0.8});
    box('needle-pack-1', [mx + 0.08, my + 0.07, z0 + 0.004], [0.06, 0.03, 0.008], 0x4aa3d9);
    box('needle-pack-2', [mx + 0.08, my + 0.115, z0 + 0.004], [0.06, 0.03, 0.008], 0x7bc66f);
    cyl('antiseptic-bottle', [mx - 0.12, my - 0.11, z0 + 0.045], 0.03, 0.09, 0xb4622d);
    cyl('antiseptic-cap', [mx - 0.12, my - 0.11, z0 + 0.097], 0.015, 0.014, 0xffffff);
    cyl('lidocaine-vial', [mx - 0.03, my + 0.12, z0 + 0.03], 0.013, 0.06, 0xeadfb0, {opacity: 0.85});
    cyl('lidocaine-cap', [mx - 0.03, my + 0.12, z0 + 0.065], 0.012, 0.012, 0xd24c4c);
    sph('kidney-dish', [mx + 0.16, my + 0.1, z0 + 0.012], [0.07, 0.04, 0.012], C.steel, {shininess: 100});
    box('sterile-drape-pack', [mx - 0.02, my - 0.0, z0 + 0.012], [0.12, 0.1, 0.024], 0x4fb3a8);

    // ---------- เสาน้ำเกลือ ด้านซ้ายของผู้ป่วยทางศีรษะ ----------
    const ix = -0.9, iy = 0.62;
    cyl('iv-pole', [ix, iy, floorZ + 0.98], 0.011, 1.96, C.steel, {shininess: 80});
    for (let k = 0; k < 5; k++) {
      const a = k * 2 * Math.PI / 5;
      box('iv-foot-' + k, [ix + 0.14 * Math.cos(a), iy + 0.14 * Math.sin(a), floorZ + 0.02], [0.3, 0.03, 0.03], C.darkSteel, {rotZ: a});
    }
    cyl('iv-hook-arm', [ix, iy + 0.07, floorZ + 1.96], 0.007, 0.14, C.steel, {axis: 'y'});
    box('iv-bag', [ix, iy + 0.14, floorZ + 1.8], [0.14, 0.03, 0.22], 0xcfe9ff, {opacity: 0.6});
    cyl('iv-drip', [ix, iy + 0.14, floorZ + 1.64], 0.012, 0.06, 0xdcecf5, {opacity: 0.8});
    cyl('iv-line', [ix, iy + 0.14, floorZ + 1.35], 0.003, 0.55, 0xe8f2f8, {opacity: 0.8});
    shadow('shadow-iv', [ix, iy], 0.5, 0.5, 0.25);

    // ---------- จอมอนิเตอร์ที่ผนังด้านศีรษะ ----------
    box('monitor-body', [wx0 + 0.06, 0.95, floorZ + 1.6], [0.08, 0.6, 0.4], 0x20262b);
    items.push({name: 'monitor-screen', kind: 'screen', pos: [wx0 + 0.104, 0.95, floorZ + 1.6], size: [0.54, 0.34], facing: 'x'});
    cyl('monitor-arm', [wx0 + 0.04, 0.95, floorZ + 1.28], 0.012, 0.25, C.steel);

    // ---------- เคาน์เตอร์ ตู้ อ่างล้างมือ ติดผนังด้านซ้ายของผู้ป่วย ----------
    const cy = wy1 - 0.3, cxm = 1.6;
    box('counter-cabinet', [cxm, cy, floorZ + 0.43], [2.6, 0.6, 0.86], 0xdfe5e8);
    for (let k = 0; k < 5; k++) box('counter-door-seam-' + k, [cxm - 1.04 + k * 0.52, cy - 0.301, floorZ + 0.43], [0.006, 0.004, 0.74], 0x9aa7ad);
    box('counter-top', [cxm, cy - 0.01, floorZ + 0.88], [2.62, 0.64, 0.04], 0x3b4045, {shininess: 50});
    box('sink-basin', [cxm - 0.6, cy - 0.02, floorZ + 0.9], [0.5, 0.38, 0.006], 0xaab4ba, {shininess: 90});
    cyl('faucet-neck', [cxm - 0.6, cy + 0.2, floorZ + 1.0], 0.012, 0.2, C.steel, {shininess: 100});
    cyl('faucet-spout', [cxm - 0.6, cy + 0.12, floorZ + 1.1], 0.01, 0.16, C.steel, {axis: 'y', shininess: 100});
    box('upper-cabinet', [cxm + 0.3, wy1 - 0.19, floorZ + 1.75], [2.0, 0.36, 0.7], 0xdfe5e8);
    for (let k = 0; k < 4; k++) box('upper-door-seam-' + k, [cxm + 0.3 - 0.75 + k * 0.5, wy1 - 0.372, floorZ + 1.75], [0.006, 0.004, 0.62], 0x9aa7ad);
    for (let k = 0; k < 3; k++) box('glove-box-' + k, [cxm + 0.35 + k * 0.24, cy + 0.12, floorZ + 0.95], [0.22, 0.1, 0.12], [0x4aa3d9, 0x7a6bd0, 0x4aa3d9][k]);
    box('sanitizer', [cxm - 1.05, wy1 - 0.05, floorZ + 1.25], [0.09, 0.07, 0.2], C.white);
    box('sharps-container', [cxm + 1.15, wy1 - 0.06, floorZ + 1.15], [0.2, 0.12, 0.3], 0xc62828);
    box('sharps-lid', [cxm + 1.15, wy1 - 0.06, floorZ + 1.32], [0.21, 0.13, 0.02], 0xffffff);

    // ---------- ประตูด้านเท้า ----------
    box('door-frame', [wx1 - 0.03, -0.9, floorZ + 1.05], [0.06, 1.12, 2.1], 0xb7c4c9);
    box('door-panel', [wx1 - 0.05, -0.9, floorZ + 1.03], [0.05, 1.0, 2.05], 0xcfd8dc);
    box('door-window', [wx1 - 0.078, -0.9, floorZ + 1.55], [0.01, 0.28, 0.6], 0x6f8f9c, {opacity: 0.75, shininess: 90});
    cyl('door-handle', [wx1 - 0.1, -1.3, floorZ + 1.0], 0.012, 0.14, C.steel, {shininess: 90});
    items.push({name: 'wall-clock', kind: 'clock', pos: [wx1 - 0.02, 0.5, floorZ + 2.25], r: 0.17});

    // ---------- ของใช้บนพื้น ----------
    box('biohazard-bin', [-1.9, -1.75, floorZ + 0.32], [0.42, 0.42, 0.64], 0xc62828);
    box('biohazard-lid', [-1.9, -1.75, floorZ + 0.655], [0.44, 0.44, 0.03], 0x8e1b1b);
    cyl('waste-bin', [-1.9, -1.15, floorZ + 0.25], 0.17, 0.5, 0x7b868c);
    shadow('shadow-bins', [-1.9, -1.45], 0.9, 1.1, 0.3);
    const sx = 0.2, sy = -1.55;                              // เก้าอี้ผู้ทำหัตถการ
    cyl('stool-seat', [sx, sy, floorZ + 0.55], 0.2, 0.06, 0x2b2f33);
    cyl('stool-column', [sx, sy, floorZ + 0.28], 0.025, 0.5, C.steel);
    for (let k = 0; k < 5; k++) {
      const a = k * 2 * Math.PI / 5;
      box('stool-foot-' + k, [sx + 0.12 * Math.cos(a), sy + 0.12 * Math.sin(a), floorZ + 0.03], [0.26, 0.03, 0.025], C.darkSteel, {rotZ: a});
    }
    shadow('shadow-stool', [sx, sy], 0.6, 0.6, 0.3);

    return {floorZ, ceilZ, room, padTop, padBottom, table: {x: tx, length: tl, width: tw}, items, lamp};
  }

  // ---------- THREE builder ----------
  function mat(THREE, it) {
    const p = {color: it.color === undefined ? 0xcccccc : it.color};
    if (it.opacity !== undefined && it.opacity < 1) { p.transparent = true; p.opacity = it.opacity; p.depthWrite = false; }
    if (it.basic) { p.color = it.emissive === undefined ? p.color : it.emissive; return new THREE.MeshBasicMaterial(p); }
    p.shininess = it.shininess === undefined ? 12 : it.shininess;
    if (it.specular !== undefined) p.specular = it.specular;
    if (it.emissive !== undefined) p.emissive = it.emissive;
    return new THREE.MeshPhongMaterial(p);
  }

  function makeTexture(THREE, canvasFactory, draw, w, h) {
    if (!canvasFactory) return null;
    const cv = canvasFactory();
    cv.width = w; cv.height = h;
    draw(cv.getContext('2d'), w, h);
    const tex = new THREE.CanvasTexture(cv);
    return tex;
  }

  const draw = {
    shadow(g, w, h) { const r = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2); r.addColorStop(0, 'rgba(0,0,0,0.9)'); r.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = r; g.fillRect(0, 0, w, h); },
    monitor(g, w, h) {
      g.fillStyle = '#05090b'; g.fillRect(0, 0, w, h);
      g.strokeStyle = '#33ff66'; g.lineWidth = 3; g.beginPath();
      for (let x = 0; x < w * 0.62; x++) {                                    // คลื่น ECG
        const ph = (x % 90) / 90, y = h * 0.28 - (ph > 0.42 && ph < 0.46 ? 38 : ph > 0.46 && ph < 0.5 ? -14 : ph > 0.7 && ph < 0.82 ? 9 * Math.sin((ph - 0.7) / 0.12 * Math.PI) : 0);
        x ? g.lineTo(x, y) : g.moveTo(x, y);
      }
      g.stroke(); g.strokeStyle = '#33c8ff'; g.beginPath();                      // คลื่น SpO2
      for (let x = 0; x < w * 0.62; x++) { const y = h * 0.62 - 20 * Math.max(0, Math.sin(x / 90 * 2 * Math.PI)) ** 1.6; x ? g.lineTo(x, y) : g.moveTo(x, y); }
      g.stroke();
      g.fillStyle = '#33ff66'; g.font = 'bold 64px sans-serif'; g.fillText('72', w * 0.72, h * 0.3); g.font = '20px sans-serif'; g.fillText('HR', w * 0.72, h * 0.36);
      g.fillStyle = '#33c8ff'; g.font = 'bold 54px sans-serif'; g.fillText('98', w * 0.72, h * 0.62); g.font = '20px sans-serif'; g.fillText('SpO2 %', w * 0.72, h * 0.68);
      g.fillStyle = '#ffffff'; g.font = '28px sans-serif'; g.fillText('118/76   RR 16', w * 0.08, h * 0.92);
    },
    clock(g, w, h) {
      g.fillStyle = '#f7f7f7'; g.beginPath(); g.arc(w / 2, h / 2, w / 2 - 4, 0, 2 * Math.PI); g.fill();
      g.strokeStyle = '#222'; g.lineWidth = 6; g.stroke();
      for (let k = 0; k < 12; k++) { const a = k * Math.PI / 6; g.beginPath(); g.moveTo(w / 2 + Math.sin(a) * w * 0.4, h / 2 - Math.cos(a) * w * 0.4); g.lineTo(w / 2 + Math.sin(a) * w * 0.46, h / 2 - Math.cos(a) * w * 0.46); g.stroke(); }
      g.lineWidth = 8; g.beginPath(); g.moveTo(w / 2, h / 2); g.lineTo(w / 2 + w * 0.2, h / 2 - w * 0.1); g.stroke();
      g.lineWidth = 5; g.beginPath(); g.moveTo(w / 2, h / 2); g.lineTo(w / 2 - w * 0.05, h / 2 - w * 0.32); g.stroke();
    },
  };

  function drapeGeometry(THREE, it, nu) {
    const n = it.xs.length, NU = nu || 24, pos = [], idx = [];
    // ลำดับ xs เรียงจากเท้า (X มาก) ไปเอว (X น้อย): ทุกหน้าตัดเป็นครึ่งวงรีบนเตียง (ด้านล่างแบนที่ผิวเบาะ)
    for (let i = 0; i < n; i++) {
      for (let j = 0; j <= NU; j++) {
        const u = Math.PI * j / NU, h = Math.max(0.02, it.top[i] - it.bottom);
        pos.push(it.xs[i], it.halfWidth[i] * Math.cos(u), it.bottom + h * Math.sin(u));
      }
    }
    for (let i = 0; i < n - 1; i++) for (let j = 0; j < NU; j++) {
      const a = i * (NU + 1) + j, b = a + NU + 1;
      idx.push(a, b, a + 1, b, b + 1, a + 1);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    return g;
  }

  /** สร้างเมชทั้งห้องเป็นกลุ่มเดียว: opts = {canvas: () => canvas (ไม่ใส่ = ไม่มีพื้นผิวภาพ)} */
  function build(THREE, L, opts) {
    const o = opts || {}, group = new THREE.Group();
    group.name = 'procedure-room';
    for (const it of L.items) {
      let mesh = null;
      if (it.kind === 'box') mesh = new THREE.Mesh(new THREE.BoxGeometry(it.size[0], it.size[1], it.size[2]), mat(THREE, it));
      else if (it.kind === 'shell') mesh = new THREE.Mesh(new THREE.BoxGeometry(it.size[0], it.size[1], it.size[2]), Object.assign(mat(THREE, it), {side: THREE.BackSide}));
      else if (it.kind === 'cyl') {
        mesh = new THREE.Mesh(new THREE.CylinderGeometry(it.r, it.r, it.h, 24), mat(THREE, it));
        if (it.axis === 'z') mesh.rotation.x = Math.PI / 2; else if (it.axis === 'x') mesh.rotation.z = Math.PI / 2;
      } else if (it.kind === 'sph') {
        mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat(THREE, it));
        mesh.scale.set(it.radii[0], it.radii[1], it.radii[2]);
      } else if (it.kind === 'drape') {
        const m = mat(THREE, it); m.side = THREE.DoubleSide;
        mesh = new THREE.Mesh(drapeGeometry(THREE, it), m);
      } else if (it.kind === 'shadow') {
        const tex = makeTexture(THREE, o.canvas, draw.shadow, 128, 128);
        mesh = new THREE.Mesh(new THREE.PlaneGeometry(it.size[0], it.size[1]),
          new THREE.MeshBasicMaterial({map: tex, color: tex ? 0xffffff : 0x000000, transparent: true, opacity: tex ? it.opacity : it.opacity * 0.5, depthWrite: false}));
      } else if (it.kind === 'screen' || it.kind === 'clock') {
        const fn = it.kind === 'screen' ? draw.monitor : draw.clock, w = it.kind === 'screen' ? 512 : 256, h = it.kind === 'screen' ? 320 : 256;
        const tex = makeTexture(THREE, o.canvas, fn, w, h);
        const dims = it.kind === 'screen' ? it.size : [2 * it.r, 2 * it.r];
        mesh = new THREE.Mesh(new THREE.PlaneGeometry(dims[0], dims[1]), new THREE.MeshBasicMaterial({map: tex, color: tex ? 0xffffff : (it.kind === 'screen' ? 0x0a1a10 : 0xf7f7f7)}));
        // ระนาบตั้งขึ้น (บน = +Z) แล้วหันหน้าเข้าห้อง: จอมอนิเตอร์อยู่ผนังด้านศีรษะ (หน้าไป +X), นาฬิกาอยู่ผนังด้านเท้า (หน้าไป -X)
        mesh.rotation.order = 'ZXY';
        mesh.rotation.set(Math.PI / 2, 0, it.kind === 'screen' ? Math.PI / 2 : -Math.PI / 2);
      }
      if (!mesh) continue;
      mesh.name = it.name;
      const p = it.pos || [0, 0, 0];                       // ผ้าคลุมใช้พิกัดโลกในเรขาคณิตเอง
      mesh.position.set(p[0], p[1], p[2]);
      if (it.kind === 'shadow') { /* ระนาบ XY อยู่ราบกับพื้นอยู่แล้ว */ }
      if (it.kind === 'box' && it.rotZ) mesh.rotation.z = it.rotZ;
      if (it.kind === 'shadow') mesh.renderOrder = 1;
      group.add(mesh);
    }
    // แสง: โคมผ่าตัดส่องหน้าอก + แสงฟ้า-พื้นอ่อนๆ ให้ห้องไม่ทึบ
    const spot = new THREE.SpotLight(0xfff2dd, 0.5, 0, 0.55, 0.7, 1);
    spot.position.set(L.lamp.pos[0], L.lamp.pos[1], L.lamp.pos[2]);
    spot.target.position.set(L.lamp.target[0], L.lamp.target[1], L.lamp.target[2]);
    group.add(spot); group.add(spot.target);
    group.add(new THREE.HemisphereLight(0xffffff, 0x9aa7ad, 0.25));
    return group;
  }

  return {layout, build, DEFAULTS: D, COLORS: C};
});