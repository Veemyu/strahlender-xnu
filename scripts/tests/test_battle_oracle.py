"""Tests für scripts/battle_oracle.py – nur die Hilfslogik, ausschließlich synthetische Daten (kein ELF, kein Unicorn)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import battle_oracle as bo  # noqa: E402


def make_elf(segments, dynamic):
    """Baut ein winziges ELF64 mit PT_LOAD-Segmenten und PT_DYNAMIC; segments: [(vaddr, bytes, memsz)]."""
    ph_count = len(segments) + 1
    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    struct.pack_into("<Q", header, 0x20, 64)
    struct.pack_into("<HH", header, 0x36, 56, ph_count)
    body = bytearray()
    phs = bytearray()
    base = 64 + 56 * ph_count
    for vaddr, data, memsz in segments:
        off = base + len(body)
        phs += struct.pack("<IIQQQQQQ", 1, 5, off, vaddr, vaddr, len(data), memsz, 0x1000)
        body += data
    dyn = b"".join(struct.pack("<qQ", tag, val) for tag, val in dynamic) + struct.pack("<qQ", 0, 0)
    off = base + len(body)
    phs += struct.pack("<IIQQQQQQ", 2, 6, off, 0x9000, 0x9000, len(dyn), len(dyn), 8)
    body += dyn
    return bytes(header + phs + body)


class BattleOracleHelperTests(unittest.TestCase):
    def test_signed_unsigned_conversion(self):
        self.assertEqual(bo.to_u32(-1), 0xFFFFFFFF)
        self.assertEqual(bo.to_s32(0xFFFFFFFF), -1)
        self.assertEqual(bo.to_s32(0x7FFFFFFF), 0x7FFFFFFF)
        self.assertEqual(bo.to_s32(0x80000000), -(1 << 31))

    def test_parse_segments_and_dynamic(self):
        elf = make_elf([(0x0, b"\x01\x02\x03\x04", 8), (0x2000, b"\xaa\xbb", 0x10)], [(7, 0x2000), (8, 24)])
        segs = bo.parse_elf_segments(elf)
        self.assertEqual([(s[0], s[2], s[3]) for s in segs], [(0x0, 4, 8), (0x2000, 2, 0x10)])
        self.assertEqual(elf[bo.vaddr_to_offset(segs, 0x2001)], 0xBB)
        with self.assertRaises(KeyError):
            bo.vaddr_to_offset(segs, 0x1000)
        dyn = bo.parse_dynamic(elf, segs)
        self.assertEqual(dyn[7], 0x2000)
        self.assertEqual(dyn[8], 24)

    def test_decomp_dat_flags(self):
        src = "if ((DAT_04dbf874 & 1) == 0) {\n x }\n if ((DAT_04dbf86d & 1) == 0) { }\n if ((DAT_04dbf874 & 1) == 0) {}"
        self.assertEqual(bo.decomp_dat_flags(src), [0x04DBF86D, 0x04DBF874])
        self.assertEqual(bo.decomp_dat_flags("nichts"), [])

    def test_parse_array_hashes_sizes_and_inline_values(self):
        h1, h2, h3 = "A" * 40, "B" * 40, "C" * 40
        dump = (
            f"\tinternal static readonly <PrivateImplementationDetails>.__StaticArrayInitTypeSize=3 {h1} /*Metadata offset 0x2*/; // 0x0\n"
            f"\tinternal static readonly int {h2} = 16910360; // 0x4\n"
            f"\tinternal static readonly long {h3} = -2; // 0x8\n"
        )
        meta = bytes(range(10))
        out = bo.parse_array_hashes(dump, meta)
        self.assertEqual(out[h1], bytes([2, 3, 4]))
        self.assertEqual(list(out[h2]), [24, 8, 2, 1])
        self.assertEqual(out[h3], (2**64 - 2).to_bytes(8, "little"))
        self.assertNotIn(h1, bo.parse_array_hashes(dump, None))

    def test_growth_formulas_against_known_values(self):
        self.assertEqual(bo.growth_exp(0, 10), 1000)
        self.assertEqual(bo.growth_exp(0, 100), 1_000_000)
        self.assertEqual(bo.growth_exp(4, 100), 800_000)
        self.assertEqual(bo.growth_exp(5, 100), 1_250_000)
        self.assertEqual(bo.growth_exp(3, 100), 1_059_860)
        self.assertEqual(bo.growth_exp(1, 100), 600_000)
        self.assertEqual(bo.growth_exp(2, 100), 1_640_000)
        self.assertEqual(bo.growth_exp(3, 2), 9)
        self.assertEqual(bo.growth_exp(3, 1), 0)
        with self.assertRaises(ValueError):
            bo.growth_exp(9, 5)

    def test_verify_growth_rows_counts_deviations(self):
        clean = [0] + [bo.growth_exp(0, n) for n in range(1, 101)]
        broken = list(clean)
        broken[50] += 1
        self.assertEqual(bo.verify_growth_rows([{"exps": clean}]), (100, 0))
        self.assertEqual(bo.verify_growth_rows([{"exps": broken}]), (100, 1))


if __name__ == "__main__":
    unittest.main()
