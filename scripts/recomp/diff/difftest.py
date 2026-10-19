#!/usr/bin/env python3
"""Differenzialtest-Treiber (docs/recomp-diff.md, Abschnitt 2): Referenz(en) gegen erzeugtes C (c-Modus).

Eigener Code. Je Test: synthetische Eingaben (cases.c, fester Startwert) -> Quellen laufen lassen -> jede
übrige Quelle gegen die erste vergleichen (v0 128 Bit, x0, NZCV, getrennt FPSR).

Quellen (--src, die erste ist die Vergleichsbasis):
  m1            nativ auf dem Apple-M1 (JIT der Schleife, nur macOS/arm64)
  uc            Unicorn, Cortex-A57-Modell (Switch-Kern)
  c:<name>=<so> erzeugtes C als Bibliothek (ctest.c + lifted.c), von build_c.sh gebaut

Aufruf: difftest.py --src uc,c:o1=work/recomp/diff/lib_o1.so [--tests tests.json] [--ids a-b] [--jobs 4] --out report.json
Ausgabe: JSON mit Ergebnis je Test und Vergleich; Kurzfassung auf stdout.
"""
import argparse
import ctypes
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import *  # noqa: E402,F403

W = {}


def init(args):
    W["tests"] = args["tests"]
    W["cl"] = load_cases_lib(args["cases_lib"])
    W["srcs"] = args["srcs"]
    W["libs"] = {}
    for s in args["srcs"]:
        if s.startswith("c:"):
            name, path = s[2:].split("=", 1)
            lib = ctypes.CDLL(path)
            lib.run_c.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64]
            if args.get("mxcsr"):
                lib.set_mxcsr(ctypes.c_uint32(args["mxcsr"]))
            W["libs"][s] = lib
        elif s == "m1":
            lib = ctypes.CDLL(str(args["native_lib"]))
            lib.run_native.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64]
            W["libs"][s] = lib


def run_src(s, t, cases):
    n = len(cases)
    if s == "uc":
        return uc_run(t["words"], cases, n)
    out = np.zeros(n, dtype=OUT_DT)
    if s == "m1":
        code = code_for(t["words"])
        r = W["libs"][s].run_native(code, len(code), cases.ctypes.data, out.ctypes.data, n)
        if r:
            raise RuntimeError(f"run_native {r}")
    else:
        r = W["libs"][s].run_c(t["id"], cases.ctypes.data, out.ctypes.data, n)
        if r:
            raise RuntimeError(f"run_c {r}")
    return out


def lane_flags(cases, rt, k):
    """(nan, denormal, inf) je Fall für Register k nach seinem Typ."""
    raw = np.ascontiguousarray(cases["v"][:, k, :])
    t = rt[k]
    if t == T_F32:
        u = raw.view("<u4")
        e, m = (u >> 23) & 0xFF, u & 0x7FFFFF
        return (((e == 255) & (m != 0)).any(1), ((e == 0) & (m != 0)).any(1), ((e == 255) & (m == 0)).any(1))
    if t == T_F64:
        u = raw.view("<u8")
        e, m = (u >> 52) & 0x7FF, u & 0xFFFFFFFFFFFFF
        return (((e == 2047) & (m != 0)).any(1), ((e == 0) & (m != 0)).any(1), ((e == 2047) & (m == 0)).any(1))
    if t == T_F16:
        u = raw.view("<u2")
        e, m = (u >> 10) & 0x1F, u & 0x3FF
        return (((e == 31) & (m != 0)).any(1), ((e == 0) & (m != 0)).any(1), ((e == 31) & (m == 0)).any(1))
    z = np.zeros(len(cases), bool)
    return z, z, z


def hexv(v):
    return f"{int(v[1]):016x}{int(v[0]):016x}"


def compare(t, cases, ref, got):
    n = len(cases)
    dv = (ref["v0"] != got["v0"]).any(1)
    dx = ref["x0"] != got["x0"]
    dn = ref["nzcv"] != got["nzcv"]
    df = ref["fpsr"] != got["fpsr"]
    d1 = ref["x1"] != got["x1"]
    dm = (ref["mem"] != got["mem"]).any(1)
    bad = dv | dx | dn | d1 | dm
    res = {"n": n, "v": int(dv.sum()), "x": int(dx.sum()), "nzcv": int(dn.sum()), "x1": int(d1.sum()), "mem": int(dm.sum()),
           "bad": int(bad.sum()), "fpsr": int(df.sum()),
           "fpsr_only": int((df & ~bad).sum())}
    if bad.any():
        tags = {}
        nan = np.zeros(n, bool)
        den = np.zeros(n, bool)
        inf = np.zeros(n, bool)
        for k in range(4):
            a, b, c = lane_flags(cases, t["rt"], k)
            nan |= a
            den |= b
            inf |= c
        rm = ((cases["fpcr"] >> 22) & 3).astype(int)
        fz = (cases["fpcr"] >> 24) & 1
        dnb = (cases["fpcr"] >> 25) & 1
        for name, m in (("nan_in", nan), ("denormal_in", den), ("inf_in", inf), ("RM!=0", rm != 0), ("FZ", fz == 1), ("DN", dnb == 1),
                        ("RN,FZ0,DN0", (rm == 0) & (fz == 0) & (dnb == 0)), ("kein_nan_denormal_inf", ~(nan | den | inf))):
            tags[name] = int((bad & m).sum())
        res["tags"] = tags
        ex = []
        for i in np.nonzero(bad)[0][:3]:
            ex.append({"i": int(i), "fpcr": hex(int(cases["fpcr"][i])), "nzcv_in": hex(int(cases["nzcv"][i])),
                       "in": [hexv(np.frombuffer(cases["v"][i, k].tobytes(), "<u8")) for k in range(4)],
                       "x_in": [hex(int(v)) for v in cases["x"][i]],
                       "ref": [hexv(ref["v0"][i]), hex(int(ref["x0"][i])), hex(int(ref["nzcv"][i])), hex(int(ref["fpsr"][i]))],
                       "got": [hexv(got["v0"][i]), hex(int(got["x0"][i])), hex(int(got["nzcv"][i])), hex(int(got["fpsr"][i]))]})
        res["examples"] = ex
    return res


def work(tid):
    t = W["tests"][tid]
    cases = make_cases(W["cl"], t["seed"], t["rt"], t["flags"], t["n"])
    outs = {}
    for s in W["srcs"]:
        try:
            outs[s] = run_src(s, t, cases.copy())
        except Exception as e:  # noqa: BLE001
            return {"id": tid, "error": f"{s}: {e!r}"}
    base = W["srcs"][0]
    r = {"id": tid, "cmp": {}}
    for s in W["srcs"][1:]:
        r["cmp"][s] = compare(t, cases, outs[base], outs[s])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--tests", default=str(ROOT / "work/recomp/diff/tests.json"))
    ap.add_argument("--cases-lib", default=str(ROOT / "work/recomp/diff/libcases.so"))
    ap.add_argument("--native-lib", default=str(ROOT / "work/recomp/diff/libnative.dylib"))
    ap.add_argument("--ids", default="")
    ap.add_argument("--mxcsr", type=lambda v: int(v, 0), default=0, help="Host-MXCSR während des C-Laufs (x86; Störversuch)")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tests = json.loads(Path(a.tests).read_text())["tests"]
    ids = list(range(len(tests)))
    if a.ids:
        lo, _, hi = a.ids.partition("-")
        ids = [i for i in ids if int(lo) <= i <= int(hi or lo)]
    srcs = a.src.split(",")
    template()
    t0 = time.time()
    results = []
    with mp.get_context("fork").Pool(a.jobs, init, ({"tests": tests, "cases_lib": a.cases_lib, "srcs": srcs, "native_lib": a.native_lib, "mxcsr": a.mxcsr},)) as p:
        for k, r in enumerate(p.imap_unordered(work, ids, chunksize=4)):
            results.append(r)
            if k % 500 == 0:
                print(f"{k}/{len(ids)} {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    results.sort(key=lambda r: r["id"])
    Path(a.out).write_text(json.dumps({"srcs": srcs, "results": results}))
    for s in srcs[1:]:
        bad = [r for r in results if "cmp" in r and r["cmp"][s]["bad"]]
        err = [r for r in results if "error" in r]
        print(f"{srcs[0]} gegen {s}: Tests {len(results)}, mit Abweichung {len(bad)}, Fehler {len(err)}, Fälle mit Abweichung {sum(r['cmp'][s]['bad'] for r in bad)}")
    print(f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
