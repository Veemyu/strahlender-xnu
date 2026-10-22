"""Tests for scripts/build_helpers.py: synthetic data only (no keys, no game files)."""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_helpers as bh  # noqa: E402

RIGHTS = bytes(range(0x10, 0x20))
KEY = bytes(range(0xA0, 0xB0))


def make_tik(sig_type=0x010004, key_type=0, rights=RIGHTS, key=KEY):
    sig_len, pad = bh.TIK_SIG_SIZES[sig_type]
    body = bytearray(0x180)
    body[0x40:0x40 + len(key)] = key
    body[0x141] = key_type
    body[0x160:0x170] = rights
    return struct.pack("<I", sig_type) + b"\xff" * sig_len + b"\0" * pad + bytes(body)


FAKE_INFO = """\
[WARN] Unable to match rights id to titlekey. Update title.keys?

NCA:
Magic:                              NCA3
Fixed-Key Index:                    0x0
Fixed-Key Signature:                AAAA
                                    BBBB
Content Size:                       0x0000a356c000
Title ID:                           0100000011d90000
Distribution type:                  Download
Content Type:                       Program
Master Key Revision:                0xC (Unknown)
Rights ID:                          0100000011D90800000000000000000D
Key Area (Encrypted):
    00: SECRETKEYAREA
"""


class TikTests(unittest.TestCase):
    def test_rsa2048_layout(self):
        data = make_tik()
        self.assertEqual(len(data), 0x2C0)
        t = bh.parse_tik(data)
        self.assertEqual(t["rights_id"], RIGHTS.hex())
        self.assertEqual(t["key_type"], 0)
        self.assertEqual(t["title_key"], KEY.hex())

    def test_other_signature_types(self):
        for sig in bh.TIK_SIG_SIZES:
            t = bh.parse_tik(make_tik(sig_type=sig))
            self.assertEqual(t["rights_id"], RIGHTS.hex(), hex(sig))
            self.assertEqual(t["title_key"], KEY.hex(), hex(sig))

    def test_personalized_has_no_key(self):
        t = bh.parse_tik(make_tik(key_type=1))
        self.assertIsNone(t["title_key"])

    def test_big_endian_signature_type(self):
        data = make_tik()
        data = struct.pack(">I", 0x010004) + data[4:]
        self.assertEqual(bh.parse_tik(data)["rights_id"], RIGHTS.hex())

    def test_invalid(self):
        with self.assertRaises(bh.TikError):
            bh.parse_tik(b"\0\0")
        with self.assertRaises(bh.TikError):
            bh.parse_tik(b"\xde\xad\xbe\xef" + b"\0" * 0x300)
        with self.assertRaises(bh.TikError):
            bh.parse_tik(make_tik()[:0x200])


class TitleKeyTests(unittest.TestCase):
    def test_parse_title_keys(self):
        text = "; Kommentar\n%s = %s\nkaputt\n%s=zz\n" % (RIGHTS.hex().upper(), KEY.hex(), "1" * 32)
        self.assertEqual(bh.parse_title_keys(text), {RIGHTS.hex(): KEY.hex()})

    def test_find_in_tik_dir_prefers_ticket(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.tik"), "wb") as f:
                f.write(make_tik())
            other = bytes(16)
            key, src = bh.find_title_key(RIGHTS.hex().upper(), d, "%s=%s\n" % (RIGHTS.hex(), other.hex()))
            self.assertEqual((key, src), (KEY.hex(), "tik"))

    def test_fallback_to_title_keys(self):
        with tempfile.TemporaryDirectory() as d:
            key, src = bh.find_title_key(RIGHTS.hex(), d, "%s=%s\n" % (RIGHTS.hex(), KEY.hex()))
            self.assertEqual((key, src), (KEY.hex(), "title.keys"))

    def test_personalized_without_fallback_fails(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.tik"), "wb") as f:
                f.write(make_tik(key_type=1))
            with self.assertRaises(KeyError):
                bh.find_title_key(RIGHTS.hex(), d, None)

    def test_missing(self):
        with self.assertRaises(KeyError):
            bh.find_title_key(RIGHTS.hex(), None, "")


class NcaInfoTests(unittest.TestCase):
    def test_parse_and_no_key_leak(self):
        info = bh.parse_nca_info(FAKE_INFO, "a.nca")
        self.assertEqual(info["title_id"], "0100000011d90000")
        self.assertEqual(info["content_type"], "Program")
        self.assertEqual(info["master_key_rev"], "0xC")
        self.assertEqual(info["rights_id"], "0100000011d90800000000000000000d")
        self.assertEqual(info["size"], 0xA356C000)
        self.assertNotIn("SECRET", bh.info_row(info))
        self.assertNotIn("AAAA", bh.info_row(info))

    def test_zero_rights_id(self):
        text = FAKE_INFO.replace("0100000011D90800000000000000000D", "0" * 32)
        self.assertEqual(bh.parse_nca_info(text)["rights_id"], "")

    def test_garbage_rejected(self):
        with self.assertRaises(ValueError):
            bh.parse_nca_info("[WARN] nope\n")

    def test_pick(self):
        rows = [
            "a\t0100000011d90000\tProgram\t0xA\tStandard crypto\t\t100",
            "b\t0100000011d90000\tProgram\t0xC\tTitlekey crypto\tx\t300",
            "c\t0100000011d90000\tControl\t0xC\t\t\t999",
            "d\t0100000022222000\tProgram\t0xC\t\t\t5000",
        ]
        self.assertEqual(bh.pick_nca(rows, "program", "0100000011D90000"), "b")
        self.assertEqual(bh.pick_nca(rows, "Control"), "c")
        self.assertIsNone(bh.pick_nca(rows, "Meta"))
        self.assertIsNone(bh.pick_nca(rows, "Program", "ffffffffffffffff"))


class MetaTests(unittest.TestCase):
    def test_cnmt_version(self):
        data = struct.pack("<QI", 0x0100000011D90800, 196608) + b"\0" * 8
        self.assertEqual(bh.cnmt_version(data), {"title_id": "0100000011d90800", "version": 196608})

    def test_nacp_version(self):
        data = bytearray(0x4000)
        data[0x3060:0x3065] = b"9.8.7"
        self.assertEqual(bh.nacp_display_version(bytes(data)), "9.8.7")
        with self.assertRaises(ValueError):
            bh.nacp_display_version(b"\0" * 10)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        os.makedirs(os.path.join(self.work, "exefs"))
        os.makedirs(os.path.join(self.work, "romfs", "Data"))
        for name, content in (("exefs/main", b"main-bytes"), ("exefs/rtld", b"r"),
                              ("romfs/Data/a.bin", b"12345"), ("romfs/b.bin", b"67")):
            with open(os.path.join(self.work, name), "wb") as f:
                f.write(content)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        bh.main(["write-manifest", "--work", self.work, "--title-id", "0100000011d90000",
                 "--title-version", "196608", "--display-version", "1.2.3",
                 "--update-applied", "1", "--xci-size", "10", "--nsp-size", "20"])

    def test_write_and_check(self):
        self.write()
        with open(os.path.join(self.work, "manifest.json")) as f:
            m = json.load(f)
        self.assertEqual(m["romfs"], {"files": 2, "bytes": 7})
        self.assertEqual(m["title_id"], "0100000011d90000")
        import hashlib
        self.assertEqual(m["exefs"]["main"]["sha256"], hashlib.sha256(b"main-bytes").hexdigest())
        self.assertEqual(m["exefs"]["main"]["sha1"], hashlib.sha1(b"main-bytes").hexdigest())
        self.assertTrue(bh.manifest_matches(self.work, 10, 20))

    def test_mismatch_cases(self):
        self.assertFalse(bh.manifest_matches(self.work, 10, 20))  # no manifest
        self.write()
        self.assertFalse(bh.manifest_matches(self.work, 11, 20))  # different input
        with open(os.path.join(self.work, "romfs", "c.bin"), "wb") as f:
            f.write(b"x")
        self.assertFalse(bh.manifest_matches(self.work, 10, 20))  # romfs changed
        os.remove(os.path.join(self.work, "romfs", "c.bin"))
        self.assertTrue(bh.manifest_matches(self.work, 10, 20))
        with open(os.path.join(self.work, "exefs", "main"), "wb") as f:
            f.write(b"changed")
        self.assertFalse(bh.manifest_matches(self.work, 10, 20))  # main changed


if __name__ == "__main__":
    unittest.main()
