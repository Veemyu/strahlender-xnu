"""Tests für scripts/texture_transcode.py – nur synthetische Texturen und Mini-Bundles, keine Spieldaten."""
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
PYDEPS = os.path.join(HERE, "..", "..", "tools", "pydeps")
if os.path.isdir(PYDEPS):
    sys.path.insert(0, PYDEPS)

try:
    import astc_encoder  # noqa: F401
    import etcpak
    import texture2ddecoder  # noqa: F401
    import UnityPy
    from UnityPy.helpers.Tpk import get_typetree_node
    from UnityPy.helpers.TypeTreeHelper import write_typetree
    from UnityPy.helpers.UnityVersion import UnityVersion
    from UnityPy.streams import EndianBinaryWriter
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False

if HAVE:
    import texture_transcode as tt
    from bundle_fixture import make_bundle

UNITY = "2019.4.27f1"
DXT1, DXT5, BC7, BC5, RGBA32, ASTC6 = 10, 12, 25, 27, 4, 50


def gradient_rgba(w, h):
    """Weicher Verlauf mit Alpha; RGBA-Bytes."""
    out = bytearray()
    for y in range(h):
        for x in range(w):
            out += bytes((x * 255 // max(1, w - 1), y * 255 // max(1, h - 1), (x + y) * 255 // max(1, w + h - 2), 255 - x * 64 // max(1, w)))
    return bytes(out)


def box_down(rgba, w, h):
    """Nächste Mip-Stufe (Box 2x2) für RGBA."""
    nw, nh = max(1, w // 2), max(1, h // 2)
    out = bytearray()
    for y in range(nh):
        for x in range(nw):
            px = [0, 0, 0, 0]
            for dy in (0, 1):
                for dx in (0, 1):
                    sx, sy = min(w - 1, 2 * x + dx), min(h - 1, 2 * y + dy)
                    o = (sy * w + sx) * 4
                    for c in range(4):
                        px[c] += rgba[o + c]
            out += bytes(v // 4 for v in px)
    return bytes(out), nw, nh


def bc_chain(fmt, w, h, mips):
    """BC-kodierte Mip-Kette aus einem Verlauf (etcpak) plus die RGBA-Referenz der Hauptstufe."""
    enc = {DXT1: etcpak.compress_bc1, DXT5: etcpak.compress_bc3, BC7: etcpak.compress_bc7, BC5: etcpak.compress_bc5}[fmt]
    rgba = gradient_rgba(w, h)
    ref = rgba
    data = bytearray()
    cw, ch, cur = w, h, rgba
    for _ in range(mips):
        pw, ph = (cw + 3) // 4 * 4, (ch + 3) // 4 * 4     # etcpak erwartet Vielfache von 4
        pad = bytearray()
        for y in range(ph):
            for x in range(pw):
                o = (min(y, ch - 1) * cw + min(x, cw - 1)) * 4
                pad += cur[o:o + 4]
        data += enc(bytes(pad), pw, ph)
        cur, cw, ch = box_down(cur, cw, ch)
    return bytes(data), ref


def psnr_bgra_vs_rgba(bgra, rgba):
    import math
    se = 0
    for i in range(0, len(rgba), 4):
        se += (bgra[i + 2] - rgba[i]) ** 2 + (bgra[i + 1] - rgba[i + 1]) ** 2 + (bgra[i] - rgba[i + 2]) ** 2
    n = len(rgba) // 4 * 3
    return 99.0 if se == 0 else 10 * math.log10(255.0 * 255.0 * n / se)


@unittest.skipUnless(HAVE, "astc_encoder/etcpak/texture2ddecoder/UnityPy fehlen (tools/pydeps)")
class CoreTests(unittest.TestCase):
    def test_mip_dims_and_sizes(self):
        self.assertEqual(tt.mip_dims(8, 4, 4), [(8, 4), (4, 2), (2, 1), (1, 1)])
        self.assertEqual(tt.bc_size(5, 5, 8), 32)
        self.assertEqual(tt.astc_size(1, 1, (6, 6)), 16)
        self.assertEqual(tt.astc_size(13, 7, (6, 6)), 3 * 2 * 16)

    def test_parse_block(self):
        self.assertEqual(tt.parse_block("6x6"), (6, 6))
        with self.assertRaises(SystemExit):
            tt.parse_block("7x7")

    def test_target_block_for_data_textures(self):
        self.assertEqual(tt.target_block(BC5, (6, 6), (4, 4)), (4, 4))
        self.assertEqual(tt.target_block(DXT1, (6, 6), (4, 4)), (6, 6))
        self.assertEqual(tt.target_block(BC5, (4, 4), (4, 4)), (4, 4))

    def test_roundtrip_quality_and_layout(self):
        for fmt in (DXT1, DXT5, BC7):
            for (w, h, mips) in ((32, 32, 6), (20, 12, 5), (9, 5, 4)):
                data, ref = bc_chain(fmt, w, h, mips)
                for block in ((6, 6), (4, 4), (8, 8)):
                    out = tt.transcode_levels(fmt, data, w, h, mips, block, True, "fast")
                    expect = sum(tt.astc_size(mw, mh, block) for mw, mh in tt.mip_dims(w, h, mips))
                    self.assertEqual(len(out), expect, (fmt, w, h, block))
                    got = tt.decode_astc_bgra(out[:tt.astc_size(w, h, block)], w, h, block, True)
                    ref_bgra = tt.decode_bc(fmt, data[:tt.bc_size(w, h, tt.BC_FORMATS[fmt][1])], w, h)
                    ref_rgba = bytearray()
                    for i in range(0, len(ref_bgra), 4):
                        ref_rgba += bytes((ref_bgra[i + 2], ref_bgra[i + 1], ref_bgra[i], ref_bgra[i + 3]))
                    if block == (4, 4):
                        self.assertGreater(psnr_bgra_vs_rgba(got, bytes(ref_rgba)), 25.0, (fmt, w, h))
                    else:
                        self.assertGreater(psnr_bgra_vs_rgba(got, bytes(ref_rgba)), 15.0, (fmt, w, h, block))

    def test_short_data_is_rejected(self):
        data, _ = bc_chain(DXT1, 16, 16, 3)
        with self.assertRaises(ValueError):
            tt.transcode_levels(DXT1, data[:-1], 16, 16, 3, (6, 6), True, "fast")

    def test_bc5_keeps_zero_blue_and_opaque_alpha(self):
        data, _ = bc_chain(BC5, 16, 16, 1)
        out = tt.transcode_levels(BC5, data, 16, 16, 1, (4, 4), False, "medium")
        got = tt.decode_astc_bgra(out, 16, 16, (4, 4), False)
        self.assertTrue(all(got[i] <= 2 for i in range(0, len(got), 4)))       # B
        self.assertTrue(all(got[i] >= 253 for i in range(3, len(got), 4)))     # A


def serialized_texture_file(textures, stream_path):
    """Serialized File (v21, ohne Typbaum) mit Texture2D-Objekten; textures = [(name, w, h, mips, fmt, data|None, stream_off)]."""
    node = get_typetree_node(28, UnityVersion.from_str(UNITY))
    objs = []
    for (name, w, h, mips, fmt, data, off) in textures:
        value = {
            "m_Name": name, "m_ForcedFallbackFormat": 4, "m_DownscaleFallback": False, "m_Width": w, "m_Height": h,
            "m_CompleteImageSize": len(data), "m_TextureFormat": fmt, "m_MipCount": mips, "m_IsReadable": False,
            "m_IgnoreMasterTextureLimit": False, "m_IsPreProcessed": False, "m_StreamingMipmaps": False,
            "m_StreamingMipmapsPriority": 0, "m_ImageCount": 1, "m_TextureDimension": 2,
            "m_TextureSettings": {"m_FilterMode": 1, "m_Aniso": 2, "m_MipBias": 0.0, "m_WrapU": 1, "m_WrapV": 1, "m_WrapW": 1},
            "m_LightmapFormat": 0, "m_ColorSpace": 1,
            "image data": b"" if stream_path else data,
            "m_StreamData": {"offset": off, "size": len(data) if stream_path else 0, "path": stream_path or ""},
        }
        wr = EndianBinaryWriter(endian="<")
        write_typetree(value, node, wr)
        objs.append(wr.bytes)
    meta = UNITY.encode() + b"\0" + struct.pack("<i", 38) + b"\0"
    meta += struct.pack("<i", 1) + struct.pack("<ibh", 28, 0, -1) + bytes(16)       # ein Typ: Texture2D
    meta += struct.pack("<i", len(objs))
    pos, table, body = 0, b"", b""
    for i, ob in enumerate(objs):
        pad = (-pos) % 8
        body += b"\0" * pad
        pos += pad
        table_pad = (-len(meta + table)) % 4
        table += b"\0" * table_pad + struct.pack("<qIIi", i + 1, pos, len(ob), 0)
        body += ob
        pos += len(ob)
    meta += table + struct.pack("<iii", 0, 0, 0) + b"\0"
    header_len = 20
    data_offset = (header_len + len(meta) + 15) // 16 * 16
    head = struct.pack(">IIII", len(meta), data_offset + len(body), 21, data_offset) + b"\0\0\0\0"
    return head + meta + b"\0" * (data_offset - header_len - len(meta)) + body


@unittest.skipUnless(HAVE, "Python-Pakete fehlen (tools/pydeps)")
class BundleTests(unittest.TestCase):
    def _bundle(self, tmp, inline=False, extra_bytes_before=b""):
        d1, _ = bc_chain(DXT5, 32, 16, 6)
        d2, _ = bc_chain(BC7, 16, 16, 5)
        keep = bytes(range(64)) * 4                 # schon "iOS-fähig" (RGBA32 16x16)
        cab = "CAB-00112233445566778899aabbccddeeff"
        if inline:
            tex = [("tex_a", 32, 16, 6, DXT5, d1, 0), ("tex_b", 16, 16, 5, BC7, d2, 0)]
            files = [(cab, serialized_texture_file(tex, None))]
        else:
            res = extra_bytes_before + d1 + d2 + keep
            p = "archive:/%s/%s.resS" % (cab, cab)
            o = len(extra_bytes_before)
            tex = [("tex_a", 32, 16, 6, DXT5, d1, o), ("tex_b", 16, 16, 5, BC7, d2, o + len(d1)),
                   ("tex_c", 16, 16, 1, RGBA32, keep, o + len(d1) + len(d2))]
            files = [(cab, serialized_texture_file(tex, p)), (cab + ".resS", res)]
        path = os.path.join(tmp, "synth")
        make_bundle(path, files, block_size=4096)
        return path, (d1, d2, keep)

    def _check(self, path, expect_names):
        env = UnityPy.load(path)
        got = {}
        for o in env.objects:
            t = o.read()
            got[t.m_Name] = t
        self.assertEqual(sorted(got), sorted(expect_names))
        return got

    def test_bundle_streamed_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, (d1, d2, keep) = self._bundle(tmp)
            dst = os.path.join(tmp, "out")
            st = tt.transcode_bundle(path, dst, (6, 6), (4, 4), "fast")
            self.assertEqual(st["texturen"], 2)
            self.assertEqual(st["formate"], {"DXT5": 1, "BC7": 1})
            got = self._check(dst, ["tex_a", "tex_b", "tex_c"])
            for n, (w, h, mips) in {"tex_a": (32, 16, 6), "tex_b": (16, 16, 5)}.items():
                t = got[n]
                self.assertEqual(int(t.m_TextureFormat), 50)
                self.assertEqual((t.m_Width, t.m_Height, t.m_MipCount, int(t.m_ColorSpace)), (w, h, mips, 1))
                size = sum(tt.astc_size(mw, mh, (6, 6)) for mw, mh in tt.mip_dims(w, h, mips))
                self.assertEqual(t.m_CompleteImageSize, size)
                self.assertEqual(t.m_StreamData.size, size)
                self.assertEqual(len(t.get_image_data()), size)
            c = got["tex_c"]
            self.assertEqual(int(c.m_TextureFormat), RGBA32)
            self.assertEqual(bytes(c.get_image_data()), keep)           # unangetastet, trotz verschobenem Offset
            offs = sorted((t.m_StreamData.offset, t.m_StreamData.size) for t in got.values())
            for (o1, s1), (o2, _) in zip(offs, offs[1:]):
                self.assertEqual(o1 + s1, o2)                            # lückenlos
            self.assertEqual(open(dst, "rb").read(8), b"UnityFS\0")

    def test_bundle_inline_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self._bundle(tmp, inline=True)
            dst = os.path.join(tmp, "out")
            self.assertEqual(tt.transcode_bundle(path, dst, (4, 4), (4, 4), "fast")["texturen"], 2)
            got = self._check(dst, ["tex_a", "tex_b"])
            self.assertEqual(int(got["tex_a"].m_TextureFormat), 48)
            self.assertEqual(len(got["tex_a"].get_image_data()), got["tex_a"].m_CompleteImageSize)
            self.assertIsNone(tt.transcode_bundle(dst, os.path.join(tmp, "out2"), (4, 4), (4, 4), "fast"))

    def test_tree_dry_run_list_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._bundle(tmp)
            with open(os.path.join(tmp, "catalog.bin"), "wb") as f:
                f.write(b"nicht-unityfs")
            self.assertEqual(tt.main(["tree", tmp, "--dry-run", "--jobs", "1"]), 0)
            self.assertEqual(os.path.getsize(os.path.join(tmp, "synth")) > 0, True)
            self.assertEqual(tt.main(["info", os.path.join(tmp, "synth")]), 0)
            listing = os.path.join(tmp, "list.txt")
            with open(listing, "w") as f:
                f.write("# Kommentar\nsynth\n")
            before = os.path.getsize(os.path.join(tmp, "synth"))
            self.assertEqual(tt.main(["tree", tmp, "--list", listing, "--jobs", "1", "--quality", "fast"]), 0)
            self.assertNotEqual(os.path.getsize(os.path.join(tmp, "synth")), before)
            after = os.path.getsize(os.path.join(tmp, "synth"))
            self.assertEqual(tt.main(["tree", tmp, "--jobs", "1"]), 0)                  # zweiter Lauf: nichts mehr zu tun
            self.assertEqual(os.path.getsize(os.path.join(tmp, "synth")), after)
            self.assertEqual(tt.main(["tree", os.path.join(tmp, "fehlt")]), 3)

    def test_psnr_command_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self._bundle(tmp)
            dst = os.path.join(tmp, "out")
            tt.transcode_bundle(path, dst, (4, 4), (4, 4), "medium")
            self.assertEqual(tt.main(["psnr", path, dst, "--samples", "5"]), 0)


if __name__ == "__main__":
    unittest.main()
