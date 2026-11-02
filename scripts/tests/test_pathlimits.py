import os
import tempfile
import unittest
from pathlib import Path

from scripts.install import pathlimits

KEY = "windows-x86_64-to-x86_64-llvm-mingw-ucrt-simd-c"


def root_of(length):
    return "C:\\" + "r" * (length - 3)


class PathLimitTests(unittest.TestCase):
    def test_the_limit_counts_the_terminating_character(self):
        longest = pathlimits.longest_relative(KEY)[0]
        fits = pathlimits.check(root_of(259 - longest), KEY)
        self.assertEqual(fits.total, 259)
        self.assertFalse(fits.too_long)
        self.assertIn("result OK", fits.line())
        full = pathlimits.check(root_of(260 - longest), KEY)
        self.assertEqual(full.total, 260)
        self.assertTrue(full.risk)
        self.assertIn("result RISK", full.line())

    def test_the_default_installer_folder_is_too_deep_and_a_short_folder_is_not(self):
        default = "C:\\Users\\someone\\AppData\\Roaming\\Veemyu\\strahlender-xnu-installer\\data\\sources\\" + "a" * 60 + "\\work"
        deep = pathlimits.check(default, KEY, long_paths=False)
        self.assertTrue(deep.risk)
        self.assertIn("LongPathsEnabled=no", deep.line())
        self.assertIn("(%d of 260 characters)" % deep.total, deep.failure())
        self.assertIn("C:\\bdsp", deep.failure())
        self.assertFalse(pathlimits.check("C:\\bdsp\\work", KEY, long_paths=False).risk)

    def test_enabled_long_paths_do_not_help_because_the_generator_is_not_long_path_aware(self):
        default = root_of(200)
        for setting in (True, False, None):
            check = pathlimits.check(default, KEY, long_paths=setting)
            self.assertTrue(check.too_long)
            self.assertTrue(check.risk)
            self.assertIn("result RISK", check.line())
            self.assertNotIn("LongPathsEnabled", check.failure())
            self.assertIn("C:\\bdsp", check.failure())
        self.assertIn("LongPathsEnabled=yes", pathlimits.check(default, KEY, long_paths=True).line())
        self.assertIn("LongPathsEnabled=unknown", pathlimits.check(default, KEY).line())

    def test_a_deep_game_folder_decides_once_the_data_is_extracted(self):
        game = "Data/StreamingAssets/AssetAssistant/" + "d" * 80 + "/file.bin"
        without = pathlimits.longest_relative(KEY)
        with_game = pathlimits.longest_relative(KEY, romfs=[game])
        self.assertGreater(with_game[0], without[0])
        self.assertEqual(with_game[1], "packaged game data")
        # The packaged copy sits below builds/, deeper than the extraction stage, and Windows paths use either separator.
        self.assertEqual(pathlimits.longest_relative(KEY, romfs=[game.replace("/", "\\")]), with_game)

    def test_the_extracted_data_of_an_earlier_run_is_listed_below_romfs(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(pathlimits.romfs_relative(temporary), [])
            folder = Path(temporary) / "romfs/Data/Sub"
            folder.mkdir(parents=True)
            (folder / "a.bin").write_bytes(b"x")
            (Path(temporary) / "romfs/top.bin").write_bytes(b"x")
            self.assertEqual(sorted(pathlimits.romfs_relative(temporary)), ["Data/Sub/a.bin", "top.bin"])

    def test_long_path_support_is_unknown_off_windows(self):
        if os.name != "nt":
            self.assertIsNone(pathlimits.long_paths_enabled())


if __name__ == "__main__":
    unittest.main()
