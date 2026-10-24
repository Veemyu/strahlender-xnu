#!/usr/bin/env python3
"""Build the memory image of an NSO module for the exception spike (relocations applied, imports -> HLE slots).

Own code. Reads scripts/recomp/upstream/generator/nso.py. Writes under --out (work/recomp/spike2):  <name>.img        flat image, module base = --base (relocations RELATIVE/ABS64/GLOB_DAT/JUMP_SLOT applied)
  <name>.syms.json  {export name: absolute guest address}
  hle.txt           import names, line i = HLE slot i (address HLE_BASE + 16 * i); is carried forward

Usage: mkimg.py <nso> <name> --base 0x7004000000 --out work/recomp/spike2
"""
import argparse
import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if os.environ.get("BDSP_INSTALLER_PRIVATE_RUNTIME") != "1":
    sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
sys.path.insert(0, str(ROOT / "scripts" / "recomp" / "upstream" / "generator"))
sys.dont_write_bytecode = True
from nso import Nso  # noqa: E402

HLE_BASE = 0x7080000000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nso")
    ap.add_argument("name")
    ap.add_argument("--base", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hle-base", type=lambda s: int(s, 0), default=HLE_BASE)
    ap.add_argument("--link", action="append", default=[], help="JSON {export name: address} of another module (repeatable)")
    ap.add_argument("--hle-list", help="text file with symbol names (one per line, '#' = comment) that are bound to an HLE slot even if an export exists")
    ap.add_argument("--interpose-from", help="JSON {export name: address} of the main module: matching symbols of the other modules are bound to its definition (ELF interposition: the definition of the executable wins, e.g. the game's operator new/delete over the SDK's)")
    ap.add_argument("--interpose-regex", default=r"^(_Zn[wa]|_Zd[la]|_ZT[IS])", help="which symbols are interposed (default: operator new/delete and typeinfo)")
    a = ap.parse_args()
    forced = set()
    if a.hle_list:
        forced = {l.strip() for l in Path(a.hle_list).read_text().splitlines() if l.strip() and not l.startswith("#")}
    import re
    interpose = {}
    if a.interpose_from:
        rx = re.compile(a.interpose_regex)
        interpose = {k: v for k, v in json.loads(Path(a.interpose_from).read_text()).items() if rx.match(k)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n = Nso(a.nso)
    img = n.image
    hle_path = out / "hle.txt"
    hle = [h for h in (hle_path.read_text().split("\n") if hle_path.exists() else []) if h]
    idx = {h: i for i, h in enumerate(hle)}

    def slot(name):
        if name not in idx:
            idx[name] = len(hle)
            hle.append(name)
        return a.hle_base + 16 * idx[name]

    exports = {s[0]: a.base + s[3] for s in n.syms if s[0] and s[2]}
    linked = {}
    for lj in a.link:
        linked.update(json.loads(Path(lj).read_text()))
    stats = {"relative": 0, "bound": 0, "linked": 0, "hle": 0}
    for off, typ, sym, add in n.relocs:
        if typ == 1027:
            struct.pack_into("<Q", img, off, a.base + add)
            stats["relative"] += 1
        elif typ in (257, 1025, 1026):
            s = n.syms[sym]
            if s[0] in forced:
                struct.pack_into("<Q", img, off, slot(s[0]) + (add if typ == 257 else 0))
                stats["hle"] += 1
            elif s[0] in interpose and a.name != "main":
                struct.pack_into("<Q", img, off, interpose[s[0]] + (add if typ == 257 else 0))
                stats["interposed"] = stats.get("interposed", 0) + 1
            elif s[2]:
                struct.pack_into("<Q", img, off, a.base + s[3] + (add if typ == 257 else 0))
                stats["bound"] += 1
            elif s[0] in linked:
                struct.pack_into("<Q", img, off, linked[s[0]] + (add if typ == 257 else 0))
                stats["linked"] += 1
            elif (s[1] >> 4) == 2:  # weak and unresolved: 0 (the code checks for it, e.g. nnosGetDefaultUserExceptionStack...)
                struct.pack_into("<Q", img, off, 0)
                stats["weak0"] = stats.get("weak0", 0) + 1
            else:
                struct.pack_into("<Q", img, off, slot(s[0]))
                stats["hle"] += 1
    (out / f"{a.name}.img").write_bytes(bytes(img))
    d = n.dyn
    (out / f"{a.name}.mod").write_text(
        f"{a.name} {a.base:#x} {n.text[0]:#x} {n.text[0] + n.text[1]:#x} {n.rodata[0]:#x} {n.rodata[0] + n.rodata[1]:#x} "
        f"{n.data[0]:#x} {n.data[0] + n.data[1]:#x} {n.size:#x} {d.get(12, 0):#x} {d.get(25, 0):#x} {d.get(27, 0):#x}\n")
    (out / f"{a.name}.syms.json").write_text(json.dumps(exports))
    hle_path.write_text("\n".join(hle) + "\n")
    print(a.name, "image", len(img), "relocations", stats, "HLE slots total", len(hle))


if __name__ == "__main__":
    sys.exit(main() or 0)
