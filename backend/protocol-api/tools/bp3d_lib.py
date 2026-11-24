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


def taubin_smooth(verts, faces, iterations=20, lam=0.5, mu=-0.53):
    """เกลี่ยผิวแบบ Taubin (λ|μ): ลดความขรุขระโดยไม่หดตัวเหมือน Laplacian ธรรมดา
    จุดยอดบนขอบเปิด (เช่น ข้อมือ ข้อเท้า คอ) ถูกตรึงไว้กันผิวหด"""
    from scipy.sparse import coo_matrix
    n = len(verts)
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    # ขอบเปิด = ขอบที่ปรากฏเพียงครั้งเดียว (ไม่นับทิศ)
    es = np.sort(e, axis=1)
    key = es[:, 0].astype(np.int64) * n + es[:, 1]
    uniq, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    boundary = np.zeros(n, dtype=bool)
    open_e = cnt[inv] == 1
    boundary[es[open_e].reshape(-1)] = True
    ue = np.stack([uniq // n, uniq % n], axis=1)
    rows = np.concatenate([ue[:, 0], ue[:, 1]])
    cols = np.concatenate([ue[:, 1], ue[:, 0]])
    A = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n)).tocsr()
    deg = np.asarray(A.sum(axis=1)).reshape(-1)
    deg[deg == 0] = 1.0
    v = verts.copy()
    for _ in range(iterations):
        for w in (lam, mu):
            avg = (A @ v) / deg[:, None]
            d = avg - v
            d[boundary] = 0.0
            v = v + w * d
    return v


def roughness_deg(verts, faces, mask_faces=None):
    """ค่าเฉลี่ยมุมระหว่างหน้าที่อยู่ติดกัน (องศา): ยิ่งน้อยยิ่งเรียบ"""
    fn, _ = face_normals_area(verts, faces)
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    fid = np.tile(np.arange(len(faces)), 3)
    es = np.sort(e, axis=1)
    key = es[:, 0].astype(np.int64) * len(verts) + es[:, 1]
    order = np.argsort(key)
    key, fid = key[order], fid[order]
    same = key[1:] == key[:-1]
    a, b = fid[:-1][same], fid[1:][same]
    if mask_faces is not None:
        keep = mask_faces[a] & mask_faces[b]
        a, b = a[keep], b[keep]
    cos = np.clip(np.einsum("ij,ij->i", fn[a], fn[b]), -1, 1)
    return float(np.degrees(np.arccos(cos)).mean())


def classify_outer_faces(verts, faces, step=2.0):
    """แยกผิวนอกออกจากผิวในของเปลือกสองชั้น (เช่น Skin ของ BodyParts3D)

    ตัดเมชด้วยระนาบแนวนอนทุก `step` mm แล้วหาทิศของเส้นตัดจากเวกเตอร์ตั้งฉากของหน้า (ให้ด้านนอกอยู่ขวามือ)
    วงรอบนอกเดินทวนเข็ม (พื้นที่มีเครื่องหมายบวก) ส่วนวงรอบในซึ่งเป็นขอบโพรงเดินตามเข็ม (ลบ)
    หน้าที่ถูกตัดโดยวงบวกถือเป็นผิวนอก หน้าที่ยังไม่ถูกจัดกลุ่มรับป้ายจากหน้าข้างเคียง (label propagation)
    คืน mask (M,) bool ของหน้าที่เป็นผิวนอก"""
    fn, _ = face_normals_area(verts, faces)
    zmin = verts[faces][:, :, 2].min(axis=1)
    zmax = verts[faces][:, :, 2].max(axis=1)
    order = np.argsort(zmin)
    zmin_s = zmin[order]
    votes = np.zeros((len(faces), 2), dtype=np.int32)          # [ผิวนอก, ผิวใน]
    h = float(verts[:, 2].min()) + step / 2
    top = float(verts[:, 2].max())
    while h < top:
        hi = np.searchsorted(zmin_s, h, side="right")
        cand = order[:hi]
        cand = cand[zmax[cand] > h]
        if len(cand):
            F = faces[cand]
            P = verts[F]                                       # (K,3,3)
            s = P[:, :, 2] - h
            pos = s > 0
            cross = pos.any(axis=1) & (~pos).any(axis=1)
            cand, P, s = cand[cross], P[cross], s[cross]
            if len(cand):
                pts, ok = [], []
                for e0, e1 in ((0, 1), (1, 2), (2, 0)):
                    a, b = s[:, e0], s[:, e1]
                    hit = (a > 0) != (b > 0)
                    t = np.where(hit, a / np.where(hit, a - b, 1.0), 0.0)
                    pts.append(P[:, e0, :2] + (P[:, e1, :2] - P[:, e0, :2]) * t[:, None])
                    ok.append(hit)
                h0, h1, h2 = ok
                A = np.where((h0 & h1)[:, None], pts[0], np.where((h1 & h2)[:, None], pts[1], pts[2]))
                Bp = np.where((h0 & h1)[:, None], pts[1], np.where((h1 & h2)[:, None], pts[2], pts[0]))
                n2 = fn[cand][:, :2]
                tang = np.stack([-n2[:, 1], n2[:, 0]], axis=1)  # หมุน n2 ไป +90°: ด้านนอกอยู่ขวามือ
                flip = np.einsum("ij,ij->i", Bp - A, tang) < 0
                A2, B2 = np.where(flip[:, None], Bp, A), np.where(flip[:, None], A, Bp)
                key = np.round(np.vstack([A2, B2]) / 1e-3).astype(np.int64)
                _, inv = np.unique(key, axis=0, return_inverse=True)
                inv = inv.reshape(-1)
                m = len(A2)
                ia, ib = inv[:m], inv[m:]
                n = inv.max() + 1
                parent = np.arange(n)

                def find(x):
                    while parent[x] != x:
                        parent[x] = parent[parent[x]]
                        x = parent[x]
                    return x
                for x, y in zip(ia, ib):
                    rx, ry = find(x), find(y)
                    if rx != ry:
                        parent[rx] = ry
                root = np.array([find(x) for x in ia])
                cross2 = (A2[:, 0] * B2[:, 1] - A2[:, 1] * B2[:, 0]) / 2
                area = {}
                for r, c in zip(root, cross2):
                    area[r] = area.get(r, 0.0) + c
                sign_outer = np.array([area[r] > 0 for r in root])
                np.add.at(votes[:, 0], cand[sign_outer], 1)
                np.add.at(votes[:, 1], cand[~sign_outer], 1)
        h += step
    label = np.full(len(faces), -1, dtype=np.int8)
    label[votes[:, 0] > votes[:, 1]] = 1
    label[votes[:, 1] > votes[:, 0]] = 0
    # label propagation ผ่านหน้าที่ใช้ขอบร่วมกัน
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    fid = np.tile(np.arange(len(faces)), 3)
    es = np.sort(e, axis=1)
    key = es[:, 0].astype(np.int64) * len(verts) + es[:, 1]
    o = np.argsort(key, kind="stable")
    key, fid = key[o], fid[o]
    same = key[1:] == key[:-1]
    fa, fb = fid[:-1][same], fid[1:][same]
    for _ in range(200):
        un = np.where(label == -1)[0]
        if len(un) == 0:
            break
        lab_a, lab_b = label[fa], label[fb]
        sel = (lab_a == -1) & (lab_b != -1)
        sel2 = (lab_b == -1) & (lab_a != -1)
        label[fa[sel]] = lab_b[sel]
        label[fb[sel2]] = lab_a[sel2]
        if not (sel.any() or sel2.any()):
            break
    label[label == -1] = 1
    return label == 1


def drop_spiky_faces(verts, faces, threshold_deg=75.0, iterations=2, min_component=200):
    """ตัดหน้าที่พับแหลมผิดปกติกับหน้าข้างเคียง (มุมไดฮีดรัล > threshold) ซ้ำ `iterations` รอบ แล้วทิ้งเศษชิ้นเล็ก
    ใช้กับผิวที่ปนเศษของผิวชั้นในตรงเบ้าตา/ขาหนีบ คืน (verts, faces) ที่เรียงจุดยอดใหม่"""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    f = faces.copy()
    for _ in range(iterations):
        fn, _ = face_normals_area(verts, f)
        e = np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
        fid = np.tile(np.arange(len(f)), 3)
        es = np.sort(e, axis=1)
        key = es[:, 0].astype(np.int64) * len(verts) + es[:, 1]
        o = np.argsort(key, kind="stable")
        key, fid = key[o], fid[o]
        same = key[1:] == key[:-1]
        a, b = fid[:-1][same], fid[1:][same]
        ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", fn[a], fn[b]), -1, 1)))
        bad = np.zeros(len(f), dtype=bool)
        bad[a[ang > threshold_deg]] = True
        bad[b[ang > threshold_deg]] = True
        f = f[~bad]
    n = len(verts)
    ed = np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    g = coo_matrix((np.ones(len(ed)), (ed[:, 0], ed[:, 1])), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    size = np.bincount(lab[f[:, 0]])
    f = f[size[lab[f[:, 0]]] >= min_component]
    used = np.unique(f)
    remap = -np.ones(n, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return verts[used], remap[f].astype(np.int32)


def max_dihedral_per_face(verts, faces):
    fn, _ = face_normals_area(verts, faces)
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    fid = np.tile(np.arange(len(faces)), 3)
    es = np.sort(e, axis=1)
    key = es[:, 0].astype(np.int64) * len(verts) + es[:, 1]
    o = np.argsort(key, kind="stable")
    key, fid = key[o], fid[o]
    same = key[1:] == key[:-1]
    a, b = fid[:-1][same], fid[1:][same]
    ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", fn[a], fn[b]), -1, 1)))
    mx = np.zeros(len(faces))
    np.maximum.at(mx, a, ang)
    np.maximum.at(mx, b, ang)
    return mx


def drop_spiky_in_region(verts, faces, region_fn, threshold_deg=40.0, iterations=2):
    """ตัดหน้าที่พับแหลม (> threshold) เฉพาะหน้าที่จุดศูนย์กลางอยู่ในภูมิภาคที่ region_fn(centroids) คืน True (ไม่เรียงจุดยอดใหม่)"""
    f = faces.copy()
    for _ in range(iterations):
        mx = max_dihedral_per_face(verts, f)
        cen = verts[f].mean(axis=1)
        f = f[~((mx > threshold_deg) & region_fn(cen))]
    return f


def fill_small_holes(verts, faces, max_perimeter=150.0):
    """ปิดรูเล็ก (ขอบเปิดที่เส้นรอบวงสั้นกว่า max_perimeter หน่วยเดียวกับพิกัด) ด้วยพัดสามเหลี่ยมจากจุดศูนย์กลางของขอบ
    คืน (verts, faces) ใหม่ (เพิ่มจุดยอดตรงกลางรูละ 1 จุด) รูใหญ่ เช่น ข้อมือ ข้อเท้า คอ ไม่ถูกปิด"""
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    es = np.sort(e, axis=1)
    key = es[:, 0].astype(np.int64) * len(verts) + es[:, 1]
    uniq, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    boundary = e[cnt[inv] == 1]                      # ทิศตามหน้าที่เป็นเจ้าของ (a -> b)
    nxt = {}
    for a, b in boundary:
        nxt.setdefault(int(a), []).append(int(b))
    seen, new_v, new_f = set(), [], []
    base = len(verts)
    for a0 in list(nxt.keys()):
        if a0 in seen:
            continue
        loop, cur, guard = [a0], a0, 0
        while guard < 100000:
            guard += 1
            seen.add(cur)
            nx = nxt.get(cur)
            if not nx:
                loop = None
                break
            cur = nx[0]
            if cur == a0:
                break
            if cur in loop:          # จุดบีบ (pinch): ข้ามรูที่ซับซ้อน
                loop = None
                break
            loop.append(cur)
        if not loop or len(loop) < 3:
            continue
        pts = verts[loop]
        per = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1).sum()
        if per > max_perimeter:
            continue
        c = pts.mean(axis=0)
        ci = base + len(new_v)
        new_v.append(c)
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            new_f.append((b, a, ci))               # ทิศตรงข้ามกับหน้าที่มีอยู่ เพื่อให้ผิวต่อเนื่อง
    if not new_v:
        return verts, faces
    return np.vstack([verts, np.array(new_v)]), np.vstack([faces, np.array(new_f, dtype=np.int32)]).astype(np.int32)


def drop_small_smooth_components(verts, faces, region_fn, max_faces=500, threshold_deg=35.0):
    """ตัดกลุ่มหน้าที่เชื่อมกันด้วยขอบเรียบ (ไดฮีดรัล < threshold) ที่เล็กกว่า max_faces และอยู่ในภูมิภาค region_fn(centroids)
    ใช้ตัดแผ่นเศษในหัว (แผ่นราบที่ระดับตา) ที่ทำให้เปลือกตาเป็นรอยหยัก"""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    fn, _ = face_normals_area(verts, faces)
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    fid = np.tile(np.arange(len(faces)), 3)
    es = np.sort(e, axis=1)
    key = es[:, 0].astype(np.int64) * len(verts) + es[:, 1]
    o = np.argsort(key, kind="stable")
    key, fid = key[o], fid[o]
    same = key[1:] == key[:-1]
    a, b = fid[:-1][same], fid[1:][same]
    ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", fn[a], fn[b]), -1, 1)))
    ok = ang < threshold_deg
    g = coo_matrix((np.ones(ok.sum()), (a[ok], b[ok])), shape=(len(faces), len(faces)))
    _, lab = connected_components(g, directed=False)
    size = np.bincount(lab)
    cen = verts[faces].mean(axis=1)
    in_region = region_fn(cen)
    # ทั้งกลุ่มต้องอยู่ในภูมิภาค จึงจะถูกตัด
    outside = np.bincount(lab[~in_region], minlength=len(size))
    drop = (size[lab] < max_faces) & (outside[lab] == 0)
    return faces[~drop]