#!/usr/bin/env python3
"""Build pinned source wheels on the native host for missing architectures."""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from pathlib import Path
from zipfile import ZipFile

from probe_runtime import ROOT, sha256


SOURCE_LOCK = ROOT / "runtime" / "source-lock.json"


def run(command, cwd=None):
    subprocess.run(command, cwd=cwd, check=True)


def find_built(build, filename):
    matches = [path for path in build.rglob(filename) if path.is_file()]
    if len(matches) != 1:
        raise ValueError(f"Expected one {filename}, found {len(matches)}")
    return matches[0]


def prebuild_windows_arm(source, package):
    if platform.system() != "Windows" or sysconfig.get_platform().replace("-", "_") != "win_arm64":
        raise ValueError("Native Windows ARM64 prebuild requires a native ARM64 Python")
    build = source / "native-build"
    flags = (["-DBUILD_SHARED_LIBS=ON", "-DBUILD_STATIC_LIBS=OFF",
              "-DCAPSTONE_BUILD_TESTS=OFF", "-DCAPSTONE_BUILD_CSTOOL=OFF"]
             if package == "capstone" else ["-DUNICORN_BUILD_TESTS=OFF"])
    run(["cmake", "-S", str(source / "src"), "-B", str(build),
         "-G", "Visual Studio 17 2022", "-A", "ARM64", *flags])
    run(["cmake", "--build", str(build), "--config", "Release", "--parallel", "4"])
    prebuilt = source / "prebuilt"
    prebuilt.mkdir(exist_ok=True)
    if package == "capstone":
        shutil.copy2(find_built(build, "capstone.dll"), prebuilt / "capstone.dll")
    else:
        shutil.copy2(find_built(build, "unicorn.dll"), prebuilt / "unicorn.dll")
        shutil.copy2(find_built(build, "unicorn.lib"), prebuilt / "unicorn.lib")


def native_members(wheel):
    with ZipFile(wheel) as archive:
        return sorted(name for name in archive.namelist()
                      if name.lower().endswith((".dll", ".pyd", ".so", ".dylib")))


def build(package, archive, output):
    lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    if lock.get("schema") != 1 or package not in lock["sources"]:
        raise ValueError("Unknown pinned source package")
    entry = lock["sources"][package]
    if archive.name != entry["archive"] or sha256(archive) != entry["sha256"]:
        raise ValueError(f"Source archive name or SHA-256 mismatch for {package}")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="installer-native-source-") as temporary:
        stage = Path(temporary)
        with tarfile.open(archive, "r:gz") as source_tar:
            source_tar.extractall(stage, filter="data")
        roots = [path for path in stage.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise ValueError("Unexpected source archive layout")
        source = roots[0]
        if (package in ("capstone", "unicorn") and platform.system() == "Windows"
                and sysconfig.get_platform().replace("-", "_") == "win_arm64"):
            prebuild_windows_arm(source, package)
        run([sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check",
             "--no-deps", "--no-cache-dir", "--wheel-dir", str(output), str(source)])
    matches = sorted(output.glob(package.lower().replace("_", "*") + "-*.whl"))
    if len(matches) != 1:
        # Wheel names normalize hyphens, underscores and case; inspect metadata below instead.
        matches = [wheel for wheel in output.glob("*.whl")
                   if wheel.name.lower().split("-", 1)[0].replace("_", "") == package.lower().replace("_", "")]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one built wheel for {package}")
    wheel = matches[0]
    members = native_members(wheel)
    if package != "tpk_ar" and not members:
        raise ValueError(f"Built {package} wheel has no native library")
    if package == "tpk_ar" and members:
        raise ValueError("tpk_ar unexpectedly contains native libraries")
    if platform.system() == "Windows" and sysconfig.get_platform().replace("-", "_") == "win_arm64":
        if package in ("capstone", "unicorn") and "win_arm64" not in wheel.name:
            raise ValueError(f"Native wheel has the wrong Windows architecture: {wheel.name}")
    record = {"package": package, "version": entry["version"], "source_sha256": entry["sha256"],
              "wheel": wheel.name, "wheel_sha256": sha256(wheel), "native_members": members}
    (output / f"{package.lower()}-build.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", choices=("capstone", "unicorn", "UnityPy", "tpk_ar"))
    parser.add_argument("--source-archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    record = build(args.package, args.source_archive.resolve(), args.output.resolve())
    print(f"Built {record['wheel']} from verified {args.package} source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
