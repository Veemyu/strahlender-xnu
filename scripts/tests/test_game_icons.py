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

    def test_mod_icons_and_names_take_priority_over_base_variants(self):
        base = self.fixture()
        mod = self.root / "Luminescent"
        control = mod / "ROMFS/control"
        control.mkdir(parents=True)
        self.picture(control, "German", "purple")
        self.nacp(control, {"de": "Platin Mod"})
        Image.new("RGB", (256, 256), "yellow").save(mod / "icon.png")
        result = icons.prepared(self.source, self.root / "mod-icons", mod, "Luminescent")
        variants = {item["id"]: item for item in result["variants"]}
        originals = {item["id"]: item for item in base["variants"]}
        self.assertNotEqual(variants["de"]["sha256"], originals["de"]["sha256"])
        self.assertNotEqual(variants["en-US"]["sha256"], originals["en-US"]["sha256"])
        self.assertEqual(result["titles"]["de"]["name"], "Platin Mod")
        self.assertEqual(result["titles"]["en-US"]["name"], "Luminescent")
        self.assertTrue((self.root / "mod-icons" / variants["de"]["image"]).is_file())

    def test_mod_icon_is_used_when_the_dump_has_no_control_icon(self):
        mod = self.root / "mod"
        mod.mkdir()
        Image.new("RGB", (256, 256), "gray").save(mod / "icon.png")
        result = icons.prepared(self.root / "missing-source", self.root / "icons", mod, "Example Mod")
        self.assertTrue(result["variants"])
        self.assertEqual(result["titles"]["de"]["name"], "Example Mod")

    def test_mod_without_artwork_has_a_distinct_offline_icon_in_every_base_language(self):
        original = self.fixture()
        mod = self.root / "Mod Without Artwork"
        mod.mkdir()
        result = icons.prepared(self.source, self.root / "mod-fallback", mod, mod.name)
        before = {variant["id"]: variant["sha256"] for variant in original["variants"]}
        self.assertEqual(set(before), {variant["id"] for variant in result["variants"]})
        self.assertTrue(result["mod_icon_fallback"])
        for variant in result["variants"]:
            self.assertNotEqual(before[variant["id"]], variant["sha256"])
        self.assertEqual(icons.load_source(self.source), original)

    def test_embedded_mod_logos_keep_locales_and_yield_to_explicit_icons(self):
        self.fixture()
        mod = self.root / "Embedded Mod"
        logos = mod / "romfs/Data/StreamingAssets/AssetAssistant/Dpr/movie/dia/logo"
        logos.mkdir(parents=True)
        for language in ("en", "ge"):
            (logos / ("logo_dia_" + language)).write_bytes(language.encode())
        self.picture(mod, "German", "purple")

        def load(path):
            image = Image.new("RGBA", (640, 240), "green" if str(path).endswith("_en") else "blue")
            texture = SimpleNamespace(m_Name=Path(path).name, image=image)
            return SimpleNamespace(objects=[SimpleNamespace(type=SimpleNamespace(name="Texture2D"), read=lambda: texture)])

        with patch.dict(sys.modules, {"UnityPy": SimpleNamespace(load=load)}):
            result = icons.prepared(self.source, self.root / "embedded-icons", mod, "Embedded Mod")
        variants = {item["id"]: item for item in result["variants"]}
        self.assertEqual(set(variants), set(icons.NACP_LANGUAGES))
        self.assertEqual(variants["en-US"]["sha256"], variants["pt-BR"]["sha256"])
        self.assertNotEqual(variants["en-US"]["sha256"], variants["de"]["sha256"])
        self.assertFalse(result["mod_icon_fallback"])
        self.assertEqual(result["mod_artwork"]["en-US"]["texture"], "logo_dia_en")
        output = self.root / "embedded-icons"
        with Image.open(output / variants["en-US"]["image"]) as image:
            self.assertEqual(image.size, (1024, 1024))
            self.assertEqual(image.getpixel((512, 512)), (0, 128, 0))
        with Image.open(output / variants["de"]["image"]) as image:
            with Image.open(mod / "icon_German.dat") as supplied:
                self.assertEqual(image.getpixel((128, 128)), supplied.convert("RGB").getpixel((128, 128)))

    def test_explicit_mod_artwork_does_not_require_the_unity_reader(self):
        self.fixture()
        mod = self.root / "Explicit Mod"
        logos = mod / "romfs/Data/StreamingAssets/AssetAssistant/Dpr/movie/dia/logo"
        logos.mkdir(parents=True)
        (logos / "logo_dia_en").write_bytes(b"not needed")
        Image.new("RGB", (256, 256), "gray").save(mod / "icon.png")
        with patch.dict(sys.modules, {"UnityPy": None}):
            result = icons.prepared(self.source, self.root / "explicit-icons", mod, mod.name)
        self.assertFalse(result["mod_icon_fallback"])
        self.assertNotIn("mod_artwork", result)

    def nacp(self, directory, titles, version="1.0.0"):
        data = bytearray(0x4000)
        for locale, name in titles.items():
            offset = icons.NACP_LANGUAGES.index(locale) * 0x300
            encoded = name.encode("utf-8")
            data[offset:offset + len(encoded)] = encoded
        data[0x3060:0x3060 + len(version)] = version.encode("utf-8")
        (directory / "control.nacp").write_bytes(data)

    def test_all_original_titles_survive_ingest_and_apple_bundle_generation(self):
        titles = {locale: 'Original "' + locale + '" 日本語' for locale in icons.NACP_LANGUAGES}
        self.nacp(self.base, titles)
        self.nacp(self.update, {"de": "Aktualisierter Titel"}, "1.3.0")
        self.picture(self.base, "AmericanEnglish", "red")
        self.picture(self.base, "German", "green")
        manifests = []
        for language in ("de-DE", "ja-JP", "pt-BR"):
            with patch.dict(os.environ, BDSP_LANG=language, LANG=language):
                manifest = icons.ingest(self.base, self.update, self.source)
            manifests.append(manifest)
        self.assertEqual(manifests[0], manifests[1])
        self.assertEqual(manifests[1], manifests[2])
        self.assertEqual(set(manifest["titles"]), set(icons.NACP_LANGUAGES))
        self.assertEqual(manifest["titles"]["de"]["name"], "Aktualisierter Titel")
        self.assertEqual(manifest["display_version"], "1.3.0")
        self.assertEqual(len(manifest["variants"]), 2)
        for resources in (self.root / "Mac.app/Contents/Resources", self.root / "iOS.app"):
            icons.write_bundle_names(manifest, resources)
            names = list(resources.glob("*.lproj/InfoPlist.strings"))
            self.assertEqual(len(names), 20)
            for locale, title in manifest["titles"].items():
                content = (resources / (locale + ".lproj/InfoPlist.strings")).read_text()
                value = content.partition(" = ")[2].removesuffix(";\n")
                self.assertEqual(json.loads(value), title["name"])

    def test_bundle_titles_preserve_other_localized_strings_and_regional_variants(self):
        resources = self.root / "Resources"
        directory = resources / "es.lproj"
        directory.mkdir(parents=True)
        path = directory / "InfoPlist.strings"
        path.write_text('"CFBundleTypeName" = "Partida";\n')
        manifest = {"titles": {"es-419": {"name": "América"}, "es-ES": {"name": "España"}}}
        for _ in range(2):
            icons.write_bundle_names(manifest, resources)
        self.assertIn('"CFBundleTypeName" = "Partida";', path.read_text())
        self.assertEqual(path.read_text().count('"CFBundleDisplayName"'), 1)
        self.assertIn("España", path.read_text())
        self.assertIn("América", (resources / "es-419.lproj/InfoPlist.strings").read_text())

    def test_truncated_nacp_is_rejected_and_missing_metadata_stays_empty(self):
        self.assertEqual(icons.read_nacp(self.base), ({}, ""))
        (self.base / "control.nacp").write_bytes(bytes(0x3000))
        with self.assertRaisesRegex(ValueError, "Invalid control.nacp"):
            icons.read_nacp(self.base)

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

    def test_missing_icons_fail_instead_of_using_a_placeholder(self):
        self.fixture()
        icons.ingest(None, None, self.source)
        for source in (self.source, self.root / "missing-source"):
            with self.assertRaisesRegex(ValueError, "No original game icon"):
                icons.build_linux(source, self.root / "linux", self.root / "game")
        self.assertEqual(icons.load_source(self.root / "missing-source")["variants"], [])

    def test_mac_icns_and_incremental_fingerprint(self):
        self.nacp(self.base, {"de": "Diamant", "ja": "ダイヤモンド"})
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
        self.assertTrue((output / "ja.lproj/InfoPlist.strings").is_file())
        self.assertTrue((output / "de.lproj/InfoPlist.strings").is_file())
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
        self.nacp(self.base, {"de": "Diamant", "ja": "ダイヤモンド"})
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
        self.assertTrue((bundle / "ja.lproj/InfoPlist.strings").is_file())
        self.assertTrue((bundle / "de.lproj/InfoPlist.strings").is_file())


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
