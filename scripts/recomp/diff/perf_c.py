#!/usr/bin/env python3
"""Kostenmessung der c-Modus-Varianten (docs/recomp-diff.md, Abschnitt 5): Zeit je erzeugter Gastfunktion (ns) für
häufige FP-/SIMD-Befehle, FPCR = 0 (Schnellpfad) und FZ bzw. RMode (langsamer Pfad). Eigener Code.
Aufruf: perf_c.py <name>=<lib.so> ... [--n 20000000]"""
import ctypes
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import *  # noqa: E402,F403

NAMES = ["fmul s0, s1, s2", "fadd s0, s1, s2", "fdiv s0, s1, s2", "fmul d0, d4, d5", "fmadd s0, s1, s2, s3", "fcmp s1, s2",
         "fmul v0.4s, v1.4s, v2.4s", "fadd v0.4s, v1.4s, v2.4s", "fmla v0.4s, v1.4s, v2.4s", "fsqrt s0, s1", "frecpe s0, s1",
         "frecps s0, s1, s2", "fcvtzs w0, s1", "scvtf s0, w1", "faddp v0.4s, v1.4s, v2.4s", "mov v0.16b, v1.16b",
         "seq fmul+fadd s", "seq fmul+fadd 4s"]
MODES = [("RN", 0), ("FZ", 0x1000000), ("RZ", 0xC00000)]


def main():
    args = [a for a in sys.argv[1:] if "=" in a]
    n = 20_000_000
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    tests = json.loads((ROOT / "work/recomp/diff/tests.json").read_text())["tests"]
    ids = {}
    for t in tests:
        ids.setdefault(t["name"], t["id"])
    res = {}
    for a in args:
        name, path = a.split("=", 1)
        lib = ctypes.CDLL(path)
        lib.bench_c.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.c_uint64]
        lib.bench_c.restype = ctypes.c_uint64
        for nm in NAMES:
            if nm not in ids:
                continue
            for mname, fpcr in MODES:
                best = 1e9
                for _ in range(3):
                    t0 = time.perf_counter()
                    lib.bench_c(ids[nm], n, fpcr)
                    best = min(best, time.perf_counter() - t0)
                res[(name, nm, mname)] = best / n * 1e9
    print("Befehl;Modus;" + ";".join(a.split("=")[0] for a in args))
    for nm in NAMES:
        for mname, _ in MODES:
            row = [res.get((a.split("=")[0], nm, mname)) for a in args]
            if row[0] is None:
                continue
            print(f"{nm};{mname};" + ";".join(f"{v:.2f}" for v in row))


if __name__ == "__main__":
    main()
