"""Tests for scripts/shader_fidelity.py: synthetic inputs only (no game content, no Metal, no spirv-cross)."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import shader_fidelity as sf  # noqa: E402

REF_FS = """#include <metal_stdlib>
using namespace metal;
struct _15 { float4 _m0[4096]; };
struct main0_out { float4 m_31 [[color(0)]]; };
struct main0_in { float4 m_28 [[user(locn0)]]; };
fragment main0_out main0(main0_in in [[stage_in]], constant _15& fp_c3 [[buffer(0)]], constant _15& fp_c1 [[buffer(1)]], texture2d<float> fp_tex_cb196610_1056805A [[texture(0)]], sampler fp_tex_cb196610_1056805ASmplr [[sampler(0)]], texture2d<float> fp_tex_cb196610_1057005C [[texture(1)]], sampler fp_tex_cb196610_1057005CSmplr [[sampler(1)]], float4 gl_FragCoord [[position]])
{
    main0_out out = {};
    return out;
}
"""

REF_VS = """struct main0_in { float4 m_29 [[attribute(0)]]; float3 m_31 [[attribute(3)]]; };
vertex main0_out main0(main0_in in [[stage_in]], constant _15& vp_c4 [[buffer(0)]], constant _9& support_buffer [[buffer(1)]], device _20& vp_s0 [[buffer(2)]])
{
}
"""


class ParseRef(unittest.TestCase):
    def test_split_params_ignores_commas_in_templates(self):
        self.assertEqual(sf.split_params("a x [[buffer(0)]], texture2d<float, access::sample> t [[texture(1)]], int y"),
                         ["a x [[buffer(0)]]", "texture2d<float, access::sample> t [[texture(1)]]", "int y"])
        self.assertEqual(sf.split_params(""), [])

    def test_texture_key_from_name(self):
        self.assertEqual(sf.tex_key_from_name("fp_tex_cb196610_1056805A"), (0x568, 0x168))
        self.assertEqual(sf.tex_key_from_name("fp_tex_cb196610_1057005C"), (0x570, 0x170))
        self.assertEqual(sf.tex_key_from_name("vp_tex_cb196610_10588062"), (0x588, 0x188))
        self.assertIsNone(sf.tex_key_from_name("fp_c3"))
        self.assertIsNone(sf.tex_key_from_name("fp_tex_something"))

    def test_fragment_interface(self):
        r = sf.parse_ref_msl(REF_FS)
        self.assertEqual(r["stage"], "fragment")
        self.assertEqual([(n, s, k, i) for n, s, k, i in r["buffers"]], [("fp_c3", 0, "cbuf", 3), ("fp_c1", 1, "cbuf", 1)])
        self.assertEqual([(t["slot"], t["sampler_slot"], t["key"]) for t in r["textures"]],
                         [(0, 0, (0x568, 0x168)), (1, 1, (0x570, 0x170))])
        self.assertEqual(r["unsupported"], [])

    def test_vertex_interface_and_unsupported(self):
        r = sf.parse_ref_msl(REF_VS)
        self.assertEqual(r["stage"], "vertex")
        self.assertEqual(r["attrs"], [(0, "float4"), (3, "float3")])
        kinds = {n: k for n, _s, k, _i in r["buffers"]}
        self.assertEqual(kinds, {"vp_c4": "cbuf", "support_buffer": "support", "vp_s0": "other"})
        self.assertEqual(r["unsupported"], ["buffer vp_s0"])

    def test_unsupported_texture_types_and_names(self):
        cube = REF_FS.replace("texture2d<float> fp_tex_cb196610_1056805A", "texturecube<float> fp_tex_cb196610_1056805A")
        self.assertIn("texture type texturecube<float>", sf.parse_ref_msl(cube)["unsupported"])
        odd = REF_FS.replace("fp_tex_cb196610_1057005C ", "mytex ").replace("fp_tex_cb196610_1057005CSmplr", "mytexSmplr")
        self.assertTrue(any(u.startswith("texture name") for u in sf.parse_ref_msl(odd)["unsupported"]))

    def test_missing_entry_point(self):
        with self.assertRaises(ValueError):
            sf.parse_ref_msl("void foo() {}")


class Inputs(unittest.TestCase):
    def test_hash_is_deterministic_and_in_range(self):
        vals = [sf.hash01(i, 5) for i in range(200)]
        self.assertEqual(vals, [sf.hash01(i, 5) for i in range(200)])
        self.assertTrue(all(0.0 <= v < 1.0 for v in vals))
        self.assertNotEqual(sf.hash01(1, 5), sf.hash01(1, 6))
        self.assertGreater(len(set(vals)), 190)

    def test_parse_profile(self):
        self.assertEqual(sf.parse_profile("identity"), ("identity", 0, 0, 0))
        self.assertEqual(sf.parse_profile("dense@2"), ("dense", 2, 0, 0))
        self.assertEqual(sf.parse_profile("hash#3"), ("hash", 0, 3, 0))
        self.assertEqual(sf.parse_profile("identity%4"), ("identity", 0, 0, 4))
        with self.assertRaises(ValueError):
            sf.parse_profile("Identity!")
        for p in sf.PROFILES:
            sf.parse_profile(p)

    def test_cbuf_profiles(self):
        ident = struct.unpack("<32f", sf.cbuf_bytes("identity", 128)[:128])
        self.assertEqual(ident[:8], (1, 0, 0, 0, 0, 1, 0, 0))
        self.assertEqual(ident[12:16], (0, 0, 0, 1))
        self.assertEqual(ident[16:20], (1, 0, 0, 0))  # next matrix
        shifted = struct.unpack("<8f", sf.cbuf_bytes("identity@1", 32))
        self.assertEqual(shifted, (0, 1, 0, 0, 0, 0, 1, 0))
        dense = struct.unpack("<4f", sf.cbuf_bytes("dense", 16))
        self.assertEqual(dense, (0.75, 0.25, 0.25, 0.25))
        self.assertEqual(len(sf.cbuf_bytes("hash")), sf.CBUF_BYTES)
        for name in ("hash", "small", "signed", "half"):
            vals = struct.unpack("<64f", sf.cbuf_bytes(name, 256))
            self.assertTrue(all(v == v and abs(v) < 2 for v in vals), name)
        self.assertEqual(sf.cbuf_bytes("hash", 64, seed=3), sf.cbuf_bytes("hash", 64, seed=3))
        self.assertNotEqual(sf.cbuf_bytes("hash", 64, seed=3), sf.cbuf_bytes("hash", 64, seed=4))
        self.assertNotEqual(sf.cbuf_bytes("hash#1", 64, seed=3), sf.cbuf_bytes("hash", 64, seed=3))
        self.assertGreater(len({sf.cbuf_bytes(f"identity%{v}", 64, k=3) for v in range(1, 9)}), 1)  # shift depends on the variant
        with self.assertRaises(ValueError):
            sf.cbuf_bytes("nosuch")

    def test_mesh(self):
        vb, stride, idx = sf.mesh([3, 0, 1], grid=4)
        self.assertEqual(stride, 48)
        self.assertEqual(len(vb), 25 * 48)
        self.assertEqual(len(idx), 4 * 4 * 6)
        self.assertEqual(max(idx), 24)
        floats = struct.unpack(f"<{len(vb) // 4}f", vb)
        pos = floats[:4]  # first vertex, lowest location = position
        self.assertAlmostEqual(pos[0], -0.9)
        self.assertAlmostEqual(pos[1], -0.9)
        self.assertEqual(pos[3], 1.0)
        self.assertTrue(all(abs(v) <= 0.9 + 1e-6 for v in floats[0::12]))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in floats[4::12]))  # other attributes: gradients in [0, 1]
        self.assertEqual(sf.mesh([2], grid=4), sf.mesh([2], grid=4))

    def test_texture_spec(self):
        a, b = sf.texture_spec((0x568, 0x168)), sf.texture_spec((0x570, 0x170))
        self.assertEqual(a["kind"], "checker")
        self.assertEqual(b["kind"], "gradient")
        self.assertEqual(sf.texture_spec((0x580, 0)), sf.texture_spec((0x580, 0)))
        self.assertNotEqual(a["colorA"], sf.texture_spec((0x580, 0x180))["colorA"])
        self.assertLess(a["colorB"][3], a["colorA"][3])  # the alpha channel varies
        self.assertEqual(sf.texture_spec(None)["kind"], "checker")


class Pairs(unittest.TestCase):
    MAPPING = {"cacheEntries": [
        {"index": 1, "status": "full", "candidates": [{"shader": "A", "pairs": [[10, 11]]}]},
        {"index": 2, "status": "full", "candidates": [{"shader": "A", "pairs": [[10, 11]]}]},   # same blob pair as 1
        {"index": 3, "status": "full", "candidates": [{"shader": "A", "pairs": [[12, 13]]}]},
        {"index": 4, "status": "full", "candidates": [{"shader": "B", "pairs": [[14, 15]]}]},
        {"index": 5, "status": "none", "candidates": [{"shader": "B", "pairs": [[14, 15]]}]},
        {"index": 6, "status": "full", "candidates": [{"shader": "C", "pairs": []}, ]},
        {"index": 7, "status": "full", "candidates": [{"shader": "D", "pairs": [[16, 17]]}]},    # blob missing
        {"index": 8, "status": "full", "candidates": [{"shader": "E", "pairs": [[18, 19]]}]},    # no SPIR-V
        {"index": 9, "status": "full", "candidates": [{"shader": "B", "pairs": [[20, 21]]}]},
    ]}
    BLOB = ["h%d" % i for i in range(30)]

    def pick(self, count=None, seed=0):
        have_spv = lambda i, st: i != 8  # noqa: E731
        have_blob = lambda h: h not in ("h16",)  # noqa: E731
        return sf.pick_pairs(self.MAPPING, self.BLOB, have_spv, have_blob, count, seed)

    def test_all_pairs_filtered(self):
        pairs = self.pick()
        self.assertEqual([p["index"] for p in pairs], [1, 3, 4, 9])  # duplicate pair, wrong status, no pairs, missing files dropped
        self.assertEqual(pairs[0], {"index": 1, "shader": "A", "vs": "h10", "fs": "h11", "bundle": ""})

    def test_sample_alternates_between_shaders(self):
        pairs = self.pick(count=3)
        self.assertEqual(len(pairs), 3)
        self.assertEqual({p["shader"] for p in pairs}, {"A", "B"})
        self.assertEqual(self.pick(count=3, seed=7), self.pick(count=3, seed=7))
        self.assertEqual([p["index"] for p in self.pick(count=99)], [1, 3, 4, 9])

    def test_missing_program_blob_is_skipped(self):
        blobs = list(self.BLOB)
        blobs[14] = None
        pairs = sf.pick_pairs(self.MAPPING, blobs, lambda i, s: True, lambda h: True)
        self.assertNotIn(4, [p["index"] for p in pairs])


class Spec(unittest.TestCase):
    INFO = {"constantBuffers": [{"index": 3, "metalBuffer": 3}, {"index": 1, "metalBuffer": 1}],
            "textures": [{"metalTexture": 0, "metalSampler": 0, "bindless": True, "textureWordOffset": 0x568, "samplerWordOffset": 0x168,
                          "handleOffset": 0x568},
                         {"metalTexture": 1, "metalSampler": 1, "bindless": False, "handleOffset": 8}]}

    def test_side_resources(self):
        ours = sf.side_resources("ours", "fs", self.INFO, None)
        self.assertEqual(ours["cbufs"], {3: 3, 1: 1})
        self.assertEqual([(t["slot"], t["key"]) for t in ours["textures"]], [(0, (0x568, 0x168)), (1, (8, -1))])
        ref = sf.side_resources("ref", "fs", None, sf.parse_ref_msl(REF_FS))
        self.assertEqual(ref["cbufs"], {0: 3, 1: 1})
        self.assertEqual([t["key"] for t in ref["textures"]], [(0x568, 0x168), (0x570, 0x170)])
        self.assertIsNone(ref["support_slot"])
        vs = sf.side_resources("ref", "vs", None, sf.parse_ref_msl(REF_VS))
        self.assertEqual(vs["support_slot"], 1)

    def test_make_spec(self):
        ours = sf.side_resources("ours", "fs", self.INFO, None)
        vs = {"cbufs": {4: 4}, "textures": [], "support_slot": None}
        spec = sf.make_spec(Path("."), "o_vs.metal", "o_fs.metal", vs, ours, [0, 3], "hash#1")
        json.dumps(spec)  # serialisable
        self.assertEqual(spec["vertex"], {"msl": "o_vs.metal"})
        self.assertEqual([(a["location"], a["offset"]) for a in spec["attributes"]], [(0, 0), (3, 16)])
        self.assertEqual(spec["vertexBuffers"][0]["stride"], 32)
        files = {(b["stage"], b["slot"]): b["file"] for b in spec["buffers"]}
        self.assertEqual(files[("vertex", 4)], "cb_vs_4_hash#1.bin")
        self.assertEqual(files[("fragment", 3)], "cb_fs_3_hash#1.bin")
        self.assertEqual(files[("fragment", 1)], "cb_fs_1.bin")  # compiler constants do not depend on the profile
        self.assertEqual([(t["stage"], t["slot"], t["samplerSlot"]) for t in spec["textures"]], [("fragment", 0, 0), ("fragment", 1, 1)])
        self.assertTrue(all(t["mipmaps"] for t in spec["textures"]))
        self.assertEqual(spec["size"], [sf.IMAGE_SIZE, sf.IMAGE_SIZE])

    def test_cbuf_file(self):
        self.assertEqual(sf.cbuf_file("fs", 1, "dense"), "cb_fs_1.bin")
        self.assertEqual(sf.cbuf_file("vs", 4, "dense@1"), "cb_vs_4_dense@1.bin")

    def test_attr_locations(self):
        self.assertEqual(sf.attr_locations({"attrs": [(3, "float4"), (0, "float4")]}, {"inputs": [{"location": 1}, {"location": 3}]}), [0, 1, 3])


class Metrics(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(sf.classify({"max_abs_diff": 0}), "passed")
        self.assertEqual(sf.classify({"max_abs_diff": 1}), "passed")
        self.assertEqual(sf.classify({"max_abs_diff": 2}), "marginal")
        self.assertEqual(sf.classify({"max_abs_diff": 3}), "marginal")
        self.assertEqual(sf.classify({"max_abs_diff": 4}), "failed")

    def test_image_stats(self):
        clear = bytes(min(255, max(0, round(c * 255))) for c in sf.CLEAR)
        px = bytearray(clear * 16)
        self.assertEqual(sf.image_stats((4, 4, px)), {"coverage": 0.0, "distinctColors": 0})
        px[0:4] = bytes([1, 2, 3, 4])
        px[4:8] = bytes([1, 2, 3, 4])
        px[8:12] = bytes([9, 9, 9, 9])
        st = sf.image_stats((4, 4, px))
        self.assertAlmostEqual(st["coverage"], 3 / 16)
        self.assertEqual(st["distinctColors"], 2)

    def test_summarize(self):
        results = [{"status": "passed"}, {"status": "passed"},
                   {"status": "failed", "compat": {"status": "passed"}},
                   {"status": "failed", "compat": {"status": "failed"}},
                   {"status": "marginal"}, {"status": "not_meaningful"}, {"status": "unsupported"}]
        s = sf.summarize(results)
        self.assertEqual(s["pairs"], 7)
        self.assertEqual(s["valid"], 5)
        self.assertEqual(s["passRate"], 0.4)
        self.assertEqual(s["withinNear"], 0.6)
        self.assertEqual(s["passedOnlyWithHalfCompat"], 1)
        self.assertEqual(s["passRateHalfCompat"], 0.6)
        self.assertIsNone(sf.summarize([{"status": "nicht_aussagekraeftig"}])["passRate"])

    def test_jsonable_drops_infinity(self):
        self.assertEqual(sf.jsonable({"psnr": float("inf"), "x": 1}), {"psnr": None, "x": 1})


class Files(unittest.TestCase):
    def test_cleanup_keeps_chosen_profile_and_constants(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            names = ["cb_vs_4_dense.bin", "cb_vs_4_hash#1.bin", "cb_fs_3_hash#1.bin", "cb_fs_3_dense.bin", "cb_fs_1.bin", "cb_vs_1.bin",
                     "vertices.bin", "spec_ref.json"]
            for n in names:
                (d / n).write_bytes(b"x")
            sf.cleanup_pair_dir(d, "hash#1")
            self.assertEqual(sorted(p.name for p in d.iterdir()),
                             sorted(["cb_vs_4_hash#1.bin", "cb_fs_3_hash#1.bin", "cb_fs_1.bin", "cb_vs_1.bin", "vertices.bin", "spec_ref.json"]))

    def test_help_exits_cleanly(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            sf.main(["--help"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
