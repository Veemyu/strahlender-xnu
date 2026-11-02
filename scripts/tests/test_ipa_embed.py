import contextlib
import io
import json
import os
import plistlib
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.install import driver, ipa_pack

POSIX = os.name == "posix"
GAME = "0100000011d90000"


def make_app(root, with_data=True, link=True):
    app = Path(root) / "BDSP.app"
    (app / "res").mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "dev.test.game"}))
    (app / "BDSP").write_bytes(b"\xcf\xfa" + b"code" * 5000)
    if POSIX:
        (app / "BDSP").chmod(0o755)
    (app / "res/install-data.plist").write_bytes(plistlib.dumps({"RomFSDirectory": "GameData/abc/romfs", "EmbeddedLibrary": with_data}))
    if with_data:
        data = app / ipa_pack.EMBED_DIR / "GameData/abc/romfs/Data"
        data.mkdir(parents=True)
        (data / "a.bin").write_bytes(bytes(range(256)) * 40)
        (data / "empty.bin").write_bytes(b"")
    if link and POSIX:
        os.symlink("Info.plist", app / "res/link-to-info")
    return app


def run_quiet(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        result = function(*args, **kwargs)
    return result, [json.loads(line) for line in out.getvalue().splitlines() if line.startswith("{")]


class EmbedTreeTests(unittest.TestCase):
    def test_romfs_and_only_the_mod_romfs_and_exefs_folders_are_embedded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            romfs = root / "romfs"
            (romfs / "Data/sub").mkdir(parents=True)
            (romfs / "Data/sub/a.bin").write_bytes(b"game")
            mod = root / "mod"
            (mod / "romfs").mkdir(parents=True)
            (mod / "romfs/m.bin").write_bytes(b"mod")
            (mod / "exefs").mkdir()
            (mod / "exefs/main.ips").write_bytes(b"ips")
            (mod / "notes").mkdir()
            (mod / "notes/readme.txt").write_bytes(b"not data")
            app = root / "BDSP.app"
            app.mkdir()
            ipa_pack.embed_data(app, romfs, "GameData/abc/romfs", mod, "Mods/def/Example")
            base = app / ipa_pack.EMBED_DIR
            self.assertEqual((base / "GameData/abc/romfs/Data/sub/a.bin").read_bytes(), b"game")
            self.assertEqual((base / "Mods/def/Example/romfs/m.bin").read_bytes(), b"mod")
            self.assertEqual((base / "Mods/def/Example/exefs/main.ips").read_bytes(), b"ips")
            self.assertFalse((base / "Mods/def/Example/notes").exists())
            ipa_pack.clear_embedded(app)
            self.assertFalse(base.exists())

    def test_invalid_input_embeds_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "romfs").mkdir()
            app = root / "BDSP.app"
            app.mkdir()
            with self.assertRaisesRegex(ValueError, "Data folder"):
                ipa_pack.embed_data(app, root / "romfs", "GameData/abc/romfs")
            (root / "romfs/Data").mkdir()
            (root / "romfs/Data/a").write_bytes(b"x")
            for bad in ("../escape", "/absolute", ""):
                with self.assertRaises(ValueError):
                    ipa_pack.embed_data(app, root / "romfs", bad)
            self.assertFalse((app / ipa_pack.EMBED_DIR / "escape").exists())
            mod = root / "mod"
            (mod / "docs").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "no romfs or exefs"):
                ipa_pack.embed_data(app, root / "romfs", "GameData/abc/romfs", mod, "Mods/def/Example")

    def test_embedding_again_replaces_the_previous_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "romfs/Data").mkdir(parents=True)
            (root / "romfs/Data/a").write_bytes(b"x")
            app = root / "BDSP.app"
            (app / ipa_pack.EMBED_DIR / "GameData/old/romfs").mkdir(parents=True)
            ipa_pack.embed_data(app, root / "romfs", "GameData/new/romfs")
            self.assertFalse((app / ipa_pack.EMBED_DIR / "GameData/old").exists())
            self.assertTrue((app / ipa_pack.EMBED_DIR / "GameData/new/romfs/Data/a").is_file())


class PackTests(unittest.TestCase):
    def test_ipa_layout_compression_modes_and_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_app(directory)
            ipa = Path(directory) / "out.ipa"
            seen = []
            stats = ipa_pack.pack_ipa(app, ipa, lambda *values: seen.append(values))
            self.assertFalse(stats["zip64"])
            with zipfile.ZipFile(ipa) as archive:
                self.assertIsNone(archive.testzip())
                names = archive.namelist()
                self.assertEqual(names[0], "Payload/")
                self.assertIn("Payload/BDSP.app/Info.plist", names)
                self.assertIn("Payload/BDSP.app/res/EmbeddedData/GameData/abc/romfs/Data/a.bin", names)
                info = archive.getinfo("Payload/BDSP.app/res/EmbeddedData/GameData/abc/romfs/Data/a.bin")
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.read(info), bytes(range(256)) * 40)
                self.assertEqual(archive.getinfo("Payload/BDSP.app/BDSP").compress_type, zipfile.ZIP_DEFLATED)
                self.assertEqual(archive.read("Payload/BDSP.app/res/EmbeddedData/GameData/abc/romfs/Data/empty.bin"), b"")
                if POSIX:
                    mode = archive.getinfo("Payload/BDSP.app/BDSP").external_attr >> 16
                    self.assertEqual(stat.S_IMODE(mode), 0o755)
                    link = archive.getinfo("Payload/BDSP.app/res/link-to-info")
                    self.assertEqual(stat.S_IFMT(link.external_attr >> 16), stat.S_IFLNK)
                    self.assertEqual(archive.read(link), b"Info.plist")
            self.assertEqual(stats["files"], len([n for n in names if not n.endswith("/")]))
            done = [value[0] for value in seen]
            self.assertEqual(done, sorted(done))
            self.assertEqual(seen[-1][0], seen[-1][1])
            self.assertEqual(seen[-1][2], seen[-1][3])

    def test_large_archives_use_zip64(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_app(directory, link=False)
            big = app / ipa_pack.EMBED_DIR / "GameData/abc/romfs/Data/big.bin"
            big.write_bytes(os.urandom(5000))
            with patch.object(zipfile, "ZIP64_LIMIT", 1000):   # stands in for the 4 GiB limits of the format
                stats = ipa_pack.pack_ipa(app, Path(directory) / "big.ipa")
            self.assertTrue(stats["zip64"])
            with zipfile.ZipFile(Path(directory) / "big.ipa") as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read("Payload/BDSP.app/res/EmbeddedData/GameData/abc/romfs/Data/big.bin"), big.read_bytes())

    def test_publish_writes_once_names_by_content_and_never_replaces_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_app(directory, link=False)
            out = Path(directory) / "exports"
            first, stats = ipa_pack.publish_ipa(app, out, "dev.test.game")
            self.assertEqual(first.name, "dev.test.game-" + ipa_pack.sha256_file(first)[:20] + ".ipa")
            self.assertEqual([p.name for p in out.iterdir()], [first.name])   # no temporary leftovers
            again, _ = ipa_pack.publish_ipa(app, out, "dev.test.game")
            self.assertEqual(again, first)
            self.assertEqual(len(list(out.iterdir())), 1)
            first.write_bytes(b"something else")
            with self.assertRaisesRegex(ValueError, "differs"):
                ipa_pack.publish_ipa(app, out, "dev.test.game")
            self.assertEqual(first.read_bytes(), b"something else")
            self.assertFalse([p for p in out.iterdir() if p.name.startswith(".ipa-")])

    def test_publish_stops_before_writing_when_space_is_short(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_app(directory, link=False)
            with patch.object(ipa_pack.shutil, "disk_usage", return_value=SimpleNamespace(free=1000)):
                with self.assertRaisesRegex(ValueError, "free space"):
                    ipa_pack.publish_ipa(app, Path(directory) / "exports", "dev.test.game")
            self.assertEqual(list((Path(directory) / "exports").iterdir()), [])


def ios_args(root, **extra):
    return SimpleNamespace(root=root / "checkout", work=root / "work", mod_root=None, mod_name=None, ios_bundle_id=None,
                           ios_export_dir=root / "exports", **extra)


def fake_work(root):
    work = root / "work"
    (work / "romfs/Data").mkdir(parents=True)
    (work / "romfs/Data/game.bin").write_bytes(b"base")
    (work / "manifest.json").write_text(json.dumps({"title_id": GAME, "display_version": "1.3.0"}))
    return work


class DriverEmbedTests(unittest.TestCase):
    def prepare(self, root, **extra):
        fake_work(root)
        args = ios_args(root, **extra)
        prepared = {"build_dir": root / "work/build", "staged": root / "work/staged", "bundle_id": "dev.test"}
        environment, events = run_quiet(driver._prepare_ios, args, prepared, None)
        metadata = plistlib.loads((root / "work/build/res/install-data.plist").read_bytes())
        return args, environment, metadata, events

    def test_ipa_export_embeds_by_default_without_any_new_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            args, environment, metadata, events = self.prepare(Path(directory), ios_delivery="ipa")
            self.assertTrue(metadata["EmbeddedLibrary"])
            self.assertTrue(metadata["ExternalLibrary"])   # saves keep the exported-app layout
            self.assertEqual(environment["BDSP_IOS_EMBED_ROMFS"], "1")
            self.assertEqual(environment["BDSP_IOS_EMBED_ROMFS_DIR"], metadata["RomFSDirectory"])
            self.assertTrue(args.ios_install["embed"])
            text = " ".join(event.get("message", "") for event in events)
            self.assertIn("never share", text)
            self.assertIn("distributes no game data", text)
            self.assertIn("--ios-export-no-embed", text)

    def test_no_embed_keeps_the_library_export_identity_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            args, environment, metadata, _ = self.prepare(Path(directory), ios_delivery="ipa", ios_export_no_embed=True)
            self.assertNotIn("EmbeddedLibrary", metadata)
            self.assertTrue(metadata["ExternalLibrary"])
            self.assertNotIn("BDSP_IOS_EMBED_ROMFS", environment)
            self.assertFalse(args.ios_install["embed"])
        with tempfile.TemporaryDirectory() as directory:
            _, _, embedded, _ = self.prepare(Path(directory), ios_delivery="ipa")
        self.assertNotEqual(embedded["DataManifest"], metadata["DataManifest"])

    def test_device_installation_never_embeds(self):
        for no_embed in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                args, environment, metadata, _ = self.prepare(Path(directory), ios_delivery="device", ios_export_no_embed=no_embed)
                self.assertNotIn("EmbeddedLibrary", metadata)
                self.assertNotIn("ExternalLibrary", metadata)
                self.assertFalse([key for key in environment if "EMBED" in key])
                self.assertFalse(args.ios_install["embed"])

    def test_embed_stops_early_when_the_export_folder_is_too_small(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_work(root)
            args = ios_args(root, ios_delivery="ipa")
            prepared = {"build_dir": root / "work/build", "staged": root / "work/staged", "bundle_id": "dev.test"}
            with patch.object(driver.shutil, "disk_usage", return_value=SimpleNamespace(free=10)), \
                    self.assertRaisesRegex(ValueError, "ios-export-no-embed"):
                run_quiet(driver._prepare_ios, args, prepared, None)

    def test_embedded_export_writes_one_ipa_with_data_and_no_game_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, environment, metadata, _ = self.prepare(root, ios_delivery="ipa")
            app = make_app(root / "built", with_data=False, link=False)
            (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": environment["BDSP_IOS_BUNDLE_ID"]}))
            (app / "res/install-data.plist").write_bytes(plistlib.dumps(metadata))
            ipa_pack.embed_data(app, root / "work/romfs", metadata["RomFSDirectory"])
            with patch.object(driver, "_run_command", side_effect=AssertionError("no helper is needed")):
                output, events = run_quiet(driver._export_ios, args, app)
            self.assertEqual(output.parent, (root / "exports").resolve())
            self.assertFalse((root / "exports/Game Library").exists())
            artifacts = [event for event in events if event["event"] == "artifact"]
            self.assertEqual([event["kind"] for event in artifacts], ["ipa"])
            progress = [event for event in events if event["event"] == "progress" and event["id"] == "install"]
            self.assertTrue(progress and progress[-1]["bytes_completed"] == progress[-1]["bytes_total"])
            with zipfile.ZipFile(output) as archive:
                prefix = "Payload/BDSP.app/res/EmbeddedData/" + metadata["RomFSDirectory"]
                self.assertEqual(archive.read(prefix + "/Data/game.bin"), b"base")
                packaged = plistlib.loads(archive.read("Payload/BDSP.app/res/install-data.plist"))
            self.assertTrue(packaged["EmbeddedLibrary"])
            self.assertIn("do not share", " ".join(e.get("message", "") for e in events).lower())

    def test_embedded_export_refuses_an_app_without_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, environment, metadata, _ = self.prepare(root, ios_delivery="ipa")
            app = make_app(root / "built", with_data=False, link=False)
            (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": environment["BDSP_IOS_BUNDLE_ID"]}))
            (app / "res/install-data.plist").write_bytes(plistlib.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "no embedded game data"):
                run_quiet(driver._export_ios, args, app)
            self.assertFalse((root / "exports").exists() and list((root / "exports").iterdir()))

    def test_no_embed_export_still_uses_the_helper_and_a_game_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, environment, metadata, _ = self.prepare(root, ios_delivery="ipa", ios_export_no_embed=True)
            app = make_app(root / "built", with_data=False, link=False)
            (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": environment["BDSP_IOS_BUNDLE_ID"]}))
            build = root / "work/build"
            (build / "BDSP.ipa").write_bytes(b"ipa without data")
            commands = []

            def fake_run(command, *a, **k):
                commands.append(command)
                return 0

            with patch.object(driver, "_run_command", side_effect=fake_run), \
                    patch.object(ipa_pack, "publish_ipa", side_effect=AssertionError("must not embed")):
                _, events = run_quiet(driver._export_ios, args, app)
            self.assertEqual([c[1] for c in commands[1:]], ["export", "publish-ipa"])
            self.assertEqual({e["kind"] for e in events if e["event"] == "artifact"}, {"game_library", "ipa"})

    def test_cli_default_embeds_and_the_switch_turns_it_off(self):
        seen = []
        common = ["build", "--root", "r", "--work", "w", "--target", "ios", "--base", "b", "--prod-keys", "k",
                  "--ios-delivery", "ipa", "--ios-export-dir", "e"]
        for extra, expected in (([], False), (["--ios-export-no-embed"], True)):
            with patch.object(driver, "build", side_effect=lambda a: seen.append(a) or 0):
                self.assertEqual(driver.main(common + extra), 0)
            self.assertIs(seen[-1].ios_export_no_embed, expected)
            self.assertEqual(driver._embed_enabled(seen[-1]), not expected)


class BuildScriptTests(unittest.TestCase):
    def test_package_step_clears_and_embeds_only_for_the_export_delivery(self):
        script = (Path(__file__).resolve().parents[1] / "recomp/ios/installer_build.sh").read_text()
        self.assertIn('ipa_pack.py clear --app "$R/derived/Build/Products/Release-iphoneos/BDSP.app"', script)
        self.assertIn('[ "$DELIVERY" = ipa ] && [ "${BDSP_IOS_EMBED_ROMFS:-}" = 1 ]', script)
        self.assertLess(script.index("ipa_pack.py clear"), script.index("xcodebuild -project"))
        self.assertLess(script.index("ipa_pack.py embed"), script.index("/usr/bin/codesign --verify"))


if __name__ == "__main__":
    unittest.main()
