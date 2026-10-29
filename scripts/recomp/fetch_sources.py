#!/usr/bin/env python3
"""Downloads the pinned inputs of the Windows build environment (GitHub Actions job windows-buildenv.yml).

Every file is checked against the size and SHA-256 recorded in installer/assets/windows-sources.json and
windows-dependencies.json before it is kept; nothing is fetched from a moving reference.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "installer/assets"


def plan(assets=ASSETS):
    """Source tarballs (name-revision.tar.gz as dependency_build expects), SDL, FFmpeg and LLVM-MinGW."""
    sources = json.loads((assets / "windows-sources.json").read_text(encoding="utf-8"))["sources"]
    components = {c["id"]: c for c in json.loads((assets / "windows-dependencies.json").read_text(encoding="utf-8"))["components"]}
    items = [{"name": name + "-" + item["revision"] + ".tar.gz",
              "url": "https://github.com/%s/archive/%s.tar.gz" % (item["repository"], item["revision"]),
              "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
             for name, item in sources.items()]
    sdl = components["SDL3"]["source_archive"]
    items.append({"name": "SDL3-source.tar.gz", **{k: sdl[k] for k in ("url", "sha256", "size_bytes")}})
    ffmpeg = components["ffmpeg"]["artifacts"][0]
    items.append({"name": "ffmpeg-binaries.zip", **{k: ffmpeg[k] for k in ("url", "sha256", "size_bytes")}})
    toolchain = components["llvm-mingw"]["artifacts"][0]
    items.append({"name": "llvm-mingw.zip", **{k: toolchain[k] for k in ("url", "sha256", "size_bytes")}})
    return items


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_url(url, destination):
    try:
        with urllib.request.urlopen(url, timeout=120) as response, open(destination, "wb") as output:
            shutil.copyfileobj(response, output)
    except OSError:
        curl = shutil.which("curl")
        if not curl:
            raise
        subprocess.run([curl, "-fsSL", "--retry", "3", "-o", str(destination), url], check=True)


def fetch(items, out, download=fetch_url):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for item in items:
        target = out / item["name"]
        if target.is_file() and target.stat().st_size == item["size_bytes"] and sha256(target) == item["sha256"]:
            continue
        temporary = target.with_suffix(target.suffix + ".part")
        download(item["url"], temporary)
        if temporary.stat().st_size != item["size_bytes"] or sha256(temporary) != item["sha256"]:
            temporary.unlink(missing_ok=True)
            raise ValueError("Size or SHA-256 mismatch: " + item["name"])
        temporary.replace(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        fetch(plan(), args.out)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("Download failed: " + str(error), file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
