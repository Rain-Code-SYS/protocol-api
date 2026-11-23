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


if __name__ == "__main__":
    unittest.main()
