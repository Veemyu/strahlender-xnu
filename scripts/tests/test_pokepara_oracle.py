"""Tests für scripts/pokepara_oracle.py – nur die Hilfslogik, ausschließlich synthetische Daten (kein ELF, kein Unicorn)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pokepara_oracle as po  # noqa: E402


class ChecksumAndCrypt(unittest.TestCase):
    def test_checksum_sums_little_endian_words(self):
        self.assertEqual(po.py_checksum(bytes([1, 2, 3, 4])), 0x0201 + 0x0403)
        self.assertEqual(po.py_checksum(b""), 0)

    def test_checksum_ignores_odd_trailing_byte(self):
        self.assertEqual(po.py_checksum(bytes([1, 2, 3])), 0x0201)

    def test_checksum_is_32_bit(self):
        self.assertEqual(po.py_checksum(b"\xff\xff" * 0x10001), (0xFFFF * 0x10001) & 0xFFFFFFFF)

    def test_crypt_is_an_involution(self):
        data = bytes(range(64))
        enc = po.py_crypt(data, 0x12345678)
        self.assertNotEqual(enc, data)
        self.assertEqual(po.py_crypt(enc, 0x12345678), data)
        self.assertEqual(len(enc), len(data))

    def test_crypt_first_word_uses_first_lcg_step(self):
        seed = 0
        key = ((seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF) >> 16
        out = po.py_crypt(b"\x00\x00", seed)
        self.assertEqual(out[0] | (out[1] << 8), key)

    def test_crypt_leaves_odd_byte_unchanged(self):
        out = po.py_crypt(bytes([0, 0, 0, 0, 7]), 5)
        self.assertEqual(out[4], 7)

    def test_keystream_wraps_at_32_bit(self):
        ks = list(po.py_keystream(0xFFFFFFFF, 3))
        self.assertTrue(all(0 <= k <= 0xFFFF for k in ks))
        self.assertEqual(len(ks), 3)


class Helpers(unittest.TestCase):
    def test_hex_roundtrip(self):
        self.assertEqual(po.unhex(po.hexs(b"\x00\xff\x10")), b"\x00\xff\x10")

    def test_mask_of(self):
        self.assertEqual(po.mask_of(1), 0xFF)
        self.assertEqual(po.mask_of(8), 0xFFFFFFFFFFFFFFFF)

    def test_layout_constants(self):
        self.assertEqual(po.SLOT_SIZE, 344)
        self.assertEqual(po.HEADER_SIZE + 4 * po.BLOCK_SIZE, po.CORE_SIZE)
        self.assertEqual(po.ENC_LEN, 4 * po.BLOCK_SIZE)

    def test_getter_and_setter_tables_have_unique_names(self):
        g = [n for n, _a, _w in po.GETTERS]
        s = [n for n, _a in po.SETTERS]
        self.assertEqual(len(g), len(set(g)))
        self.assertEqual(len(s), len(set(s)))

    def test_accessor_addresses_parse_header_lines(self):
        if not po.ACCESSOR_C.exists():
            self.skipTest("Pseudocode-Export nicht vorhanden")
        addrs = po.accessor_addresses()
        self.assertEqual(addrs["GetCoreDataBlockPos"], 0x25A3E00)
        for name, _a, _w in po.GETTERS:
            self.assertIn(name, addrs)
        for name, _a in po.SETTERS:
            self.assertIn(name, addrs)

    def test_random_plain_clears_bad_egg_bit(self):
        import random
        for i in range(20):
            core, calc = po.random_plain(random.Random(i))
            self.assertEqual(len(core), po.CORE_SIZE)
            self.assertEqual(len(calc), po.CALC_SIZE)
            self.assertEqual(core[4] & 4, 0)


class Fixtures(unittest.TestCase):
    """Erzeugte Fixtures (falls vorhanden): Gegenprobe der Spielfunktionen gegen die Python-Referenz."""

    def load(self, name):
        path = po.DEFAULT_OUT / name
        if not path.exists():
            self.skipTest(name + " nicht vorhanden")
        return json.loads(path.read_text())

    def test_codec_fixture_matches_python_reference(self):
        d = self.load("PokeParaCodec.json")
        for c in d["checksum"]:
            self.assertEqual(po.py_checksum(po.unhex(c["data"])), c["sum"])
        for c in d["crypt"]:
            self.assertEqual(po.py_crypt(po.unhex(c["plain"]), c["seed"]), po.unhex(c["encoded"]))
            self.assertEqual(po.unhex(c["decodedAgain"]), po.unhex(c["plain"]))

    def test_shuffle_table_rows_are_permutations_and_repeat_after_24(self):
        d = self.load("PokeParaCodec.json")
        t = d["shuffleTable"]
        self.assertEqual(len(t), 32)
        for row in t:
            self.assertEqual(sorted(row), [0, 1, 2, 3])
        for i in range(24, 32):
            self.assertEqual(t[i], t[i - 24])

    def test_accessor_fixture_slots_are_consistent(self):
        d = self.load("PokeParaAccessor.json")
        for s in d["slots"]:
            slot = po.unhex(s["slot"])
            self.assertEqual(len(slot), po.SLOT_SIZE)
            core = slot[:po.CORE_SIZE]
            rnd = int.from_bytes(core[:4], "little")
            self.assertEqual(rnd, s["rnd"])
            plain = core[:po.HEADER_SIZE] + po.py_crypt(core[po.HEADER_SIZE:], rnd)
            self.assertEqual(plain, po.unhex(s["plainCore"]))
            self.assertEqual(int.from_bytes(core[6:8], "little"), po.py_checksum(plain[po.HEADER_SIZE:]) & 0xFFFF)
            self.assertEqual(po.py_crypt(slot[po.CORE_SIZE:], rnd), po.unhex(s["plainCalc"]))


if __name__ == "__main__":
    unittest.main()
