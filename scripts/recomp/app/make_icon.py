#!/usr/bin/env python3
"""Placeholder icon for BDSP.app: a geometric diamond on a blue gradient, without any game artwork.

Writes <folder>/BDSP.iconset (PNG in all sizes, standard library only) and calls `iconutil`, which
creates <output>.icns. Usage: make_icon.py <output.icns>
"""
import os
import shutil
import struct
import subprocess
import sys
import zlib


def png(size, pixel):
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            row += bytes(pixel(x / (size - 1), y / (size - 1)))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def pixel(u, v):
    # rounded square (alpha outside), gradient dark blue -> light blue, white diamond in the middle
    cx, cy = abs(u - 0.5), abs(v - 0.5)
    r, half = 0.18, 0.42
    qx, qy = max(cx - (half - r), 0), max(cy - (half - r), 0)
    if (qx * qx + qy * qy) ** 0.5 > r:
        return (0, 0, 0, 0)
    base = (20 + int(50 * (1 - v)), 40 + int(90 * (1 - v)), 110 + int(110 * (1 - v)))
    if cx + cy < 0.26:
        edge = 0.26 - (cx + cy)
        k = 1.0 if edge > 0.012 else edge / 0.012
        return tuple(int(base[i] * (1 - k) + 245 * k) for i in range(3)) + (255,)
    return base + (255,)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = os.path.abspath(sys.argv[1])
    iconset = os.path.splitext(out)[0] + ".iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    for base in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = "icon_%dx%d%s.png" % (base, base, "@2x" if scale == 2 else "")
            with open(os.path.join(iconset, name), "wb") as f:
                f.write(png(base * scale, pixel))
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
    shutil.rmtree(iconset, ignore_errors=True)
    print("Symbol: %s (%d Byte)" % (out, os.path.getsize(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
