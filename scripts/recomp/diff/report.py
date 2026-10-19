#!/usr/bin/env python3
"""Auswertung des Differenzialtests (docs/recomp-diff.md): Tabellen aus tests.json, hist.json und Berichten.
Eigener Code. Aufruf: report.py <bericht.json> [...] [--top 45]   (Markdown auf stdout)"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
D = ROOT / "work/recomp/diff"


def main():
    reps = [a for a in sys.argv[1:] if a.endswith(".json")]
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 45
    T = json.loads((D / "tests.json").read_text())
    tests = T["tests"]
    h = json.loads((D / "hist.json").read_text())
    mn = Counter()  # nur FP-/SIMD-Formen (Daten-Verarbeitung und FP/SIMD-Laden/Speichern), keine Ganzzahl-Verwendung von mov/add/ldr
    for c in h["shapes"].values():
        for s, v in c.items():
            mn[s.split()[0]] += v
    total_words = sum(h["words"].values())
    for rp in reps:
        r = json.loads(Path(rp).read_text())
        print(f"\n### Bericht {Path(rp).name}: Basis `{r['srcs'][0]}`")
        for s in r["srcs"][1:]:
            res = [x for x in r["results"] if "cmp" in x]
            cases = sum(x["cmp"][s]["n"] for x in res)
            bad = sum(x["cmp"][s]["bad"] for x in res)
            fpsr = sum(x["cmp"][s]["fpsr"] for x in res)
            fo = sum(x["cmp"][s]["fpsr_only"] for x in res)
            tb = sum(1 for x in res if x["cmp"][s]["bad"])
            print(f"- `{s}`: Tests {len(res)}, Fälle {cases:,}, Tests mit Abweichung {tb}, Fälle mit Abweichung {bad:,}, FPSR-Abweichungen {fpsr:,}")
        if len(reps) == 1 or rp == reps[0]:
            pass
    # Familientabelle (Bericht 1)
    r = json.loads(Path(reps[0]).read_text())
    fam = defaultdict(lambda: {"tests": 0, "cases": 0, "bad": defaultdict(int)})
    for x in r["results"]:
        if "cmp" not in x:
            continue
        t = tests[x["id"]]
        k = t["mn"] if t["shape"] not in ("SEQ", "CHAIN") else "(" + t["shape"].lower() + ")"
        fam[k]["tests"] += 1
        fam[k]["cases"] += t["n"]
        for s in r["srcs"][1:]:
            fam[k]["bad"][s] += x["cmp"][s]["bad"]
    print("\n| Befehl | Vorkommen im Spiel | Anteil an allen Wörtern | Tests | Fälle | Abweichungen |")
    print("|---|---:|---:|---:|---:|---:|")
    rows = sorted(fam.items(), key=lambda kv: -mn.get(kv[0], 0))
    for k, v in rows[:top]:
        n = mn.get(k, 0)
        print(f"| {k} | {n:,} | {100 * n / total_words:.3f} % | {v['tests']} | {v['cases']:,} | {sum(v['bad'].values()):,} |".replace(",", "."))
    rest = rows[top:]
    print(f"| übrige {len(rest)} Befehle/Gruppen | {sum(mn.get(k, 0) for k, _ in rest):,} | | {sum(v['tests'] for _, v in rest)} | {sum(v['cases'] for _, v in rest):,} | {sum(sum(v['bad'].values()) for _, v in rest):,} |".replace(",", "."))
    # Spielabdeckung
    gs = sum(t["freq"] for t in tests if t["shape"] not in ("SEQ", "CHAIN"))
    uns = T["unsupported"]
    print(f"\nTests {len(tests)}; Formen ohne Lifter-Unterstützung: {len(uns)} (Spielvorkommen {sum(u['freq'] for u in uns)}); Spielformen ohne Vertreter: {len(T['game_shapes_not_found'])}")


if __name__ == "__main__":
    main()
