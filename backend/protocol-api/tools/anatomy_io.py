"""อ่านไฟล์ anatomy.json / anatomy.bin กลับเป็น numpy (ใช้ในเทสต์และภาพตรวจสอบ): คืน {id: (verts เมตร, faces)}"""
import json
import os

import numpy as np


def load_anatomy(folder):
    with open(os.path.join(folder, "anatomy.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    raw = open(os.path.join(folder, "anatomy.bin"), "rb").read()
    out = {}
    for m in man["meshes"]:
        q = np.frombuffer(raw, dtype=np.uint16, count=m["nv"] * 3, offset=m["vOff"]).reshape(-1, 3).astype(np.float64)
        lo, hi = np.array(m["min"]), np.array(m["max"])
        v = lo + q / 65535.0 * (hi - lo)
        dt = np.uint32 if m["wide"] else np.uint16
        f = np.frombuffer(raw, dtype=dt, count=m["nf"] * 3, offset=m["iOff"]).reshape(-1, 3).astype(np.int64)
        out[m["id"]] = (v, f, m["group"], m["name"])
    return man, out
