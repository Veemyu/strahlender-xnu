#!/usr/bin/env python3
"""Assemble a verified, offline-capable private backend Python on the native host."""

import argparse
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from probe_runtime import MANIFEST, ROOT, sha256, validate_manifest


LOCK = ROOT / "runtime" / "wheels.lock.json"


def host_target():
    system = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    machine = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64",
               "AMD64": "x86_64"}.get(platform.machine())
    return f"{system}-{machine}" if system and machine else None


def run(command, env=None):
    subprocess.run(command, check=True, env=env)


def verify_wheels(wheelhouse, expected):
    for package, entry in expected.items():
        path = wheelhouse / entry["wheel"]
        if not path.is_file():
            raise ValueError(f"Missing locked wheel for {package}: {path.name}")
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"SHA-256 mismatch for {path.name}")


def python_path(directory, name):
    return (directory / "python" / "python.exe" if name.startswith("windows-") else
            directory / "python" / "bin" / "python3")


def assemble(name, archive, output, wheelhouse, fetch):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if lock["schema"] != 1 or lock["python"] != manifest["python"]["version"]:
        raise ValueError("Wheel lock and Python manifest disagree")
    if name != host_target():
        raise ValueError(f"Native assembly requires {host_target()}, received {name}")
    if name not in lock["targets"]:
        raise ValueError(f"No verified wheel lock for {name}")
    expected_archive = manifest["targets"][name]["python_sha256"]
    if sha256(archive) != expected_archive:
        raise ValueError("Python archive SHA-256 mismatch")
    if output.exists():
        raise ValueError(f"Output already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="installer-runtime-stage-", dir=output.parent) as stage_name:
        stage = Path(stage_name)
        wheels = wheelhouse or stage / "wheels"
        wheels.mkdir(parents=True, exist_ok=True)
        platforms = manifest["targets"][name]["pip_platform"]
        if isinstance(platforms, str):
            platforms = [platforms]
        if fetch:
            for package in manifest["packages"]["base"]:
                run([sys.executable, "-m", "pip", "download", "--disable-pip-version-check",
                     "--only-binary=:all:", "--no-deps", "--python-version", "3.13",
                     "--implementation", "cp", "--abi", "cp313",
                     *(part for item in platforms for part in ("--platform", item)),
                     "--dest", str(wheels), package, "--quiet"])
        verify_wheels(wheels, lock["targets"][name])

        runtime = stage / "runtime"
        runtime.mkdir()
        with tarfile.open(archive, "r:gz") as source:
            source.extractall(runtime, filter="data")
        python = python_path(runtime, name)
        if not python.is_file():
            raise ValueError("Verified archive does not contain the expected Python executable")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PYTHONNOUSERSITE"] = "1"
        run([str(python), "-I", "-B", "-m", "pip", "install", "--no-index",
             "--disable-pip-version-check", "--no-compile", "--no-deps",
             "--find-links", str(wheels), *manifest["packages"]["base"]], env=env)
        run([str(python), "-I", "-B", "-c",
             "import sys; assert sys.version_info[:3] == (3, 13, 15)"], env=env)
        run([str(python), "-I", "-B", str(ROOT / "runtime" / "native_smoke.py")], env=env)
        (runtime / "runtime.json").write_text(json.dumps({
            "schema": 1, "target": name, "python": manifest["python"]["version"],
            "python_sha256": expected_archive,
            "wheels": lock["targets"][name],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        runtime.rename(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=host_target())
    parser.add_argument("--python-archive", required=True, type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--fetch-wheels", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.fetch_wheels and args.wheelhouse is None:
        parser.error("Specify --wheelhouse or --fetch-wheels")
    output = assemble(args.target, args.python_archive.resolve(), args.output.resolve(),
                      args.wheelhouse.resolve() if args.wheelhouse else None, args.fetch_wheels)
    print(f"Private runtime verified at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
