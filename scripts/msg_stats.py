#!/usr/bin/env python3
"""Statistik ueber die exportierten Message-Daten (work/masterdata/msg_*/MsbtData.json); nur Zahlen/Strukturen.

Schreibt work/ui/msg_stats.json. Gibt keine Spieltexte aus (nur Zeichenklassen und Zaehler).
Aufruf: scripts/msg_stats.py [german] [english] [common]
"""
import collections
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "work", "masterdata")
OUT = os.path.join(ROOT, "work", "ui")


def analyse(name):
    with open(os.path.join(SRC, "msg_" + name, "MsbtData.json"), encoding="utf-8") as f:
        d = json.load(f)
    st = collections.defaultdict(collections.Counter)
    tot = collections.Counter()
    rich = collections.Counter()
    special = collections.Counter()
    for inst in d["instances"]:
        x = inst["data"]
        tot["dateien"] += 1
        st["isResident"][x["isResident"]] += 1
        st["isKanji"][x["isKanji"]] += 1
        st["langID"][x["langID"]] += 1
        for lab in x["labelDataArray"]:
            tot["labels"] += 1
            si = lab["styleInfo"]
            st["styleIndex"][si["styleIndex"]] += 1
            st["colorIndex"][si["colorIndex"]] += 1
            st["controlID"][si["controlID"]] += 1
            st["fontSize"][si["fontSize"]] += 1
            st["attributeLen"][len(lab["attributeValueArray"])] += 1
            if lab["labelIndex"] != lab["arrayIndex"]:
                tot["labelIndex!=arrayIndex"] += 1
            for t in lab["tagDataArray"]:
                tot["tags"] += 1
                st["tagPattern"][t["tagPatternID"]] += 1
                st["tagGroup/tag"][(t["groupID"], t["tagID"])] += 1
                st["tagParameter"][t["tagParameter"]] += 1
                st["forceGrm"][t["forceGrmID"]] += 1
                st["tagWords"][len(t["tagWordArray"] or [])] += 1
            tagidx_used = set()
            for w in lab["wordDataArray"]:
                tot["woerter"] += 1
                st["wordPattern"][w["patternID"]] += 1
                st["eventID"][w["eventID"]] += 1
                if w["patternID"] != 0:
                    st["wordPattern/tagIndexGueltig"][(w["patternID"], w["tagIndex"] >= 0)] += 1
                    if w["tagIndex"] >= len(lab["tagDataArray"]):
                        tot["tagIndex ausserhalb"] += 1
                s = w["str"] or ""
                for m in re.findall(r"<[^>]{0,40}>", s):
                    rich[re.sub(r"[=#:][^>]*", "=*", m)] += 1
                for ch in s:
                    if ord(ch) < 32 or 0x2000 <= ord(ch) <= 0x206F or ch in "\u25bc\u25bd|{}[]":
                        special[hex(ord(ch))] += 1
                if "\n" in s:
                    tot["str mit \\n"] += 1
    return {"summe": dict(tot), "felder": {k: {str(a): b for a, b in sorted(v.items(), key=lambda kv: -kv[1])[:40]} for k, v in st.items()},
            "richtext": dict(rich.most_common(40)), "sonderzeichen": dict(special.most_common(20))}


def main():
    names = sys.argv[1:] or ["german", "english", "common"]
    out = {}
    for n in names:
        out[n] = analyse(n)
        print("==", n, out[n]["summe"])
        for k, v in out[n]["felder"].items():
            print("  ", k, dict(list(v.items())[:14]))
        print("   richtext", out[n]["richtext"])
        print("   sonder", out[n]["sonderzeichen"])
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "msg_stats.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
