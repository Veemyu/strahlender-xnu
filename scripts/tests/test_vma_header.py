import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.install import vma_header


def lock():
    pin = lambda data: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return {"version": "9.9.9", "commit": "c" * 40, "url": "https://example.test/{commit}/{file}",
            "files": {"include/vk_mem_alloc.h": pin(b"header"), "LICENSE.txt": pin(b"mit")}}


class VmaHeaderTests(unittest.TestCase):
    def test_the_shipped_pin_matches_what_the_installer_reads(self):
        pinned = vma_header.load_lock()
        self.assertEqual(len(pinned["commit"]), 40)
        self.assertTrue(pinned["url"].startswith("https://"))
        for pin in pinned["files"].values():
            self.assertEqual(len(pin["sha256"]), 64)
            self.assertGreater(pin["bytes"], 0)

    def test_a_matching_download_is_stored_verified_and_not_fetched_twice(self):
        calls = []

        def get(url, limit):
            calls.append(url)
            return b"mit" if url.endswith("LICENSE.txt") else b"header"

        with tempfile.TemporaryDirectory() as temporary:
            folder = vma_header.ensure(temporary, lock(), get)
            self.assertTrue(vma_header.is_verified(folder, lock()))
            self.assertTrue(all(url.startswith("https://example.test/" + "c" * 40 + "/") for url in calls))
            fetched = len(calls)
            self.assertEqual(vma_header.ensure(temporary, lock(), get), folder)
            self.assertEqual(len(calls), fetched)
            (Path(folder) / "include/vk_mem_alloc.h").write_bytes(b"tampered")
            self.assertFalse(vma_header.is_verified(folder, lock()))

    def test_a_download_that_differs_is_rejected_and_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "does not match the pinned version 9.9.9"):
                vma_header.ensure(temporary, lock(), lambda url, limit: b"other")
            folder = Path(temporary) / "vma"
            self.assertEqual(list(folder.iterdir()) if folder.exists() else [], [])

    def test_the_default_folder_matches_the_installer_data_folder_on_linux(self):
        self.assertEqual(vma_header.default_data_dir({"XDG_DATA_HOME": "/x"}), Path("/x/strahlender-xnu-installer"))
        self.assertEqual(vma_header.default_data_dir({"HOME": "/h"}), Path("/h/.local/share/strahlender-xnu-installer"))


if __name__ == "__main__":
    unittest.main()
