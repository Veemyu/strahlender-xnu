#!/usr/bin/env python3
"""Findet Bundles mit MonoBehaviours einer Skriptklasse und gibt (optional) deren Felder aus.

Aufruf: scripts/ui_find_script.py <Klassenname> [--projects Dpr UIs ...] [--dump] [--max 5]
--dump gibt die Felder des TypeTrees aus, Strings werden auf Laenge gekuerzt (keine Spieltexte).
Liest nur MonoScript/MonoBehaviour. Ausgabe nur auf stdout.
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "pydeps"))
ASSETS = os.path.join(ROOT, "work", "romfs", "Data", "StreamingAssets", "AssetAssistant")


def shrink(v, depth=0):
    if isinstance(v, str):
        return "str(%d)" % len(v) if len(v) > 24 else v
    if isinstance(v, list):
        return [shrink(x, depth + 1) for x in v[:12]] + (["...%d" % len(v)] if len(v) > 12 else [])
    if isinstance(v, dict):
        return {k: shrink(x, depth + 1) for k, x in v.items()}
    return v


def main():
    import UnityPy
    ap = argparse.ArgumentParser()
    ap.add_argument("cls")
    ap.add_argument("--projects", nargs="*", default=["Dpr"])
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--max", type=int, default=3)
    a = ap.parse_args()
    cat = json.load(open(os.path.join(ROOT, "work", "dpr_catalog.json"), encoding="utf-8"))
    hits = 0
    for r in cat["recs"]:
        if r["p"] not in a.projects or r["sc"]:
            continue
        path = os.path.join(ASSETS, r["p"], r["n"])
        if not os.path.isfile(path):
            continue
        try:
            env = UnityPy.load(path)
        except Exception:  # noqa: BLE001
            continue
        for o in env.objects:
            if o.type.name != "MonoBehaviour":
                continue
            try:
                s = o.read().m_Script.read()
            except Exception:  # noqa: BLE001
                continue
            if s.m_ClassName == a.cls:
                hits += 1
                print(r["p"], r["n"], "path_id", o.path_id)
                if a.dump and hits <= a.max:
                    print(json.dumps(shrink(o.read_typetree()), ensure_ascii=False)[:3000])
    print("Treffer:", hits)


if __name__ == "__main__":
    main()
