#!/usr/bin/env python3
"""Vergleicht die Hashzeilen des erschöpfenden Tests (exh_run.sh): exh_cmp.py <exh_m1.txt> <exh_c.txt>. Eigener Code."""
import sys
from collections import defaultdict


def load(p):
    d = {}
    for l in open(p):
        k, name, fpcr, step, h, n = l.strip().split("|")
        d[(int(k), fpcr)] = (name, step, h, int(n))
    return d


a, b = load(sys.argv[1]), load(sys.argv[2])
bad, cases = [], 0
per = defaultdict(lambda: [0, 0])
for key, (name, step, h, n) in a.items():
    if key not in b:
        print("fehlt in", sys.argv[2], key, name)
        continue
    cases += n
    per[key[1]][0] += n
    if b[key][2] != h or b[key][3] != n:
        bad.append((name, key[1], h, b[key][2]))
        per[key[1]][1] += 1
print(f"Läufe {len(a)} (Befehl x FPCR), Fälle {cases:,}, abweichende Läufe {len(bad)}")
for fpcr, (n, nb) in sorted(per.items()):
    print(f"  FPCR {fpcr}: Fälle {n:,}, abweichende Läufe {nb}")
for x in bad[:40]:
    print("  ABWEICHUNG", x)
