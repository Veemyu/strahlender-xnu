#!/usr/bin/env python3
"""Zaehlt Eintraege im Ryujinx-Shader-Cache und sucht SPIR-V-Module (nur Zahlen/Groessen).

Aufruf: python3 scripts/shader_cache_scan.py [cache_dir] [--extract N out_dir]
Braucht das Python-Paket `brotli` (pip install brotli, z. B. in tools/venv-shader).
Layout laut oeffentlichem Ryujinx-Quellcode (DiskCache/*Storage.cs), selbst nachgebaut.
"""
import struct
import sys
import zlib
from pathlib import Path

import brotli

DEFAULT = "Ryujinx/games/0100000011d90000/cache/shader"
SPIRV_MAGIC = 0x07230203


def read_ulz(buf, pos, expected):
    """Liest [algo:1][komprimierter Strom]; gibt (Daten, Algo) zurueck."""
    algo = buf[pos]
    body = buf[pos + 1:]
    if algo == 0:
        return bytes(body[:expected]), algo
    if algo == 1:
        return zlib.decompressobj(-15).decompress(body, expected), algo
    if algo == 2:
        d = brotli.Decompressor()
        out = d.process(bytes(body[: max(expected * 2, 65536)]))
        return out[:expected], algo
    raise ValueError(f"algo {algo}")


def header(path):
    d = path.read_bytes()
    magic = d[:4].decode("ascii")
    ver, cg = struct.unpack_from("<II", d, 4)
    ts = struct.unpack_from("<Q", d, 16)[0]
    return d, magic, (ver >> 16, ver & 0xFFFF), cg, ts


def main():
    args = sys.argv[1:]
    extract = 0
    out_dir = None
    if "--extract" in args:
        i = args.index("--extract")
        extract = int(args[i + 1])
        out_dir = Path(args[i + 2])
        del args[i:i + 3]
    base = Path(args[0] if args else DEFAULT)

    for name, entry in (("guest", 16), ("shared", 8), ("vulkan_apple", 16)):
        d, magic, ver, cg, ts = header(base / f"{name}.toc")
        n = (len(d) - 32) // entry
        data = base / f"{name}.data"
        print(f"{name}.toc: magic={magic} version={ver[0]}.{ver[1]} codegen={cg} "
              f"ts={ts} entries={n} data={data.stat().st_size} B")

    # Host-Cache (Vulkan): Eintraege = (Offset, unkomprimiert, komprimiert)
    toc, *_ = header(base / "vulkan_apple.toc")
    data = (base / "vulkan_apple.data").read_bytes()
    n = (len(toc) - 32) // 16
    algos = {}
    spirv_modules = 0
    sizes = []
    fail = 0
    extracted = 0
    stages = {}
    for i in range(n):
        off, unc, comp = struct.unpack_from("<QII", toc, 32 + i * 16)
        try:
            blob, algo = read_ulz(data, off, unc)
        except Exception:
            fail += 1
            continue
        algos[algo] = algos.get(algo, 0) + 1
        sizes.append(unc)
        # Host-Code: [count:i32] { [stage:i32][len:i32][SPIR-V] }
        cnt = struct.unpack_from("<i", blob, 0)[0]
        p = 4
        mods = []
        for _ in range(cnt):
            stage, ln = struct.unpack_from("<ii", blob, p)
            p += 8
            code = blob[p:p + ln]
            p += ln
            if struct.unpack_from("<I", code, 0)[0] == SPIRV_MAGIC:
                mods.append((stage, code))
                stages[stage] = stages.get(stage, 0) + 1
        spirv_modules += len(mods)
        if out_dir and extracted < extract and len(mods) >= 2:
            out_dir.mkdir(parents=True, exist_ok=True)
            for stage, code in mods:
                (out_dir / f"prog{i:04d}_stage{stage}.spv").write_bytes(code)
            extracted += 1
    print(f"vulkan host entries ok={n - fail} fail={fail} algos={algos}")
    if sizes:
        print(f"host blob size: min={min(sizes)} max={max(sizes)} avg={sum(sizes) // len(sizes)} sum={sum(sizes)}")
    print(f"SPIR-V modules: {spirv_modules}, per stage id: {dict(sorted(stages.items()))}")


if __name__ == "__main__":
    main()
