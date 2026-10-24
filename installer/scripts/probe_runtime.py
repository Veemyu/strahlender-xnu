#!/usr/bin/env python3
"""Probe pinned Python wheels for every installer host without installing them."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "runtime" / "manifest.json"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(manifest):
    if manifest.get("schema") != 1 or len(manifest.get("targets", {})) != 6:
        raise ValueError("Expected manifest schema 1 with six host targets")
    if set(manifest.get("packages", {})) != {"base", "shaders"}:
        raise ValueError("Expected base and shaders package profiles")
    for name, target in manifest["targets"].items():
        if not re.fullmatch(r"[0-9a-f]{64}", target["python_sha256"]):
            raise ValueError(f"Invalid Python SHA-256 for {name}")
        if not target["python_asset"].endswith("-install_only_stripped.tar.gz"):
            raise ValueError(f"Unexpected Python archive for {name}")
        if manifest["python"]["version"] not in target["python_asset"]:
            raise ValueError(f"Python version mismatch for {name}")


def probe_target(name, target, packages, python_version, resolve, find_links=None):
    result = {"target": name, "platform": target["pip_platform"], "packages": {}, "resolved": None}
    with tempfile.TemporaryDirectory(prefix="installer-wheel-probe-") as temporary:
        destination = Path(temporary)
        platforms = target["pip_platform"]
        if isinstance(platforms, str):
            platforms = [platforms]
        common = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check",
                  "--only-binary=:all:", *(part for platform in platforms for part in ("--platform", platform)),
                  "--python-version", ".".join(python_version.split(".")[:2]),
                  "--implementation", "cp", "--abi", "cp313", "--dest", str(destination),
                  "--quiet"]
        if find_links:
            common += ["--find-links", str(find_links)]
        for package in packages:
            completed = subprocess.run([*common, "--no-deps", package], capture_output=True, text=True,
                                       check=False)
            wheels = sorted(destination.glob("*.whl"))
            normalized = package.split("==", 1)[0].lower().replace("-", "_")
            match = next((wheel for wheel in wheels if wheel.name.lower().startswith(normalized + "-")), None)
            result["packages"][package] = ({"wheel": match.name, "sha256": sha256(match)}
                                           if completed.returncode == 0 and match else
                                           {"error": last_error(completed.stderr)})
        if resolve:
            completed = subprocess.run([*common, *packages], capture_output=True, text=True, check=False)
            result["resolved"] = (self_contained_wheels(destination) if completed.returncode == 0
                                  else {"error": last_error(completed.stderr)})
    return result


def self_contained_wheels(destination):
    return {wheel.name: sha256(wheel) for wheel in sorted(destination.glob("*.whl"))}


def last_error(stderr):
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return next((line[:500] for line in reversed(lines) if line.startswith("ERROR:")),
                lines[-1][:500] if lines else "pip download failed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", help="Host target; default: all six")
    parser.add_argument("--profile", choices=("base", "shaders"), default="base")
    parser.add_argument("--resolve", action="store_true", help="Also resolve all transitive wheels")
    parser.add_argument("--find-links", type=Path, help="Include locally built wheels in the probe")
    parser.add_argument("--python-archive", type=Path, help="Verify a downloaded Python archive")
    parser.add_argument("--output", type=Path, help="Write machine-readable probe report")
    args = parser.parse_args(argv)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    names = args.target or list(manifest["targets"])
    unknown = set(names) - set(manifest["targets"])
    if unknown:
        parser.error("Unknown host target: " + ", ".join(sorted(unknown)))
    if args.python_archive and len(names) != 1:
        parser.error("--python-archive requires exactly one --target")
    packages = list(manifest["packages"]["base"])
    if args.profile == "shaders":
        packages += manifest["packages"]["shaders"]
    report = {"python": manifest["python"], "profile": args.profile, "targets": {}}
    if args.python_archive:
        expected = manifest["targets"][names[0]]["python_sha256"]
        actual = sha256(args.python_archive)
        report["python_archive"] = {"name": args.python_archive.name, "ok": actual == expected,
                                    "expected_sha256": expected, "actual_sha256": actual}
    for name in names:
        result = probe_target(name, manifest["targets"][name], packages,
                              manifest["python"]["version"], args.resolve, args.find_links)
        report["targets"][name] = result
        found = sum("wheel" in value for value in result["packages"].values())
        print(f"{name}: {found}/{len(packages)} direct wheels" +
              ("; complete dependency resolution " + ("OK" if "error" not in result["resolved"] else "FAILED")
               if args.resolve else ""))
        for package, value in result["packages"].items():
            if "error" in value:
                print(f"  {package}: {value['error']}")
        if args.resolve and "error" in result["resolved"]:
            print("  dependencies: " + result["resolved"]["error"])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if (args.python_archive and not report["python_archive"]["ok"]) or any(
        any("error" in value for value in target["packages"].values()) or
        (args.resolve and "error" in target["resolved"])
        for target in report["targets"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
