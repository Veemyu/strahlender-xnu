#!/usr/bin/env python3
"""Builds Strahlender-Installer-x86_64.exe: ONE executable. The helper programs, the verified private Python runtime, the
build tools and the licence files are a ZIP appended to strahlender-xnu-installer.exe, closed by the trailer that
installer/src/bundle.rs reads (MAGIC, ZIP length u64 LE, SHA-256 of the ZIP). The installer unpacks it on first start.
windows-components.zip and its metadata come from .github/workflows/windows-components.yml.

Usage: python installer/scripts/package_windows.py RUNTIME_DIR TOOLS_DIR   (after cargo build --release --bins;
TOOLS_DIR holds windows-components.zip and windows-components.json)"""
import hashlib
import shutil
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer"
MAIN = "strahlender-xnu-installer"
HELPERS = ("ips_patch", "firmware_import", "installer_update", "installer_setup")
NAME = "Strahlender-Installer-x86_64.exe"
MAGIC = b"BDSPBNDL"


def stage(runtime, tools, folder):
    """The folder the installer unpacks: helper programs and resources/."""
    resources = folder / "resources"
    resources.mkdir(parents=True)
    for binary in HELPERS:
        shutil.copy2(INSTALLER / "target/release" / f"{binary}.exe", folder)
    for source in (ROOT / "THIRD_PARTY_NOTICES.md", INSTALLER / "assets/FIRA-LICENSE", INSTALLER / "assets/OCTICONS-LICENSE"):
        shutil.copy2(source, resources)
    shutil.copy2(INSTALLER / "vendor/iced_winit/LICENSE", resources / "ICED-WINIT-LICENSE")
    shutil.copytree(INSTALLER / "assets/lucide", resources / "lucide")
    shutil.copytree(INSTALLER / "assets/firmware-import-licenses", resources / "firmware-import-licenses")
    shutil.copytree(runtime, resources / "runtime")
    for name in ("windows-components.zip", "windows-components.json"):
        shutil.copy2(tools / name, resources)


def pack(folder, archive):
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(folder).as_posix())


def append(executable, archive, output):
    data = archive.read_bytes()
    output.write_bytes(
        executable.read_bytes() + data + MAGIC + struct.pack("<Q", len(data)) + hashlib.sha256(data).digest()
    )
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (output.parent / "SHA256SUMS").write_bytes(f"{digest}  {output.name}\n".encode())  # LF even on Windows


def main(argv):
    runtime, tools = Path(argv[1]), Path(argv[2])
    work = ROOT / "work/installer-packages/windows-x86_64"
    if work.exists():
        shutil.rmtree(work)
    folder = work / "bundle"
    stage(runtime, tools, folder)
    archive = work / "bundle.zip"
    pack(folder, archive)
    output = work / NAME
    append(INSTALLER / "target/release" / f"{MAIN}.exe", archive, output)
    shutil.rmtree(folder)
    archive.unlink()
    print(output)


if __name__ == "__main__":
    main(sys.argv)
