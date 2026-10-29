import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.recomp import fetch_sources


class FetchSourcesTests(unittest.TestCase):
    def test_plan_covers_every_pinned_input_with_the_names_the_recipes_expect(self):
        names = {item["name"] for item in fetch_sources.plan()}
        sources = json.loads((fetch_sources.ASSETS / "windows-sources.json").read_text())["sources"]
        for name, item in sources.items():
            self.assertIn(name + "-" + item["revision"] + ".tar.gz", names)
        self.assertTrue({"SDL3-source.tar.gz", "ffmpeg-binaries.zip", "llvm-mingw.zip"} <= names)
        for item in fetch_sources.plan():
            self.assertTrue(item["url"].startswith("https://") and len(item["sha256"]) == 64)

    def test_only_verified_files_are_kept_and_matching_ones_are_not_fetched_again(self):
        data = b"pinned archive"
        item = {"name": "a.tar.gz", "url": "https://example.invalid/a", "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
        calls = []
        def good(url, destination):
            calls.append(url)
            Path(destination).write_bytes(data)
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            fetch_sources.fetch([item], out, good)
            fetch_sources.fetch([item], out, good)
            self.assertEqual(calls, ["https://example.invalid/a"])
            (out / "a.tar.gz").unlink()
            with self.assertRaisesRegex(ValueError, "mismatch"):
                fetch_sources.fetch([item], out, lambda url, destination: Path(destination).write_bytes(b"tampered"))
            self.assertEqual(list(out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
