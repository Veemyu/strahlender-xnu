"""Tests für scripts/bundle_retarget.py – nur synthetische Bundles, keine Spieldaten."""
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
PYDEPS = os.path.join(HERE, "..", "..", "tools", "pydeps")
if os.path.isdir(PYDEPS):
    sys.path.insert(0, PYDEPS)
import bundle_retarget as br  # noqa: E402

try:
    import lz4.block as lz4block
except ImportError:  # pragma: no cover
    lz4block = None


def serialized_file(platform, version=21, little=True, payload=b"payload"):
    unity = b"2019.4.27f1\0"
    head = struct.pack(">IIII", 0, 0, version, 0) + bytes([0 if little else 1]) + b"\0\0\0"
    return head + unity + struct.pack("<i" if little else ">i", platform) + payload


def make_bundle(path, files, block_size=64, compress=True, platform_nodes=None):
    """UnityFS v7: files = [(Name, Bytes)]; Blockinfo und Blöcke LZ4 (oder unkomprimiert)."""
    stream = b"".join(data for _, data in files)
    nodes, off = [], 0
    for name, data in files:
        nodes.append((off, len(data), 4, name))
        off += len(data)
    blocks, parts = [], []
    for i in range(0, len(stream), block_size):
        chunk = stream[i:i + block_size]
        if compress:
            comp = lz4block.compress(chunk, mode="high_compression", store_size=False)
            if len(comp) < len(chunk):
                blocks.append((len(chunk), len(comp), 3)); parts.append(comp); continue
        blocks.append((len(chunk), len(chunk), 0)); parts.append(chunk)
    info = bytes(16) + struct.pack(">i", len(blocks))
    for u, c, fl in blocks:
        info += struct.pack(">IIH", u, c, fl)
    info += struct.pack(">i", len(nodes))
    for o, s, fl, name in nodes:
        info += struct.pack(">QQI", o, s, fl) + name.encode() + b"\0"
    cinfo = lz4block.compress(info, mode="high_compression", store_size=False) if compress else info
    head = b"UnityFS\0" + struct.pack(">I", 7) + b"5.x.x\0" + b"2019.4.27f1\0"
    size_pos = len(head)
    head += struct.pack(">QIII", 0, len(cinfo), len(info), 0x43 if compress else 0x40)
    head += b"\0" * ((-len(head)) % 16)
    data = b"".join(parts)
    head = head[:size_pos] + struct.pack(">Q", len(head) + len(cinfo) + len(data)) + head[size_pos + 8:]
    with open(path, "wb") as f:
        f.write(head + cinfo + data)


@unittest.skipIf(lz4block is None, "lz4 fehlt (tools/pydeps)")
class RetargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def bundle(self, name, platform=38, **kw):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        files = [("CAB-aaa", serialized_file(platform, payload=b"A" * 300)), ("CAB-aaa.resS", b"B" * 200)]
        make_bundle(path, files, **kw)
        return path, files

    def read_all(self, path):
        info = br.parse(path)
        with open(path, "rb") as f:
            return b"".join(br._read_block(f, info, i) for i in range(len(info["blocks"])))

    def test_platform_is_read(self):
        path, _ = self.bundle("a")
        self.assertEqual(br.read_platforms(path), [("CAB-aaa", 38)])

    def test_retarget_changes_only_the_platform(self):
        path, files = self.bundle("a")
        out = os.path.join(self.dir, "out")
        self.assertEqual(br.retarget(path, out, 2), (38, 2))
        self.assertEqual(br.read_platforms(out), [("CAB-aaa", 2)])
        expect = serialized_file(2, payload=b"A" * 300) + b"B" * 200
        self.assertEqual(self.read_all(out), expect)
        self.assertEqual([n[3] for n in br.parse(out)["nodes"]], ["CAB-aaa", "CAB-aaa.resS"])

    def test_original_is_untouched_and_noop_returns_none(self):
        path, _ = self.bundle("a", platform=2)
        before = open(path, "rb").read()
        self.assertIsNone(br.retarget(path, os.path.join(self.dir, "o"), 2))
        self.assertEqual(open(path, "rb").read(), before)

    def test_uncompressed_bundle_and_big_endian(self):
        path = os.path.join(self.dir, "u")
        make_bundle(path, [("CAB-b", serialized_file(38, little=False, payload=b"x" * 50))], compress=False)
        br.retarget(path, path, 9)
        self.assertEqual(br.read_platforms(path), [("CAB-b", 9)])

    def test_tree_in_place_skips_non_bundles(self):
        self.bundle("x/one")
        self.bundle("two")
        with open(os.path.join(self.dir, "Dpr.bin"), "wb") as f:
            f.write(b"not a bundle")
        self.assertEqual(br.cmd_tree(self.dir, 2, None, True), 0)
        self.assertEqual(br.read_platforms(os.path.join(self.dir, "two")), [("CAB-aaa", 38)])
        self.assertEqual(br.cmd_tree(self.dir, 2, None, False), 0)
        self.assertEqual(br.read_platforms(os.path.join(self.dir, "x", "one")), [("CAB-aaa", 2)])
        self.assertEqual(open(os.path.join(self.dir, "Dpr.bin"), "rb").read(), b"not a bundle")

    def test_subset_copies_listed_bundles_and_catalog(self):
        src = os.path.join(self.dir, "src")
        os.makedirs(src)
        make_bundle(os.path.join(src, "keep"), [("CAB-k", serialized_file(38))])
        make_bundle(os.path.join(src, "drop"), [("CAB-d", serialized_file(38))])
        with open(os.path.join(src, "Dpr.bin"), "wb") as f:
            f.write(b"catalog")
        lst = os.path.join(self.dir, "list.txt")
        with open(lst, "w") as f:
            f.write("# Kommentar\nkeep\n")
        dst = os.path.join(self.dir, "dst")
        self.assertEqual(br.cmd_subset(src, dst, lst, 9), 0)
        self.assertEqual(sorted(os.listdir(dst)), ["Dpr.bin", "keep"])
        self.assertEqual(br.read_platforms(os.path.join(dst, "keep")), [("CAB-k", 9)])

    def test_subset_reports_missing_entries(self):
        src = os.path.join(self.dir, "src")
        os.makedirs(src)
        lst = os.path.join(self.dir, "list.txt")
        with open(lst, "w") as f:
            f.write("nothere\n")
        self.assertEqual(br.cmd_subset(src, os.path.join(self.dir, "dst"), lst, 9), 3)

    def test_parse_platform_names(self):
        self.assertEqual(br.parse_platform("macos"), 2)
        self.assertEqual(br.parse_platform("ios"), 9)
        self.assertEqual(br.parse_platform("38"), 38)
        with self.assertRaises(SystemExit):
            br.parse_platform("amiga")


if __name__ == "__main__":
    unittest.main()
