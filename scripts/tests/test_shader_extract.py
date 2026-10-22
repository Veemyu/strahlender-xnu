"""Tests for scripts/shader_extract_blobs.py: synthetic containers only, no game data."""
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import shader_extract_blobs as sx  # noqa: E402

SCHED = 0x001f8000fc0007ff
MOV = 0x5c9807800ff70003
EXIT = 0xe30000000007000f
BRA_SELF_8 = 0xe2400fffff87000f
BRA_SELF_16 = 0xe2400fffff07000f
NOP = 0x50b0000000070f00
JUNK = 0xbf19a0003f000000


def code(words):
    head = bytearray(0x80)
    struct.pack_into("<I", head, 0, 0x12345678)
    return bytes(head) + b"".join(struct.pack("<Q", w) for w in words)


def program(stage, keywords, payload, local=()):
    d = bytearray(0x18)
    struct.pack_into("<II", d, 0, sx.PROGRAM_MAGIC, 201806)

    def entries(words):
        out = b""
        for w in words:
            raw = w.encode() + b"\0"
            out += struct.pack("<I", len(raw)) + raw + b"\0" * (-len(raw) % 4)
        return out

    # 0x18: count of the global keywords, then their entries, then count and entries of the local ones
    d += struct.pack("<I", len(keywords)) + entries(keywords) + struct.pack("<I", len(local)) + entries(local)
    ctrl = bytearray(0x40)
    struct.pack_into("<IIIII", ctrl, 0, 0x200, stage, 0, 0x100, 0x80)
    struct.pack_into("<I", ctrl, 0x14, sx.CONTROL_MAGIC)
    return bytes(d + ctrl + payload)


OK = [SCHED, MOV, MOV, EXIT, SCHED, BRA_SELF_16, NOP, NOP, SCHED, JUNK, JUNK, JUNK]


class ParseProgram(unittest.TestCase):
    def test_stage_keywords_blob(self):
        payload = code(OK)
        p = sx.parse_program(program(1, ["A_ON", "B"], payload, local=["L"]))
        self.assertEqual(p["stage"], "fs")
        self.assertEqual(p["keywords"], ["A_ON", "B", "L"])
        self.assertEqual(p["blob"], payload)
        self.assertEqual(p["version"], 201806)

    def test_vertex_and_other_stage(self):
        self.assertEqual(sx.parse_program(program(0, [], code(OK)))["stage"], "vs")
        self.assertIsNone(sx.parse_program(program(3, [], code(OK)))["stage"])

    def test_keyword_length_does_not_change_blob(self):
        a = sx.parse_program(program(1, [], code(OK)))["blob"]
        b = sx.parse_program(program(1, ["LONG_KEYWORD_NAME_1", "X"], code(OK)))["blob"]
        self.assertEqual(a, b)

    def test_errors(self):
        good = program(1, ["A"], code(OK))
        with self.assertRaises(ValueError):
            sx.parse_program(b"\0" * 64)
        with self.assertRaises(ValueError):
            sx.parse_program(good[:0x30])
        bad_ctrl = bytearray(good)
        i = bad_ctrl.find(struct.pack("<I", sx.CONTROL_MAGIC))
        bad_ctrl[i:i + 4] = b"\0\0\0\0"
        with self.assertRaises(ValueError):
            sx.parse_program(bytes(bad_ctrl))
        no_blob = good.replace(sx.BLOB_MAGIC, b"\0\0\0\0")
        with self.assertRaises(ValueError):
            sx.parse_program(no_blob)
        huge = bytearray(good)
        struct.pack_into("<I", huge, 0x18, 100000)
        with self.assertRaises(ValueError):
            sx.parse_program(bytes(huge))


class CodeEnd(unittest.TestCase):
    def test_both_branch_spellings(self):
        for bra in (BRA_SELF_8, BRA_SELF_16):
            words = [SCHED, MOV, MOV, EXIT, SCHED, bra, NOP, NOP, SCHED, JUNK, JUNK, JUNK]
            self.assertEqual(sx.code_end(code(words)), 0x80 + 8 * 4, hex(bra))

    def test_constants_do_not_matter_for_code_hash(self):
        a = code([SCHED, MOV, MOV, EXIT, SCHED, BRA_SELF_16, NOP, NOP, SCHED, JUNK, 0, 0])
        b = code([SCHED, MOV, MOV, EXIT, SCHED, BRA_SELF_16, NOP, NOP, SCHED, 1, 2, 3])
        self.assertNotEqual(sx.blob_hash(a), sx.blob_hash(b))
        self.assertEqual(sx.code_hash(a), sx.code_hash(b))

    def test_zero_word_ends_code(self):
        blob = code([SCHED, MOV, MOV, EXIT, SCHED, MOV, MOV, MOV, SCHED, MOV, MOV, MOV, SCHED, 0, 0, 0])
        self.assertEqual(sx.code_end(blob), 0x80 + 8 * 12)

    def test_without_terminator_runs_to_end(self):
        blob = code([SCHED, MOV, MOV, EXIT])
        self.assertEqual(sx.code_end(blob), len(blob))


class Collect(unittest.TestCase):
    def test_dedupe_index_and_files(self):
        base = code(OK)
        other = code([SCHED, MOV, EXIT, BRA_SELF_8])
        progs = [
            ("shaders", "S1", program(1, ["A"], base)),
            ("shaders", "S1", program(1, ["LONGER_KEYWORD"], base)),  # gleicher Blob, andere Keywords
            ("fxparticle", "S2", program(1, [], base)),
            ("shaders", "S3", program(0, [], other)),
            ("shaders", "Bad", b"\0" * 40),
            ("shaders", "Odd", program(3, [], base)),
        ]
        with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(__file__))) as tmp:
            out = Path(tmp) / "blobs"
            summary = sx.collect(iter(progs), out)
            self.assertEqual(summary["programs"], 6)
            self.assertEqual(summary["parsed"], 4)
            self.assertEqual(summary["parseFailures"], 2)
            self.assertEqual(summary["unique"], 2)
            self.assertEqual(summary["uniqueCodes"], 2)
            self.assertEqual(summary["uniqueByStage"], {"fs": 1, "vs": 1})
            idx = json.loads((out / "index.json").read_text())
            blobs = {e["hash"]: e for e in idx["blobs"]}
            h = sx.blob_hash(base)
            self.assertEqual(blobs[h]["programs"], 3)
            self.assertEqual(blobs[h]["bundles"], ["fxparticle", "shaders"])
            self.assertEqual(blobs[h]["shaders"], ["S1", "S2"])
            self.assertEqual(blobs[h]["stage"], "fs")
            self.assertEqual((out / f"{h}.bin").read_bytes(), base)
            self.assertEqual(sorted(p.name for p in out.glob("*.bin")), sorted(f"{x}.bin" for x in blobs))
            self.assertEqual(len(idx["parseFailureList"]), 2)

    def test_refuses_output_outside_work(self):
        saved = sys.argv
        sys.argv = ["x", "--out", "/nowhere/blobs"]
        try:
            with self.assertRaises(SystemExit):
                sx.main()
        finally:
            sys.argv = saved


if __name__ == "__main__":
    unittest.main()
