import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest

from scripts.container_extract import container_entries, extract_container


def container(files, hashed=False):
    names, table, payload = bytearray(), bytearray(), bytearray()
    for name, contents in files:
        entry = struct.pack("<QQII", len(payload), len(contents), len(names), len(contents) if hashed else 0)
        if hashed:
            entry += struct.pack("<Q", 0) + hashlib.sha256(contents).digest()
        table.extend(entry)
        names.extend(name.encode("utf-8") + b"\0")
        payload.extend(contents)
    return (b"HFS0" if hashed else b"PFS0") + struct.pack("<III", len(files), len(names), 0) + table + names + payload


class ContainerExtractTests(unittest.TestCase):
    def test_unicode_pfs_hfs_and_xci_bounded_copy(self):
        for hashed in (False, True):
            with self.subTest(hashed=hashed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                files = [("one.nca", b"\x00\xff\n"), ("two-\u65e5\u672c\u8a9e.tik", b"synthetic ticket")]
                archive = root / "input.nsp"
                partition = container(files, hashed)
                archive.write_bytes(container(files))
                destination = extract_container(archive, root / "output", "nsp")
                self.assertEqual({p.name: p.read_bytes() for p in destination.iterdir()}, dict(files))
                with self.assertRaisesRegex(ValueError, "existing"):
                    extract_container(archive, destination, "nsp")
                if hashed:
                    outer = container([("secure", partition)], True)
                    header = bytearray(0x200)
                    header[0x100:0x104] = b"HEAD"
                    struct.pack_into("<QQ", header, 0x130, len(header), len(outer) - len(partition))
                    header[0x140:0x160] = hashlib.sha256(outer[:len(outer) - len(partition)]).digest()
                    archive.write_bytes(header + outer)
                    destination = extract_container(archive, root / "xci-output", "xci")
                    self.assertEqual({p.name: p.read_bytes() for p in destination.iterdir()}, dict(files))

    def test_names_bounds_overlap_and_hash_failure_are_not_published(self):
        invalid = ("../escape", "a\\escape", "C:escape", "NUL", "con.txt", "a.", "", "a/b")
        for name in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                container_entries(io.BytesIO(container([(name, b"data")])))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            container_entries(io.BytesIO(container([("A", b"x"), ("a", b"y")])))
        data = bytearray(container([("one", b"x"), ("two", b"y")]))
        struct.pack_into("<Q", data, 16 + 24, 0)
        with self.assertRaisesRegex(ValueError, "overlap"):
            container_entries(io.BytesIO(data))
        struct.pack_into("<Q", data, 16, 2**63)
        with self.assertRaisesRegex(ValueError, "bounds"):
            container_entries(io.BytesIO(data))
        for length in (0, 3, 15, 17):
            with self.assertRaises(ValueError):
                container_entries(io.BytesIO(data[:length]))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.nsp"
            data = bytearray(container([("one", b"data")], True))
            data[-1] ^= 1
            outer = container([("secure", bytes(data))], True)
            header = bytearray(0x200)
            header[0x100:0x104] = b"HEAD"
            size = len(outer) - len(data)
            struct.pack_into("<QQ", header, 0x130, len(header), size)
            header[0x140:0x160] = hashlib.sha256(outer[:size]).digest()
            archive.write_bytes(header + outer)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                extract_container(archive, root / "output", "xci")
            self.assertFalse((root / "output").exists())
            self.assertEqual(list(root.glob("container-*")), [])
            archive.write_bytes(header + outer[:-1])
            with self.assertRaises(ValueError):
                extract_container(archive, root / "output", "xci")
            data = bytearray(container([("one", b"data")], True))
            struct.pack_into("<Q", data, 16 + 24, 1)
            with self.assertRaisesRegex(ValueError, "reserved"):
                container_entries(io.BytesIO(data))


if __name__ == "__main__":
    unittest.main()
