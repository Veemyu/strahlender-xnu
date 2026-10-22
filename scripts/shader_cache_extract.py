#!/usr/bin/env python3
"""Exports SPIR-V modules from the Ryujinx host shader cache (vulkan_apple.toc/.data).

Usage:
  python3 scripts/shader_cache_extract.py [--cache DIR] [--out DIR] [--index N ...]
                                          [--smallest N] [--limit N] [--list]

Output: <out>/<index>_<stage>.spv (stage: vert, frag, comp, ...) and <out>/index.json
(index, stage, size per module). The cache is only read.
Default: --cache Ryujinx/games/0100000011d90000/cache/shader, --out work/shaders/spirv.
With --index/--smallest/--limit only matching programs are written.
Layout per the public Ryujinx source code, re-implemented independently (see docs/shaders.md).
Brotli entries need the package `brotli`; deflate/uncompressed work with the standard library.
"""
import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

DEFAULT_CACHE = "Ryujinx/games/0100000011d90000/cache/shader"
DEFAULT_OUT = "work/shaders/spirv"
SPIRV_MAGIC = 0x07230203
# Ryujinx ShaderStage: Compute, Vertex, TessControl, TessEval, Geometry, Fragment
STAGE_NAMES = {0: "comp", 1: "vert", 2: "tesc", 3: "tese", 4: "geom", 5: "frag"}


def decompress(buf, pos, expected):
    """Block: [algo:1][Strom]; algo 0 = roh, 1 = Deflate, 2 = Brotli."""
    algo = buf[pos]
    body = buf[pos + 1:]
    if algo == 0:
        return bytes(body[:expected])
    if algo == 1:
        return zlib.decompressobj(-15).decompress(body, expected)
    if algo == 2:
        import brotli  # only when needed
        out = brotli.Decompressor().process(bytes(body[: max(expected * 2, 65536)]))
        return out[:expected]
    raise ValueError(f"unbekannter Kompressionsalgorithmus {algo}")


def parse_blob(blob):
    """Host-Paket: [count:i32] { [stage:i32][len:i32][SPIR-V] } -> [(stage, code)]."""
    cnt = struct.unpack_from("<i", blob, 0)[0]
    pos = 4
    mods = []
    for _ in range(cnt):
        stage, ln = struct.unpack_from("<ii", blob, pos)
        pos += 8
        code = blob[pos:pos + ln]
        pos += ln
        if len(code) == ln and ln >= 4 and struct.unpack_from("<I", code, 0)[0] == SPIRV_MAGIC:
            mods.append((stage, code))
    return mods


def iter_programs(cache):
    """Yields (index, [(stage, code)]) per cache entry; damaged entries are skipped."""
    toc = (cache / "vulkan_apple.toc").read_bytes()
    if toc[:4] != b"TOCH":
        raise SystemExit(f"{cache}/vulkan_apple.toc: magic {toc[:4]!r}, expected b'TOCH'")
    data = (cache / "vulkan_apple.data").read_bytes()
    n = (len(toc) - 32) // 16
    for i in range(n):
        off, unc, _comp = struct.unpack_from("<QII", toc, 32 + i * 16)
        try:
            yield i, parse_blob(decompress(data, off, unc))
        except Exception as e:  # defekter Eintrag
            print(f"Entry {i}: skipped ({e})", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--index", type=int, nargs="*", help="only these program indices")
    ap.add_argument("--smallest", type=int, help="only the N vertex+fragment programs with the smallest total size")
    ap.add_argument("--limit", type=int, help="only the first N programs")
    ap.add_argument("--list", action="store_true", help="only list, write nothing")
    a = ap.parse_args()

    progs = []
    for i, mods in iter_programs(Path(a.cache)):
        if a.index is not None and i not in a.index:
            continue
        progs.append((i, mods))
    if a.smallest:
        pairs = [(i, m) for i, m in progs
                 if {s for s, _ in m} >= {1, 5}]
        pairs.sort(key=lambda p: sum(len(c) for _, c in p[1]))
        progs = pairs[: a.smallest]
    if a.limit:
        progs = progs[: a.limit]

    index = []
    out = Path(a.out)
    if not a.list:
        out.mkdir(parents=True, exist_ok=True)
    for i, mods in progs:
        for stage, code in mods:
            name = STAGE_NAMES.get(stage, f"stage{stage}")
            index.append({"index": i, "stage": name, "bytes": len(code), "file": f"{i}_{name}.spv"})
            if not a.list:
                (out / f"{i}_{name}.spv").write_bytes(code)
    if a.list:
        for e in index:
            print(f"{e['index']:5d} {e['stage']:5s} {e['bytes']:7d} B")
    else:
        (out / "index.json").write_text(json.dumps(index, indent=1))
        print(f"{len(progs)} Programme, {len(index)} Module nach {out}")


if __name__ == "__main__":
    main()
