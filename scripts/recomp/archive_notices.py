#!/usr/bin/env python3
"""Writes the NOTICES folder of the Windows tools: what is shipped, under which licence, and the source code the GPL
requires for Unicorn. Qt, FFmpeg and SDL3 are downloaded by the installer from their publishers and not redistributed.

Standard library only. Run by .github/workflows/windows-components.yml when the tools are packed."""
import argparse
import hashlib
import json
import tarfile
import urllib.request
from pathlib import Path

UNICORN = ("2.1.4", "https://github.com/unicorn-engine/unicorn/archive/refs/tags/2.1.4.tar.gz")

OFFER = """\
# Notices for the Windows tools

The Strahlender installer ships these programs with the Windows installer. Everything in here is third-party software
under its own licence; the game itself is not part of it.

## Shipped by us

| Component | Licence | Source |
|---|---|---|
| Unicorn {unicorn} (`generator/libunicorn.dll`, built from the unmodified upstream source with LLVM-MinGW) | GPL-2.0 | `source/unicorn-{unicorn}.tar.gz`, licence in `unicorn/COPYING` |
| winpthreads (`generator/libwinpthread-1.dll`, from the LLVM-MinGW toolchain) | MIT-style | https://github.com/mingw-w64/mingw-w64 |
| hactool (`hactool/`) with its bundled mbed TLS (Apache-2.0 option), cJSON, lz4 library, ConvertUTF | ISC and others | notices inside `hactool/notices/` |
| shaderc, glslang, SPIRV-Tools, Vulkan headers, VMA (`vulkan/`) | Apache-2.0, BSD, MIT | notices inside `vulkan/notices/` |

**Written offer.** The code generator `bdsp_codegen.exe` loads `unicorn.dll`; both are distributed together. For three years from
the date of this release, the complete corresponding source of Unicorn is available from
https://github.com/Veemyu/strahlender-xnu/releases or on request. It is also included in `source/`, unchanged:

{hashes}
## Downloaded by the installer from the original publishers (not redistributed by us)

Qt 6 (LGPL-3.0) and the LLVM-MinGW toolchain Qt pairs with it from download.qt.io, FFmpeg (BtbN LGPL shared build)
from github.com/BtbN/FFmpeg-Builds, SDL3 (zlib) from github.com/libsdl-org/SDL. Their licence texts are stored next to
the files they belong to (`qt/notices/`, `ffmpeg/notices/`, `sdl/notices/`, `toolchain/`).

The Microsoft Visual C++ runtime is not needed: everything is built with LLVM-MinGW against the Universal C Runtime.

## Versions of the shipped parts

{table}"""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table(contract, sources):
    rows = ["| Component | Version | Licence | Origin |", "|---|---|---|---|"]
    for item in contract["components"]:
        if item["id"] not in ("vulkan", "hactool"):
            continue
        rows.append(f"| {item['id']} | {item.get('version') or 'rolling'} | {item['license']} | {item.get('source', '')} |")
    for name, entry in sources["sources"].items():
        if name in ("ffmpeg",):
            continue
        rows.append(f"| {name} | {entry.get('version', '')} | {entry.get('license', '')} | https://github.com/{entry['repository']} ({(entry.get('revision') or '')[:12]}) |")
    return "\n".join(rows) + "\n"


def unicorn_source(destination, fetch=urllib.request.urlretrieve):
    target = destination / f"unicorn-{UNICORN[0]}.tar.gz"
    fetch(UNICORN[1], target)
    with tarfile.open(target) as archive:
        member = next(m for m in archive.getmembers() if m.isfile() and m.name.count("/") == 1 and m.name.endswith("/COPYING"))
        copying = archive.extractfile(member).read()
    return target, copying


def write(resolved, out, fetch=urllib.request.urlretrieve):
    resolved, out = Path(resolved), Path(out)
    contract = json.loads((resolved / "windows-dependencies.json").read_text(encoding="utf-8"))
    sources = json.loads((resolved / "windows-sources.json").read_text(encoding="utf-8"))
    (out / "source").mkdir(parents=True)
    (out / "unicorn").mkdir()
    archive, copying = unicorn_source(out / "source", fetch)
    (out / "unicorn" / "COPYING").write_bytes(copying)
    hashes = f"- `{archive.name}`: {sha256(archive)}\n"
    (out / "README.md").write_text(OFFER.format(unicorn=UNICORN[0], hashes=hashes, table=table(contract, sources)), encoding="utf-8")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    write(args.resolved, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
