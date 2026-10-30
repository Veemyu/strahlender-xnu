"""The archive's NOTICES folder carries the source the copyleft licences require."""
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.recomp import archive_notices as notices


def fake_fetch(url, target):
    with tarfile.open(target, "w:gz") as archive:
        data = b"GNU GENERAL PUBLIC LICENSE Version 2"
        info = tarfile.TarInfo("unicorn-2.1.4/COPYING")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


class ArchiveNoticesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.resolved, self.downloads = base / "resolved", base / "downloads"
        self.resolved.mkdir()
        self.downloads.mkdir()
        (self.resolved / "windows-dependencies.json").write_text(json.dumps(
            {"components": [{"id": "SDL3", "license": "Zlib", "version": "3.4.2", "source": "https://libsdl.org"}]}))
        (self.resolved / "windows-sources.json").write_text(json.dumps(
            {"sources": {"ffmpeg": {"repository": "FFmpeg/FFmpeg", "license": "LGPL-2.1-or-later", "version": "n8.1", "revision": "a" * 40}}}))
        (self.resolved / "qt.json").write_text(json.dumps({"qt": "6.12.0"}))
        (self.downloads / "qtbase-src.tar.xz").write_bytes(b"qt")
        (self.downloads / ("ffmpeg-" + "a" * 40 + ".tar.gz")).write_bytes(b"ff")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sources_licence_and_offer_are_written(self):
        out = notices.write(self.resolved, self.downloads, Path(self.tmp.name) / "NOTICES", fake_fetch)
        self.assertEqual((out / "source/qtbase-src.tar.xz").read_bytes(), b"qt")
        self.assertIn("GENERAL PUBLIC LICENSE", (out / "unicorn/COPYING").read_text())
        text = (out / "README.md").read_text(encoding="utf-8")
        for expected in ("Written offer", "Qt 6.12.0", "unicorn-2.1.4.tar.gz", "| SDL3 | 3.4.2 | Zlib |", "not part of this archive"):
            self.assertIn(expected, text)

    def test_missing_source_archive_is_an_error(self):
        (self.downloads / "qtbase-src.tar.xz").unlink()
        with self.assertRaises(ValueError):
            notices.write(self.resolved, self.downloads, Path(self.tmp.name) / "NOTICES", fake_fetch)


if __name__ == "__main__":
    unittest.main()
