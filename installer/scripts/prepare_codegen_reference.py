#!/usr/bin/env python3
"""Extract locked development-only oracle packages outside the shipped runtime."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def extract_verified(wheel, expected, output):
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != expected:
        raise ValueError("Oracle wheel checksum mismatch")
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                raise ValueError("Unsafe oracle wheel path")
        archive.extractall(output)


def prepare(target, output, wheelhouse=None):
    lock = json.loads((ROOT / "runtime/reference-wheels.lock.json").read_text())
    if output.exists():
        raise ValueError("Oracle output already exists")
    expected = lock["targets"][target]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="codegen-reference-") as name:
        stage = Path(name)
        packages = stage / "packages"
        packages.mkdir()
        for item in expected.values():
            wheel = (wheelhouse / item["wheel"]) if wheelhouse else stage / item["wheel"]
            if not wheelhouse:
                distribution, version = item["wheel"].split("-", 2)[:2]
                with urllib.request.urlopen(f"https://pypi.org/pypi/{distribution}/{version}/json", timeout=30) as response:
                    data = json.load(response)
                asset = next(x for x in data["urls"] if x["filename"] == item["wheel"] and x["digests"]["sha256"] == item["sha256"])
                urllib.request.urlretrieve(asset["url"], wheel)
            extract_verified(wheel, item["sha256"], packages)
        (packages / "reference.json").write_text(json.dumps(dict(target=target, wheels=expected), indent=2) + "\n")
        packages.rename(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--wheelhouse", type=Path, help="Use only existing locked wheels")
    args = parser.parse_args()
    print(prepare(args.target, args.output.resolve(), args.wheelhouse))
