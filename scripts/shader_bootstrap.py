#!/usr/bin/env python3
"""Prepares the shader bootstrap on this computer, from the user's own RomFS: the game's Maxwell shader programs are translated to MSL
(shader_translator, the same translator and key the runtime uses) and compiled to Metal libraries with the target SDK, so the first
start finds a prebuilt library for nearly every shader instead of compiling it while the game runs.

Nothing here is downloaded or shipped: inputs are work/romfs, outputs live in the shader cache (default work/recomp/cache, or
BDSP_SHADER_CACHE_DIR), which make_app.sh and installer_build.sh already bundle (shaders-bin, pipelines.bin).

Usage: python3 scripts/shader_bootstrap.py --sdk macosx|iphoneos [--work work] [--cache DIR] [--force]
Exit codes: 0 ready (or reused), 3 a prerequisite is missing (UnityPy, clang, Metal compiler), 4 a step failed.
Own code."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ("romfs/Data/StreamingAssets/AssetAssistant/Dpr/shaders",   # below the work folder
           "romfs/Data/StreamingAssets/AssetAssistant/Effects/fxparticle",
           "romfs/Data/resources.assets",
           "romfs/Data/StreamingAssets/AssetAssistant/Dpr/tmpshader")
TRANSLATOR_SOURCES = ("main.c", "translate.c", "container.c", "container.h", "shader.h")
EX_MISSING, EX_FAILED = 3, 4


class Missing(Exception):
    pass


def say(message):
    print("shaders: " + message, flush=True)


def sha256_of(parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else str(part).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def fnv64(text):
    """The runtime's fnv64 (renderer.m): the name under which it looks for a prebuilt library."""
    value = 0xcbf29ce484222325
    for byte in text:
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return "%016x" % value


def metal_version(sdk):
    result = subprocess.run(["xcrun", "-sdk", sdk, "metal", "--version"], capture_output=True, text=True)
    if result.returncode:
        raise Missing("The %s Metal compiler is missing. Install it with: xcodebuild -downloadComponent MetalToolchain" % sdk)
    return result.stdout.strip()


def stamp(root, work, sdk, metal):
    """Everything the output depends on: the translator, the compile script, the game's shader files and the Metal compiler."""
    parts = [sdk, metal, (root / "scripts/recomp/shader_bin.sh").read_bytes(), (root / "scripts/shader_extract_blobs.py").read_bytes()]
    parts += [(root / "shader_translator" / name).read_bytes() for name in TRANSLATOR_SOURCES]
    for bundle in BUNDLES:
        path = work / bundle
        parts.append("%s:%s" % (bundle, path.stat().st_size if path.is_file() else "none"))
    return sha256_of(parts)


def run(command, **options):
    result = subprocess.run(command, capture_output=True, text=True, **options)
    if result.returncode:
        raise RuntimeError("%s failed (%d): %s" % (Path(command[0]).name, result.returncode, (result.stderr or result.stdout).strip()[-300:]))
    return result


def extract_blobs(root, work):
    """The game's shader programs from its Unity bundles (scripts/shader_extract_blobs.py), including resources.assets and tmpshader."""
    if not (work / BUNDLES[0]).is_file():
        raise Missing("The game's shader bundle is missing: run the extract step first.")
    try:
        import UnityPy  # noqa: F401
    except ImportError as error:
        raise Missing("UnityPy is not available in this Python runtime.") from error
    if work != root / "work":
        raise Missing("The shader extraction reads work/ of the source folder.")
    out = work / "shaders/blobs"
    environment = dict(os.environ)
    pydeps = root / "tools/pydeps"
    if pydeps.is_dir():
        environment["PYTHONPATH"] = str(pydeps) + os.pathsep + environment.get("PYTHONPATH", "")
    run([sys.executable, str(root / "scripts/shader_extract_blobs.py"), "--out", str(out), "--extra"], cwd=root, env=environment)
    return out


def build_translator(root, work):
    binary = work / "shaders/maxwell2msl"
    binary.parent.mkdir(parents=True, exist_ok=True)
    sources = [str(root / "shader_translator" / name) for name in ("main.c", "translate.c", "container.c")]
    try:
        run(["clang", "-O2", "-std=gnu11", "-w", "-o", str(binary), *sources, "-lm"])
    except FileNotFoundError as error:
        raise Missing("clang is missing.") from error
    return binary


def translate(binary, blobs, cache_shaders):
    """One process translates every program and writes <cache>/shaders/{v,f}_<fnv64>.metal (identical text once)."""
    index = json.loads((blobs / "index.json").read_text())["blobs"]
    listing = blobs / "translate-list.txt"
    listing.write_text("".join("%s %s\n" % (entry["stage"], blobs / (entry["hash"] + ".bin")) for entry in index if entry["stage"] in ("vs", "fs")))
    cache_shaders.mkdir(parents=True, exist_ok=True)
    log = blobs / "translate-log.jsonl"
    result = subprocess.run([str(binary), "--batch", str(listing), "--emit-cache", str(cache_shaders), "-o", str(log), "--vs-out-mask", "0x0"],
                            capture_output=True, text=True)
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    failed = [row for row in rows if "error" in row]
    skipped = sum(1 for row in rows if "skipped" in row)
    unique = len({(row["stage"], row["fnv"]) for row in rows if "fnv" in row})
    if result.returncode not in (0, 1) or len(failed) > len(rows) // 20:
        raise RuntimeError("translation failed for %d of %d programs: %s" % (len(failed), len(rows), (failed[0] if failed else result.stderr)))
    return {"programs": len(rows), "unique": unique, "skipped_global_memory": skipped, "failed": len(failed)}


def compile_libraries(root, sdk, cache_shaders, cache_bin):
    run(["bash", str(root / "scripts/recomp/shader_bin.sh"), sdk, str(cache_shaders), str(cache_bin)], cwd=root)
    return len(list(cache_bin.glob("[vf]_*.metallib")))


def prepare(root, work, cache, sdk, force=False):
    started = time.monotonic()
    metal = metal_version(sdk)
    cache_shaders, cache_bin = cache / "shaders", cache / ("shaders-bin-" + sdk)
    stamp_file = cache / ("bootstrap-%s.stamp" % sdk)
    wanted = stamp(root, work, sdk, metal)
    if not force and stamp_file.is_file() and stamp_file.read_text().strip() == wanted and any(cache_bin.glob("[vf]_*.metallib")):
        say("reusing the libraries prepared earlier (%d)" % len(list(cache_bin.glob("[vf]_*.metallib"))))
        return 0
    say("reading the shader programs of the game")
    blobs = extract_blobs(root, work)
    say("building the translator")
    binary = build_translator(root, work)
    say("translating")
    summary = translate(binary, blobs, cache_shaders)
    say("%(unique)d distinct shaders from %(programs)d programs (%(skipped_global_memory)d use global memory and compile at run time)" % summary)
    say("compiling the Metal libraries for %s" % sdk)
    count = compile_libraries(root, sdk, cache_shaders, cache_bin)
    cache.mkdir(parents=True, exist_ok=True)
    stamp_file.write_text(wanted + "\n")
    say("%d libraries ready in %.0f s" % (count, time.monotonic() - started))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sdk", required=True, choices=("macosx", "iphoneos"))
    parser.add_argument("--work", default=str(ROOT / "work"))
    parser.add_argument("--cache", default=os.environ.get("BDSP_SHADER_CACHE_DIR") or "")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    work = Path(args.work).resolve()
    cache = Path(args.cache).resolve() if args.cache else work / "recomp/cache"
    try:
        return prepare(ROOT, work, cache, args.sdk, args.force)
    except Missing as error:
        say("skipped: %s" % error)
        return EX_MISSING
    except (RuntimeError, OSError, ValueError) as error:
        say("failed: %s" % error)
        return EX_FAILED


if __name__ == "__main__":
    sys.exit(main())
