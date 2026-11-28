#!/usr/bin/env python3
"""แปลงโมเดล BodyParts3D (partof_BP3D_4.0_obj_99) เป็นไฟล์ที่หน้า Simulation โหลดได้: static/anatomy/anatomy.json + anatomy.bin

รัน (จากโฟลเดอร์ protocol-api):
    python tools/build_anatomy.py --src /path/to/partof_BP3D_4.0_obj_99 --out static/anatomy

ผลลัพธ์
- meshes: ผิวหนังทั้งตัว (เปลือกนอก), กระดูกซี่โครง/กระดูกอ่อน/กระดูกอก/ไหปลาร้า/สะบัก/ต้นแขน/กระดูกสันหลัง/กระดูกเชิงกราน sacrum,
  กะบังลม ตับ กระเพาะ หัวใจ หลอดเลือดใหญ่ หลอดลม หลอดอาหาร  (ลดโพลีกอนแบบ quadric clustering, ตำแหน่งบีบเป็น int16)
- polar: ตารางหน้าตัดทรวงอกรอบแกนกลาง (รัศมีผิว / รัศมีด้านในกรงซี่โครง / ขอบมีเดียสตินัม) ใช้สร้างปอด จุดเจาะ และเวกเตอร์ตั้งฉากผิว
- ribs: ความสูง z ของแนวกลางซี่โครงแต่ละซี่ตามมุมรอบลำตัว ใช้ตัดสินโซนช่องซี่โครงที่ 4-6

พิกัดผลลัพธ์ = พิกัดผู้ป่วยของซิม (หน่วยเมตร): x = หน้า(+) / หลัง(-), y = ซ้ายของผู้ป่วย(+), z = ศีรษะ(+)
  z = 0.232 ที่รอยบุ๋มเหนือกระดูกอก (ขอบบน manubrium), x = 0 ที่ศูนย์กลางความลึกของกรงซี่โครง (ซี่ 4-7)

BodyParts3D, © The Database Center for Life Science, licensed under CC Attribution 4.0 International
(https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html)
"""
import argparse
import json
import os
import re
import struct
import sys

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bp3d_lib as B  # noqa: E402

ORD = "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth"
ORD_N = {w: i + 1 for i, w in enumerate(ORD.split("|"))}
NOTCH_Z = 0.232          # z (เมตร) ของรอยบุ๋มเหนือกระดูกอก ตามที่หน้า Simulation ใช้อยู่เดิม
TH_BINS = 120            # ช่องมุมรอบลำตัว (3 องศา)
DZ_MM = 4.0              # ระยะห่างหน้าตัด
SLICE_Z_BP = (880.0, 1420.0)   # ช่วง z ของ BodyParts3D ที่ทำตารางหน้าตัด (mm)

# (id, กลุ่ม/วัสดุ, ตัวเลือกไฟล์, cell mm ของการลดโพลีกอน หรือ None = ไม่ลด, inflate mm)
CELL = {"rib": 2.5, "cart": 2.5, "sternum": 2.0, "clav": 2.0, "scap": 4.0, "humerus": 3.0, "vert": 3.0,
        "sacrum": 3.5, "diaphragm": 6.0, "liver": 5.0, "stomach": 4.0, "heart": 3.0, "vessel": 2.0,
        "airway": None, "esoph": 1.5, "skin": 4.0}


def pick(by_name, pattern):
    rx = re.compile(pattern)
    out = []
    for name, paths in by_name.items():
        if name and rx.search(name):
            out += [(name, p) for p in paths]
    return sorted(out, key=lambda t: (t[0], t[1]))


def compact(v, f):
    used = np.unique(f)
    remap = -np.ones(len(v), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return v[used], remap[f].astype(np.int32)


def outer_shell(v, f):
    """เก็บเฉพาะก้อนผิวที่ใหญ่ที่สุด (ตัดชิ้นเศษ) -- ผิวหนังของ BodyParts3D เป็นเปลือก 2 ชั้นที่เชื่อมกันที่ปากช่อง
    จึงต้องแยกชั้นในออกอีกขั้นด้วย B.classify_outer_faces"""
    n = len(v)
    e = np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    k, lab = connected_components(g, directed=False)
    best, best_vol = None, -1.0
    for c in range(k):
        m = lab == c
        if m.sum() < 100:
            continue
        ext = v[m].max(axis=0) - v[m].min(axis=0)
        vol = float(np.prod(ext))
        if vol > best_vol:
            best, best_vol = c, vol
    keep = lab[f[:, 0]] == best
    f2 = f[keep]
    used = np.unique(f2)
    remap = -np.ones(n, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return v[used], remap[f2].astype(np.int32), k


class Pack:
    """เก็บเมชเป็นไบนารี: positions uint16 (ปรับสเกลตาม bbox ของชิ้น) + indices uint16/uint32"""

    def __init__(self):
        self.buf = bytearray()
        self.meshes = []

    def _align(self):
        while len(self.buf) % 4:
            self.buf.append(0)

    def add(self, mid, group, name, v, f):
        lo, hi = v.min(axis=0), v.max(axis=0)
        span = np.maximum(hi - lo, 1e-9)
        q = np.round((v - lo) / span * 65535.0).astype(np.uint16)
        self._align()
        v_off = len(self.buf)
        self.buf += q.tobytes()
        self._align()
        i_off = len(self.buf)
        wide = len(v) > 65535
        self.buf += f.astype(np.uint32 if wide else np.uint16).tobytes()
        self.meshes.append({"id": mid, "group": group, "name": name, "nv": int(len(v)), "nf": int(len(f)),
                            "min": [round(float(x), 6) for x in lo], "max": [round(float(x), 6) for x in hi],
                            "vOff": v_off, "iOff": i_off, "wide": bool(wide)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="โฟลเดอร์ partof_BP3D_4.0_obj_99 (ไฟล์ .obj)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "anatomy"))
    ap.add_argument("--preview", default=None, help="โฟลเดอร์เก็บภาพตรวจสอบ (ไม่บังคับ)")
    ap.add_argument("--original", action="store_true",
                    help="ใช้เรขาคณิตตามไฟล์ BodyParts3D เดิมโดยไม่ดัดแปลงเมช: ไม่ขยายโพรงหัวใจ และผิวหนังไม่ผ่านขั้นทำความสะอาด "
                         "(ตัดผิวชั้นใน/เศษแหลม/เศษลอย/ปิดรู) เหลือแค่ลดโพลีกอนกับแปลงพิกัด; ตารางหน้าตัดยังคำนวณเหมือนเดิม")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    by_name, _ = B.index_dir(args.src)

    def load(paths):
        return B.merge([B.weld(*B.load_obj(p)) for p in paths])

    # ---------- เลือกชิ้นส่วน ----------
    parts = []   # (id, group, name, [paths])

    def add(group, items, merge_all=False, mid=None):
        if merge_all:
            parts.append((mid or group, group, mid or group, [p for _, p in items]))
        else:
            for name, p in items:
                parts.append((os.path.splitext(os.path.basename(p))[0], group, name, [p]))

    add("rib", pick(by_name, rf"^(Left|Right) ({ORD}) rib$"))
    add("cart", pick(by_name, rf"^(Left|Right) ({ORD}) costal cartilage$"))
    add("sternum", pick(by_name, r"^(Manubrium|Body of sternum|Xiphoid process)$"))
    add("clav", pick(by_name, r"^(Left|Right) clavicle$"))
    add("scap", pick(by_name, r"^(Left|Right) scapula$"))
    add("humerus", pick(by_name, r"^(Left|Right) humerus$"))
    add("vert", [(n, p) for n, p in pick(by_name, r"vertebra$") if "Intervertebral" not in n])
    add("sacrum", pick(by_name, r"^Sacrum$"))
    add("diaphragm", pick(by_name, r"^Diaphragm$"))
    add("liver", pick(by_name, r"^(Hepatovenous segment (II|III|IV|V|VI|VII|VIII)|Caudate lobe of liver)$"), True, "liver")
    add("stomach", pick(by_name, r"^Stomach$"))
    add("heart", pick(by_name, r"^(Wall of (left|right) atrium)$"), True, "heart_atria")
    add("heart", pick(by_name, r"^Cavity of (left|right) ventricle$"), True, "heart_ventricles")
    add("vessel", pick(by_name, r"^(Ascending aorta|Arch of aorta|Descending thoracic aorta|Pulmonary trunk|"
                                r"Left pulmonary artery|Right pulmonary artery|Superior vena cava|Inferior vena cava|"
                                r"Brachiocephalic artery)$"), True, "vessels")
    add("airway", pick(by_name, r"^(Trachea|Left main bronchus|Right main bronchus)$|bronchial tree$"), True, "airways")
    add("esoph", pick(by_name, r"^Esophagus$"))
    skin_paths = [p for _, p in pick(by_name, r"^Skin$")]
    assert skin_paths, "ไม่พบชิ้น Skin"

    # ---------- จุดอ้างอิงในพิกัด BodyParts3D (mm) ----------
    manu = load([p for n, p in pick(by_name, r"^Manubrium$")])[0]
    ztop = float(manu[:, 2].max())
    rib_meshes = {}
    for name, p in pick(by_name, rf"^(Left|Right) ({ORD}) rib$"):
        m = re.match(rf"^(Left|Right) ({ORD}) rib$", name)
        rib_meshes[(ORD_N[m.group(2)], m.group(1))] = B.weld(*B.load_obj(p))
    assert len(rib_meshes) == 24, f"พบซี่โครง {len(rib_meshes)} ซี่ (ต้อง 24)"
    cart_meshes = {}   # กระดูกอ่อนซี่โครง 1-7 ต่อกับปลายซี่โครงด้านหน้า: ใช้ต่อแนวกลางซี่โครงไปถึงกระดูกอก
    for name, p_ in pick(by_name, rf"^(Left|Right) ({ORD}) costal cartilage$"):
        m = re.match(rf"^(Left|Right) ({ORD}) costal cartilage$", name)
        cart_meshes[(ORD_N[m.group(2)], m.group(1))] = B.weld(*B.load_obj(p_))
    mid_ribs = np.vstack([rib_meshes[(k, s)][0] for k in (4, 5, 6, 7) for s in ("Left", "Right")])
    y0 = float((mid_ribs[:, 1].min() + mid_ribs[:, 1].max()) / 2)

    def to_patient(vmm):
        out = np.empty_like(vmm)
        out[:, 0] = -(vmm[:, 1] - y0) / 1000.0
        out[:, 1] = vmm[:, 0] / 1000.0
        out[:, 2] = (vmm[:, 2] - ztop) / 1000.0 + NOTCH_Z
        return out

    def z_to_bp(z):
        return (z - NOTCH_Z) * 1000.0 + ztop

    pack = Pack()
    stats = []

    # ---------- เมชทั่วไป ----------
    for mid, group, name, paths in parts:
        v, f = load(paths)
        if mid == "heart_ventricles" and not args.original:   # ผนังกล้ามเนื้อไม่มีในชุดข้อมูล: ขยายโพรงออก 8 mm ประมาณความหนาผนัง
            v = v + B.vertex_normals(v, f) * 8.0
        cell = CELL.get(group)
        n0 = len(f)
        if cell:
            v, f = B.cluster_simplify(v, f, cell)
        pack.add(mid, group, name, to_patient(v), f)
        stats.append((mid, group, n0, len(f)))

    # ---------- ผิวหนัง (เปลือกนอก) ----------
    sv, sf = load(skin_paths)
    sv, sf, ncomp = outer_shell(sv, sf)
    raw_skin = (sv.copy(), sf.copy())                 # ผิวตามไฟล์เดิม (ก้อนใหญ่สุดก้อนเดียว) ใช้แสดงผลเมื่อ --original
    keep = B.classify_outer_faces(sv, sf)             # ตัดผิวชั้นในทิ้ง (ไม่งั้นลดโพลีกอนแล้วสองชั้นปนกันเป็นผิวหยัก)
    n_shell = len(sf)
    sv, sf = compact(sv, sf[keep])
    n_outer = len(sf)
    sv, sf = B.drop_spiky_faces(sv, sf)               # เศษพับแหลมตรงเบ้าตา/ขาหนีบ
    # เปลือกตาในข้อมูลต้นฉบับเป็นรอยหยัก: ตัดเศษแหลมเฉพาะบริเวณใบหน้าให้เข้มขึ้น แล้วปิดรูเล็กรอบตา (รูใหญ่ เช่น ข้อมือ คอ ไม่ปิด)
    # ที่ระดับ z ≈ 1513-1526 มีแผ่นราบเล็กๆ ลอยอยู่ในหัว (รอยต่อของชิ้นผิว) โผล่ตรงเปลือกตา: ตัดทิ้ง
    sf = B.drop_small_smooth_components(sv, sf, lambda c: (c[:, 2] > 1500) & (c[:, 2] < 1540), 500)
    sv, sf = compact(sv, sf)
    sv, sf = B.fill_small_holes(sv, sf, 160.0)
    print(f"skin: outer faces {n_outer:,} / {n_shell:,} -> {len(sf):,} after cleanup; roughness {B.roughness_deg(sv, sf):.2f} deg")
    skin_full = (sv.copy(), sf.copy())
    # skin_full (ทำความสะอาดแล้ว) ใช้คำนวณตารางหน้าตัด/จุดอ้างอิงเสมอ; เมชที่แสดงเป็นผิวเดิมเมื่อ --original
    show_v, show_f = raw_skin if args.original else skin_full
    sv_s, sf_s = B.cluster_simplify(show_v, show_f, CELL["skin"])
    pack.add("skin", "skin", "Skin", to_patient(sv_s), sf_s)
    stats.append(("skin", "skin", len(show_f), len(sf_s)))

    # ---------- ตารางหน้าตัด (polar map) ----------
    # จุดของกระดูกอก/ซี่โครง/กระดูกอ่อน/กระดูกสันหลังส่วนอก ใช้หาแกนกลางและขอบด้านในของกรงซี่โครง
    cage_pts = [m[0] for m in rib_meshes.values()]
    for _, grp, name, paths in parts:
        if grp in ("cart", "sternum") or (grp == "vert" and "thoracic" in name):
            cage_pts.append(load(paths)[0])
    cage = np.vstack(cage_pts)
    # มีเดียสตินัม = หัวใจ + หลอดเลือดใหญ่ + หลอดลมคอ/หลอดลมใหญ่ + หลอดอาหาร (ไม่รวมกิ่งหลอดลมย่อยและหลอดเลือดแดงปอดที่แทรกเข้าเนื้อปอด)
    MED_RX = re.compile(r"^(Wall of (left|right) atrium|Cavity of (left|right) ventricle|Ascending aorta|Arch of aorta|"
                        r"Descending thoracic aorta|Pulmonary trunk|Superior vena cava|Inferior vena cava|Brachiocephalic artery|"
                        r"Trachea|Left main bronchus|Right main bronchus|Esophagus)$")
    med_pts = []
    for name, paths in by_name.items():
        if name and MED_RX.search(name):
            for p_ in paths:
                v_ = B.load_obj(p_)[0]
                med_pts.append(v_)
    med = np.vstack(med_pts)

    zs = np.arange(SLICE_Z_BP[0], SLICE_Z_BP[1] + 0.1, DZ_MM)
    nz = len(zs)
    th = (np.arange(TH_BINS) + 0.5) * 2 * np.pi / TH_BINS
    cx = np.zeros(nz); cy = np.zeros(nz)
    r_skin = np.full((nz, TH_BINS), np.nan)
    r_in = np.full((nz, TH_BINS), np.nan)
    med_l = np.full(nz, np.nan); med_r = np.full(nz, np.nan)   # ขอบมีเดียสตินัมในพิกัด y ของผู้ป่วย (mm จากแกนกลาง; ซ้าย +, ขวา -)

    # แกนกลาง: กึ่งกลางขอบเขตของกรงซี่โครงในแต่ละชั้น (BodyParts3D: x = ซ้าย+, y = หลัง+)
    zc_all = cage[:, 2]
    for i, z in enumerate(zs):
        m = np.abs(zc_all - z) < 10.0
        if m.sum() >= 20:
            cx[i] = (cage[m, 0].min() + cage[m, 0].max()) / 2
            cy[i] = (cage[m, 1].min() + cage[m, 1].max()) / 2
        else:
            cx[i] = cy[i] = np.nan
    ok = ~np.isnan(cx)
    cx = np.interp(zs, zs[ok], cx[ok]); cy = np.interp(zs, zs[ok], cy[ok])
    # ทำให้เรียบ
    k = np.ones(7) / 7
    cx = np.convolve(np.pad(cx, 3, mode="edge"), k, mode="valid")
    cy = np.convolve(np.pad(cy, 3, mode="edge"), k, mode="valid")

    # มุม θ (ตามซิม): 0 = ด้านหน้า (-y_bp), เพิ่มไปทางซ้ายผู้ป่วย (+x_bp)
    def theta_of(dx_bp, dy_bp):
        return np.mod(np.arctan2(dx_bp, -dy_bp), 2 * np.pi)

    def radial_hits(segs, c_x, c_y):
        """ยิงรังสีจากจุดศูนย์กลาง (c_x,c_y) ที่มุมของซิม คืนรัศมีแรกที่ชนเส้นตัดของผิว"""
        d = np.stack([np.sin(th), -np.cos(th)], axis=1)        # ทิศใน (x_bp, y_bp)
        p = segs[:, 0, :] - np.array([c_x, c_y])
        e = segs[:, 1, :] - segs[:, 0, :]
        denom = d[:, None, 0] * e[None, :, 1] - d[:, None, 1] * e[None, :, 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (p[None, :, 0] * e[None, :, 1] - p[None, :, 1] * e[None, :, 0]) / denom
            u = (p[None, :, 0] * d[:, None, 1] - p[None, :, 1] * d[:, None, 0]) / denom
        good = (np.abs(denom) > 1e-9) & (t > 0) & (u >= 0) & (u <= 1)
        t = np.where(good, t, np.inf)
        return t.min(axis=1)

    for i, z in enumerate(zs):
        segs = B.slice_segments(skin_full[0], skin_full[1], z)
        if len(segs):
            r = radial_hits(segs, cx[i], cy[i])
            r_skin[i] = np.where(np.isfinite(r), r, np.nan)
        m = np.abs(zc_all - z) < 9.0
        if m.sum():
            q = cage[m]
            a = theta_of(q[:, 0] - cx[i], q[:, 1] - cy[i])
            rr = np.hypot(q[:, 0] - cx[i], q[:, 1] - cy[i])
            bins = np.minimum((a / (2 * np.pi) * TH_BINS).astype(int), TH_BINS - 1)
            for b in range(TH_BINS):
                s = rr[bins == b]
                if len(s):
                    r_in[i, b] = s.min()
        mm = np.abs(med[:, 2] - z) < 6.0
        if mm.sum():
            xs = med[mm, 0]
            med_l[i] = xs.max() - cx[i]
            med_r[i] = xs.min() - cx[i]

    def fill_circular(row):
        """เติมช่องว่างของแถวมุม (วงกลม) ด้วย interpolation"""
        good = ~np.isnan(row)
        if good.sum() < 3:
            return None
        idx = np.arange(len(row))
        ext = np.concatenate([row[good], row[good][:1]])
        xs = np.concatenate([idx[good], [idx[good][0] + len(row)]])
        return np.interp(idx, xs, ext, period=None)

    for i in range(nz):
        for arr in (r_in,):
            filled = fill_circular(arr[i])
            if filled is not None:
                arr[i] = filled
    # ขอบในเรียบขึ้น: median filter ตามมุม + ตามแนวสูง
    from scipy.ndimage import median_filter, uniform_filter1d

    def circ_median(a, size):
        """median filter 2 มิติ (แกนแรก = ความสูง ขอบแบบ nearest, แกนที่สอง = มุม ขอบแบบวงกลม)"""
        pad = size[1] // 2
        w = np.concatenate([a[:, -pad:], a, a[:, :pad]], axis=1) if pad else a
        return median_filter(w, size=size, mode="nearest")[:, pad:pad + a.shape[1]]
    r_in = np.where(np.isnan(r_in), np.nanmedian(r_in), r_in)
    r_in = circ_median(r_in, (5, 5))
    r_in = uniform_filter1d(r_in, size=3, axis=1, mode="wrap")

    # ความหนาเนื้อเยื่อปกติ = มัธยฐานของ (r_skin - r_in) ในช่วงอกด้านหน้า-ข้าง (ใช้แทนค่าบริเวณที่แขนบัง)
    thick = r_skin - r_in
    valid = np.isfinite(thick) & (thick > 5) & (thick < 70)
    t_med = float(np.median(thick[valid]))
    bad = ~valid
    r_skin2 = np.where(bad, r_in + t_med, r_skin)
    # รัศมีผิวต้องไม่น้อยกว่าขอบกระดูก+5mm และเรียบตามมุม
    r_skin2 = np.maximum(r_skin2, r_in + 5.0)
    r_skin2 = uniform_filter1d(circ_median(r_skin2, (3, 3)), size=3, axis=1, mode="wrap")
    med_l = np.where(np.isnan(med_l), np.nanmedian(med_l), med_l)
    med_r = np.where(np.isnan(med_r), np.nanmedian(med_r), med_r)
    med_l = uniform_filter1d(med_l, size=5, mode="nearest"); med_r = uniform_filter1d(med_r, size=5, mode="nearest")

    # ---------- ตารางความสูงของแนวกลางซี่โครงตามมุม ----------
    zrib = np.full((12, TH_BINS), np.nan)
    for (kk, side), (v, f) in rib_meshes.items():
        if (kk, side) in cart_meshes:
            v = np.vstack([v, cart_meshes[(kk, side)][0]])
        zi = np.clip(np.round((v[:, 2] - zs[0]) / DZ_MM).astype(int), 0, nz - 1)
        a = theta_of(v[:, 0] - cx[zi], v[:, 1] - cy[zi])
        bins = np.minimum((a / (2 * np.pi) * TH_BINS).astype(int), TH_BINS - 1)
        for b in np.unique(bins):
            s = v[bins == b, 2]
            if len(s) >= 3:
                zrib[kk - 1, b] = s.mean()
        # เติมช่องว่างเล็กๆ ภายในช่วงมุมที่ซี่โครงครอบคลุม (ซี่ซ้ายอยู่ครึ่งมุมแรก ซี่ขวาอยู่ครึ่งหลัง)
        sl = slice(0, TH_BINS // 2) if side == "Left" else slice(TH_BINS // 2, TH_BINS)
        row = zrib[kk - 1, sl].copy()
        good = ~np.isnan(row)
        if good.sum() >= 2:
            idx = np.arange(len(row))
            lo, hi = idx[good][0], idx[good][-1]
            row[lo:hi + 1] = np.interp(idx[lo:hi + 1], idx[good], row[good])
            zrib[kk - 1, sl] = row

    # ---------- แปลงตารางเป็นพิกัดผู้ป่วย (เมตร) ----------
    z_p = (zs - ztop) / 1000.0 + NOTCH_Z
    # แปลงจุดศูนย์กลางเป็นพิกัดผู้ป่วย: x = -(y_bp - y0)/1000, y = x_bp/1000
    cx_p = -(cy - y0) / 1000.0
    cy_p = cx / 1000.0
    zrib_p = (zrib - ztop) / 1000.0 + NOTCH_Z

    def q16(a, scale):
        return np.round(np.asarray(a) * scale).astype(np.int32).tolist()

    polar = {
        "z0": round(float(z_p[0]), 6), "dz": DZ_MM / 1000.0, "nz": int(nz), "nth": TH_BINS,
        "cx": q16(cx_p, 1e5), "cy": q16(cy_p, 1e5),                        # หน่วย 0.01 mm
        "rs": q16(r_skin2, 10), "ri": q16(r_in, 10),                       # หน่วย 0.1 mm
        "medL": q16(med_l, 10), "medR": q16(med_r, 10),                    # หน่วย 0.1 mm (ในแนว y ผู้ป่วย จากแกนกลาง)
        "scale": {"cxy": 1e-5, "r": 1e-4, "med": 1e-4},
        "tissueMedianMm": round(t_med, 2),
    }
    ribs = {"nth": TH_BINS, "z": [[None if np.isnan(x) else int(round(x * 1e5)) for x in row] for row in zrib_p],
            "scale": 1e-5}

    # ---------- ค่าอ้างอิงอื่นๆ ----------
    skin_t = to_patient(skin_full[0])
    torso = (skin_full[0][:, 2] > 1000) & (skin_full[0][:, 2] < 1330) & (np.abs(skin_full[0][:, 0]) < 160)
    back_x = float(skin_t[torso, 0].min())
    landmarks = {"notchZ": NOTCH_Z, "backX": round(back_x, 5), "ztopBp": ztop, "y0Bp": y0}

    # ---------- ข้อมูลสำหรับฉากห้อง: โปรไฟล์ขา (ผ้าคลุมผู้ป่วย) และท้ายทอย (หมอน) ----------
    leg = np.abs(skin_t[:, 1]) < 0.21                       # ตัดแขน/มือที่ห้อยข้างลำตัวออก
    env_z = np.arange(-1.26, -0.039, 0.04)
    half_w, ant_x = [], []
    for z in env_z:
        m = leg & (np.abs(skin_t[:, 2] - z) < 0.03)
        half_w.append(float(np.abs(skin_t[m, 1]).max()) if m.any() else np.nan)
        ant_x.append(float(skin_t[m, 0].max()) if m.any() else np.nan)
    half_w, ant_x = np.array(half_w), np.array(ant_x)
    for arr in (half_w, ant_x):
        ok_ = ~np.isnan(arr)
        arr[:] = np.interp(env_z, env_z[ok_], arr[ok_])
    half_w = uniform_filter1d(half_w, size=3, mode="nearest")
    ant_x = uniform_filter1d(ant_x, size=3, mode="nearest")
    head = (skin_t[:, 2] > 0.40) & (skin_t[:, 2] < 0.56)
    env = {"z0": round(float(env_z[0]), 4), "dz": 0.04, "n": int(len(env_z)),
           "halfWidthMm": [int(round(x * 1000)) for x in half_w], "anteriorXMm": [int(round(x * 1000)) for x in ant_x],
           "headBackX": round(float(skin_t[head, 0].min()), 4), "headTopZ": round(float(skin_t[:, 2].max()), 4),
           "footZ": round(float(skin_t[:, 2].min()), 4)}

    with open(os.path.join(args.out, "anatomy.bin"), "wb") as fh:
        fh.write(pack.buf)
    manifest = {
        "version": 1,
        "units": "m, patient frame (x anterior, y patient-left, z superior)",
        "attribution": "BodyParts3D, © The Database Center for Life Science, licensed under CC Attribution 4.0 International "
                       "(https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html). Modified: coordinate transform, mesh simplification.",
        "meshes": pack.meshes, "polar": polar, "ribs": ribs, "landmarks": landmarks, "env": env, "binBytes": len(pack.buf),
    }
    with open(os.path.join(args.out, "anatomy.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, separators=(",", ":"))

    tot_f = sum(m["nf"] for m in pack.meshes)
    by_group = {}
    for m in pack.meshes:
        by_group[m["group"]] = by_group.get(m["group"], 0) + m["nf"]
    print("faces by group:", {k: f"{v:,}" for k, v in sorted(by_group.items(), key=lambda kv: -kv[1])})
    print(f"meshes {len(pack.meshes)}, faces {tot_f:,}, bin {len(pack.buf)/1e6:.2f} MB, skin shells {ncomp}")
    print(f"landmarks {landmarks}; tissue median {t_med:.1f} mm")
    for mid, grp, n0, n1 in stats:
        if grp in ("skin", "liver", "heart") or n0 > 12000:
            print(f"  {mid:20s} {grp:9s} {n0:>8,} -> {n1:>8,}")
    return manifest


if __name__ == "__main__":
    main()