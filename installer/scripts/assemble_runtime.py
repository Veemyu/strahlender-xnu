#!/usr/bin/env python3
"""Assemble a verified, offline-capable private backend Python on the native host."""

import argparse
import json
import os
import platform
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from probe_runtime import MANIFEST, ROOT, sha256, validate_manifest


LOCK = ROOT / "runtime" / "wheels.lock.json"


def windows_inventory(runtime):
    files = {}
    def failed_walk(error):
        raise error
    for parent, directories, names in os.walk(runtime, onerror=failed_walk):
        for path in (Path(parent), *(Path(parent) / name for name in [*directories, *names])):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Windows runtime cannot contain links or reparse points")
        for name in sorted(names):
            path = Path(parent) / name
            files[path.relative_to(runtime).as_posix()] = sha256(path)
    if not files:
        raise ValueError("Windows runtime inventory is empty")
    if "runtime.json" in files:
        raise ValueError("Windows runtime already contains an assembly receipt")
    return files


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


def strip_unicorn_bindings(runtime):
    """Keep the verified C headers/library as a namespace; remove Python bindings."""
    count = 0
    for package in runtime.glob("python/**/site-packages/unicorn"):
        for path in package.rglob("*"):
            if path.is_file() and (path.suffix in (".py", ".pyi", ".pyc") or path.name == "py.typed"):
                path.unlink()
                count += 1
        # Unix links the shared library; the wheel's static engine archive is unused.
        # Keep Windows import libraries, which are needed to link a DLL.
        if os.name != "nt":
            for archive in (package / "lib").glob("*.a"):
                archive.unlink()
    if not count:
        raise ValueError("Verified Unicorn wheel did not contain the expected bindings")
    return count


def assemble(name, archive, output, wheelhouse, fetch, profile="base", source_builds=None):
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
    expected = dict(lock["targets"][name])
    if profile == "shaders":
        shaders = json.loads((ROOT / "runtime" / "shader-wheels.lock.json").read_text())
        if shaders["schema"] != 1 or shaders["python"] != lock["python"]:
            raise ValueError("Shader lock and base runtime disagree")
        for wheel, digest in {**shaders["common"], **shaders["targets"][name]}.items():
            expected[wheel] = {"wheel": wheel, "sha256": digest}
    if source_builds:
        sources = json.loads((ROOT / "runtime" / "source-lock.json").read_text())["sources"]
        for record_path in source_builds.glob("*-build.json"):
            record = json.loads(record_path.read_text())
            package = record["package"]
            if profile != "shaders" or not (package == "tpk_ar" or (name == "linux-aarch64" and package == "UnityPy")):
                raise ValueError("Unexpected source wheel substitution")
            if record["source_sha256"] != sources[package]["sha256"]:
                raise ValueError("Source wheel provenance disagrees with source lock")
            wheel = source_builds / record["wheel"]
            portable = ("manylinux_2_28_aarch64" in wheel.name if package == "UnityPy" else wheel.name.endswith("-py3-none-any.whl"))
            if wheel.name != record["wheel"] or not portable or sha256(wheel) != record["wheel_sha256"]:
                raise ValueError("Source-built wheel is missing, damaged or not portable")
            expected = {k: v for k, v in expected.items() if not v["wheel"].startswith(package.lower() + "-")}
            expected[wheel.name] = {"wheel": wheel.name, "sha256": record["wheel_sha256"],
                                    "source_sha256": record["source_sha256"]}
    if sha256(archive) != expected_archive:
        raise ValueError("Python archive SHA-256 mismatch")
    if output.exists():
        raise ValueError(f"Output already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="installer-runtime-stage-", dir=output.parent) as stage_name:
        stage = Path(stage_name)
        wheels = wheelhouse or stage / "wheels"
        wheels.mkdir(parents=True, exist_ok=True)
        if source_builds:
            import shutil
            for entry in expected.values():
                source = source_builds / entry["wheel"]
                if "source_sha256" in entry and source.resolve() != (wheels / source.name).resolve():
                    shutil.copy2(source, wheels / source.name)
        platforms = manifest["targets"][name]["pip_platform"]
        if isinstance(platforms, str):
            platforms = [platforms]
        if fetch:
            for entry in expected.values():
                destination = wheels / entry["wheel"]
                if destination.is_file():
                    continue
                distribution, version = entry["wheel"].split("-", 2)[:2]
                with urllib.request.urlopen(f"https://pypi.org/pypi/{distribution}/{version}/json", timeout=60) as response:
                    metadata = json.load(response)
                asset = next((item for item in metadata["urls"] if item["filename"] == entry["wheel"]
                              and item["digests"]["sha256"] == entry["sha256"]), None)
                if asset is None:
                    raise ValueError(f"Supply the verified source-built wheel in --wheelhouse: {entry['wheel']}")
                urllib.request.urlretrieve(asset["url"], destination)
        verify_wheels(wheels, expected)

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
             "--find-links", str(wheels), *(str(wheels / entry["wheel"]) for entry in expected.values())], env=env)
        run([str(python), "-I", "-B", "-c",
             "import sys; assert sys.version_info[:3] == (3, 13, 15)"], env=env)
        removed_bindings = strip_unicorn_bindings(runtime)
        run([str(python), "-I", "-B", str(ROOT / "runtime" / "native_smoke.py")], env=env)
        run([str(python), "-I", "-B", "-m", "pip", "check"], env=env)
        if profile == "shaders":
            run([str(python), "-I", "-B", "-c",
                 "import UnityPy, UnityPy.UnityPyBoost; "
                 "from PIL import Image; import texture2ddecoder; "
                 "assert len(texture2ddecoder.decode_bc1(bytes(8), 4, 4)) == 64; "
                 "import io; f=io.BytesIO(); Image.new('RGBA',(8,8)).save(f,format='PNG'); "
                 "assert Image.open(io.BytesIO(f.getvalue())).size == (8,8)"], env=env)
        # pip records absolute build-machine wheel URLs when installing local files.
        for metadata in runtime.glob("python/**/site-packages/*.dist-info/direct_url.json"):
            metadata.unlink()
        (runtime / "runtime.json").write_text(json.dumps({
            "schema": 1, "target": name, "python": manifest["python"]["version"],
            "python_sha256": expected_archive,
            "profile": profile, "wheels": expected,
            "unicorn_python_files_removed": removed_bindings,
            "unicorn_native_linkage": "shared",
            **({"files": windows_inventory(runtime)} if name.startswith("windows-") else {}),
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        runtime.rename(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=host_target())
    parser.add_argument("--profile", choices=("base", "shaders"), default="base")
    parser.add_argument("--source-builds", type=Path)
    parser.add_argument("--python-archive", required=True, type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--fetch-wheels", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.fetch_wheels and args.wheelhouse is None:
        parser.error("Specify --wheelhouse or --fetch-wheels")
    output = assemble(args.target, args.python_archive.resolve(), args.output.resolve(),
                      args.wheelhouse.resolve() if args.wheelhouse else None, args.fetch_wheels, args.profile,
                      args.source_builds.resolve() if args.source_builds else None)
    print(f"Private runtime verified at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
