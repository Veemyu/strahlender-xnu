#!/usr/bin/env python3
"""Spike S1, Offline-Teil: Skriptbindung der UI-Prefab-Bundles (nur Strukturen, keine Inhalte).

Aufruf: scripts/ui_s1_scan.py <Bundle-Name-aus-Katalog> [...]   (z. B. ui/uiresidentwindow)
Je Bundle: MonoBehaviours nach (Assembly, Namespace, Klasse), ob das MonoScript im Bundle liegt,
Anzahl serialisierter Felder im TypeTree. Ausgabe auf stdout; mit --json <Datei> zusaetzlich JSON
(nur unter work/, gitignoriert).
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "pydeps"))
ASSETS = os.path.join(ROOT, "work", "romfs", "Data", "StreamingAssets", "AssetAssistant", "UIs")


def scan(path):
    import UnityPy
    env = UnityPy.load(path)
    stats = collections.OrderedDict()
    scripts = {}
    types = collections.Counter()
    for o in env.objects:
        types[o.type.name] += 1
        if o.type.name == "MonoScript":
            s = o.read()
            scripts[o.path_id] = (s.m_AssemblyName, s.m_Namespace, s.m_ClassName)
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            mb = o.read(check_read=False)
            ptr = mb.m_Script
            local = ptr.file_id == 0 and ptr.path_id in scripts
            if local:
                asm, ns, cls = scripts[ptr.path_id]
            else:
                s = ptr.read()
                asm, ns, cls = s.m_AssemblyName, s.m_Namespace, s.m_ClassName
            tree = o.read_typetree()
            nfields = len(tree)
        except Exception as e:  # noqa: BLE001
            asm, ns, cls, local, nfields = "?", "?", "ERR:" + type(e).__name__, False, -1
        key = (asm, ns, cls)
        e = stats.setdefault(key, {"count": 0, "script_in_bundle": 0, "fields": nfields})
        e["count"] += 1
        e["script_in_bundle"] += 1 if local else 0
    return types, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundles", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()
    out = {}
    for b in a.bundles:
        types, stats = scan(os.path.join(ASSETS, b))
        total = sum(v["count"] for v in stats.values())
        by_asm = collections.Counter()
        for (asm, ns, cls), v in stats.items():
            by_asm[asm] += v["count"]
        print("== %s: %d Objekte, %d MonoBehaviours, %d Klassen" % (b, sum(types.values()), total, len(stats)))
        print("   Typen:", dict(types.most_common(8)))
        print("   Assemblies:", dict(by_asm))
        for (asm, ns, cls), v in sorted(stats.items(), key=lambda kv: -kv[1]["count"])[:25]:
            print("   %5d  %-26s %s.%s  (Felder %d, Skript im Bundle %d)" % (v["count"], asm, ns, cls, v["fields"], v["script_in_bundle"]))
        out[b] = {"%s|%s|%s" % k: v for k, v in stats.items()}
    if a.json:
        p = os.path.abspath(a.json)
        if not p.startswith(os.path.join(ROOT, "work") + os.sep):
            sys.exit("JSON nur unter work/")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
