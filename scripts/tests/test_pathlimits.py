import os
import tempfile
import unittest
from pathlib import Path

from scripts.install import pathlimits
from scripts.recomp import windows_support as windows

KEY = windows.profile("x86_64", "x86_64")["cache_key"]


GAME = ["Data/StreamingAssets/AssetAssistant/Effects/effect/prefab/field/" + "e" * 44,
        "Data/StreamingAssets/AssetAssistant/UIs/textures/halloffame/langdatas/" + "f" * 20]
NOTICES = ["notices/qt/licenses/LICENSE.GPL3-EXCEPT.txt"]
MOD = {"identity": "a" * 10, "slug": "s" * 32}


def default_root(user, source="a" * 12 + "-" + "1" * 13):
    return ("C:\\Users\\" + user + "\\AppData\\Roaming\\Veemyu\\strahlender-xnu-installer\\data\\sources\\" + source + "\\work")


def default_install(user, mod):
    return "C:\\Users\\" + user + "\\AppData\\Local\\StrahlenderXnu\\" + (
        "mod-apps\\" + pathlimits.installed_folder(mod) if mod else "app")


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

    def test_the_default_installer_folder_fits_for_every_user_name_and_a_deep_one_does_not(self):
        for user, margin in (("abcde", 20), ("u" * 20, 0)):
            root = default_root(user)
            for label, mod in (("vanilla", None), ("mod", MOD)):
                check = pathlimits.check(root, KEY, romfs=GAME, long_paths=False, mod=mod, package=NOTICES,
                                         install=default_install(user, mod))
                self.assertFalse(check.risk, (user, label, check.line()))
                self.assertLessEqual(check.total, pathlimits.LIMIT - 1 - margin, (user, label, check.line()))
                self.assertLessEqual(check.installed, pathlimits.LIMIT - 1 - margin, (user, label, check.line()))
        # An installer 0.1.4 still creates the 60 character source folder: it stops at the preflight with the clear message.
        old = default_root("abcde", "a" * 40 + "-" + "1" * 19)
        deep = pathlimits.check(old, KEY, romfs=GAME, long_paths=False)
        self.assertTrue(deep.risk)
        self.assertIn("LongPathsEnabled=no", deep.line())
        self.assertIn("(%d of 260 characters)" % deep.total, deep.failure())
        self.assertIn("C:\\bdsp", deep.failure())
        self.assertFalse(pathlimits.check("C:\\bdsp\\work", KEY, romfs=GAME, long_paths=False).risk)

    def test_a_deep_install_folder_is_reported_as_such(self):
        check = pathlimits.check(default_root("abcde"), KEY, romfs=GAME, install="C:\\" + "d" * 150 + "\\app")
        self.assertTrue(check.risk and not check.too_long)
        self.assertIn("installed app", check.line())
        self.assertIn("installed app is too deep".replace("installed app", "folder for the installed app"), check.failure())

    def test_a_code_mod_and_the_package_are_planned(self):
        plain = dict(pathlimits.planned_paths(KEY))
        self.assertGreater(len(max(pathlimits.planned_paths(KEY, mod=MOD), key=lambda item: len(item[1]))[1]),
                           len(max(pathlimits.planned_paths(KEY), key=lambda item: len(item[1]))[1]))
        paths = [path for _label, path in pathlimits.planned_paths(KEY, romfs=GAME, mod=MOD, package=NOTICES)]
        self.assertIn("pkg/m-" + MOD["identity"][:8] + "/romfs/" + GAME[0], paths)
        self.assertIn("pkg/.xxxxxxxx/romfs-patch/" + GAME[1], paths)
        self.assertIn("recomp/mods/" + "x" * 20 + "/" + KEY + "/objects/c-xxxxxxxx/subsdk0_subsdk0_00000_0000.o", paths)
        self.assertTrue(plain)

    def test_the_planned_names_match_what_the_build_creates(self):
        root = Path(__file__).resolve().parents[2]
        build = (root / "scripts/recomp/portable_build.py").read_text(encoding="utf-8")
        self.assertIn('prefix="%s"' % pathlimits.GENERATE_PREFIX, build)
        self.assertIn('prefix="%s"' % pathlimits.COMPILE_PREFIX, build)
        self.assertIn('work / "%s"' % pathlimits.RUNTIME_DIR, build)
        self.assertIn('prefix=".", dir=destination.parent', build)
        patch = (root / "scripts/recomp/ui_aspect_patch.py").read_text(encoding="utf-8")
        for folder in pathlimits.PATCH_ROOTS:
            self.assertIn('Path("%s")' % folder, patch)
        runtime = root / "scripts/recomp/runtime"
        names = [path.parent.name + "_" + path.stem + ".o" for path in runtime.glob("*.c")]
        self.assertEqual(len(max(names, key=len)), len(pathlimits.RUNTIME_OBJECT))
        overlay = root / "scripts/recomp/runtime/nvn"
        files = [path.relative_to(tree).as_posix() for tree in (overlay / "src", overlay / "vulkan/src")
                 for path in tree.rglob("*") if path.is_file()] + ["nvn/maxwell/translate.c"]
        self.assertLessEqual(len(max(files, key=len)), len(pathlimits.OVERLAY_FILE.split("/nvn-src-vk/")[1]))

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
