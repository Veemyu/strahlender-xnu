#!/usr/bin/env python3
"""Schreibt die Namen des Spiel-Enums ZoneID (Name -> Zonen-ID) nach work/masterdata/field/ZoneNames.json.

Quelle ist work/il2cpp/dump.cs (lokal, gitignoriert). Es entstehen nur Bezeichner und Zahlen.
Die MapWarp-/PlaceData-Instanzen heissen "MapWarp_<Name>" / "PlaceData_<Name>" nach diesem Enum.

Aufruf: python3 scripts/field_zone_names.py [--dump work/il2cpp/dump.cs] [--out work/masterdata/field/ZoneNames.json]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENUM_HEADER = "public enum ZoneID // TypeDefIndex"
CONST_RE = re.compile(r"public const ZoneID (\w+) = (-?\d+);")


def parse_enum(text, name):
    """Liest die Konstanten eines Enums (ZoneID, TrainerID) aus dem Text von dump.cs."""
    start = text.find("public enum %s // TypeDefIndex" % name)
    if start < 0:
        raise ValueError("Enum %s nicht gefunden" % name)
    end = text.find("\n}", start)
    body = text[start:end if end > 0 else len(text)]
    rx = re.compile(r"public const %s (\w+) = (-?\d+);" % name)
    return {m.group(1): int(m.group(2)) for m in rx.finditer(body)}


def parse_zone_enum(text):
    """Liest die Konstanten des Enums ZoneID aus dem Text von dump.cs."""
    return parse_enum(text, "ZoneID")


def ignored(path):
    r = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=ROOT)
    return r.returncode == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dump", default=str(ROOT / "work/il2cpp/dump.cs"))
    ap.add_argument("--out", default=str(ROOT / "work/masterdata/field/ZoneNames.json"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    if not ignored(out):
        print("Zielordner ist nicht gitignoriert: " + str(out), file=sys.stderr)
        return 2
    text = Path(args.dump).read_text(encoding="utf-8", errors="replace")
    names = parse_zone_enum(text)
    trainers = parse_enum(text, "TrainerID")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ZoneID": names, "TrainerID": trainers}, indent=1, sort_keys=True), encoding="utf-8")
    print("%d Zonennamen, %d Trainernamen -> %s" % (len(names), len(trainers), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
