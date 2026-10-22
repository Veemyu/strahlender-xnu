#!/usr/bin/env python3
"""Pixel comparison of two PNG images (Python standard library only).

Usage:
  python3 scripts/shader_compare.py a.png b.png [--threshold N] [--ignore-alpha]
          [--diff diff.png] [--diff-gain G] [--json]
          [--max-diff N] [--max-pixels N] [--min-psnr DB]

Metrics (on RGBA8, or RGB with --ignore-alpha):
  max_abs_diff      largest deviation of a channel (0..255)
  mean_abs_diff     mean deviation over all channel values
  pixels_over       number of pixels where at least one channel deviates by more than --threshold
  mse / psnr        mean squared error / PSNR in dB (inf for identical images)
Exit code: 0 = fine (or no limits given), 1 = limit exceeded, 2 = error.

The PNG decoder handles all color types, bit depths 1-16, Adam7 and tRNS; color profiles/gamma are ignored
(the stored raw values count).
"""
import argparse
import json
import math
import struct
import sys
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
VALID_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
ADAM7 = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]


class PngError(Exception):
    pass


def _chunks(data):
    if data[:8] != PNG_SIG:
        raise PngError("no PNG signature")
    pos = 8
    while pos + 12 <= len(data):
        n, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        crc_bytes = data[pos + 8 + n:pos + 12 + n]
        if len(body) != n or len(crc_bytes) != 4 or zlib.crc32(typ + body) & 0xFFFFFFFF != struct.unpack(">I", crc_bytes)[0]:
            raise PngError(f"Chunk {typ!r}: Laenge/CRC fehlerhaft")
        yield typ, body
        pos += 12 + n
        if typ == b"IEND":
            return
    raise PngError("IEND missing")


def _unfilter(ftype, row, prev, bpp):
    n = len(row)
    if ftype == 0:
        return
    if ftype == 1:
        for i in range(bpp, n):
            row[i] = (row[i] + row[i - bpp]) & 255
    elif ftype == 2:
        for i in range(n):
            row[i] = (row[i] + prev[i]) & 255
    elif ftype == 3:
        for i in range(n):
            left = row[i - bpp] if i >= bpp else 0
            row[i] = (row[i] + ((left + prev[i]) >> 1)) & 255
    elif ftype == 4:
        for i in range(n):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            row[i] = (row[i] + pr) & 255
    else:
        raise PngError(f"unbekannter Filtertyp {ftype}")


def _samples(row, count, depth):
    """Splits an unfiltered row into samples (integers)."""
    if depth == 8:
        return list(row[:count])
    if depth == 16:
        return [(row[2 * i] << 8) | row[2 * i + 1] for i in range(count)]
    out = []
    mask = (1 << depth) - 1
    for i in range(count):
        bit = i * depth
        out.append((row[bit >> 3] >> (8 - depth - (bit & 7))) & mask)
    return out


def _scale8(v, depth):
    if depth == 8:
        return v
    if depth == 16:
        return (v * 255 + 32767) // 65535
    return v * 255 // ((1 << depth) - 1)


def decode_png(data):
    """Returns (width, height, rgba); rgba is a bytearray with 4 bytes per pixel."""
    ihdr = plte = trns = None
    idat = bytearray()
    for typ, body in _chunks(data):
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"PLTE":
            plte = body
        elif typ == b"tRNS":
            trns = body
        elif typ == b"IDAT":
            idat += body
    if ihdr is None:
        raise PngError("IHDR missing")
    w, h, depth, ctype, comp, filt, inter = ihdr
    if ctype not in CHANNELS or depth not in VALID_DEPTHS[ctype] or comp != 0 or filt != 0 or inter not in (0, 1):
        raise PngError(f"unsupported header {ihdr}")
    if w == 0 or h == 0:
        raise PngError("leeres Bild")
    if ctype == 3 and plte is None:
        raise PngError("PLTE missing")
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        raise PngError(f"IDAT nicht entpackbar: {e}")

    nch = CHANNELS[ctype]
    bits = nch * depth
    bpp = max(1, bits // 8)
    out = bytearray(w * h * 4)
    passes = [(0, 0, 1, 1)] if inter == 0 else ADAM7
    pos = 0
    for x0, y0, dx, dy in passes:
        pw = (w - x0 + dx - 1) // dx
        ph = (h - y0 + dy - 1) // dy
        if pw <= 0 or ph <= 0:
            continue
        rowlen = (pw * bits + 7) // 8
        prev = bytearray(rowlen)
        for j in range(ph):
            if pos + 1 + rowlen > len(raw):
                raise PngError("Bilddaten zu kurz")
            ftype = raw[pos]
            row = bytearray(raw[pos + 1:pos + 1 + rowlen])
            pos += 1 + rowlen
            _unfilter(ftype, row, prev, bpp)
            prev = row
            y = y0 + j * dy
            if ctype == 6 and depth == 8 and inter == 0:
                out[y * w * 4:(y + 1) * w * 4] = row
                continue
            s = _samples(row, pw * nch, depth)
            for i in range(pw):
                px = s[i * nch:(i + 1) * nch]
                if ctype == 0:
                    g = _scale8(px[0], depth)
                    a = 0 if (trns and len(trns) >= 2 and px[0] == struct.unpack(">H", trns[:2])[0]) else 255
                    rgba = (g, g, g, a)
                elif ctype == 2:
                    a = 255
                    if trns and len(trns) >= 6 and tuple(px) == struct.unpack(">HHH", trns[:6]):
                        a = 0
                    rgba = (_scale8(px[0], depth), _scale8(px[1], depth), _scale8(px[2], depth), a)
                elif ctype == 3:
                    k = px[0]
                    if 3 * k + 3 > len(plte):
                        raise PngError("palette index outside PLTE")
                    a = trns[k] if trns and k < len(trns) else 255
                    rgba = (plte[3 * k], plte[3 * k + 1], plte[3 * k + 2], a)
                elif ctype == 4:
                    g = _scale8(px[0], depth)
                    rgba = (g, g, g, _scale8(px[1], depth))
                else:
                    rgba = tuple(_scale8(v, depth) for v in px)
                o = (y * w + x0 + i * dx) * 4
                out[o:o + 4] = bytes(rgba)
    return w, h, out


def read_png(path):
    with open(path, "rb") as f:
        return decode_png(f.read())


def encode_png(w, h, rgba):
    """RGBA8 -> PNG (filter 0, no extra chunks)."""
    if len(rgba) != w * h * 4:
        raise ValueError("rgba-Laenge passt nicht zu Breite*Hoehe*4")

    def chunk(typ, body):
        return struct.pack(">I", len(body)) + typ + body + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def write_png(path, w, h, rgba):
    with open(path, "wb") as f:
        f.write(encode_png(w, h, rgba))


def compare(a, b, threshold=0, ignore_alpha=False):
    """Compares two (w, h, rgba) images. Returns a dict with the metrics."""
    (wa, ha, pa), (wb, hb, pb) = a, b
    if (wa, ha) != (wb, hb):
        raise ValueError(f"Image sizes differ: {wa}x{ha} vs {wb}x{hb}")
    nch = 3 if ignore_alpha else 4
    count = wa * ha
    max_diff = 0
    total = 0
    sq = 0
    over = 0
    for p in range(count):
        o = p * 4
        worst = 0
        for c in range(nch):
            d = abs(pa[o + c] - pb[o + c])
            if d:
                total += d
                sq += d * d
                if d > worst:
                    worst = d
        if worst > max_diff:
            max_diff = worst
        if worst > threshold:
            over += 1
    values = count * nch
    mse = sq / values
    psnr = math.inf if mse == 0 else 10 * math.log10(255 * 255 / mse)
    return {
        "width": wa, "height": ha, "channels": "RGB" if ignore_alpha else "RGBA",
        "max_abs_diff": max_diff, "mean_abs_diff": total / values,
        "threshold": threshold, "pixels_over": over, "pixels_total": count,
        "mse": mse, "psnr": psnr,
    }


def diff_image(a, b, gain=1):
    """Differenzbild: RGB = |a-b| * gain (auf 255 begrenzt), Alpha = 255."""
    (w, h, pa), (_, _, pb) = a, b
    out = bytearray(w * h * 4)
    for p in range(w * h):
        o = p * 4
        for c in range(3):
            out[o + c] = min(255, abs(pa[o + c] - pb[o + c]) * gain)
        out[o + 3] = 255
    return w, h, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--threshold", type=int, default=0, help="channel deviation from which a pixel counts (default 0)")
    ap.add_argument("--ignore-alpha", action="store_true")
    ap.add_argument("--diff", help="write the difference image as PNG")
    ap.add_argument("--diff-gain", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="output as JSON")
    ap.add_argument("--max-diff", type=int, help="error if max_abs_diff is above this")
    ap.add_argument("--max-pixels", type=int, help="error if pixels_over is above this")
    ap.add_argument("--min-psnr", type=float, help="error if PSNR is below this")
    args = ap.parse_args(argv)

    try:
        a, b = read_png(args.a), read_png(args.b)
        res = compare(a, b, args.threshold, args.ignore_alpha)
        if args.diff:
            write_png(args.diff, *diff_image(a, b, args.diff_gain))
    except (PngError, ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    failures = []
    if args.max_diff is not None and res["max_abs_diff"] > args.max_diff:
        failures.append(f"max_abs_diff {res['max_abs_diff']} > {args.max_diff}")
    if args.max_pixels is not None and res["pixels_over"] > args.max_pixels:
        failures.append(f"pixels_over {res['pixels_over']} > {args.max_pixels}")
    if args.min_psnr is not None and res["psnr"] < args.min_psnr:
        failures.append(f"psnr {res['psnr']:.2f} < {args.min_psnr}")
    res["failures"] = failures

    if args.json:
        out = dict(res)
        out["psnr"] = None if math.isinf(res["psnr"]) else res["psnr"]  # None = identical
        print(json.dumps(out, indent=1))
    else:
        psnr = "inf" if math.isinf(res["psnr"]) else f"{res['psnr']:.2f} dB"
        print(f"Image {res['width']}x{res['height']} ({res['channels']})")
        print(f"max_abs_diff   {res['max_abs_diff']}")
        print(f"mean_abs_diff  {res['mean_abs_diff']:.6f}")
        print(f"pixels_over    {res['pixels_over']} / {res['pixels_total']} (threshold {res['threshold']})")
        print(f"psnr           {psnr}")
        for f in failures:
            print("LIMIT EXCEEDED: " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
