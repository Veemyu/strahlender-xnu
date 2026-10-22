"""Tests for scripts/shader_compare.py: synthetic images only."""
import io
import math
import os
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import shader_compare as sc  # noqa: E402


def chunk(typ, body):
    return struct.pack(">I", len(body)) + typ + body + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF)


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def filter_row(ftype, row, prev, bpp):
    out = bytearray()
    for i, v in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        pred = [0, a, b, (a + b) // 2, paeth(a, b, c)][ftype]
        out.append((v - pred) & 255)
    return bytes([ftype]) + bytes(out)


def make_png(w, h, ctype, depth, rows, filters=None, extra=(), interlace_data=None):
    """rows: already packed rows (bytes). filters: filter type per row (default 0)."""
    nch = sc.CHANNELS[ctype]
    bpp = max(1, nch * depth // 8)
    raw = b""
    prev = bytes(len(rows[0]))
    for y, r in enumerate(rows):
        raw += filter_row((filters or [0] * len(rows))[y], r, prev, bpp)
        prev = r
    if interlace_data is not None:
        raw = interlace_data
    body = struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 1 if interlace_data is not None else 0)
    parts = [sc.PNG_SIG, chunk(b"IHDR", body)]
    parts += [chunk(t, b) for t, b in extra]
    parts += [chunk(b"IDAT", zlib.compress(raw)), chunk(b"IEND", b"")]
    return b"".join(parts)


def solid(w, h, color):
    return bytearray(bytes(color) * (w * h))


def test_pattern(w, h):
    """Checkerboard with a color gradient (RGBA)."""
    px = bytearray()
    for y in range(h):
        for x in range(w):
            odd = (x // 2 + y // 2) % 2
            px += bytes([(x * 255) // max(w - 1, 1), (y * 255) // max(h - 1, 1), 200 if odd else 20, 255 - 5 * odd])
    return px


class DecodeTests(unittest.TestCase):
    def test_rgba8_all_filters(self):
        w, h = 8, 5
        px = test_pattern(w, h)
        rows = [bytes(px[y * w * 4:(y + 1) * w * 4]) for y in range(h)]
        for ftype in range(5):
            png = make_png(w, h, 6, 8, rows, filters=[ftype] * h)
            dw, dh, out = sc.decode_png(png)
            self.assertEqual((dw, dh), (w, h))
            self.assertEqual(bytes(out), bytes(px), f"Filter {ftype}")

    def test_mixed_filters(self):
        w, h = 7, 5
        px = test_pattern(w, h)
        rows = [bytes(px[y * w * 4:(y + 1) * w * 4]) for y in range(h)]
        png = make_png(w, h, 6, 8, rows, filters=[1, 2, 3, 4, 0])
        self.assertEqual(bytes(sc.decode_png(png)[2]), bytes(px))

    def test_rgb8_gets_opaque_alpha(self):
        rows = [bytes([10, 20, 30, 40, 50, 60]), bytes([1, 2, 3, 4, 5, 6])]
        _, _, out = sc.decode_png(make_png(2, 2, 2, 8, rows, filters=[1, 4]))
        self.assertEqual(bytes(out), bytes([10, 20, 30, 255, 40, 50, 60, 255, 1, 2, 3, 255, 4, 5, 6, 255]))

    def test_gray8_and_gray_alpha(self):
        _, _, out = sc.decode_png(make_png(2, 1, 0, 8, [bytes([0, 200])]))
        self.assertEqual(bytes(out), bytes([0, 0, 0, 255, 200, 200, 200, 255]))
        _, _, out = sc.decode_png(make_png(2, 1, 4, 8, [bytes([10, 128, 99, 7])]))
        self.assertEqual(bytes(out), bytes([10, 10, 10, 128, 99, 99, 99, 7]))

    def test_gray16_scaled(self):
        row = struct.pack(">HH", 0, 65535) + struct.pack(">H", 32768)
        _, _, out = sc.decode_png(make_png(3, 1, 0, 16, [row]))
        self.assertEqual([out[0], out[4], out[8]], [0, 255, 128])

    def test_rgba16_scaled(self):
        row = struct.pack(">HHHH", 65535, 0, 32768, 65535)
        _, _, out = sc.decode_png(make_png(1, 1, 6, 16, [row]))
        self.assertEqual(bytes(out), bytes([255, 0, 128, 255]))

    def test_gray1_bit_unpacking(self):
        # 10 Pixel, 1 Bit: 1010101011 -> Bytes 0xAA 0xC0
        _, _, out = sc.decode_png(make_png(10, 1, 0, 1, [bytes([0xAA, 0xC0])]))
        self.assertEqual([out[4 * i] for i in range(10)], [255, 0, 255, 0, 255, 0, 255, 0, 255, 255])

    def test_palette_with_trns(self):
        plte = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
        png = make_png(3, 1, 3, 8, [bytes([2, 0, 1])], extra=[(b"PLTE", plte), (b"tRNS", bytes([255, 128]))])
        _, _, out = sc.decode_png(png)
        self.assertEqual(bytes(out), bytes([0, 0, 255, 255, 255, 0, 0, 255, 0, 255, 0, 128]))

    def test_palette_4bit(self):
        plte = bytes([0, 0, 0, 9, 9, 9, 200, 100, 50])
        png = make_png(3, 1, 3, 4, [bytes([0x21, 0x00])], extra=[(b"PLTE", plte)])
        _, _, out = sc.decode_png(png)
        self.assertEqual([tuple(out[i * 4:i * 4 + 3]) for i in range(3)], [(200, 100, 50), (9, 9, 9), (0, 0, 0)])

    def test_adam7(self):
        w, h = 11, 9
        px = test_pattern(w, h)
        raw = b""
        for x0, y0, dx, dy in sc.ADAM7:
            pw, ph = (w - x0 + dx - 1) // dx, (h - y0 + dy - 1) // dy
            if pw <= 0 or ph <= 0:
                continue
            prev = bytes(pw * 4)
            for j in range(ph):
                y = y0 + j * dy
                row = b"".join(bytes(px[(y * w + x0 + i * dx) * 4:(y * w + x0 + i * dx) * 4 + 4]) for i in range(pw))
                raw += filter_row(j % 5, row, prev, 4)
                prev = row
        png = make_png(w, h, 6, 8, [bytes(w * 4)], interlace_data=raw)
        self.assertEqual(bytes(sc.decode_png(png)[2]), bytes(px))

    def test_roundtrip_encode(self):
        px = test_pattern(16, 16)
        self.assertEqual(bytes(sc.decode_png(sc.encode_png(16, 16, px))[2]), bytes(px))

    def test_errors(self):
        good = sc.encode_png(2, 2, solid(2, 2, (1, 2, 3, 4)))
        with self.assertRaises(sc.PngError):
            sc.decode_png(b"nicht png")
        broken = bytearray(good)
        broken[20] ^= 0xFF  # IHDR content -> CRC no longer matches
        with self.assertRaises(sc.PngError):
            sc.decode_png(bytes(broken))
        with self.assertRaises(sc.PngError):
            sc.decode_png(good[:-20])
        short = make_png(2, 2, 6, 8, [bytes(8), bytes(8)])
        # shorten the image data: IDAT with too few rows
        short = short.replace(zlib.compress(b"".join(b"\x00" + bytes(8) for _ in range(2))), zlib.compress(b"\x00" + bytes(8)))
        with self.assertRaises(sc.PngError):
            sc.decode_png(short)


class MetricTests(unittest.TestCase):
    def img(self, w, h, color):
        return (w, h, solid(w, h, color))

    def test_identical(self):
        a = (8, 8, test_pattern(8, 8))
        r = sc.compare(a, a)
        self.assertEqual(r["max_abs_diff"], 0)
        self.assertEqual(r["mean_abs_diff"], 0)
        self.assertEqual(r["pixels_over"], 0)
        self.assertTrue(math.isinf(r["psnr"]))

    def test_uniform_difference(self):
        r = sc.compare(self.img(4, 4, (100, 100, 100, 255)), self.img(4, 4, (110, 100, 100, 255)))
        self.assertEqual(r["max_abs_diff"], 10)
        self.assertAlmostEqual(r["mean_abs_diff"], 10 / 4)
        self.assertEqual(r["pixels_over"], 16)
        self.assertAlmostEqual(r["mse"], 100 / 4)
        self.assertAlmostEqual(r["psnr"], 10 * math.log10(255 * 255 / 25))

    def test_single_pixel_and_threshold(self):
        a = self.img(10, 10, (0, 0, 0, 255))
        b = (10, 10, bytearray(a[2]))
        b[2][(3 * 10 + 4) * 4 + 1] = 5
        b[2][(7 * 10 + 7) * 4 + 2] = 1
        self.assertEqual(sc.compare(a, b)["pixels_over"], 2)
        self.assertEqual(sc.compare(a, b, threshold=1)["pixels_over"], 1)
        self.assertEqual(sc.compare(a, b, threshold=5)["pixels_over"], 0)
        r = sc.compare(a, b)
        self.assertEqual(r["max_abs_diff"], 5)
        self.assertAlmostEqual(r["mean_abs_diff"], 6 / 400)

    def test_ignore_alpha(self):
        a = self.img(2, 2, (9, 9, 9, 255))
        b = self.img(2, 2, (9, 9, 9, 0))
        self.assertEqual(sc.compare(a, b)["max_abs_diff"], 255)
        r = sc.compare(a, b, ignore_alpha=True)
        self.assertEqual((r["max_abs_diff"], r["pixels_over"], r["channels"]), (0, 0, "RGB"))

    def test_size_mismatch(self):
        with self.assertRaises(ValueError):
            sc.compare(self.img(2, 2, (0, 0, 0, 0)), self.img(2, 3, (0, 0, 0, 0)))

    def test_diff_image(self):
        a = self.img(1, 2, (10, 20, 30, 255))
        b = (1, 2, bytearray([20, 20, 25, 255, 10, 20, 30, 0]))
        _, _, d = sc.diff_image(a, b, gain=2)
        self.assertEqual(bytes(d), bytes([20, 0, 10, 255, 0, 0, 0, 255]))


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sc.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            pa, pb, pd = (os.path.join(d, n) for n in ("a.png", "b.png", "d.png"))
            a = test_pattern(16, 16)
            b = bytearray(a)
            b[0] = (b[0] + 20) & 255
            sc.write_png(pa, 16, 16, a)
            sc.write_png(pb, 16, 16, b)

            code, out, _ = self.run_cli(pa, pa)
            self.assertEqual(code, 0)
            self.assertIn("psnr           inf", out)

            code, out, _ = self.run_cli(pa, pb, "--diff", pd)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(pd))
            self.assertIn("max_abs_diff   20", out)

            code, out, _ = self.run_cli(pa, pb, "--max-diff", "10")
            self.assertEqual(code, 1)
            self.assertIn("LIMIT EXCEEDED", out)
            self.assertEqual(self.run_cli(pa, pb, "--max-diff", "20", "--max-pixels", "1")[0], 0)
            self.assertEqual(self.run_cli(pa, pb, "--min-psnr", "90")[0], 1)

            code, out, _ = self.run_cli(pa, pb, "--json")
            self.assertIn('"pixels_over": 1', out)

            code, _, err = self.run_cli(pa, os.path.join(d, "missing.png"))
            self.assertEqual(code, 2)
            self.assertIn("ERROR", err)


def sips_available():
    return sys.platform == "darwin" and os.path.exists("/usr/bin/sips")


class SipsCrossCheck(unittest.TestCase):
    @unittest.skipUnless(sips_available(), "sips not available")
    def test_decode_png_written_by_system_tools(self):
        import subprocess
        px = test_pattern(12, 7)
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "s.png"), os.path.join(d, "t.png")
            sc.write_png(src, 12, 7, px)
            # sips rewrites the file (other filters/chunks); the pixels must stay the same
            subprocess.run(["/usr/bin/sips", "-s", "format", "png", src, "--out", dst],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            w, h, out = sc.read_png(dst)
            self.assertEqual((w, h), (12, 7))
            # alpha is fully opaque here except for 250: premultiplied rounding is tolerated
            r = sc.compare((w, h, out), (12, 7, px))
            self.assertLessEqual(r["max_abs_diff"], 4)


if __name__ == "__main__":
    unittest.main()
