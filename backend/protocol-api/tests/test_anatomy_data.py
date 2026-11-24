"""ทดสอบไฟล์โมเดลร่างกายจริง static/anatomy/ (สร้างโดย tools/build_anatomy.py จาก BodyParts3D) และตัวช่วย tools/bp3d_lib.py

ไฟล์ต้นฉบับ BodyParts3D ไม่อยู่ใน repo: เทสต์ตรวจเฉพาะผลลัพธ์ที่ commit ไว้ (ทิศ หน่วย ตำแหน่งอวัยวะ ตารางหน้าตัด ตารางซี่โครง)
"""
import json
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import bp3d_lib as B  # noqa: E402
from anatomy_io import load_anatomy  # noqa: E402

DATA = os.path.join(ROOT, "static", "anatomy")
MAN, MESH = load_anatomy(DATA)
P = MAN["polar"]
NZ, NTH = P["nz"], P["nth"]
ZS = P["z0"] + np.arange(NZ) * P["dz"]
RS = np.array(P["rs"]).reshape(NZ, NTH) * P["scale"]["r"]
RI = np.array(P["ri"]).reshape(NZ, NTH) * P["scale"]["r"]
RIB_Z = np.array([[np.nan if x is None else x * MAN["ribs"]["scale"] for x in row] for row in MAN["ribs"]["z"]])
DEG = np.pi / 180


def group(g):
    return [(mid, v, f, name) for mid, (v, f, grp, name) in MESH.items() if grp == g]


def centroid(g):
    return np.vstack([v for _, v, _, _ in group(g)]).mean(axis=0)


class AssetTests(unittest.TestCase):
    def test_files_and_size(self):
        size = os.path.getsize(os.path.join(DATA, "anatomy.bin"))
        self.assertEqual(size, MAN["binBytes"])
        self.assertLess(size, 6_000_000)                 # โหลดผ่านเว็บฟรีได้ไม่หนักเกิน
        self.assertEqual(MAN["version"], 1)

    def test_attribution_present(self):
        self.assertIn("BodyParts3D", MAN["attribution"])
        self.assertIn("CC Attribution 4.0", MAN["attribution"])
        self.assertTrue(os.path.exists(os.path.join(DATA, "ATTRIBUTION.txt")))

    def test_all_meshes_valid(self):
        for mid, (v, f, grp, name) in MESH.items():
            self.assertTrue(np.isfinite(v).all(), mid)
            self.assertGreater(len(f), 0, mid)
            self.assertLess(f.max(), len(v), mid)
            self.assertEqual(len(np.unique(f)), len(v), f"{mid}: มีจุดยอดที่ไม่ถูกใช้")


class AnatomyTests(unittest.TestCase):
    def test_expected_parts_present(self):
        self.assertEqual(len(group("rib")), 24)
        self.assertEqual(len(group("sternum")), 3)
        self.assertEqual(len(group("clav")), 2)
        self.assertEqual(len(group("scap")), 2)
        self.assertEqual(len([1 for _, _, _, n in group("vert") if "thoracic" in n]), 12)
        for mid in ("skin", "liver", "heart_atria", "heart_ventricles", "vessels", "airways"):
            self.assertIn(mid, MESH)

    def test_patient_frame_orientation_and_units(self):
        """x = หน้า(+), y = ซ้ายผู้ป่วย(+), z = ศีรษะ(+) หน่วยเมตร"""
        skin = MESH["skin"][0]
        height = skin[:, 2].max() - skin[:, 2].min()
        self.assertTrue(1.55 < height < 1.90, height)
        self.assertGreater(centroid("heart")[1], 0.0)            # หัวใจเอียงไปทางซ้ายของผู้ป่วย
        self.assertLess(MESH["liver"][0][:, 1].mean(), 0.0)      # ตับอยู่ด้านขวา
        self.assertGreater(np.vstack([v for _, v, _, _ in group("sternum")])[:, 0].mean(), 0.05)   # กระดูกอกอยู่ด้านหน้า
        self.assertLess(np.vstack([v for _, v, _, n in group("vert") if "thoracic" in n])[:, 0].mean(), -0.03)   # กระดูกสันหลังอยู่ด้านหลัง

    def test_suprasternal_notch_at_0232(self):
        manu = [v for _, v, _, n in group("sternum") if n == "Manubrium"][0]
        self.assertAlmostEqual(float(manu[:, 2].max()), MAN["landmarks"]["notchZ"], delta=0.002)
        self.assertAlmostEqual(MAN["landmarks"]["notchZ"], 0.232)

    def test_origin_is_rib_cage_mid_depth(self):
        ribs = np.vstack([v for _, v, _, n in group("rib") if any(w in n for w in ("fourth", "fifth", "sixth", "seventh"))])
        self.assertAlmostEqual(float((ribs[:, 0].min() + ribs[:, 0].max()) / 2), 0.0, delta=0.003)
        self.assertAlmostEqual(float((ribs[:, 1].min() + ribs[:, 1].max()) / 2), 0.0, delta=0.006)   # สมมาตรซ้าย-ขวา

    def test_back_plane_below_chest(self):
        self.assertLess(MAN["landmarks"]["backX"], -0.10)
        self.assertGreater(MAN["landmarks"]["backX"], -0.20)

    def test_ribs_are_ordered_top_to_bottom(self):
        for deg in (90, 270):                                    # ด้านข้างซ้าย/ขวา
            col = RIB_Z[:, int(deg / 360 * NTH)]
            for k in range(3, 9):
                self.assertTrue(np.isfinite(col[k]) and np.isfinite(col[k - 1]))
                self.assertLess(col[k], col[k - 1])
            self.assertTrue(0.05 < col[3] - col[6] < 0.16)       # ซี่ 4 ถึง 7 ห่างกัน 5-16 cm


class TableTests(unittest.TestCase):
    def test_skin_outside_cage(self):
        chest = (ZS > 0.0) & (ZS < 0.22)
        self.assertTrue((RS[chest] > RI[chest] + 0.005).all())
        self.assertTrue(np.isfinite(RS).all() and np.isfinite(RI).all())

    def test_chest_wall_thickness_is_plausible_at_zone(self):
        for z in (0.06, 0.09, 0.12, 0.15):
            i = int(round((z - P["z0"]) / P["dz"]))
            for deg in (60, 75, 90, 270, 285, 300):
                th = int(deg / 360 * NTH)
                self.assertTrue(0.02 < RS[i, th] - RI[i, th] < 0.07, (z, deg, RS[i, th] - RI[i, th]))

    def test_mediastinum_sides(self):
        medL, medR = np.array(P["medL"]), np.array(P["medR"])
        self.assertTrue((medL > -0.05 / P["scale"]["med"]).all())
        i = int(round((0.14 - P["z0"]) / P["dz"]))
        self.assertGreater(medL[i] * P["scale"]["med"], 0.05)     # หัวใจยื่นไปทางซ้ายมากกว่าขวา
        self.assertLess(medR[i] * P["scale"]["med"], -0.02)

    def test_rib_table_covers_the_site_zone(self):
        for deg in range(24, 151, 3):
            for th in (deg, 360 - deg):
                i = int(th / 360 * NTH)
                self.assertTrue(np.isfinite(RIB_Z[3, i]) and np.isfinite(RIB_Z[6, i]), (th,))
                self.assertGreater(RIB_Z[3, i], RIB_Z[6, i])


class LibTests(unittest.TestCase):
    @staticmethod
    def sphere(n=24, r=50.0):
        """ทรงกลมสามเหลี่ยมจากกริดมุม (มีขั้วที่จุดยอดซ้ำ ใช้ทดสอบ weld)"""
        v, f = [], []
        for i in range(n + 1):
            a = np.pi * i / n
            for j in range(2 * n):
                b = np.pi * j / n
                v.append([r * np.sin(a) * np.cos(b), r * np.sin(a) * np.sin(b), r * np.cos(a)])
        w = 2 * n
        for i in range(n):
            for j in range(w):
                p, q = i * w + j, i * w + (j + 1) % w
                f += [(p, q, p + w), (q, q + w, p + w)]
        return np.array(v), np.array(f, dtype=np.int32)

    def test_weld_merges_pole_duplicates(self):
        v, f = self.sphere()
        v2, f2 = B.weld(v, f)
        self.assertLess(len(v2), len(v))
        self.assertTrue(((f2[:, 0] != f2[:, 1]) & (f2[:, 1] != f2[:, 2]) & (f2[:, 0] != f2[:, 2])).all())

    def test_cluster_simplify_reduces_and_keeps_shape(self):
        v, f = B.weld(*self.sphere(40))
        v2, f2 = B.cluster_simplify(v, f, 8.0)
        self.assertLess(len(f2), len(f) / 3)
        self.assertLess(f2.max(), len(v2))
        r = np.linalg.norm(v2, axis=1)
        self.assertLess(abs(r.mean() - 50.0), 3.0)                # ยังเป็นทรงกลมรัศมี ~50
        self.assertLess(np.abs(v2.max(axis=0) - 50.0).max(), 6.0)

    def test_slice_loop_of_cube(self):
        v = np.array([[x, y, z] for x in (0, 10) for y in (0, 10) for z in (0, 10)], dtype=float)
        quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        f = np.array([t for q in quads for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))], dtype=np.int32)
        segs = B.slice_segments(v, f, 5.0)
        loops = B.segment_loops(segs)
        self.assertEqual(len(loops), 1)
        pts = loops[0].reshape(-1, 2)
        self.assertAlmostEqual(float(pts[:, 0].min()), 0.0)
        self.assertAlmostEqual(float(pts[:, 0].max()), 10.0)


class SkinTests(unittest.TestCase):
    def test_skin_is_smooth_single_layer(self):
        """ผิวต้องเป็นผิวชั้นนอกชั้นเดียว: เคยปนผิวชั้นใน (เปลือก 2 ชั้นของ BodyParts3D) แล้วขรุขระ ~56 องศา"""
        v, f, _, _ = MESH["skin"]
        cz = v[f].mean(axis=1)[:, 2]
        torso = (cz > 0.0) & (cz < 0.3) & (np.abs(v[f].mean(axis=1)[:, 1]) < 0.17)
        self.assertLess(B.roughness_deg(v, f, torso), 9.0)
        self.assertLess(B.roughness_deg(v, f), 9.0)
        for z in (-0.3, 0.05, 0.3):                              # ชั้นเดียว: วงนอกของแต่ละหน้าตัดไม่ซ้อนกันสองชั้น
            segs = B.slice_segments(v, f, z)
            loops = B.segment_loops(segs)
            self.assertLessEqual(len(loops), 4, (z, len(loops)))   # ลำตัว/ขา + แขน (ไม่ใช่ 2 เท่า)

    def test_skin_has_no_floating_shard_at_eye_level(self):
        v, f, _, _ = MESH["skin"]
        z_eye = (1520.0 - MAN["landmarks"]["ztopBp"]) / 1000.0 + MAN["landmarks"]["notchZ"]
        cen = v[f].mean(axis=1)
        band = np.abs(cen[:, 2] - z_eye) < 0.006
        fn, _ = B.face_normals_area(v, f)
        horizontal = np.abs(fn[:, 2]) > 0.95
        self.assertLess(int((band & horizontal).sum()), 40)       # แผ่นราบลอยในหัวต้องหมดไป

    def test_polar_skin_uses_outer_surface(self):
        v, f, _, _ = MESH["skin"]
        i = int(round((0.09 - P["z0"]) / P["dz"]))
        th = int(285 / 360 * NTH)
        cx, cy = P["cx"][i] * 1e-5, P["cy"][i] * 1e-5
        ang = (th + 0.5) * 2 * np.pi / NTH
        d = np.array([np.cos(ang), np.sin(ang)])
        sel = (np.abs(v[:, 2] - 0.09) < 0.004)
        rel = v[sel][:, :2] - np.array([cx, cy])
        along = rel @ d
        perp = np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0])
        r_mesh = along[(perp < 0.006) & (along > 0.1)].max()
        self.assertAlmostEqual(float(RS[i, th]), float(r_mesh), delta=0.006)   # ตารางตรงกับผิวนอกของเมช (ไม่ใช่ผิวใน ~2 mm)


class SkinLibTests(unittest.TestCase):
    @staticmethod
    def double_wall_sphere(n=26, r_out=50.0, r_in=47.0):
        def outward(v, f):      # ให้ตั้งฉากชี้ออกจากจุดศูนย์กลาง (ดูจากปริมาตรมีเครื่องหมาย)
            a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
            vol = np.einsum("ij,ij->i", a, np.cross(b, c)).sum()
            return f if vol > 0 else f[:, ::-1]
        vo, fo = LibTests.sphere(n, r_out)
        vi, fi = LibTests.sphere(n, r_in)
        fo, fi = outward(vo, fo), outward(vi, fi)
        v = np.vstack([vo, vi]); f = np.vstack([fo, fi[:, ::-1] + len(vo)])   # ผิวในกลับทิศ (ตั้งฉากชี้เข้าหาแกน = ออกจากเนื้อเปลือก)
        return B.weld(v, f)

    def test_classify_outer_faces_picks_outer_shell(self):
        v, f = self.double_wall_sphere()
        outer = B.classify_outer_faces(v, f, 2.0)
        cr = np.linalg.norm(v[f].mean(axis=1), axis=1)
        self.assertGreater(outer[cr > 48.5].mean(), 0.95)
        self.assertLess(outer[cr < 48.5].mean(), 0.05)

    def test_fill_small_holes_closes_small_but_not_large(self):
        n = 41                                                                   # กริดระนาบ 40x40 ช่อง ช่องละ 1 mm
        v = np.array([[x, y, 0.0] for y in range(n) for x in range(n)])
        f = []
        for y in range(n - 1):
            for x in range(n - 1):
                a, b, c, d = y * n + x, y * n + x + 1, (y + 1) * n + x, (y + 1) * n + x + 1
                f += [(a, b, d), (a, d, c)]
        f = np.array(f, dtype=np.int32)
        cen = v[f].mean(axis=1)
        small = (np.abs(cen[:, 0] - 10) < 2) & (np.abs(cen[:, 1] - 10) < 2)      # รู 4x4 (ขอบ ~16 mm)
        big = (np.abs(cen[:, 0] - 28) < 6) & (np.abs(cen[:, 1] - 28) < 6)        # รู 12x12 (ขอบ ~48 mm)
        f2 = f[~(small | big)]
        v3, f3 = B.fill_small_holes(v, f2, max_perimeter=30.0)                   # ขอบนอกของกริด ~160 mm ก็ไม่ถูกปิด
        self.assertEqual(len(v3), len(v) + 1)                                    # ปิดรูเล็กรูเดียว
        self.assertEqual(len(f3) - len(f2), 16)                                  # พัดสามเหลี่ยม 16 หน้า (ตามจำนวนจุดบนขอบ)

    def test_drop_small_smooth_components_only_in_region(self):
        v, f = B.weld(*LibTests.sphere(24, 50.0))
        shard_v = np.array([[0, 0, 80.0], [10, 0, 80.0], [0, 10, 80.0]])      # แผ่นสามเหลี่ยมเดี่ยวลอยแยก
        v2 = np.vstack([v, shard_v]); f2 = np.vstack([f, [[len(v), len(v) + 1, len(v) + 2]]]).astype(np.int32)
        keep_all = B.drop_small_smooth_components(v2, f2, lambda c: c[:, 2] < 0, 500)       # ภูมิภาคไม่ครอบคลุมแผ่น
        self.assertEqual(len(keep_all), len(f2))
        dropped = B.drop_small_smooth_components(v2, f2, lambda c: c[:, 2] > 60, 500)
        self.assertEqual(len(dropped), len(f))


class EnvTests(unittest.TestCase):
    """ข้อมูลสำหรับฉากห้อง: โปรไฟล์ขา (ผ้าคลุม) และท้ายทอย (หมอน)"""
    E = MAN["env"]

    def test_leg_profile(self):
        e = self.E
        self.assertEqual(len(e["halfWidthMm"]), e["n"])
        self.assertEqual(len(e["anteriorXMm"]), e["n"])
        zs = e["z0"] + np.arange(e["n"]) * e["dz"]
        self.assertLess(zs[0], -1.2)
        self.assertGreater(zs[-1], -0.1)                         # สิ้นสุดที่ใต้ซี่โครง (ผ้าคลุมไม่ปิดหน้าอก)
        hw = np.array(e["halfWidthMm"]) / 1000.0
        self.assertTrue(((hw > 0.04) & (hw < 0.25)).all(), hw)    # ตัดแขนออกแล้ว: ไม่กว้างเท่าช่วงแขน
        ax_ = np.array(e["anteriorXMm"]) / 1000.0
        self.assertTrue(((ax_ > -0.05) & (ax_ < 0.35)).all(), ax_)

    def test_head_numbers(self):
        e = self.E
        skin = MESH["skin"][0]
        self.assertAlmostEqual(e["headTopZ"], float(skin[:, 2].max()), delta=0.002)
        self.assertAlmostEqual(e["footZ"], float(skin[:, 2].min()), delta=0.002)
        self.assertTrue(-0.2 < e["headBackX"] < -0.05)           # ท้ายทอยอยู่หลังกึ่งกลางความลึกกรงซี่โครงแต่ไม่ลึกเกินไป
        self.assertGreater(e["headBackX"], MAN["landmarks"]["backX"])   # ท้ายทอยสูงกว่าหลังส่วนอก: ต้องมีหมอนรอง


if __name__ == "__main__":
    unittest.main()