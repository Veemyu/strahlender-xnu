"""Synthetic mod NSOs: no game files, keys or saves."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ModCodegenTests(unittest.TestCase):
    def fixture_nso(self, folder, text, unwind=False):
        ro = bytearray(0x40)
        ro[:4] = b"MOD0"
        struct.pack_into("<i", ro, 4, 0x30)
        if unwind:
            struct.pack_into("<ii", ro, 16, 0x20, 0x2c)
            struct.pack_into("<4Bii", ro, 0x20, 1, 0x1b, 3, 0x3b, 0, 0)
        header = bytearray(0x100)
        header[:4] = b"NSO0"
        offset = len(header)
        for i, (memory, data) in enumerate(((0, text), (0x1000, ro), (0x2000, bytes(16)))):
            struct.pack_into("<III", header, 0x10 + i * 0x10, offset, memory, len(data))
            struct.pack_into("<I", header, 0x60 + i * 4, len(data))
            offset += len(data)
        nso = folder / "subsdk1"
        nso.write_bytes(header + text + ro + bytes(16))
        return nso

    def test_homebrew_without_unwind_data_keeps_native_cross_module_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            text = bytearray(0x20)
            struct.pack_into("<II", text, 0, 0xd65f03c0, 0x1000)
            # Empty unwind offsets both resolve to MOD0, not an EH header.
            nso = self.fixture_nso(folder, text)
            entries = folder / "subsdk1.entries"
            entries.write_text("0\n")
            command = [sys.executable, str(ROOT / "scripts/recomp/eh_gen.py"), "gen", "subsdk1",
                       str(nso), "0x806708000", str(folder / "gen"), "--simd", "c",
                       "--entry-offsets", str(entries)]
            result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            table = (folder / "gen/subsdk1_table.c").read_text()
            self.assertIn("f_806708000", table)
            entries.write_text("1000\n")
            rejected = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Cross-module entry outside subsdk1 text", rejected.stderr)

    def test_jump_table_targets_across_inferred_partitions_are_compiled(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            # Hand-written AArch64: cmp; b.hi; ADR table/case; indexed LDRB;
            # ADD; BR; two return blocks, and a two-byte offset table.
            words = (0x14000002, 0x1000, 0x7100041f, 0x540000e8, 0x10000141, 0x100000a2,
                     0x38604820, 0x8b20c840, 0xd61f0000, 0xd503201f, 0x52800160, 0xd65f03c0,
                     0x528002c0, 0xd65f03c0, 0x00000200, 0)
            for unwind in (False, True):
                nso = self.fixture_nso(folder, bytearray(struct.pack("<16I", *words)), unwind=unwind)
                entries = folder / "entries"
                entries.write_text("0\n")
                result = subprocess.run([sys.executable, str(ROOT / "scripts/recomp/eh_gen.py"), "gen", "subsdk1",
                                         str(nso), "0x806708000", str(folder / "gen"), "--simd", "c",
                                         "--entry-offsets", str(entries)], cwd=ROOT, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                table = (folder / "gen/subsdk1_table.c").read_text()
                self.assertIn("f_806708028", table)
                self.assertIn("f_806708030", table)

    def test_spawn_workers_preserve_chunks_tables_and_partial_stubs(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "O'Brien parallel build"
            folder.mkdir()
            words = (0x14000002, 0x1000, 0x7100041f, 0x540000e8, 0x10000141, 0x100000a2,
                     0x38604820, 0x8b20c840, 0xd61f0000, 0xd503201f, 0x52800160, 0xd65f03c0,
                     0x528002c0, 0xd65f03c0, 0x00000200, 0)
            nso = self.fixture_nso(folder, bytearray(struct.pack("<16I", *words)))
            entries = folder / "entries"
            entries.write_text("0\n")
            only = folder / "only"
            only.write_text("0\n28\n")
            for simd, extra in (("asm", ["--window", "0", "--chunk-bytes", "16"]),
                                ("c", ["--window", "0x20", "--big-fn", "1"]),
                                ("c", ["--only", str(only)])):
                expected = None
                for jobs in ("1", "2"):
                    out = folder / ("out-" + jobs)
                    command = [sys.executable, str(ROOT / "scripts/recomp/eh_gen.py"), "gen", "subsdk1",
                               str(nso), "0x806708000", str(out), "--simd", simd,
                               "--entry-offsets", str(entries), "--jobs", jobs, *extra]
                    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("generator workers " + jobs, result.stderr)
                    actual = {file.name: file.read_bytes() for file in out.glob("*.c")}
                    if expected is None:
                        expected = actual
                    else:
                        self.assertEqual(expected, actual)



if __name__ == "__main__":
    unittest.main()
