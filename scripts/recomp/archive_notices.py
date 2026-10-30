#!/usr/bin/env python3
"""Writes the NOTICES folder of the Windows components archive: what is inside, under which licence, and the source
code the copyleft licences require (Qt and FFmpeg under the LGPL, Unicorn under the GPL).

Standard library only. Run by .github/workflows/windows-components.yml right before the archive is packed."""
import argparse
import hashlib
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

UNICORN = ("2.1.4", "https://github.com/unicorn-engine/unicorn/archive/refs/tags/2.1.4.tar.gz")

OFFER = """\
# Notices for the Windows components

These files are the Windows components the Strahlender installer downloads. Everything in here is third-party
software under its own licence; the game itself is not part of it. The versions and SHA-256 values of what was
built are in `../inputs/` and `../windows-components.json`.

## Copyleft components and their source

| Component | Licence | How it is used | Corresponding source |
|---|---|---|---|
| Qt {qt} (Core, Gui, Widgets and plugins) | LGPL-3.0 (+ third-party notices in `qt/`) | shared DLLs, unmodified; replace them to relink | `source/{qt_source}` |
| FFmpeg (BtbN `lgpl-shared` build) | LGPL-2.1-or-later | shared DLLs, unmodified | `source/{ffmpeg_source}` |
| Unicorn {unicorn} | GPL-2.0 | `unicorn.dll`, loaded by the code generator `bdsp_codegen.exe`; the generator and this DLL are distributed together | `source/unicorn-{unicorn}.tar.gz`, licence in `unicorn/COPYING` |

**Written offer.** For three years from the date of this archive, the sources named above are available from
https://github.com/Veemyu/strahlender-xnu/releases/tag/windows-components or on request. They are also included in
`source/`, unchanged, with the SHA-256 values below.

{hashes}
The Visual C++ runtime is not part of this archive. The installer asks you to install Microsoft's own
redistributable (https://aka.ms/vs/17/release/vc_redist.x64.exe) if it is missing.

## Everything else

{table}
Licence texts of the toolchain (`toolchain/`), FFmpeg (`ffmpeg/notices/`), hactool, SDL, Vulkan and Qt (`qt/notices/`)
stay next to the files they belong to.
"""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table(contract, sources):
    rows = ["| Component | Version | Licence | Origin |", "|---|---|---|---|"]
    for item in contract["components"]:
        rows.append(f"| {item['id']} | {item.get('version') or 'rolling'} | {item['license']} | {item.get('source', '')} |")
    for name, entry in sources["sources"].items():
        rows.append(f"| {name} | {entry.get('version', '')} | {entry.get('license', '')} | https://github.com/{entry['repository']} ({(entry.get('revision') or '')[:12]}) |")
    return "\n".join(rows) + "\n"


def unicorn_source(destination, fetch=urllib.request.urlretrieve):
    target = destination / f"unicorn-{UNICORN[0]}.tar.gz"
    fetch(UNICORN[1], target)
    with tarfile.open(target) as archive:
        member = next(m for m in archive.getmembers() if m.isfile() and m.name.count("/") == 1 and m.name.endswith("/COPYING"))
        copying = archive.extractfile(member).read()
    return target, copying


def write(resolved, downloads, out, fetch=urllib.request.urlretrieve):
    resolved, downloads, out = Path(resolved), Path(downloads), Path(out)
    contract = json.loads((resolved / "windows-dependencies.json").read_text(encoding="utf-8"))
    sources = json.loads((resolved / "windows-sources.json").read_text(encoding="utf-8"))
    qt = json.loads((resolved / "qt.json").read_text(encoding="utf-8"))
    (out / "source").mkdir(parents=True)
    (out / "unicorn").mkdir()
    qt_archive = downloads / "qtbase-src.tar.xz"
    ffmpeg = next(downloads.glob("ffmpeg-[0-9a-f]*.tar.gz"), None)
    if not qt_archive.is_file() or ffmpeg is None:
        raise ValueError("The Qt and FFmpeg source archives are required for the source offer")
    uni, copying = unicorn_source(out / "source", fetch)
    (out / "unicorn" / "COPYING").write_bytes(copying)
    for path in (qt_archive, ffmpeg):
        shutil.copyfile(path, out / "source" / path.name)
    names = [qt_archive.name, ffmpeg.name, uni.name]
    hashes = "\n".join(f"- `{name}`: {sha256(out / 'source' / name)}" for name in names) + "\n"
    (out / "README.md").write_text(OFFER.format(
        qt=qt["qt"], qt_source=qt_archive.name, ffmpeg_source=ffmpeg.name, unicorn=UNICORN[0], hashes=hashes,
        table=table(contract, sources)), encoding="utf-8")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved", required=True)
    parser.add_argument("--downloads", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    write(args.resolved, args.downloads, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
