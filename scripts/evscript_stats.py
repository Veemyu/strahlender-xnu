#!/usr/bin/env python3
"""Befehlsstatistik ueber alle Event-Skripte (work/masterdata/ev_script/EvData.json) mit Namen aus dump.cs.

Gibt nur Zahlen und Befehlsnamen (EvCmdID) aus, keine Texte. Schreibt work/evscript/stats.json.
Je Befehl: Anzahl, Anzahl Skripte, Anzahl Dateien, haeufigste Argument-Signaturen (argType-Folge).
Aufruf: scripts/evscript_stats.py [Top-N=60]
"""
import collections
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EV = os.path.join(ROOT, "work", "masterdata", "ev_script", "EvData.json")
DUMP = os.path.join(ROOT, "work", "il2cpp", "dump.cs")
OUT = os.path.join(ROOT, "work", "evscript")

ENUM_RE = re.compile(r"public const EvCmdID\.NAME (\w+) = (-?\d+);")


def load_names(path=DUMP):
    names = {}
    inside = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not inside:
                if line.startswith("public enum EvCmdID.NAME"):
                    inside = True
                continue
            if line.startswith("}"):
                break
            m = ENUM_RE.search(line)
            if m:
                names[int(m.group(2))] = m.group(1).lstrip("_")
    return names


def analyse(ev, names):
    cnt = collections.Counter()
    scripts = collections.defaultdict(set)
    files = collections.defaultdict(set)
    sigs = collections.defaultdict(collections.Counter)
    tot = collections.Counter()
    sid = 0
    for inst in ev["instances"]:
        tot["dateien"] += 1
        for sc in inst["data"]["Scripts"]:
            tot["skripte"] += 1
            sid += 1
            for cmd in sc["Commands"]:
                tot["befehle"] += 1
                arg = cmd["Arg"]
                if not arg:
                    cnt["leer"] += 1
                    continue
                cid = arg[0]["data"]
                cnt[cid] += 1
                scripts[cid].add(sid)
                files[cid].add(inst["name"])
                sigs[cid]["".join(str(a["argType"]) for a in arg[1:])] += 1
    return tot, cnt, scripts, files, sigs


def main():
    top = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    names = load_names()
    with open(EV, encoding="utf-8") as f:
        ev = json.load(f)
    tot, cnt, scripts, files, sigs = analyse(ev, names)
    ids = sorted((k for k in cnt if k != "leer"), key=lambda k: -cnt[k])
    rows = []
    for k in ids:
        rows.append({
            "id": k, "name": names.get(k, "?"), "count": cnt[k], "scripts": len(scripts[k]),
            "files": len(files[k]), "signatures": dict(sigs[k].most_common(4)),
        })
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8") as f:
        json.dump({"totals": dict(tot), "empty": cnt["leer"], "commands": rows}, f, indent=1)
    print("Dateien %d, Skripte %d, Befehle %d, leere Befehle %d, verschiedene IDs %d (davon -1: %d)" % (
        tot["dateien"], tot["skripte"], tot["befehle"], cnt["leer"], len(ids), cnt.get(-1, 0)))
    print("EvCmdID im Dump: %d, davon benutzt: %d" % (len(names), len([k for k in ids if k in names])))
    cum = 0
    for i, r in enumerate(rows[:top]):
        cum += r["count"]
        print("%3d %5d %-34s n=%6d skripte=%5d dateien=%3d kum=%5.1f%% sig=%s" % (
            i + 1, r["id"], r["name"], r["count"], r["scripts"], r["files"], 100.0 * cum / tot["befehle"],
            list(r["signatures"].items())[:2]))


if __name__ == "__main__":
    main()
