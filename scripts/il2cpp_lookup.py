#!/usr/bin/env python3
"""Sucht IL2CPP-Methoden aus work/il2cpp/script.json und gibt Ghidra-Adressen aus.

Ghidra importiert main.elf mit Image Base 0x100000, Il2CppDumper rechnet ab 0.
Beispiel: scripts/il2cpp_lookup.py '^SaveData\\$\\$' --limit 20
"""
import argparse
import json
import re
from pathlib import Path

IMAGE_BASE = 0x100000
SCRIPT = Path(__file__).resolve().parent.parent / "work/il2cpp/script.json"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pattern", help="Regex auf den Methodennamen (Klasse$$Methode)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--sig", action="store_true", help="Signatur mit ausgeben")
    args = p.parse_args()
    rx = re.compile(args.pattern)
    shown = 0
    for m in json.load(open(SCRIPT))["ScriptMethod"]:
        if rx.search(m["Name"]):
            line = f"0x{m['Address'] + IMAGE_BASE:x}  {m['Name']}"
            if args.sig:
                line += f"  {m['Signature']}"
            print(line)
            shown += 1
            if shown >= args.limit:
                break


if __name__ == "__main__":
    main()
