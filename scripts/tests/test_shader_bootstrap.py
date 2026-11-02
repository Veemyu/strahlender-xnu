import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import shader_bootstrap as boot  # noqa: E402


def layout(directory):
    """A tiny source tree with the files the stamp reads."""
    root = Path(directory) / "src"
    (root / "scripts/recomp").mkdir(parents=True)
    (root / "shader_translator").mkdir()
    (root / "scripts/recomp/shader_bin.sh").write_text("bin")
    (root / "scripts/recomp/macos_target.sh").write_text("BDSP_MACOS_MIN=14.0\n")
    (root / "scripts/shader_extract_blobs.py").write_text("extract")
    for name in boot.TRANSLATOR_SOURCES:
        (root / "shader_translator" / name).write_text(name)
    work = Path(directory) / "work"
    bundle = work / boot.BUNDLES[0]
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(b"x" * 10)
    return root, work


class ShaderBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="shader-bootstrap-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.directory, ignore_errors=True))

    def test_the_cache_names_use_the_runtimes_fnv64(self):
        self.assertEqual(boot.fnv64(b""), "cbf29ce484222325")
        self.assertEqual(boot.fnv64(b"a"), "af63dc4c8601ec8c")  # FNV-1a 64 test vector

    def test_the_stamp_follows_everything_the_output_depends_on(self):
        root, work = layout(self.directory)
        first = boot.stamp(root, work, "macosx", "Metal 1")
        self.assertEqual(first, boot.stamp(root, work, "macosx", "Metal 1"))
        self.assertNotEqual(first, boot.stamp(root, work, "iphoneos", "Metal 1"))   # another SDK
        self.assertNotEqual(first, boot.stamp(root, work, "macosx", "Metal 2"))     # another compiler
        (root / "shader_translator/translate.c").write_text("changed")              # another translator
        self.assertNotEqual(first, boot.stamp(root, work, "macosx", "Metal 1"))
        (root / "scripts/recomp/macos_target.sh").write_text("BDSP_MACOS_MIN=15.0\n")   # another deployment target
        self.assertNotEqual(boot.stamp(root, work, "macosx", "Metal 1"), first)
        again = boot.stamp(root, work, "macosx", "Metal 1")
        (work / boot.BUNDLES[0]).write_bytes(b"y" * 11)                             # another game version
        self.assertNotEqual(again, boot.stamp(root, work, "macosx", "Metal 1"))

    @unittest.skipIf(sys.platform == "win32", "uses a shell script as the translator")
    def test_translate_reads_the_summary_the_translator_writes(self):
        blobs = self.directory / "blobs"
        blobs.mkdir()
        (blobs / "index.json").write_text(json.dumps({"blobs": [
            {"hash": "aa", "stage": "vs"}, {"hash": "bb", "stage": "fs"}, {"hash": "cc", "stage": "fs"}, {"hash": "dd", "stage": "cs"}]}))
        fake = self.directory / "fake-translator"
        fake.write_text("#!/bin/bash\n"
                        "while [ $# -gt 0 ]; do [ \"$1\" = -o ] && out=\"$2\"; shift; done\n"
                        "printf '%s\\n' '{\"file\": \"a\", \"stage\": \"vs\", \"fnv\": \"1\", \"new\": true}' "
                        "'{\"file\": \"b\", \"stage\": \"fs\", \"fnv\": \"2\", \"new\": true}' "
                        "'{\"file\": \"c\", \"stage\": \"fs\", \"fnv\": \"2\", \"new\": false}' "
                        "'{\"file\": \"d\", \"stage\": \"fs\", \"skipped\": \"global memory\"}' > \"$out\"\n")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        summary = boot.translate(fake, blobs, self.directory / "cache/shaders")
        self.assertEqual(summary, {"programs": 4, "unique": 2, "skipped_global_memory": 1, "failed": 0})
        listing = (blobs / "translate-list.txt").read_text().splitlines()
        self.assertEqual([line.split()[0] for line in listing], ["vs", "fs", "fs"])  # compute programs are not listed

    @unittest.skipIf(sys.platform == "win32", "uses a shell script as the translator")
    def test_translate_fails_when_many_programs_do_not_translate(self):
        blobs = self.directory / "blobs"
        blobs.mkdir()
        (blobs / "index.json").write_text(json.dumps({"blobs": [{"hash": "a%d" % i, "stage": "fs"} for i in range(10)]}))
        fake = self.directory / "bad-translator"
        fake.write_text("#!/bin/bash\nwhile [ $# -gt 0 ]; do [ \"$1\" = -o ] && out=\"$2\"; shift; done\n"
                        "for i in 1 2 3 4 5 6 7 8 9 10; do echo '{\"file\": \"x\", \"error\": \"nope\"}'; done > \"$out\"\nexit 1\n")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        with self.assertRaises(RuntimeError):
            boot.translate(fake, blobs, self.directory / "cache/shaders")

    def test_a_prepared_cache_is_reused_without_any_work(self):
        root, work = layout(self.directory)
        cache = self.directory / "cache"
        (cache / "shaders-bin-macosx").mkdir(parents=True)
        (cache / "shaders-bin-macosx/v_0000000000000001.metallib").write_bytes(b"lib")
        with mock.patch.object(boot, "metal_version", return_value="Metal 1"):
            (cache / "bootstrap-macosx.stamp").write_text(boot.stamp(root, work, "macosx", "Metal 1") + "\n")
            with mock.patch.object(boot, "extract_blobs", side_effect=AssertionError("must not run")):
                self.assertEqual(boot.prepare(root, work, cache, "macosx"), 0)

    def test_a_missing_prerequisite_is_reported_not_raised_as_a_failure(self):
        with mock.patch.object(boot, "prepare", side_effect=boot.Missing("UnityPy is not available")):
            self.assertEqual(boot.main(["--sdk", "macosx", "--work", str(self.directory)]), boot.EX_MISSING)
        with mock.patch.object(boot, "prepare", side_effect=RuntimeError("translation failed")):
            self.assertEqual(boot.main(["--sdk", "macosx", "--work", str(self.directory)]), boot.EX_FAILED)


if __name__ == "__main__":
    unittest.main()
