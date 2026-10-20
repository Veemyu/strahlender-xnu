"""Original-icon pipeline tests using only synthetic pictures under work/."""
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "scripts/recomp/app"
sys.path.insert(0, str(APP))
import game_icons as icons

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipUnless(Image, "Pillow required")
class GameIconTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / "work/tests"
        work.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="icons-", dir=work)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.update = self.root / "update"
        self.base.mkdir()
        self.update.mkdir()
        self.source = self.root / "source"

    def picture(self, directory, language, color):
        stream = io.BytesIO()
        Image.new("RGB", (256, 256), color).save(stream, "JPEG")
        path = directory / ("icon_" + language + ".dat")
        path.write_bytes(stream.getvalue())
        return path

    def fixture(self):
        self.picture(self.base, "AmericanEnglish", "red")
        self.picture(self.base, "Japanese", "red")
        self.picture(self.base, "German", "green")
        self.picture(self.update, "German", "blue")
        (self.update / "icon_Japanese.dat").write_bytes(b"invalid synthetic image")
        return icons.ingest(self.base, self.update, self.source, "0000000000000000")

    def test_update_merge_and_image_deduplication(self):
        metadata = self.fixture()
        variants = {v["id"]: v for v in metadata["variants"]}
        self.assertEqual(set(variants), {"en-US", "ja", "de"})
        self.assertEqual(metadata["default"], "en-US")
        self.assertEqual(variants["ja"]["icon"], variants["en-US"]["icon"])
        with Image.open(self.source / variants["de"]["image"]) as image:
            self.assertGreater(image.getpixel((0, 0))[2], 240)

    def test_language_recommendation_and_missing_choice(self):
        variants = [{"id": x} for x in ("de", "en-US", "en-GB", "ja", "zh-Hans", "zh-Hant")]
        self.assertEqual(icons.recommend(variants, ["de-DE"]), "de")
        self.assertEqual(icons.recommend(variants, ["en-GB"]), "en-GB")
        self.assertEqual(icons.recommend(variants, ["ja-JP"]), "ja")
        self.assertEqual(icons.recommend(variants, ["zh-TW"]), "zh-Hant")
        self.assertEqual(icons.recommend(variants, ["zh-CN"]), "zh-Hans")
        self.assertEqual(icons.recommend(variants, ["xx"]), "en-US")
        self.assertEqual(icons.default_variant([{"id": "en-GB"}, {"id": "de"}]), "en-GB")

    def test_corrupt_english_falls_back_to_valid_original(self):
        metadata = self.fixture()
        english = next(v for v in metadata["variants"] if v["id"] == "en-US")
        (self.source / english["image"]).write_bytes(b"broken")
        loaded = icons.load_source(self.source)
        self.assertEqual([v["id"] for v in loaded["variants"]], ["de"])
        self.assertEqual(loaded["default"], "de")

    def test_missing_icons_generate_placeholder_without_reusing_stale_sources(self):
        self.fixture()
        icons.ingest(None, None, self.source)
        output = self.root / "linux"
        icons.build_linux(self.source, output, self.root / "game")
        metadata = json.loads((output / "icons.json").read_text())
        self.assertEqual(metadata["default"], "placeholder")
        self.assertEqual(len(metadata["variants"]), 1)
        entry = metadata["variants"][0]
        for size in (16, 32, 48, 64, 128, 256, 512):
            with Image.open(output / "hicolor" / ("%dx%d" % (size, size)) / "apps" / (entry["icon"] + ".png")) as image:
                self.assertEqual(image.size, (size, size))

    def test_mac_icns_and_incremental_fingerprint(self):
        self.fixture()
        output = self.root / "mac"
        import icon_composer
        def compile_icons(documents, primary, destination, platform):
            destination.mkdir(parents=True)
            Image.new("RGBA", (1024, 1024), "red").save(destination / (primary + ".icns"), "ICNS")
            (destination / "Assets.car").write_bytes(b"synthetic archive")
            return {"CFBundleIconName": primary}
        with patch.object(icon_composer, "compile_icons", side_effect=compile_icons):
            icons.build_mac(self.source, output)
        with Image.open(output / "BDSP.icns") as image:
            self.assertEqual(image.format, "ICNS")
            self.assertEqual(image.size, (1024, 1024))
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_stages
        before, _ = build_stages.stage_hash("recomp", str(ROOT), str(self.root), env={"BDSP_ICON_SOURCE": str(self.source)})
        self.picture(self.update, "German", "yellow")
        icons.ingest(self.base, self.update, self.source)
        after, _ = build_stages.stage_hash("recomp", str(ROOT), str(self.root), env={"BDSP_ICON_SOURCE": str(self.source)})
        self.assertNotEqual(before, after)

    def test_apple_composition_is_deterministic_and_uses_platform_specific_margins(self):
        from icon_artwork import mac_artwork, ipad_artwork
        self.fixture()
        metadata = icons.load_source(self.source)
        entry = next(v for v in metadata["variants"] if v["id"] == "en-US")
        data = (self.source / entry["image"]).read_bytes()
        mac = mac_artwork(data)
        self.assertEqual(mac.tobytes(), mac_artwork(data).tobytes())
        self.assertEqual(mac.size, (1024, 1024))
        self.assertEqual(mac.mode, "RGBA")
        self.assertEqual(mac.getpixel((0, 0))[3], 0)
        self.assertEqual(mac.getpixel((512, 512))[3], 255)
        self.assertEqual(mac.getpixel((20, 512))[3], 0)
        # Both tiles must be rounded: the inner bounding-box corner exposes the frame.
        self.assertLess(mac.getpixel((154, 154))[0], 100)
        self.assertGreater(mac.getpixel((154, 512))[0], 240)
        ipad = ipad_artwork(data)
        self.assertEqual(ipad.mode, "RGB")
        self.assertEqual(ipad.size, (1024, 1024))
        self.assertEqual(ipad.tobytes(), ipad_artwork(data).tobytes())
        self.assertGreater(ipad.getpixel((64, 512))[0], 240)
        self.assertLess(ipad.getpixel((63, 512))[0], 100)
        self.assertLess(ipad.getpixel((64, 64))[0], 100)
        self.assertGreater(ipad.getpixel((200, 200))[0], 240)

    def test_outputs_cannot_write_into_tracked_source_tree(self):
        with self.assertRaises(ValueError):
            icons.output_path(ROOT / "scripts/AppIcon.png")

    def test_control_selection_excludes_other_titles_and_rejects_ambiguity(self):
        path = self.root / "ncandidates.tsv"
        rows = ["other.nca\t0000000000002000\tControl\t0\t\t\t9999",
                "matching.nca\t0000000000001800\tControl\t0\t\t\t20"]
        path.write_text("\n".join(rows))
        self.assertEqual(icons.pick_control(path, "0000000000001000"), "matching.nca")
        self.assertEqual(icons.pick_control(path, "0000000000003000"), "")
        path.write_text("\n".join(rows + ["duplicate.nca\t0000000000001000\tControl\t0\t\t\t10"]))
        with self.assertRaises(ValueError):
            icons.pick_control(path, "0000000000001000")

    def test_fresh_xci_and_nsp_icon_supply_chain_needs_no_preexisting_work_data(self):
        import build_helpers
        from icon_composer import write_documents
        # Simulate only container decryption; all normalization and composition is real.
        keys = self.root / "synthetic.keys"
        keys.write_text("not real keys")
        picture = self.picture(self.base, "AmericanEnglish", "red").read_bytes()
        def hactool(tool, keyfile, *args, **kwargs):
            target = next((str(a) for a in args if str(a).startswith(("--securedir=", "--pfs0dir="))), None)
            if target:
                folder = Path(target.split("=", 1)[1]); folder.mkdir()
                for name in ("program", "control", "other-control"):
                    (folder / (name + ".nca")).write_bytes(b"synthetic NCA")
            target = next((str(a) for a in args if str(a).startswith("--romfsdir=")), None)
            if target:
                folder = Path(target.split("=", 1)[1]); folder.mkdir()
                (folder / "icon_AmericanEnglish.dat").write_bytes(picture)
            return 0, "synthetic header"
        def info(text, path):
            name = Path(path).stem
            return {"content_type": "Program" if name == "program" else "Control",
                    "title_id": "0000000000002000" if name == "other-control" else "0000000000001000",
                    "rights_id": "", "path": path}
        for kind in ("xci", "nsp"):
            args = SimpleNamespace(prod_keys=str(keys), title_keys=None, title_id=None,
                npdm=str(self.root / "missing.npdm"), output=self.root / kind,
                xci="own.xci" if kind == "xci" else None, nsp="own.nsp" if kind == "nsp" else None,
                update_nsp=None, base_dir=None, update_dir=None, hactool="synthetic-tool")
            with patch.object(icons, "silent_hactool", side_effect=hactool), \
                    patch.object(build_helpers, "parse_nca_info", side_effect=info):
                manifest = icons.extract(args)
            self.assertEqual([v["id"] for v in manifest["variants"]], ["en-US"])
            self.assertEqual(manifest["title_id"], "0000000000001000")
            documents = write_documents(manifest, args.output, self.root / (kind + "-documents"))
            for package in documents.values():
                with Image.open(package / "Assets/artwork.png") as image:
                    self.assertEqual(image.size, (1024, 1024))
                    self.assertEqual(image.getchannel("A").getextrema(), (255, 255))

    def test_ios_catalog_and_settings_include_all_variants(self):
        self.fixture()
        bundle = self.root / "BDSP.app"
        bundle.mkdir()
        (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "synthetic.icons"}))
        output = self.root / "ios"

        def actool(command, **kwargs):
            partial = Path(command[command.index("--output-partial-info-plist") + 1])
            partial.write_bytes(plistlib.dumps({"CFBundleIcons": {"CFBundlePrimaryIcon": {"CFBundleIconName": "test"}}}))
            import subprocess
            return subprocess.CompletedProcess(command, 0, "")

        with patch.object(icons.subprocess, "run", side_effect=actool):
            icons.build_ios(self.source, output, bundle, APP.parent / "ios/app/Settings.bundle")
        # Equal images share one compiled app icon, but remain independently selectable by language.
        self.assertEqual(len(list((output / "Documents").glob("*.icon"))), 2)
        for path in (output / "Documents").glob("*.icon"):
            with Image.open(path / "Assets/artwork.png") as image:
                self.assertEqual(image.size, (1024, 1024))
                self.assertEqual(image.getchannel("A").getextrema(), (255, 255))
            definition = json.loads((path / "icon.json").read_text())
            self.assertEqual(definition["groups"][0]["layers"][0]["position"],
                             {"scale": 1, "translation-in-points": [0, 0]})
        settings = plistlib.loads((bundle / "Settings.bundle/Root.plist").read_bytes())
        icon_setting = next(v for v in settings["PreferenceSpecifiers"] if v.get("Key") == "bdsp_app_icon")
        self.assertEqual(icon_setting["DefaultValue"], "default")
        self.assertEqual(set(icon_setting["Values"]), {"default", "de", "en-US", "ja"})
        self.assertIn("empfohlen", (bundle / "Settings.bundle/de.lproj/Root.strings").read_text())
        self.assertIn("recommended", (bundle / "Settings.bundle/ja.lproj/Root.strings").read_text())
        info = plistlib.loads((bundle / "Info.plist").read_bytes())
        self.assertEqual(info["CFBundleIdentifier"], "synthetic.icons")
        self.assertIn("CFBundleIcons", info)


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("clang"), "Apple compiler required")
class AppleIconTests(unittest.TestCase):
    def test_native_locale_resolver(self):
        work = ROOT / "work/tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="icon-native-", dir=work) as directory:
            binary = str(Path(directory) / "icon_native")
            result = subprocess.run(["/usr/bin/clang", "-fobjc-arc", "-framework", "Foundation",
                                     str(ROOT / "scripts/tests/icon_apple_harness.m"), "-o", binary], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([binary], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
