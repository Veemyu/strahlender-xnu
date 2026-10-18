#!/usr/bin/env python3
"""Fasst eine `maxwell2msl --survey --batch`-Ausgabe (JSON-Zeilen) zu einem Abdeckungs-Histogramm zusammen.

Eingabe: index.json von scripts/shader_extract_blobs.py und die Survey-Datei. Ausgabe: Text (stdout) und optional JSON.
Gezaehlt wird dreifach: eindeutige Blobs (Datei je Hash), eindeutige Codes (SPH + Code, ohne Konstanten/Reflexion) und
Programme (Blobs gewichtet mit der Zahl der Bundle-Programme, die sie verwenden).

    python3 shader_translator/survey_report.py work/shaders/blobs/index.json work/shaders/blobs/survey.jsonl \
        [--json work/shaders/blobs/report.json] [--wall-seconds 1.3] [--bundle shaders --bundle fxparticle]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Bedeutung der unbekannten Opcode-Gruppen (obere 12 Bit), soweit bestimmt; Quelle siehe docs/shader-translator.md
KNOWN_NAMES = {
    "op7e8": "HSETP2, Konstantenpuffer-Form (nur Registerform ist implementiert)",
    "op7e0": "HSETP2, Immediate-Form (nur Registerform ist implementiert)",
}


def load(index_path, survey_path, bundles):
    index = {e["hash"]: e for e in json.loads(Path(index_path).read_text())["blobs"]}
    rows = {}
    for line in Path(survey_path).read_text().splitlines():
        r = json.loads(line)
        h = Path(r["file"]).stem
        rows[h] = r
    shaders = []
    for h, e in index.items():
        r = rows.get(h)
        if r is None:
            continue
        if bundles and not (set(e["bundles"]) & set(bundles)):
            continue
        items = [("unknown:" + i["name"], i["count"]) for i in r.get("unknownOpcodes", [])]
        items += [("form:" + i["name"], i["count"]) for i in r.get("unsupportedForms", [])]
        if "inputError" in r:
            items.append(("input:" + r["inputError"], 1))
        elif "error" in r:
            items.append(("error:" + r["error"], 1))
        shaders.append({"hash": h, "code": e["codeHash"], "stage": e["stage"], "programs": e["programs"], "us": r.get("us", 0),
                        "insts": r.get("insts", 0), "items": items, "ok": not items})
    return shaders


def pct(a, b):
    return f"{100.0 * a / b:5.1f} %" if b else "    -"


def summarize(shaders):
    out = {}
    codes = {}
    for s in shaders:
        c = codes.setdefault((s["code"], s["stage"]), {"programs": 0, "ok": s["ok"], "items": {k for k, _ in s["items"]}, "insts": s["insts"]})
        c["programs"] += s["programs"]
        c["items"] |= {k for k, _ in s["items"]}
        c["ok"] = c["ok"] and s["ok"]
    for stage in ("all", "vs", "fs"):
        sel = [s for s in shaders if stage == "all" or s["stage"] == stage]
        selc = [c for (h, st), c in codes.items() if stage == "all" or st == stage]
        out[stage] = {
            "blobs": len(sel), "blobsOk": sum(s["ok"] for s in sel),
            "codes": len(selc), "codesOk": sum(c["ok"] for c in selc),
            "programs": sum(s["programs"] for s in sel), "programsOk": sum(s["programs"] for s in sel if s["ok"]),
        }
    # Rangliste je Problem
    miss = defaultdict(lambda: {"blobs": 0, "codes": set(), "programs": 0, "occurrences": 0, "vs": 0, "fs": 0, "onlyThis": 0})
    for s in shaders:
        keys = {k for k, _ in s["items"]}
        for k, n in s["items"]:
            m = miss[k]
            m["blobs"] += 1
            m["codes"].add((s["code"], s["stage"]))
            m["programs"] += s["programs"]
            m["occurrences"] += n
            m[s["stage"]] += 1
            if keys == {k}:
                m["onlyThis"] += 1
    ranking = []
    for k, m in miss.items():
        kind, name = k.split(":", 1)
        ranking.append({"kind": kind, "name": name, "meaning": KNOWN_NAMES.get(name, ""), "blobs": m["blobs"], "codes": len(m["codes"]),
                        "programs": m["programs"], "occurrences": m["occurrences"], "vs": m["vs"], "fs": m["fs"],
                        "blockedOnlyByThis": m["onlyThis"]})
    ranking.sort(key=lambda r: (-r["blobs"], r["name"]))
    # Greedy: welche Reihenfolge der Umsetzung macht am schnellsten die meisten Shader uebersetzbar
    pending = [s for s in shaders if not s["ok"]]
    done = set()
    total = len(shaders)
    ok0 = sum(s["ok"] for s in shaders)
    prog_total = sum(s["programs"] for s in shaders)
    prog_ok0 = sum(s["programs"] for s in shaders if s["ok"])
    greedy = []
    while pending:
        best, gain = None, 0
        cand = {k for s in pending for k, _ in s["items"]} - done
        for k in sorted(cand):
            g = sum(1 for s in pending if {i for i, _ in s["items"]} - done <= {k})
            if g > gain:
                best, gain = k, g
        if best is None:
            break
        done.add(best)
        ok0 += gain
        prog_ok0 += sum(s["programs"] for s in pending if {i for i, _ in s["items"]} - (done - {best}) <= {best})
        pending = [s for s in pending if {i for i, _ in s["items"]} - done]
        greedy.append({"implement": best, "newlyTranslatableBlobs": gain, "cumulativeBlobs": ok0, "cumulativeShare": round(ok0 / total, 4),
                       "cumulativeProgramShare": round(prog_ok0 / prog_total, 4)})
    unreachable = len(pending)
    us = sorted(s["us"] for s in shaders)
    insts = sum(s["insts"] for s in shaders)
    timing = {"shaders": len(us), "sumSeconds": round(sum(us) / 1e6, 3), "meanUs": round(sum(us) / max(len(us), 1), 1),
              "medianUs": us[len(us) // 2] if us else 0, "p95Us": us[int(len(us) * 0.95)] if us else 0, "maxUs": us[-1] if us else 0,
              "instructionsTotal": insts}
    return {"coverage": out, "missing": ranking, "greedyOrder": greedy, "stillBlockedAfterGreedy": unreachable, "timing": timing}


def render(rep, bundles, wall):
    L = []
    L.append("Abdeckung" + (f" (Bundles: {', '.join(bundles)})" if bundles else ""))
    L.append(f"{'Stufe':6}{'Blobs':>8}{'ok':>8}{'Anteil':>10}   {'Codes':>6}{'ok':>7}{'Anteil':>10}   {'Programme':>9}{'ok':>7}{'Anteil':>10}")
    for st in ("all", "vs", "fs"):
        c = rep["coverage"][st]
        L.append(f"{st:6}{c['blobs']:>8}{c['blobsOk']:>8}{pct(c['blobsOk'], c['blobs']):>10}   {c['codes']:>6}{c['codesOk']:>7}"
                 f"{pct(c['codesOk'], c['codes']):>10}   {c['programs']:>9}{c['programsOk']:>7}{pct(c['programsOk'], c['programs']):>10}")
    L.append("")
    L.append("Fehlende Befehle/Formen (je Blob gezaehlt):")
    L.append(f"{'Art':8}{'Name':34}{'Blobs':>7}{'Codes':>7}{'Progr.':>8}{'Vorkomm.':>9}{'nur dies':>9}{'VS':>6}{'FS':>6}  Bedeutung")
    for r in rep["missing"]:
        L.append(f"{r['kind']:8}{r['name'][:33]:34}{r['blobs']:>7}{r['codes']:>7}{r['programs']:>8}{r['occurrences']:>9}"
                 f"{r['blockedOnlyByThis']:>9}{r['vs']:>6}{r['fs']:>6}  {r['meaning']}")
    L.append("")
    L.append("Reihenfolge nach Nutzen (greedy, kumulativ):")
    for g in rep["greedyOrder"]:
        L.append(f"  +{g['newlyTranslatableBlobs']:>5} Blobs durch {g['implement']:36} -> {g['cumulativeBlobs']} ({100 * g['cumulativeShare']:.1f} % Blobs, "
                 f"{100 * g['cumulativeProgramShare']:.1f} % Programme)")
    if rep["stillBlockedAfterGreedy"]:
        L.append(f"  noch blockiert: {rep['stillBlockedAfterGreedy']}")
    t = rep["timing"]
    L.append("")
    L.append(f"Laufzeit: {t['shaders']} Shader, {t['instructionsTotal']} Instruktionen; Summe {t['sumSeconds']} s, Mittel {t['meanUs']} us, "
             f"Median {t['medianUs']} us, P95 {t['p95Us']} us, Max {t['maxUs']} us" + (f"; Wandzeit des Laufs {wall} s" if wall else ""))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("index")
    ap.add_argument("survey")
    ap.add_argument("--json")
    ap.add_argument("--wall-seconds", type=float)
    ap.add_argument("--bundle", action="append", help="nur Blobs, die in diesem Bundle vorkommen (mehrfach moeglich)")
    a = ap.parse_args()
    shaders = load(a.index, a.survey, a.bundle)
    if not shaders:
        sys.exit("keine Shader gefunden")
    rep = summarize(shaders)
    print(render(rep, a.bundle, a.wall_seconds))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
