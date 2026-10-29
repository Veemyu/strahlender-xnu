#!/usr/bin/env python3
"""Checks the git repo for files that must never be in it (game data, keys, dumps).

Usage:   scripts/repo_check.py            checks tracked files and the index
         scripts/repo_check.py --staged    checks only the index (for a pre-commit hook)
Exit code 0 = clean, 1 = violation, 2 = error.
Own code. Reports only paths, never file contents.
"""
import argparse
import re
import subprocess
import sys

# File extensions that point to game or console data.
FORBIDDEN_SUFFIXES = (
    ".nsp", ".xci", ".nca", ".nso", ".nro", ".nsz", ".xcz", ".ncz",
    ".keys", ".tik", ".cert", ".romfs",
    ".unity3d", ".assetbundle", ".bnk", ".wem", ".webm",
    ".p12", ".mobileprovision", ".cer", ".ipa",
)

# Path components that mark local data.
FORBIDDEN_PARTS = (
    "nsp/", "Ryujinx/", "Ryujinx_", "work/", "tools/", "research/", "cache/shaders/",
    "StreamingAssets/AssetAssistant", "GameData/",
)

# File names that look like keys (independent of the folder).
FORBIDDEN_NAMES = re.compile(r"(prod|title|dev|console)\.keys$|(^|/)\.env$|(^|/)local\.env$", re.IGNORECASE)

# Size from which a tracked file is suspicious (bytes).
MAX_BYTES = 5 * 1024 * 1024

# Allowed exceptions (relative paths): deliberately keep empty and justify each one.
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
            problems.append((p, "forbidden file extension"))
            continue
        if any(part in p for part in FORBIDDEN_PARTS):
            problems.append((p, "local data path"))
            continue
        if FORBIDDEN_NAMES.search(p):
            problems.append((p, "key/environment file"))
            continue
        size = blob_size(p, staged_only)
        if size > MAX_BYTES:
            problems.append((p, f"larger than {MAX_BYTES // (1024 * 1024)} MiB ({size} bytes)"))
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", action="store_true", help="check only the index")
    args = ap.parse_args()
    try:
        paths = tracked_files(args.staged)
        problems = check(paths, args.staged)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    for path, reason in problems:
        print(f"VIOLATION: {path}: {reason}")
    if problems:
        print(f"{len(problems)} violation(s).")
        return 1
    print(f"OK: {len(paths)} files checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
