#!/usr/bin/env python3
"""Leitet aus der dekompilierten IL2CPP-Marshal-Funktion (work/decomp/save-spec/marshal_savedata.c)
die nativen Offsets der Top-Level-Felder von PlayerWork.SaveData ab. Heuristik: je Feld
der kleinste param_2-Offset zwischen der ersten param_1-Referenz des Felds und der des naechsten."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from save_layout import load_types

ROOT = Path(__file__).resolve().parent.parent
src = open(ROOT / "work/decomp/save-spec/marshal_savedata.c").read().split("\n")
src = src[:[i for i, l in enumerate(src) if l.startswith("// 002acb90")][0]]

types = load_types()
sd = [t for t in types if t["name"] == "PlayerWork.SaveData"][0]
fields = [(int(off, 16), name, decl) for decl, name, off, st in sd["fields"] if not st and off]

def p1(line):
    out = []
    for m in re.finditer(r"\(long\)param_1 \+ (0x[0-9a-f]+|\d+)\b|\bparam_1 \+ (0x[0-9a-f]+|\d+)\b|\*param_1\b|\(\*\(long \*\)\(param_1 \+ (0x[0-9a-f]+|\d+)\)", line):
        pass
    for m in re.finditer(r"(\(long\))?param_1(?: \+ (0x[0-9a-f]+|\d+))?(?![\w])", line):
        v = int(m.group(2), 0) if m.group(2) else 0
        out.append(v if m.group(1) else v * 4)
    return out

def p2(line):
    out = []
    for m in re.finditer(r"(\(long\))?param_2(?: \+ (0x[0-9a-f]+|\d+))?(?![\w])", line):
        v = int(m.group(2), 0) if m.group(2) else 0
        out.append(v if m.group(1) else v * 4)
    return out

first = {}
nat = {}
cur = None
fo = {o: (n, d) for o, n, d in fields}
for i, line in enumerate(src):
    for v in p1(line):
        if v in fo and v not in first:
            first[v] = i
            cur = v
            break
    if cur is not None:
        for v in p2(line):
            nat.setdefault(cur, []).append(v)

print("%-6s %-24s %-10s %s" % ("mgd", "name", "native", "decl"))
for o, n, d in fields:
    cands = nat.get(o)
    print("0x%03x  %-24s %-10s %s" % (o, n, hex(min(cands)) if cands else "?", d))
