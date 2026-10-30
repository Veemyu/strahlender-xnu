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
        self.resolved = base / "resolved"
        self.resolved.mkdir()
        (self.resolved / "windows-dependencies.json").write_text(json.dumps(
            {"components": [{"id": "vulkan", "license": "Apache-2.0 AND MIT", "version": "1.4", "source": "https://vulkan.org"}]}))
        (self.resolved / "windows-sources.json").write_text(json.dumps(
            {"sources": {"shaderc": {"repository": "google/shaderc", "license": "Apache-2.0", "version": "v2026.4", "revision": "a" * 40}}}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_unicorn_source_licence_and_offer_are_written(self):
        out = notices.write(self.resolved, Path(self.tmp.name) / "NOTICES", fake_fetch)
        self.assertTrue((out / "source/unicorn-2.1.4.tar.gz").is_file())
        self.assertIn("GENERAL PUBLIC LICENSE", (out / "unicorn/COPYING").read_text())
        text = (out / "README.md").read_text(encoding="utf-8")
        for expected in ("Written offer", "unicorn-2.1.4.tar.gz", "| shaderc |", "| vulkan | 1.4 |", "Visual C++ runtime is not needed"):
            self.assertIn(expected, text)
        self.assertNotIn("| ffmpeg |", text)


if __name__ == "__main__":
    unittest.main()
