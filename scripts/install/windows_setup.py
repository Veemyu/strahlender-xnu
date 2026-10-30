"""Windows setup: fetches what the installer does not ship (Qt and its LLVM-MinGW, SDL3, FFmpeg) from the original
publishers, bundles it with the tools our CI built (hactool, Vulkan/shaderc, the code generator with Unicorn) and writes
the dependency catalog the game build reads. Runs on the user's machine; the CI runs the very same code before its tests.

Every download is checked against the hash its publisher gives: the .sha1 next to Qt's archives, and the SHA-256 GitHub
publishes for SDL3 and FFmpeg release assets. Archives are unpacked by `bdsp-extract unpack` (BDSP_EXTRACT).
"""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import urllib.request

from scripts.install import windows_pipeline as pipeline
from scripts.recomp import dependency_build as dependencies
from scripts.recomp import portable_build as build
from scripts.recomp import resolve_inputs
from scripts.recomp import resolve_qt


def fetch(url, destination, *, sha1=None, sha256=None, progress=print):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digests = {"sha1": hashlib.sha1(), "sha256": hashlib.sha256()}
    progress("Downloading " + destination.name)
    partial = destination.with_suffix(destination.suffix + ".partial")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "strahlender-xnu-installer"}), timeout=600) as response, \
            open(partial, "wb") as output:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            for digest in digests.values():
                digest.update(chunk)
            output.write(chunk)
    for name, expected in (("sha1", sha1), ("sha256", sha256)):
        if expected and digests[name].hexdigest() != expected:
            partial.unlink(missing_ok=True)
            raise ValueError(f"{name.upper()} mismatch for {destination.name}")
    partial.replace(destination)
    return destination


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


def setup(tools, out, target=None, progress=print, get=fetch, unpacker=unpack):
    """Builds <out> (toolchain, qt, sdl, ffmpeg + the CI tools + catalog.json) from the tools folder and the Internet."""
    tools, out = Path(tools).resolve(), Path(out).resolve()
    selected = build.windows.profile(target)
    downloads, raw = out / "downloads", out / "raw"
    qt = resolve_qt.resolve()
    sdl, ffmpeg = resolve_inputs.latest_sdl_devel(), resolve_inputs.latest_ffmpeg()
    sources = {
        "qtbase.7z": (qt["qtbase"], {"sha1": resolve_qt.text(qt["qtbase"] + ".sha1").split()[0]}),
        "toolchain.7z": (qt["toolchain"], {"sha1": resolve_qt.text(qt["toolchain"] + ".sha1").split()[0]}),
        "sdl.tar.gz": (sdl["url"], {"sha256": sdl["sha256"]}),
        "ffmpeg.zip": (ffmpeg["url"], {"sha256": ffmpeg["sha256"]}),
    }
    for name, (url, check) in sources.items():
        get(url, downloads / name, progress=progress, **check)
        progress("Unpacking " + name)
        unpacker(downloads / name, raw / name.split(".")[0])
    compiler_in_raw = find(raw / "toolchain", selected["target"] + "-w64-mingw32-clang.exe")
    shutil.move(str(compiler_in_raw.parent.parent), str(out / "toolchain"))
    compiler = out / "toolchain/bin" / compiler_in_raw.name
    qt_root = find(raw / "qtbase", "Qt6Core.dll").parent.parent
    progress("Bundling Qt, FFmpeg and SDL3")
    dependencies.build_qt(qt_root, tools / "license-texts/qt", out / "qt", compiler, selected, qt["qt"])
    dependencies.import_ffmpeg(downloads / "ffmpeg.zip", out / "ffmpeg", selected, license_dir=tools / "license-texts/ffmpeg")
    sdl_root = next(path for path in (raw / "sdl").iterdir() if path.is_dir())
    build.import_sdl(sdl_root, out / "sdl", selected)
    for name in ("vulkan", "hactool", "generator", "NOTICES"):
        shutil.copytree(tools / name, out / name)
    shutil.rmtree(downloads)
    shutil.rmtree(raw)
    progress("Registering the build environment")
    pipeline.write_catalog(out / "catalog.json", compiler, out / "generator/bdsp_codegen.exe", selected,
                           sdl=out / "sdl", vulkan=out / "vulkan", ffmpeg=out / "ffmpeg", hactool=out / "hactool", qt=out / "qt")
    return out / "catalog.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, required=True, help="Folder with the CI-built tools (vulkan, hactool, generator, notices)")
    parser.add_argument("--out", type=Path, required=True, help="New folder for the build environment")
    args = parser.parse_args(argv)
    try:
        print(setup(args.tools, args.out))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("Windows setup failed: " + str(error), file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
