#!/usr/bin/env python3
"""IL2CPP method names -> guest address (from the memory image of the main module and the RomFS's global-metadata.dat).

Writes work/recomp/il2sym.tsv (address hex <TAB> name, names only, no game bytes in the repository). Usage:
  python3 -I scripts/recomp/il2sym.py                       # (-I: no search path of the script folder)
  BDSP_IL2SYM=work/recomp/il2sym.tsv work/recomp/bdsp_boot ...   # every method on its first call: "[il2] <ms> t<thread> <name>"
  ... | python3 -I scripts/recomp/symres.py                  # annotate guest addresses in reports (crash, ring) with names
Environment: IMG (default work/recomp/img_gfx2), METADATA (default work/romfs/Data/Managed/Metadata/global-metadata.dat).
Metadata version 24 (Unity 2019): header with (offset, size) pairs; table 20 = images (40 bytes), 19 = types (92 bytes), 5 = methods (32 bytes),
table 2 = strings. The pointers per module are in Il2CppCodeGenModule (name, count, pointer), found via the name string in the image.
"""
import os
import struct

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
img = open(os.path.join(ROOT, os.environ.get("IMG", "work/recomp/img_gfx2"), "main.img"), "rb").read()
BASE = 0x7000000000
md = open(os.path.join(ROOT, os.environ.get("METADATA", "work/romfs/Data/Managed/Metadata/global-metadata.dat")), "rb").read()
h = struct.unpack("<64i", md[8:264])


def tab(i):
    return h[2 * i], h[2 * i + 1]


str_off, _ = tab(2)


def sname(i):
    o = str_off + i
    return md[o:md.index(b"\0", o)].decode("utf8", "replace")


imgs_off, imgs_sz = tab(20)
td_off, td_sz = tab(19)
m_off, m_sz = tab(5)
nimg = imgs_sz // 40
print("Images", nimg, "types", td_sz // 92, "methods", m_sz // 32)


def u64(o):
    return struct.unpack_from("<Q", img, o)[0]


def u32(o):
    return struct.unpack_from("<I", img, o)[0]


arr = np.frombuffer(img[: len(img) // 8 * 8], dtype="<u8")
modules = {}
for k in range(nimg):
    nm = sname(struct.unpack_from("<i", md, imgs_off + 40 * k)[0])
    key = nm.encode() + b"\0"
    ptrs, pos = [], 0
    while True:
        pos = img.find(key, pos)
        if pos < 0:
            break
        if pos == 0 or img[pos - 1] == 0:
            ptrs.append(BASE + pos)
        pos += 1
    if not ptrs:
        continue
    for q in np.nonzero(np.isin(arr, np.array(ptrs, dtype="<u8")))[0]:
        o = int(q) * 8
        cnt, mp = u32(o + 8), u64(o + 16)
        if 0 < cnt < 200000 and BASE <= mp < BASE + len(img):
            modules[nm] = (cnt, mp - BASE)
print("Modules", len(modules))
out = []
for k in range(nimg):
    nameidx, _asm, tstart, tcount = struct.unpack_from("<iiii", md, imgs_off + 40 * k)
    nm = sname(nameidx)
    if nm not in modules:
        continue
    cnt, mpo = modules[nm]
    for t in range(tstart, tstart + tcount):
        f = struct.unpack_from("<17i8H", md, td_off + 92 * t)
        tn, tns = sname(f[0]), sname(f[1])
        for m in range(f[10], f[10] + f[17]):
            mf = struct.unpack_from("<6i4H", md, m_off + 32 * m)
            rid = mf[5] & 0xFFFFFF
            if rid == 0 or rid > cnt:
                continue
            p = u64(mpo + 8 * (rid - 1))
            if p:
                out.append((p, "%s%s.%s::%s" % (nm.replace(".dll", ""), "/" + tns if tns else "", tn, sname(mf[0]))))
out.sort()
dst = os.path.join(ROOT, "work/recomp/il2sym.tsv")
with open(dst, "w") as fo:
    for p, n in out:
        fo.write("%x\t%s\n" % (p, n))
print("Symbols", len(out), "->", dst)
