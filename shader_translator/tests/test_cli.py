#!/usr/bin/env python3
"""CLI tests for maxwell2msl with synthetic input files (no game data). Run via `make test`."""
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "build" / "maxwell2msl"

SCHED = 0x001f8000fc0007ff
MOV = 0x5c9807800ff70003
EXIT = 0xe30000000007000f
BRA_SELF = 0xe2400fffff87000f
UNKNOWN_OP = 0xfee0000000070001
BINDLESS = 0xdeb80001a0b70008
MOV_C2_168_R11 = 0x4c98078805a7000b
LOP_OR_C2_568_R11 = 0x4c47020815a70b0b


def blob(words, graphics=True):
    head = bytearray(0x80) if graphics else bytearray()
    if graphics:
        struct.pack_into("<I", head, 0, 0x12345678)
    return bytes(head) + b"".join(struct.pack("<Q", w) for w in words)


def unity_program(stage, payload):
    d = bytearray(0x18)
    struct.pack_into("<II", d, 0, 0x0C07513C, 201806)
    d += struct.pack("<I", 1) + struct.pack("<I", 3) + b"AB\0\0" + struct.pack("<I", 0)
    hdr = len(d)
    ctrl = bytearray(0x40)
    struct.pack_into("<IIIII", ctrl, 0, 0x200, stage, 0, 0x100, 0x80)
    struct.pack_into("<I", ctrl, 0x14, 0x98761234)
    return bytes(d + ctrl + payload)


OK_CODE = [SCHED, MOV, EXIT, BRA_SELF]
BAD_CODE = [SCHED, UNKNOWN_OP, BINDLESS, EXIT, SCHED, BRA_SELF, 0, 0]  # an unknown opcode and a TEX.B without handle
TEX_CODE = [SCHED, MOV_C2_168_R11, LOP_OR_C2_568_R11, BINDLESS, SCHED, EXIT, 0, BRA_SELF]
CONSTANTS = struct.pack("<4f", 1.0, 2.0, 3.0, 4.0)


def run(*args, **kw):
    return subprocess.run([str(BIN), *map(str, args)], capture_output=True, text=True, **kw)


class Cli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BIN.exists():
            raise unittest.SkipTest("build/maxwell2msl missing (make)")
        scratch = ROOT / "build"
        cls.tmp = tempfile.TemporaryDirectory(dir=scratch)
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "ok.bin").write_bytes(blob(OK_CODE))
        (cls.dir / "bad.bin").write_bytes(blob(BAD_CODE))
        tex = blob(TEX_CODE)
        (cls.dir / "tex.bin").write_bytes(tex + b"\0" * (0x100 - len(tex)) + CONSTANTS)  # compiler constants behind the code
        (cls.dir / "ok_cs.bin").write_bytes(blob(OK_CODE, graphics=False))
        (cls.dir / "unity_vs.bin").write_bytes(unity_program(0, blob(OK_CODE)))
        (cls.dir / "unity_fs_bad.bin").write_bytes(unity_program(1, blob(BAD_CODE)))
        (cls.dir / "garbage.bin").write_bytes(b"\x00" * 64)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def p(self, name):
        return self.dir / name

    def test_help(self):
        r = run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--survey", r.stdout)

    def test_usage_errors(self):
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run("--bogus", self.p("ok.bin")).returncode, 2)
        self.assertEqual(run("--stage", "xs", self.p("ok.bin")).returncode, 2)
        self.assertEqual(run("--stage").returncode, 2)
        self.assertEqual(run("--attr-kind", "40=f", "--stage", "vs", self.p("ok.bin")).returncode, 2)
        self.assertEqual(run("--rt-kind", "0=x", "--stage", "fs", self.p("ok.bin")).returncode, 2)
        self.assertEqual(run("--batch", "x", self.p("ok.bin"), "--survey").returncode, 2)
        self.assertEqual(run("--batch", "x").returncode, 2)  # --batch without --survey

    def test_input_errors(self):
        self.assertEqual(run("--stage", "vs", self.p("missing.bin")).returncode, 3)
        r = run(self.p("ok.bin"))  # raw blob without stage
        self.assertEqual(r.returncode, 3)
        self.assertIn("--stage", r.stderr)
        self.assertEqual(run("--stage", "vs", self.p("garbage.bin")).returncode, 3)

    def test_translate_stages(self):
        for stage, marker in (("vs", "vertex VOut main0("), ("fs", "fragment FOut main0(")):
            r = run("--stage", stage, self.p("ok.bin"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(marker, r.stdout)
        r = run("--stage", "cs", self.p("ok_cs.bin"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kernel void main0(", r.stdout)

    def test_output_file_and_info(self):
        out = self.p("out.metal")
        info = self.p("info.json")
        r = run("--stage", "vs", "-o", out, "--info", info, self.p("ok.bin"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIn("vertex VOut main0(", out.read_text())
        data = json.loads(info.read_text())
        self.assertEqual(data["stage"], "vs")
        self.assertEqual(data["instructions"], 2)
        self.assertEqual(data["textures"], [])

    def test_unsupported_fails_with_exit_1(self):
        r = run("--stage", "fs", self.p("bad.bin"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("translation failed", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_unity_container(self):
        r = run(self.p("unity_vs.bin"))  # stage from the container
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("vertex VOut main0(", r.stdout)
        r = run("--survey", self.p("unity_fs_bad.bin"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["stage"], "fs")

    def test_survey_json(self):
        r = run("--survey", "--stage", "fs", self.p("bad.bin"))
        self.assertEqual(r.returncode, 1)
        data = json.loads(r.stdout)
        self.assertFalse(data["translatable"])
        self.assertEqual([i["name"] for i in data["unknownOpcodes"]], ["opfee"])
        self.assertEqual(data["unknownOpcodes"][0]["bits"], "0xfee")
        self.assertEqual(data["unknownOpcodes"][0]["example"], "0xfee0000000070001")
        self.assertEqual([i["name"] for i in data["unsupportedForms"]], ["bindless handle not from cbuf words"])
        self.assertGreaterEqual(data["us"], 0)

    def test_survey_clean(self):
        r = run("--survey", "--stage", "vs", self.p("ok.bin"))
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data["translatable"])
        self.assertEqual(data["unknownOpcodes"] + data["unsupportedForms"], [])

    def test_survey_batch(self):
        lst = self.p("list.txt")
        lst.write_text(f"vs {self.p('ok.bin')}\nfs {self.p('bad.bin')}\nvs {self.p('missing.bin')}\n\n{self.p('unity_vs.bin')}\n")
        out = self.p("batch.jsonl")
        r = run("--survey", "--batch", lst, "-o", out)
        self.assertEqual(r.returncode, 3)  # one unreadable file
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        self.assertEqual(len(rows), 4)
        self.assertTrue(rows[0]["translatable"])
        self.assertFalse(rows[1]["translatable"])
        self.assertIn("inputError", rows[2])
        self.assertTrue(rows[3]["translatable"])
        self.assertIn("4 shaders, 1 with problems, 1 unreadable", r.stderr)

    def test_rscale_option(self):
        ald = 0xefd800000007ff03 | (0x70 << 20)  # R3 = a[0x70] (fragment x)
        (self.dir / "coord.bin").write_bytes(blob([SCHED, ald, EXIT, BRA_SELF]))
        plain = run("--stage", "fs", self.p("coord.bin"))
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertNotIn("rscale", plain.stdout)
        scaled = run("--stage", "fs", "--rscale", self.p("coord.bin"))
        self.assertIn("rscale", scaled.stdout)

    def test_key_options(self):
        r = run("--stage", "vs", "--flip-y", "--depth-minus-one", "--annotate", self.p("ok.bin"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("out.pos.y = -out.pos.y;", r.stdout)
        self.assertIn("out.pos.z = (out.pos.z + out.pos.w) * 0.5f;", r.stdout)
        self.assertIn("// pc ", r.stdout)

    def test_math_pragmas(self):
        r = run("--stage", "vs", self.p("ok.bin"))
        self.assertTrue(r.stdout.startswith("#pragma METAL fp math_mode(safe)\n#pragma METAL fp contract(off)\n"))
        r = run("--stage", "vs", "--fast-math", self.p("ok.bin"))
        self.assertNotIn("#pragma", r.stdout)

    def test_languages(self):
        for language in ("hlsl", "wgsl"):
            r = run("--lang", language, "--stage", "vs", self.p("ok.bin"))
            self.assertEqual(r.returncode, 2, language)
            self.assertIn("unknown language", r.stderr)
        r = run("--lang", "glsl", "--stage", "vs", self.p("ok.bin"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("#pragma METAL", r.stdout)

    def test_resource_map(self):
        info = self.p("tex.json")
        cbuf1 = self.p("tex.cbuf1")
        r = run("--stage", "fs", "--info", info, "--cbuf1", cbuf1, "-o", self.p("tex.metal"), self.p("tex.bin"))
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(info.read_text())
        self.assertEqual(data["metal"]["entry"], "main0")
        tex = data["textures"]
        self.assertEqual(len(tex), 1)
        self.assertEqual({k: tex[0][k] for k in ("slot", "metalTexture", "metalSampler", "bindless", "handleCbuf", "textureWordOffset",
                                                 "samplerWordOffset", "textureTableIndex", "samplerTableIndex", "typeName")},
                         {"slot": 0, "metalTexture": 0, "metalSampler": 0, "bindless": True, "handleCbuf": 2, "textureWordOffset": 0x568,
                          "samplerWordOffset": 0x168, "textureTableIndex": 0, "samplerTableIndex": 0, "typeName": "2d"})
        cb = {c["index"]: c for c in data["constantBuffers"]}
        self.assertEqual(list(cb), [2])
        self.assertEqual((cb[2]["metalBuffer"], cb[2]["staticMinOffset"], cb[2]["staticEndOffset"]), (2, 0x168, 0x56C))
        self.assertFalse(cb[2]["dynamic"])
        self.assertEqual(data["compilerConstants"]["blobOffset"], 0x100)
        self.assertEqual(data["compilerConstants"]["bytesAvailable"], len(CONSTANTS))
        self.assertEqual(cbuf1.read_bytes(), CONSTANTS)
        self.assertIn("texture2d<float> t0 [[texture(0)]]", self.p("tex.metal").read_text())
        for key in ("inputs", "outputs", "cbufSize", "attrMask", "outMask"):  # earlier keys stay
            self.assertIn(key, data)


if __name__ == "__main__":
    unittest.main(verbosity=1)
