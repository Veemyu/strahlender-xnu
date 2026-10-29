"""The native generator pins LZ4 by hash instead of vendoring it."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts/recomp/native-generator"
SPEC = importlib.util.spec_from_file_location("native_codegen_build_pin", HERE / "build.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
PIN = json.loads((HERE / "vendor/lz4/source.json").read_text())


class Lz4PinTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def sources(self):
        folder = self.folder / "lz4"
        folder.mkdir()
        for name in ("lz4.c", "lz4.h"):
            (folder / name).write_bytes(b"/* " + name.encode() + b" */\n")
        return folder

    def test_repository_keeps_only_pin_and_license(self):
        self.assertEqual(sorted(p.name for p in (HERE / "vendor/lz4").iterdir()), ["LICENSE", "source.json"])
        self.assertEqual(hashlib.sha256((HERE / "vendor/lz4/LICENSE").read_bytes()).hexdigest(), PIN["files"]["LICENSE"])

    def test_explicit_root_with_changed_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            builder.lz4_dependency(self.sources())

    def test_explicit_root_with_missing_source_is_rejected_without_download(self):
        with mock.patch.object(builder, "download") as download:
            with self.assertRaisesRegex(ValueError, "missing"):
                builder.lz4_dependency(self.folder)
        download.assert_not_called()

    def test_tampered_download_is_rejected_and_not_cached(self):
        with mock.patch.object(builder, "ROOT", self.folder), mock.patch.object(builder, "download", return_value=b"evil"):
            with self.assertRaisesRegex(ValueError, "Downloaded LZ4 source checksum mismatch"):
                builder.lz4_dependency()
        self.assertEqual(list(self.folder.rglob("lz4.*")), [])

    def test_download_is_cached_and_reused_offline(self):
        real = {}
        for name in ("lz4.c", "lz4.h"):
            cached = ROOT / "work/native-generator/deps" / ("lz4-" + PIN["version"]) / name
            if not cached.is_file():
                self.skipTest("pinned LZ4 has not been downloaded on this machine yet")
            real[PIN["url"].format(name=name)] = cached.read_bytes()
        with mock.patch.object(builder, "ROOT", self.folder), mock.patch.object(builder, "download", side_effect=real.__getitem__) as download:
            root = builder.lz4_dependency()
            self.assertEqual(download.call_count, 2)
            self.assertEqual(builder.lz4_dependency(), root)
            self.assertEqual(download.call_count, 2)
        shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
