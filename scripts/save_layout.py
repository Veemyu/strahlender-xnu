#!/usr/bin/env python3
"""Reconstructs the marshal layout of PlayerWork.SaveData from dump.cs and global-metadata.dat.

Field order and types come from dump.cs, ByValArray/ByValTStr sizes from
fieldMarshaledSizes of the metadata (Il2Cpp v24). Output: field, offset, size.
"""
import re, struct, sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "work/il2cpp/dump.cs"
META = ROOT / "work/romfs/Data/Managed/Metadata/global-metadata.dat"

def load_types():
    types = []  # dict(name, idx, kind, fields[(decl, name, offset_or_none, static)])
    cur = None
    in_fields = False
    for line in open(DUMP, errors="replace"):
        line = line.rstrip("\n")
        m = re.match(r"^(?:public |internal |private |protected |sealed |abstract |static |unsafe |readonly )*(class|struct|enum|interface) (\S+).*// TypeDefIndex: (\d+)", line)
        if m:
            cur = {"kind": m.group(1), "name": m.group(2), "idx": int(m.group(3)), "fields": []}
            types.append(cur)
            in_fields = False
            continue
        if cur is None:
            continue
        if line.strip() == "// Fields":
            in_fields = True
            continue
        if in_fields:
            if line.strip() == "" or line.strip().startswith("// "):
                if line.strip() == "":
                    in_fields = False
                continue
            if line.startswith("\t[") or not line.startswith("\t"):
                continue
            fm = re.match(r"^\t(.*?) (\S+?)(?: = [^;]*)?;(?: // (0x[0-9A-Fa-f]+))?\s*$", line)
            if fm:
                decl = fm.group(1)
                cur["fields"].append((decl, fm.group(2), fm.group(3), "static" in decl.split() or "const" in decl.split()))
            else:
                print("unparsed:", line, file=sys.stderr)
    return types

def load_marshal():
    d = open(META, "rb").read()
    off, size = struct.unpack_from("<ii", d, 80)
    nfields = struct.unpack_from("<i", d, 100)[0] // 12
    res = {}
    for i in range(size // 12):
        fi, ti, sz = struct.unpack_from("<iii", d, off + i * 12)
        res[fi] = (ti, sz)
    return res, nfields

if __name__ == "__main__":
    types = load_types()
    types.sort(key=lambda t: t["idx"])
    ms, nf = load_marshal()
    total = sum(len(t["fields"]) for t in types)
    print("Fields dump.cs:", total, "metadata:", nf)
