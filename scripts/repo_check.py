#!/usr/bin/env python3
"""Prüft das Git-Repo auf Dateien, die nie hineingehören (Spieldaten, Schlüssel, Dumps).

Aufruf:  scripts/repo_check.py            prüft getrackte Dateien und den Index
         scripts/repo_check.py --staged    prüft nur den Index (für einen Pre-Commit-Hook)
Exit-Code 0 = sauber, 1 = Verstoß, 2 = Fehler.
Eigener Code. Meldet nur Pfade, nie Dateiinhalte.
"""
import argparse
import re
import subprocess
import sys

# Dateiendungen, die auf Spiel- oder Konsolendaten hindeuten.
FORBIDDEN_SUFFIXES = (
    ".nsp", ".xci", ".nca", ".nso", ".nro", ".nsz", ".xcz", ".ncz",
    ".keys", ".tik", ".cert", ".romfs",
    ".unity3d", ".assetbundle", ".bnk", ".wem", ".webm",
    ".p12", ".mobileprovision", ".cer", ".ipa",
)

# Pfadbestandteile, die lokale Daten markieren.
FORBIDDEN_PARTS = (
    "nsp/", "Ryujinx/", "work/", "tools/", "research/",
    "StreamingAssets/AssetAssistant", "GameData/",
    "unity/Library/", "unity/Temp/",
)

# Dateinamen mit Schlüssel-Charakter (unabhängig vom Ordner).
FORBIDDEN_NAMES = re.compile(r"(prod|title|dev|console)\.keys$|(^|/)\.env$|(^|/)local\.env$", re.IGNORECASE)

# Größe, ab der eine getrackte Datei verdächtig ist (Byte).
MAX_BYTES = 5 * 1024 * 1024

# Erlaubte Ausnahmen (relative Pfade) – bewusst leer halten und begründen.
ALLOWED = set()


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def tracked_files(staged_only):
    if staged_only:
        out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    else:
        out = git("ls-files", "-z")
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def blob_size(path, staged_only):
    spec = f":{path}"
    try:
        return int(git("cat-file", "-s", spec).decode().strip())
    except subprocess.CalledProcessError:
        return 0


def check(paths, staged_only):
    problems = []
    for p in paths:
        if p in ALLOWED:
            continue
        low = p.lower()
        if low.endswith(FORBIDDEN_SUFFIXES):
            problems.append((p, "verbotene Dateiendung"))
            continue
        if any(part in p for part in FORBIDDEN_PARTS):
            problems.append((p, "lokaler Datenpfad"))
            continue
        if FORBIDDEN_NAMES.search(p):
            problems.append((p, "Schlüssel-/Umgebungsdatei"))
            continue
        size = blob_size(p, staged_only)
        if size > MAX_BYTES:
            problems.append((p, f"größer als {MAX_BYTES // (1024 * 1024)} MiB ({size} Byte)"))
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", action="store_true", help="nur den Index prüfen")
    args = ap.parse_args()
    try:
        paths = tracked_files(args.staged)
        problems = check(paths, args.staged)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    for path, reason in problems:
        print(f"VERSTOSS: {path}: {reason}")
    if problems:
        print(f"{len(problems)} Verstoß/Verstöße.")
        return 1
    print(f"OK: {len(paths)} Dateien geprüft.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
