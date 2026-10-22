"""Tests for scripts/bdsp_save.py: synthetic data only."""
import contextlib
import hashlib
import io
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bdsp_save as bs  # noqa: E402


def make_save(version=0x34, size=None, valid_hash=True):
    """Creates a synthetic save: pattern filler bytes, version, MD5 per spec."""
    n = bs.expected_size(version) if size is None else size
    buf = bytearray((i * 31 + 7) & 0xFF for i in range(n))
    struct.pack_into("<i", buf, 0, version)
    if n >= bs.HASH_END:
        buf[bs.HASH_OFFSET:bs.HASH_END] = bytes(16)
        if valid_hash:
            buf[bs.HASH_OFFSET:bs.HASH_END] = hashlib.md5(buf).digest()
        else:
            buf[bs.HASH_OFFSET:bs.HASH_END] = b"\xAA" * 16
    return bytes(buf)


class TestTables(unittest.TestCase):
    def test_binary_size_table(self):
        self.assertEqual(len(bs.BINARY_SIZE), 16)
        self.assertEqual(bs.expected_size(0x34), 0xEF0A4)
        self.assertEqual(bs.expected_size(0x25), 0xE9828)
        self.assertEqual(bs.expected_size(0x2B), 0xEDC20)
        self.assertEqual(bs.expected_size(0x31), 0xEDC20)
        self.assertEqual(bs.expected_size(0x32), 0xEED8C)
        self.assertIsNone(bs.expected_size(0x24))
        self.assertIsNone(bs.expected_size(0x35))

    def test_fields_contiguous_and_total(self):
        pos = 0
        for off, size, _name, _typ in bs.TOP_LEVEL_FIELDS:
            self.assertEqual(off, pos)
            pos += size
        self.assertEqual(pos, 0xEF0A4)

    def test_hash_field_in_table(self):
        f = {n: (o, s) for o, s, n, _ in bs.TOP_LEVEL_FIELDS}
        self.assertEqual(f["saveDataHash"], (0xE9818, 16))
        self.assertEqual(f["gmsdata"][0], 0x9D03C)

    def test_version_sizes_match_field_starts(self):
        starts = {o for o, *_ in bs.TOP_LEVEL_FIELDS}
        for n in set(bs.BINARY_SIZE[:-1]):
            self.assertIn(n, starts)


class TestHeaderAndHash(unittest.TestCase):
    def test_read_header(self):
        data = make_save()
        self.assertEqual(bs.read_header(data), (0x34, 0xEF0A4))

    def test_valid_current(self):
        data = make_save()
        self.assertEqual(len(data), 0xEF0A4)
        self.assertTrue(bs.verify_hash(data))
        self.assertEqual(bs.compute_hash(data), bs.stored_hash(data))

    def test_valid_all_known_versions(self):
        for v in range(0x25, 0x35):
            with self.subTest(version=v):
                data = make_save(v)
                self.assertEqual(len(data), bs.expected_size(v))
                self.assertTrue(bs.verify_hash(data))

    def test_wrong_hash(self):
        data = make_save(valid_hash=False)
        self.assertFalse(bs.verify_hash(data))

    def test_flipped_payload_byte(self):
        data = bytearray(make_save())
        data[0x1000] ^= 1
        self.assertFalse(bs.verify_hash(bytes(data)))

    def test_wrong_size_too_long_hash_covers_n_only(self):
        # the game hashes only N bytes; an appendix does not change the hash, but the size is wrong
        data = make_save() + b"\x00" * 8
        self.assertTrue(bs.verify_hash(data))
        r = bs.check(data)
        self.assertFalse(r["size_ok"])
        self.assertTrue(r["problems"])

    def test_truncated(self):
        data = make_save()[:0xEF0A4 - 1]
        with self.assertRaises(bs.SaveFormatError):
            bs.verify_hash(data)
        r = bs.check(data)
        self.assertFalse(r["size_ok"])
        self.assertIsNone(r["hash_valid"])

    def test_truncated_below_hash_field(self):
        data = make_save()[:0x1000]
        with self.assertRaises(bs.SaveFormatError):
            bs.verify_hash(data)

    def test_too_short_for_header(self):
        with self.assertRaises(bs.SaveFormatError):
            bs.read_header(b"\x34\x00")

    def test_unknown_version(self):
        data = bytearray(make_save())
        struct.pack_into("<i", data, 0, 0x35)
        with self.assertRaises(bs.SaveFormatError):
            bs.verify_hash(bytes(data))
        r = bs.check(bytes(data))
        self.assertIsNone(r["hash_valid"])
        self.assertTrue(any("unknown version" in p for p in r["problems"]))

    def test_old_version_not_checked(self):
        data = struct.pack("<i", 0x20) + bytes(100)
        self.assertIsNone(bs.verify_hash(data))

    def test_hash_depends_on_zeroed_field(self):
        data = make_save()
        other = bytearray(data)
        other[bs.HASH_OFFSET:bs.HASH_END] = b"\x11" * 16
        self.assertEqual(bs.compute_hash(data), bs.compute_hash(bytes(other)))


class TestFixHashAndCli(unittest.TestCase):
    def setUp(self):
        # temp folder in the test directory instead of the system temp
        self._td = tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(__file__)))
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _write(self, name, data):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_fix_hash_writes_copy_only(self):
        bad = make_save(valid_hash=False)
        src = self._write("in.bin", bad)
        dst = os.path.join(self.dir, "out.bin")
        h = bs.fix_hash(src, dst)
        with open(src, "rb") as f:
            self.assertEqual(f.read(), bad)
        with open(dst, "rb") as f:
            fixed = f.read()
        self.assertTrue(bs.verify_hash(fixed))
        self.assertEqual(h, fixed[bs.HASH_OFFSET:bs.HASH_END])
        self.assertEqual(fixed[:bs.HASH_OFFSET], bad[:bs.HASH_OFFSET])
        self.assertEqual(fixed[bs.HASH_END:], bad[bs.HASH_END:])

    def test_fix_hash_refuses_same_or_existing(self):
        src = self._write("in.bin", make_save(valid_hash=False))
        with self.assertRaises(bs.SaveFormatError):
            bs.fix_hash(src, src)
        other = self._write("other.bin", b"x")
        with self.assertRaises(bs.SaveFormatError):
            bs.fix_hash(src, other)

    def _run(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = bs.main(list(argv))
        return code, out.getvalue()

    def test_cli_check_valid(self):
        p = self._write("ok.bin", make_save())
        code, out = self._run("check", p)
        self.assertEqual(code, 0)
        self.assertIn("Hash valid: yes", out)
        self.assertNotIn("saveDataHash", out)

    def test_cli_check_invalid_with_fields(self):
        p = self._write("bad.bin", make_save(valid_hash=False))
        code, out = self._run("check", p, "--fields")
        self.assertEqual(code, 1)
        self.assertIn("Hash valid: no", out)
        self.assertIn("saveDataHash", out)

    def test_cli_check_truncated(self):
        p = self._write("short.bin", make_save()[:5000])
        code, out = self._run("check", p)
        self.assertNotEqual(code, 0)
        self.assertIn("Hash valid: not checkable", out)

    def test_cli_dump_fields(self):
        code, out = self._run("dump-fields")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 1 + len(bs.TOP_LEVEL_FIELDS))

    def test_cli_fix_hash(self):
        src = self._write("in.bin", make_save(valid_hash=False))
        dst = os.path.join(self.dir, "out.bin")
        code, _ = self._run("fix-hash", src, dst)
        self.assertEqual(code, 0)
        with open(dst, "rb") as f:
            self.assertTrue(bs.verify_hash(f.read()))


if __name__ == "__main__":
    unittest.main()
