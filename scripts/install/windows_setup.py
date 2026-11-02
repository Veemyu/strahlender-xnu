"""Windows setup: fetches what the installer does not ship (Qt and its LLVM-MinGW, SDL3, FFmpeg) from the original
publishers, bundles it with the tools our CI built (hactool, Vulkan/shaderc, the code generator with Unicorn) and writes
the dependency catalog the game build reads. Runs on the user's machine; the CI runs the very same code before its tests.

Every download is checked against the hash its publisher gives: the .sha1 next to Qt's archives, and the SHA-256 GitHub
publishes for SDL3 and FFmpeg release assets. Archives are unpacked by `bdsp-extract unpack` (BDSP_EXTRACT).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.request

from scripts.install import windows_pipeline as pipeline
from scripts.recomp import dependency_build as dependencies
from scripts.recomp import portable_build as build
from scripts.recomp import resolve_inputs
from scripts.recomp import resolve_qt
from scripts.recomp import web


# Windows keeps freshly unpacked files open for a while (Defender scans them, the indexer reads them). Renaming or deleting such a folder
# then fails with "access denied", "in use" or "directory not empty" (WinError 5, 32, 145) and succeeds a few seconds later.
RETRY_SECONDS = 90


def retry(action, seconds=RETRY_SECONDS, pause=1.0, sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + seconds
    while True:
        try:
            return action()
        except OSError:
            if clock() >= deadline:
                raise
            sleep(pause)


def _writable(function, path, *_):
    """rmtree handler: a read-only file blocks deleting its folder."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove_tree(path, seconds=RETRY_SECONDS, sleep=time.sleep, clock=time.monotonic):
    """Deletes a folder, waiting for Windows to release it. Returns False (never raises) when it stays locked: the leftover is renamed
    out of the way, because cleaning up must not fail the setup."""
    path = Path(path)
    if not path.exists():
        return True
    handler = {"onexc": _writable} if sys.version_info >= (3, 12) else {"onerror": _writable}
    try:
        retry(lambda: shutil.rmtree(path, **handler) if path.exists() else None, seconds, sleep=sleep, clock=clock)
        return True
    except OSError:
        try:
            os.replace(path, path.with_name("%s.old-%d" % (path.name, os.getpid())))
        except OSError:
            pass
        return False


def move_tree(source, destination, seconds=RETRY_SECONDS, sleep=time.sleep, clock=time.monotonic):
    """Renames a folder (same volume); if it stays locked, copies it and removes the source in the background of the setup."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        retry(lambda: os.replace(source, destination), seconds, sleep=sleep, clock=clock)
    except OSError:
        shutil.copytree(source, destination, symlinks=True)
        remove_tree(source, 10, sleep=sleep, clock=clock)


LEFTOVERS = ("downloads", "raw", "toolchain", "qt", "sdl", "ffmpeg", "vulkan", "hactool", "generator", "NOTICES", "catalog.json")


def clear_leftovers(out):
    """A setup that was interrupted (or failed on a locked folder) leaves its parts behind; start from nothing."""
    for name in LEFTOVERS:
        part = Path(out) / name
        if part.is_dir():
            remove_tree(part)
        elif part.exists():
            part.unlink()


def fetch(url, destination, *, sha1=None, sha256=None, progress=print, on_bytes=None):
    """Downloads one archive and checks it against the hash its publisher gives. A certificate error from Python's own TLS is retried
    once with the system curl (scripts/recomp/web.py); the hash check is the same either way."""
    destination = Path(destination)
    progress("Downloading " + destination.name)
    web.download_file(url, destination, on_bytes=on_bytes)
    digests = {"sha1": hashlib.sha1(), "sha256": hashlib.sha256()}
    with open(destination, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            for digest in digests.values():
                digest.update(chunk)
    for name, expected in (("sha1", sha1), ("sha256", sha256)):
        if expected and digests[name].hexdigest() != expected:
            destination.unlink(missing_ok=True)
            raise ValueError(f"{name.upper()} mismatch for {destination.name}")
    return destination


class Events:
    """Machine readable progress for the installer (--events): one JSON object per line on stdout.
      {"event": "steps", "total": N}                         how many steps there are
      {"event": "step", "index": i, "id": "qt", "phase": "download"|"unpack"|"work"}
      {"event": "bytes", "completed": n, "total": m}          while a download runs (total 0 = unknown)
    Everything else the setup prints stays an ordinary text line."""
    def __init__(self, write=None):
        self.write = write or (lambda line: print(line, flush=True))
        self.index = 0

    def emit(self, **fields):
        self.write(json.dumps(fields))

    def steps(self, total):
        self.emit(event="steps", total=total)

    def step(self, id, phase):
        self.index += 1
        self.emit(event="step", index=self.index, id=id, phase=phase)

    def bytes(self, completed, total):
        self.emit(event="bytes", completed=completed, total=total)


# What the setup does, in order: (id, phase) per step. The installer shows a name for each.
SOURCES = (("qt", "qtbase.7z"), ("toolchain", "toolchain.7z"), ("sdl", "sdl.tar.gz"), ("ffmpeg", "ffmpeg.zip"))
STEP_COUNT = 1 + 2 * len(SOURCES) + 3   # versions, a download and an unpack per source, then bundle, tools, register


def unpack(archive, destination):
    """`bdsp-extract unpack` (or the installer's `--cli unpack`), named by BDSP_EXTRACT / BDSP_EXTRACT_PREFIX."""
    tool = os.environ.get("BDSP_EXTRACT")
    if not tool:
        raise ValueError("BDSP_EXTRACT (the unpack tool) is not set")
    prefix = shlex.split(os.environ.get("BDSP_EXTRACT_PREFIX", ""))
    subprocess.run([tool, *prefix, "unpack", str(archive), str(destination)], check=True)


def find(root, name):
    found = next(Path(root).rglob(name), None)
    if not found:
        raise ValueError(f"{name} was not found in the downloaded files")
    return found


def setup(tools, out, target=None, progress=print, get=fetch, unpacker=unpack, events=None):
    """Builds <out> (toolchain, qt, sdl, ffmpeg + the CI tools + catalog.json) from the tools folder and the Internet."""
    tools, out = Path(tools).resolve(), Path(out).resolve()
    selected = build.windows.profile(target)
    downloads, raw = out / "downloads", out / "raw"
    clear_leftovers(out)
    if events:
        events.steps(STEP_COUNT)
        events.step("versions", "work")
    qt = resolve_qt.resolve()
    sdl, ffmpeg = resolve_inputs.latest_sdl_devel(), resolve_inputs.latest_ffmpeg()
    sources = {
        "qtbase.7z": (qt["qtbase"], {"sha1": resolve_qt.text(qt["qtbase"] + ".sha1").split()[0]}),
        "toolchain.7z": (qt["toolchain"], {"sha1": resolve_qt.text(qt["toolchain"] + ".sha1").split()[0]}),
        "sdl.tar.gz": (sdl["url"], {"sha256": sdl["sha256"]}),
        "ffmpeg.zip": (ffmpeg["url"], {"sha256": ffmpeg["sha256"]}),
    }
    for (id, _), (name, (url, check)) in zip(SOURCES, sources.items()):
        if events:
            events.step(id, "download")
            get(url, downloads / name, progress=progress, on_bytes=events.bytes, **check)
            events.step(id, "unpack")
        else:
            get(url, downloads / name, progress=progress, **check)
        progress("Unpacking " + name)
        unpacker(downloads / name, raw / name.split(".")[0])
    compiler_in_raw = find(raw / "toolchain", selected["target"] + "-w64-mingw32-clang.exe")
    move_tree(compiler_in_raw.parent.parent, out / "toolchain")
    compiler = out / "toolchain/bin" / compiler_in_raw.name
    qt_root = find(raw / "qtbase", "Qt6Core.dll").parent.parent
    if events:
        events.step("bundle", "work")
    progress("Bundling Qt, FFmpeg and SDL3")
    dependencies.build_qt(qt_root, tools / "license-texts/qt", out / "qt", compiler, selected, qt["qt"])
    dependencies.import_ffmpeg(downloads / "ffmpeg.zip", out / "ffmpeg", selected, license_dir=tools / "license-texts/ffmpeg")
    sdl_root = next(path for path in (raw / "sdl").iterdir() if path.is_dir())
    build.import_sdl(sdl_root, out / "sdl", selected)
    if events:
        events.step("tools", "work")
    for name in ("vulkan", "hactool", "generator", "NOTICES"):
        shutil.copytree(tools / name, out / name)
    for part in (downloads, raw):   # the setup is done: a folder Windows still holds is only a leftover
        if not remove_tree(part):
            progress("Could not remove %s yet; it is cleaned up with the next build." % part.name)
    if events:
        events.step("register", "work")
    progress("Registering the build environment")
    pipeline.write_catalog(out / "catalog.json", compiler, out / "generator/bdsp_codegen.exe", selected,
                           sdl=out / "sdl", vulkan=out / "vulkan", ffmpeg=out / "ffmpeg", hactool=out / "hactool", qt=out / "qt")
    return out / "catalog.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, required=True, help="Folder with the CI-built tools (vulkan, hactool, generator, notices)")
    parser.add_argument("--out", type=Path, required=True, help="New folder for the build environment")
    parser.add_argument("--events", action="store_true", help="Print progress as JSON lines (see Events) for the installer")
    args = parser.parse_args(argv)
    try:
        print(setup(args.tools, args.out, events=Events() if args.events else None), flush=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("Windows setup failed: " + str(error), file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
