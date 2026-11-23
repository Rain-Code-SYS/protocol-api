"""ตัวช่วยอ่าน/แปลง/ลดโพลีกอนโมเดล BodyParts3D (OBJ) สำหรับ tools/build_anatomy.py

BodyParts3D, © The Database Center for Life Science, CC Attribution 4.0 International
(https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html)
"""
import glob
import os
import re

import numpy as np


def load_obj(path):
    """อ่าน OBJ ที่มีเฉพาะ v และ f (สามเหลี่ยม) คืน (verts float64 (N,3) หน่วย mm, faces int32 (M,3))"""
    verts, faces = [], []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line.startswith("v "):
                verts.append(line[2:].split()[:3])
            elif line.startswith("f "):
                idx = [int(tok.split("/")[0]) for tok in line[2:].split()]
                for i in range(1, len(idx) - 1):          # polygon -> fan
                    faces.append((idx[0], idx[i], idx[i + 1]))
    v = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3) - 1
    return v, f.astype(np.int32)


def read_header(path):
    info = {}
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            m = re.match(r"#\s*(English name|Concept ID|File ID)\s*:\s*(.*)", line)
            if m:
                info[m.group(1)] = m.group(2).strip()
    return info


def index_dir(src):
    """{ชื่ออังกฤษ: [ไฟล์,...]} และ {file_id: ชื่อ}"""
    by_name, by_id = {}, {}
    for p in sorted(glob.glob(os.path.join(src, "*.obj"))):
        h = read_header(p)
        name = h.get("English name")
        fid = os.path.splitext(os.path.basename(p))[0]
        by_id[fid] = name
        by_name.setdefault(name, []).append(p)
    return by_name, by_id


def merge(meshes):
    """รวมหลายเมช (verts, faces) เป็นชิ้นเดียว"""
    vs, fs, off = [], [], 0
    for v, f in meshes:
        vs.append(v)
        fs.append(f + off)
        off += len(v)
    return np.vstack(vs), np.vstack(fs).astype(np.int32)


def weld(verts, faces, tol=1e-4):
    """รวมจุดยอดซ้ำ (ตำแหน่งเดียวกัน) แล้วตัดสามเหลี่ยมเสื่อม"""
    key = np.round(verts / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    v2 = verts[first]
    f2 = inv[faces]
    ok = (f2[:, 0] != f2[:, 1]) & (f2[:, 1] != f2[:, 2]) & (f2[:, 0] != f2[:, 2])
    return v2, f2[ok].astype(np.int32)


def face_normals_area(verts, faces):
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    n = np.cross(b - a, c - a)
    area2 = np.linalg.norm(n, axis=1)
    return n / np.maximum(area2, 1e-12)[:, None], area2 * 0.5


def vertex_normals(verts, faces):
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    fn = np.cross(b - a, c - a)            # ขนาด = 2*พื้นที่ → ถ่วงน้ำหนักตามพื้นที่โดยอัตโนมัติ
    vn = np.zeros_like(verts)
    for k in range(3):
        np.add.at(vn, faces[:, k], fn)
    return vn / np.maximum(np.linalg.norm(vn, axis=1), 1e-12)[:, None]


def cluster_simplify(verts, faces, cell):
    """ลดโพลีกอนด้วย vertex clustering แบบ quadric (Lindstrom / Garland-Heckbert):
    แบ่งพื้นที่เป็นกริดขนาด `cell` mm รวม quadric ของทุกจุดยอดในช่อง แล้วหาจุดที่ error น้อยสุด (บีบให้อยู่ในช่อง)
    คืน (verts, faces) ใหม่ ผิวเรียบกว่า centroid และเก็บขอบ/สันได้ดีกว่า"""
    verts, faces = weld(verts, faces)
    fn, area = face_normals_area(verts, faces)
    d = -np.einsum("ij,ij->i", fn, verts[faces[:, 0]])
    plane = np.hstack([fn, d[:, None]])                      # (M,4)
    Kf = area[:, None, None] * plane[:, :, None] * plane[:, None, :]   # (M,4,4)
    Kv = np.zeros((len(verts), 4, 4))
    for k in range(3):
        np.add.at(Kv, faces[:, k], Kf)
    lo = verts.min(axis=0)
    ijk = np.floor((verts - lo) / cell).astype(np.int64)
    dims = ijk.max(axis=0) + 1
    key = (ijk[:, 0] * dims[1] + ijk[:, 1]) * dims[2] + ijk[:, 2]
    uniq, inv = np.unique(key, return_inverse=True)
    inv = inv.reshape(-1)
    Kc = np.zeros((len(uniq), 4, 4))
    np.add.at(Kc, inv, Kv)
    cnt = np.bincount(inv, minlength=len(uniq)).astype(np.float64)
    cen = np.zeros((len(uniq), 3))
    for k in range(3):
        cen[:, k] = np.bincount(inv, weights=verts[:, k], minlength=len(uniq)) / cnt
    A = Kc[:, :3, :3]
    b = -Kc[:, :3, 3]
    # ถ่วงเข้าหา centroid เล็กน้อย (regularize) กัน A เอกพันธ์บนผิวแบนๆ
    trace = np.trace(A, axis1=1, axis2=2)
    lam = 1e-3 * np.maximum(trace, 1e-9)
    A = A + lam[:, None, None] * np.eye(3)
    b = b + lam[:, None] * cen
    x = np.linalg.solve(A, b[:, :, None])[:, :, 0]
    cell_lo = lo + (np.stack(np.unravel_index(uniq, dims), axis=1) * cell)
    x = np.clip(x, cell_lo - 0.25 * cell, cell_lo + 1.25 * cell)
    f2 = inv[faces]
    ok = (f2[:, 0] != f2[:, 1]) & (f2[:, 1] != f2[:, 2]) & (f2[:, 0] != f2[:, 2])
    f2 = f2[ok]
    # ตัดหน้าซ้ำ
    s = np.sort(f2, axis=1)
    _, keep = np.unique(s, axis=0, return_index=True)
    f2 = f2[np.sort(keep)]
    used = np.unique(f2)
    remap = -np.ones(len(x), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return x[used], remap[f2].astype(np.int32)


def slice_segments(verts, faces, h, axis=2):
    """ตัดเมชด้วยระนาบ coord[axis] = h คืนเส้นตรง (K,2,2) ในพิกัด 2 แกนที่เหลือ"""
    ax = [i for i in range(3) if i != axis]
    zv = verts[:, axis] - h
    s = zv[faces]                                   # (M,3)
    pos = s > 0
    cross = pos.any(axis=1) & (~pos).any(axis=1)
    F = faces[cross]
    P = verts[F]                                    # (K,3,3)
    sv = zv[F]
    segs = []
    for e0, e1 in ((0, 1), (1, 2), (2, 0)):
        a, b = sv[:, e0], sv[:, e1]
        hit = (a > 0) != (b > 0)
        t = np.where(hit, a / np.where(hit, a - b, 1.0), 0.0)
        pt = P[:, e0, :] + (P[:, e1, :] - P[:, e0, :]) * t[:, None]
        segs.append((hit, pt[:, ax]))
    out = []
    # แต่ละสามเหลี่ยมที่ตัดจะมี 2 ขอบที่โดนระนาบ
    h0, h1, h2 = segs[0][0], segs[1][0], segs[2][0]
    p0, p1, p2 = segs[0][1], segs[1][1], segs[2][1]
    A = np.where((h0 & h1)[:, None], p0, np.where((h1 & h2)[:, None], p1, p2))
    Bp = np.where((h0 & h1)[:, None], p1, np.where((h1 & h2)[:, None], p2, p0))
    return np.stack([A, Bp], axis=1)


def segment_loops(segs, tol=1e-3):
    """ต่อเส้นตรงเป็นวง (union-find บนปลายที่ตรงกัน) คืนรายการ array จุด (n,2) ต่อวง (ไม่เรียงลำดับตามเส้นรอบ แต่แยกกลุ่มได้)"""
    key = np.round(segs.reshape(-1, 2) / tol).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1, 2)
    n = inv.max() + 1
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in inv:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(i) for i in inv[:, 0]])
    groups = {}
    for i, r in enumerate(roots):
        groups.setdefault(r, []).append(i)
    return [segs[idx] for idx in groups.values()]
