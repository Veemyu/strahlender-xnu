import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.install import ffmpeg_cache

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/install/ffmpeg_cache.py"
SCRIPT = ROOT / "scripts/recomp/ios/build_ffmpeg_ios.sh"


def make_prepared(folder, stamp):
    (folder / "lib").mkdir(parents=True)
    (folder / "include").mkdir()
    for name in ffmpeg_cache.LIBRARIES:
        (folder / "lib" / name).write_bytes(b"!<arch>\n")
    (folder / ffmpeg_cache.STAMP_FILE).write_text(stamp + "\n")


class FfmpegCacheTests(unittest.TestCase):
    def test_default_is_the_work_folder_of_the_checkout(self):
        self.assertEqual(ffmpeg_cache.ffmpeg_dir("/repo", {}), Path("/repo/work/ios/ffmpeg-ios"))
        self.assertEqual(ffmpeg_cache.ffmpeg_dir("/repo", {"BDSP_IOS_FFMPEG_DIR": ""}), Path("/repo/work/ios/ffmpeg-ios"))
        self.assertEqual(ffmpeg_cache.ffmpeg_dir(None, {}), ROOT / "work/ios/ffmpeg-ios")

    def test_environment_variable_selects_a_persistent_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            persistent = Path(temporary) / "ios-ffmpeg"
            self.assertEqual(ffmpeg_cache.ffmpeg_dir("/repo", {"BDSP_IOS_FFMPEG_DIR": str(persistent)}), persistent)

    def test_command_line_prints_the_resolved_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            persistent = Path(temporary) / "ios-ffmpeg"
            env = dict(os.environ, BDSP_IOS_FFMPEG_DIR=str(persistent))
            out = subprocess.run([sys.executable, str(HELPER), "dir"], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(Path(out.stdout.strip()), persistent)

    def test_stamp_changes_with_every_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "build.sh"
            script.write_text("one")
            base = ("sha", "/sdk", "26.0", "clang 17", str(script))
            first = ffmpeg_cache.stamp(*base)
            self.assertEqual(first, ffmpeg_cache.stamp(*base))
            for index, value in enumerate(("other", "/sdk2", "26.1", "clang 18")):
                changed = list(base)
                changed[index] = value
                self.assertNotEqual(first, ffmpeg_cache.stamp(*changed), index)
            script.write_text("two")
            self.assertNotEqual(first, ffmpeg_cache.stamp(*base))

    def test_folder_is_reused_only_with_matching_stamp_and_all_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "ios-ffmpeg"
            self.assertFalse(ffmpeg_cache.is_current(folder, "a"))
            make_prepared(folder, "a")
            self.assertTrue(ffmpeg_cache.is_current(folder, "a"))
            self.assertFalse(ffmpeg_cache.is_current(folder, "b"))
            (folder / "lib/libavcodec.a").unlink()
            self.assertFalse(ffmpeg_cache.is_current(folder, "a"))

    def test_folder_without_stamp_is_not_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "ffmpeg-ios"
            make_prepared(folder, "a")
            (folder / ffmpeg_cache.STAMP_FILE).unlink()
            self.assertFalse(ffmpeg_cache.is_current(folder, "a"))

    def test_command_line_current_uses_the_exit_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "ffmpeg"
            make_prepared(folder, "s1")

            def run(stamp):
                return subprocess.run([sys.executable, str(HELPER), "current", str(folder), stamp]).returncode

            self.assertEqual(run("s1"), 0)
            self.assertEqual(run("s2"), 1)

    def test_build_script_builds_aside_and_stamps_last(self):
        text = SCRIPT.read_text()
        if sys.platform != "win32":   # a macOS build script; Windows has no bash to parse it
            self.assertEqual(subprocess.run(["bash", "-n", str(SCRIPT)]).returncode, 0)
        self.assertLess(text.index('mktemp -d "$FFDIR.building'), text.index('> "$PREFIX/.bdsp-stamp"'))
        self.assertLess(text.index('> "$PREFIX/.bdsp-stamp"'), text.index('mv "$PREFIX" "$FFDIR"'))


if __name__ == "__main__":
    unittest.main()
