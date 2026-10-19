#!/usr/bin/env python3
"""Gibt Klassen aus work/il2cpp/dump.cs ohne RVA-Zeilen aus (nur lesen, Analysephase ap-ui).

Beispiel: scripts/ui_dump_view.py MessageEnumData.TagPatternID --methods
Name = vollstaendiger Name wie im Dump (ggf. 'Aussen.Innen'); Namespace-unabhaengig, erste Uebereinstimmung je Namespace.
"""
import argparse
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DUMP = os.path.join(ROOT, "work", "il2cpp", "dump.cs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--methods", action="store_true", help="Methodensignaturen mit ausgeben")
    ap.add_argument("--ns", default=None, help="Namespace-Filter (Teilstring)")
    ap.add_argument("--max", type=int, default=400, help="max Zeilen je Klasse")
    a = ap.parse_args()
    wanted = set(a.names)
    with open(DUMP, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    ns = ""
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln.startswith("// Namespace:"):
            ns = ln.split(":", 1)[1].strip()
        m = re.match(r"(?:public |internal |private |protected )?(?:sealed |abstract |static )*(?:class|struct|enum|interface) ([^\s{]+)", ln)
        if m and not ln.startswith("\t") and m.group(1) in wanted and (not a.ns or a.ns in ns):
            j = i
            out = ["// Namespace: " + ns, ln]
            j += 1
            while j < n and lines[j] != "}":
                t = lines[j]
                if t.strip().startswith("// RVA"):
                    j += 1
                    continue
                if not a.methods and "(" in t and ")" in t and "{ }" in t:
                    j += 1
                    continue
                if t.strip() == "" or t.strip() in ("// Methods", "// Fields", "// Properties"):
                    j += 1
                    continue
                out.append(t)
                j += 1
            out.append("}")
            print("\n".join(out[: a.max]))
            print()
        i += 1


if __name__ == "__main__":
    main()
