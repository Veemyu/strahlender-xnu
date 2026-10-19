#!/usr/bin/env python3
"""Testliste des Differenzialtests erzeugen (docs/recomp-diff.md, Abschnitt 2).

Eigener Code. Durchsucht den FP-/SIMD-Kodierungsraum (Bits 27:25 = 111) mit Capstone, bildet je Befehlsform
("Shape", wie in hist.py) Vertreter, lässt die Vertreter vom c-Modus-Lifter (research/LASRecomp/tools, nur importiert)
in C umsetzen und schreibt
  work/recomp/diff/tests.json   Testliste (Befehlswörter, Form, Spielhäufigkeit, Eingabetypen, Fallzahl)
  work/recomp/diff/lifted.c     eine Gastfunktion t_<id>(Cpu *) je Test + Tabelle test_fns[]
Zusätzlich handgeschriebene Befehlsfolgen (FMUL+FADD usw.) für die Fusionsprüfung. Keine Spielbytes im Ergebnis;
die Häufigkeiten stammen aus hist.json (nur Zähler).

Aufruf: mktests.py [--hist work/recomp/diff/hist.json] [--ncases 10240] [--reps 3] [--out work/recomp/diff]
"""
import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import *  # noqa: E402,F403
sys.path.insert(0, str(LAS / "tools"))
import capstone  # noqa: E402
from hist import shape  # noqa: E402
from lifter import Lifter, Unsupported  # noqa: E402

GPR = re.compile(r"\b([wx])(\d+)\b")
C3S = ["fadd", "fsub", "fmul", "fdiv", "fmax", "fmin", "fmaxnm", "fminnm", "fnmul", "fmulx", "fabd", "frecps", "frsqrts"]
C3V = ["fadd", "fsub", "fmul", "fdiv", "fmax", "fmin", "fmaxnm", "fminnm", "fabd", "fmulx", "frecps", "frsqrts", "faddp", "fmaxp", "fminp"]
C4S = ["fmadd", "fmsub", "fnmadd", "fnmsub"]
C1S = ["fabs", "fneg", "fsqrt", "frintn", "frintz", "frintm", "frintp", "frinta", "frintx", "frinti", "frecpe", "frsqrte", "frecpx"]
C1V = ["fabs", "fneg", "fsqrt", "frintn", "frintz", "frintm", "frintp", "frinta", "frintx", "frinti", "frecpe", "frsqrte"]
BADREG = re.compile(r"\b(sp|wsp|xzr|wzr)\b")

SEQS = [  # (Name, Zeilen)
    ("seq fmul+fadd s", ["fmul s0, s1, s2", "fadd s0, s0, s3"]),
    ("seq fmul+fadd s (Addend links)", ["fmul s0, s1, s2", "fadd s0, s3, s0"]),
    ("seq fmul+fsub s", ["fmul s0, s1, s2", "fsub s0, s0, s3"]),
    ("seq fmul+fsub s (Produkt abgezogen)", ["fmul s0, s1, s2", "fsub s0, s3, s0"]),
    ("seq fmul+fadd d", ["fmul d0, d1, d2", "fadd d0, d0, d3"]),
    ("seq fmul+fsub d", ["fmul d0, d1, d2", "fsub d0, d0, d3"]),
    ("seq fmul+fadd 4s", ["fmul v0.4s, v1.4s, v2.4s", "fadd v0.4s, v0.4s, v3.4s"]),
    ("seq fmul+fsub 4s", ["fmul v0.4s, v1.4s, v2.4s", "fsub v0.4s, v0.4s, v3.4s"]),
    ("seq fmul+fadd 2d", ["fmul v0.2d, v1.2d, v2.2d", "fadd v0.2d, v0.2d, v3.2d"]),
    ("seq fmul+fadd 2s", ["fmul v0.2s, v1.2s, v2.2s", "fadd v0.2s, v0.2s, v3.2s"]),
    ("seq fmul(lane)+fadd 4s", ["fmul v0.4s, v1.4s, v2.s[1]", "fadd v0.4s, v0.4s, v3.4s"]),
    ("seq fmul+fmul+fadd s (Skalarprodukt)", ["fmul s0, s1, s2", "fmul s4, s3, s5", "fadd s0, s0, s4"]),
    ("seq fmul+fadd+fsub s", ["fmul s4, s1, s2", "fadd s0, s4, s3", "fsub s0, s0, s4"]),
    ("seq fmul+fneg+fadd s", ["fmul s4, s1, s2", "fneg s4, s4", "fadd s0, s3, s4"]),
    ("seq fmul+fcvt+fadd d", ["fmul s0, s1, s2", "fcvt d0, s0", "fadd d0, d0, d3"]),
    ("seq fdiv+fmul s", ["fdiv s4, s1, s2", "fmul s0, s4, s3"]),
    ("seq fsqrt+fmul s", ["fsqrt s4, s1", "fmul s0, s4, s3"]),
    ("seq frecpe+frecps+fmul s", ["frecpe s4, s1", "frecps s5, s4, s1", "fmul s0, s4, s5"]),
    ("seq frsqrte+frsqrts+fmul s", ["frsqrte s4, s1", "fmul s5, s4, s4", "frsqrts s5, s1, s5", "fmul s0, s4, s5"]),
    ("seq fcmp+fcsel s", ["fcmp s1, s2", "fcsel s0, s1, s2, mi"]),
    ("seq fcmp+fcsel d", ["fcmp d1, d2", "fcsel d0, d1, d2, gt"]),
    ("seq scvtf+fmul s", ["scvtf s4, w1", "fmul s0, s4, s2"]),
    ("seq fcvtzs+scvtf s", ["fcvtzs w0, s1", "scvtf s0, w0"]),
    ("seq fmla+fadd 4s", ["fmla v0.4s, v1.4s, v2.4s", "fadd v0.4s, v0.4s, v3.4s"]),
    ("seq faddp+faddp 4s", ["faddp v0.4s, v1.4s, v2.4s", "faddp v0.4s, v0.4s, v0.4s"]),
    ("seq fadd+fadd s (Assoziativität)", ["fadd s4, s1, s2", "fadd s0, s4, s3"]),
    ("fcmp s #0.0", ["fcmp s1, #0.0"]),
    ("fcmp d #0.0", ["fcmp d1, #0.0"]),
    ("fcmpe s #0.0", ["fcmpe s1, #0.0"]),
    ("fcmpe d #0.0", ["fcmpe d1, #0.0"]),
    ("fccmpe s", ["fccmpe s1, s2, #5, mi"]),
    ("fccmpe d", ["fccmpe d1, d2, #5, ge"]),
    ("fmov s0, wzr", ["fmov s0, wzr"]),
    ("fmov d0, xzr", ["fmov d0, xzr"]),
    ("dup 4s, wzr", ["dup v0.4s, wzr"]),
    ("dup 8h, wzr", ["dup v0.8h, wzr"]),
    ("dup 2d, xzr", ["dup v0.2d, xzr"]),
    ("mov d[1], xzr", ["mov v0.d[1], xzr"]),
    ("mov d[0], xzr", ["mov v0.d[0], xzr"]),
    ("mov s[3], wzr", ["mov v0.s[3], wzr"]),
]


def reg_ok(text):
    if BADREG.search(text):
        return False
    return all(int(m.group(2)) <= 7 for m in TOK.finditer(text)) and all(int(m.group(2)) <= 3 for m in GPR.finditer(text))


MEMOP = re.compile(r"\[x1(?:, #(-?(?:0x[0-9a-f]+|\d+)))?\]")


def mem_ok(ops):
    """Nur Zugriffe auf [x1 (+ kleine Konstante)]: der Testspeicher ist 192 Byte, x1 zeigt auf Byte 64."""
    m = MEMOP.search(ops)
    return bool(m) and -48 <= int(m.group(1) or "0", 0) <= 32 and not re.search(r"\], x1$", ops)


def enum_shapes(md, rns, rds, wanted_only=None, mem=False):
    """Alle gültigen Wörter (Daten-Verarbeitung Bits 27:25 = 111 oder, mit mem, FP/SIMD-Laden/Speichern)
    -> {shape: [(word, mn, ops)]} (Reservoir 64)."""
    rnd = random.Random(1)
    out, seen = defaultdict(list), Counter()
    for hi in range(1 << 22):
        base = hi << 10
        if mem:
            if not ((base >> 27) & 1 and (base >> 26) & 1 and not (base >> 25) & 1):
                continue
        elif (base >> 25) & 7 != 7:
            continue
        for rn in rns:
            for rd in rds:
                w = base | (rn << 5) | rd
                for ins in md.disasm_lite(w.to_bytes(4, "little"), 0):
                    mn, ops = ins[2], ins[3]
                    if not reg_ok(ops) or (mem and not mem_ok(ops)):
                        continue
                    sh = shape(mn, ops)
                    if wanted_only is not None and sh not in wanted_only:
                        continue
                    seen[sh] += 1
                    lst = out[sh]
                    if len(lst) < 64:
                        lst.append((w, mn, ops))
                    else:
                        j = rnd.randrange(seen[sh])
                        if j < 64:
                            lst[j] = (w, mn, ops)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hist", default=str(ROOT / "work/recomp/diff/hist.json"))
    ap.add_argument("--ncases", type=int, default=10240)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--chains", type=int, default=800)
    ap.add_argument("--out", default=str(ROOT / "work/recomp/diff"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    h = json.loads(Path(a.hist).read_text())
    game = Counter()
    for c in h["shapes"].values():
        game.update(c)
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    cat = enum_shapes(md, [1], [0])
    catm = enum_shapes(md, [1], [0], mem=True)
    memshapes = set(catm)
    cat.update(catm)
    print("Pass 1:", len(cat), "Formen (davon Speicher", len(memshapes), "); Spielformen abgedeckt:", sum(1 for s in game if s in cat), "/", len(game), file=sys.stderr)
    missing = {s for s in game if s not in cat}
    if missing:
        more = enum_shapes(md, [0, 1, 2, 3], [0, 1, 2, 3, 16, 17], missing)
        for s, l in more.items():
            cat[s] = l
        print("Pass 2: nachgetragen", sum(1 for s in missing if s in cat), "von", len(missing), file=sys.stderr)
    notfound = sorted(s for s in game if s not in cat)
    L = Lifter(0x7000000000, "c")
    rnd = random.Random(2)
    tests, unsupported = [], []
    funcs = []

    def add(name, words, texts, freq, shp, rt=None, extra=0):
        tid = len(tests)
        code = []
        try:
            for i, w in enumerate(words):
                ins = L.lift(w, 0x7000000000 + 4 * i)
                if ins.kind != "op":
                    raise Unsupported("kind " + ins.kind)
                code.append(ins.code)
        except Unsupported as e:
            unsupported.append({"shape": shp, "name": name, "words": [f"{w:08x}" for w in words], "freq": freq, "why": str(e)})
            return
        mn0 = texts[0][0]
        fpish = any(FPISH.match(m) for m, _ in texts)
        flags = (DF_FPCR if fpish else 0) | extra | (DF_MEM if shp in memshapes else 0)
        if any(re.search(r"\bh\d", o) or re.search(r"\.\d*h\b", o) for _, o in texts):
            flags |= DF_AHP
        if any(m in ("fmadd", "fmsub", "fnmadd", "fnmsub", "fmla", "fmls") for m, _ in texts):
            flags |= DF_FMACANCEL
        rt = rt or reg_types(texts)
        funcs.append((tid, code))
        tests.append({"id": tid, "name": name, "mn": mn0, "shape": shp, "words": words, "texts": [f"{m} {o}" for m, o in texts],
                      "freq": freq, "rt": rt, "flags": flags, "n": a.ncases, "seed": 1000 + tid})

    for sh in sorted(cat, key=lambda s: -game.get(s, 0)):
        lst = cat[sh]
        inst = game.get(sh, 0) > 0
        k = a.reps * (2 if inst and ("#" in sh or "[" in sh) else 1)
        # Vertreter: zuerst natürliche Registerwahl (Rm=2, Ra=3), dann zufällig
        lst = sorted(lst, key=lambda t: (sum(1 for m in TOK.finditer(t[2]) if int(m.group(2)) > 3), rnd.random()))
        for w, mn, ops in lst[:k]:
            add(f"{mn} {ops}", [w], [(mn, ops)], game.get(sh, 0), sh)
    for name, lines in SEQS:
        words = assemble(lines)
        texts = []
        for l in lines:
            mn, _, ops = l.partition(" ")
            texts.append((mn, ops))
        add(name, words, texts, 0, "SEQ")
    # Zufallsketten: 2 bis 4 abhängige FP-Befehle auf V0..V3 (Fusions- und Zwischenwertprüfung über Befehlsgrenzen)
    crnd = random.Random(7)
    chains = []
    for ci in range(a.chains):
        arr = crnd.choice(["s", "d", "4s", "2d", "2s"])
        scalar = arr in ("s", "d")
        n = crnd.randint(2, 4)
        lines, kinds = [], []
        for i in range(n):
            dst = 0 if i == n - 1 else crnd.randint(0, 3)
            r = lambda: crnd.randint(0, 3)
            nm = lambda x: f"{arr}{x}" if scalar else f"v{x}.{arr}"
            m = crnd.random()
            if m < 0.62:
                op = crnd.choice(C3S if scalar else C3V)
                lines.append(f"{op} {nm(dst)}, {nm(r())}, {nm(r())}")
            elif m < 0.8 and scalar:
                lines.append(f"{crnd.choice(C4S)} {nm(dst)}, {nm(r())}, {nm(r())}, {nm(r())}")
            elif m < 0.8:
                lines.append(f"{crnd.choice(['fmla', 'fmls'])} {nm(dst)}, {nm(r())}, {nm(r())}")
            else:
                lines.append(f"{crnd.choice(C1S if scalar else C1V)} {nm(dst)}, {nm(r())}")
        chains.append((f"chain {ci}: " + "; ".join(lines), lines, T_F64 if arr in ("d", "2d") else T_F32))
    allw = assemble([l for _, ls, _ in chains for l in ls])
    pos = 0
    for name, lines, ty in chains:
        words = allw[pos:pos + len(lines)]
        pos += len(lines)
        texts = [(l.partition(" ")[0], l.partition(" ")[2]) for l in lines]
        add(name, words, texts, 0, "CHAIN", rt=[ty] * 4 + [T_BITS] * 4)
    # CRC32 (Ganzzahl-Klasse, im Spiel vereinzelt im SDK) und Verschlüsselungsbefehle mit Gast-Registerpaaren
    crc = [f"crc32{k} w0, w1, {'x' if k in ('x', 'cx') else 'w'}2" for k in ("b", "h", "w", "x", "cb", "ch", "cw", "cx")]
    for l, w in zip(crc, assemble(crc)):
        add("crc " + l, [w], [(l.partition(" ")[0], l.partition(" ")[2])], 0, "SEQ")
    (out / "tests.json").write_text(json.dumps({"tests": tests, "unsupported": unsupported, "game_shapes_not_found": notfound,
                                                "game_total": sum(game.values()), "game_shapes": len(game)}, indent=0))
    with open(out / "lifted.c", "w") as f:
        f.write('#include "cpu.h"\n#include "simd.h"\n')
        for tid, code in funcs:
            f.write(f"void t_{tid}(Cpu *c) {{\n" + "\n".join(code) + "\n}\n")
        f.write("GuestFn test_fns[] = {\n" + ",\n".join(f"t_{t['id']}" for t in tests) + "};\n")
        f.write(f"const int test_count = {len(tests)};\n")
    ug = sum(u["freq"] for u in unsupported)
    print(f"Tests {len(tests)}, nicht unterstützt {len(unsupported)} (Spielvorkommen {ug}), Spielformen ohne Vertreter {len(notfound)}", file=sys.stderr)
    for u in unsupported[:30]:
        print("  unsupported:", u["name"], u["why"], u["freq"], file=sys.stderr)


if __name__ == "__main__":
    main()
