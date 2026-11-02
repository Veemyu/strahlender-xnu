"""Downloads the pinned Vulkan Memory Allocator header for Linux systems without a package for it (Arch, SteamOS).

Same pin and folder as the graphical installer (installer/assets/vma.json, installer/src/vma.rs): the version, commit and SHA-256
of every file come from that file, a download that does not match is never used, and the copy is stored with its license in
<data folder>/vma/<version>/ with a ".verified" marker written last. scripts/recomp/linux/deps.sh reads it after the system headers.
Usage: vma_header.py ensure [--data FOLDER]      (prints the folder)
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "installer/assets/vma.json"
VERIFIED = ".verified"


def load_lock(path=LOCK):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def default_data_dir(environ=None):
    environ = os.environ if environ is None else environ
    base = environ.get("XDG_DATA_HOME") or str(Path(environ.get("HOME") or Path.home()) / ".local/share")
    return Path(base) / "strahlender-xnu-installer"


def _matches(data, pin):
    return len(data) == pin["bytes"] and hashlib.sha256(data).hexdigest() == pin["sha256"].lower()


def is_verified(folder, lock):
    folder = Path(folder)
    if not (folder / VERIFIED).is_file():
        return False
    for name, pin in lock["files"].items():
        try:
            if not _matches((folder / name).read_bytes(), pin):
                return False
        except OSError:
            return False
    return True


def _download(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "Strahlender-Installer-script"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(limit + 1)


def ensure(data_dir, lock=None, get=_download):
    """Returns the folder of a verified copy, downloading it first if needed. get(url, limit) returns at most limit + 1 bytes."""
    lock = lock or load_lock()
    target = Path(data_dir) / "vma" / lock["version"]
    if is_verified(target, lock):
        return target
    partial = target.parent / ("%s.partial-%d" % (lock["version"], os.getpid()))
    shutil.rmtree(partial, ignore_errors=True)
    try:
        for name, pin in lock["files"].items():
            data = get(lock["url"].format(commit=lock["commit"], file=name), pin["bytes"])
            if not _matches(data, pin):
                raise ValueError("The downloaded %s does not match the pinned version %s (SHA-256 or size differs); it was not used."
                                 % (name, lock["version"]))
            path = partial / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (partial / VERIFIED).write_bytes(b"")
        shutil.rmtree(target, ignore_errors=True)
        partial.rename(target)
    finally:
        shutil.rmtree(partial, ignore_errors=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ensure"])
    parser.add_argument("--data", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        print(ensure(args.data or default_data_dir()))
    except (OSError, ValueError) as error:
        print("Vulkan Memory Allocator download failed: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
