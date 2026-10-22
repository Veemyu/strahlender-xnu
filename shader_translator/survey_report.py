#!/usr/bin/env python3
"""Summarizes a `maxwell2msl --survey --batch` output (JSON lines) into a coverage histogram.

Input: index.json from scripts/shader_extract_blobs.py and the survey file. Output: text (stdout) and optionally JSON.
Counted three ways: unique blobs (one file per hash), unique codes (SPH + code, without constants/reflection) and
programs (blobs weighted by the number of bundle programs that use them).

    python3 shader_translator/survey_report.py work/shaders/blobs/index.json work/shaders/blobs/survey.jsonl \
        [--json work/shaders/blobs/report.json] [--wall-seconds 1.3] [--bundle shaders --bundle fxparticle]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Meaning of the unknown opcode groups (upper 12 bits), as far as determined; source see docs/shaders.md
KNOWN_NAMES = {
    "op7e8": "HSETP2, constant buffer form (implemented since part 2; name only for older survey runs)",
    "op7e0": "HSETP2, immediate form (implemented since part 2; name only for older survey runs)",
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
    # Greedy: which implementation order makes the most shaders translatable the fastest
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
    L.append("Coverage" + (f" (bundles: {', '.join(bundles)})" if bundles else ""))
    L.append(f"{'Stage':6}{'Blobs':>8}{'ok':>8}{'Share':>10}   {'Codes':>6}{'ok':>7}{'Share':>10}   {'Programs':>9}{'ok':>7}{'Share':>10}")
    for st in ("all", "vs", "fs"):
        c = rep["coverage"][st]
        L.append(f"{st:6}{c['blobs']:>8}{c['blobsOk']:>8}{pct(c['blobsOk'], c['blobs']):>10}   {c['codes']:>6}{c['codesOk']:>7}"
                 f"{pct(c['codesOk'], c['codes']):>10}   {c['programs']:>9}{c['programsOk']:>7}{pct(c['programsOk'], c['programs']):>10}")
    L.append("")
    L.append("Missing instructions/forms (counted per blob):")
    L.append(f"{'Kind':8}{'Name':34}{'Blobs':>7}{'Codes':>7}{'Progr.':>8}{'Occur.':>9}{'only this':>9}{'VS':>6}{'FS':>6}  Meaning")
    for r in rep["missing"]:
        L.append(f"{r['kind']:8}{r['name'][:33]:34}{r['blobs']:>7}{r['codes']:>7}{r['programs']:>8}{r['occurrences']:>9}"
                 f"{r['blockedOnlyByThis']:>9}{r['vs']:>6}{r['fs']:>6}  {r['meaning']}")
    L.append("")
    L.append("Order by benefit (greedy, cumulative):")
    for g in rep["greedyOrder"]:
        L.append(f"  +{g['newlyTranslatableBlobs']:>5} blobs through {g['implement']:36} -> {g['cumulativeBlobs']} ({100 * g['cumulativeShare']:.1f} % blobs, "
                 f"{100 * g['cumulativeProgramShare']:.1f} % programs)")
    if rep["stillBlockedAfterGreedy"]:
        L.append(f"  still blocked: {rep['stillBlockedAfterGreedy']}")
    t = rep["timing"]
    L.append("")
    L.append(f"Run time: {t['shaders']} shaders, {t['instructionsTotal']} instructions; sum {t['sumSeconds']} s, mean {t['meanUs']} us, "
             f"median {t['medianUs']} us, P95 {t['p95Us']} us, max {t['maxUs']} us" + (f"; wall time of the run {wall} s" if wall else ""))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("index")
    ap.add_argument("survey")
    ap.add_argument("--json")
    ap.add_argument("--wall-seconds", type=float)
    ap.add_argument("--bundle", action="append", help="only blobs that occur in this bundle (repeatable)")
    a = ap.parse_args()
    shaders = load(a.index, a.survey, a.bundle)
    if not shaders:
        sys.exit("no shaders found")
    rep = summarize(shaders)
    print(render(rep, a.bundle, a.wall_seconds))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
