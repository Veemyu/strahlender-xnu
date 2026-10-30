#!/usr/bin/env python3
"""Builds installer-windows-x86_64.zip: the installer executables, the verified private Python runtime and the licence
files, laid out as installer/src/runtime.rs expects (resources/ beside the executable). The build tools are not part of
it: the installer downloads them from the release "windows-components" on first use.

Usage: python installer/scripts/package_windows.py RUNTIME_DIR   (run on Windows, after cargo build --release --bins)"""
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer"
BINARIES = ("strahlender-xnu-installer", "ips_patch", "firmware_import", "installer_update", "installer_setup")
NAME = "installer-windows-x86_64"


def stage(runtime, output):
    app = output / "Strahlender Installer"
    resources = app / "resources"
    resources.mkdir(parents=True)
    for binary in BINARIES:
        shutil.copy2(INSTALLER / "target/release" / f"{binary}.exe", app)
    for source in (ROOT / "THIRD_PARTY_NOTICES.md", INSTALLER / "assets/FIRA-LICENSE", INSTALLER / "assets/OCTICONS-LICENSE"):
        shutil.copy2(source, resources)
    shutil.copy2(INSTALLER / "vendor/iced_winit/LICENSE", resources / "ICED-WINIT-LICENSE")
    shutil.copytree(INSTALLER / "assets/lucide", resources / "lucide")
    shutil.copytree(INSTALLER / "assets/firmware-import-licenses", resources / "firmware-import-licenses")
    shutil.copytree(runtime, resources / "runtime")
    return app


def pack(app, archive):
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(app.parent).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (archive.parent / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")


def main(argv):
    runtime = Path(argv[1])
    output = ROOT / "work/installer-packages/windows-x86_64"
    if output.exists():
        shutil.rmtree(output)
    app = stage(runtime, output)
    pack(app, output / f"{NAME}.zip")
    print(output / f"{NAME}.zip")


if __name__ == "__main__":
    main(sys.argv)
