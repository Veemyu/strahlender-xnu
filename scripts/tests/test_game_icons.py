"""Original-icon pipeline tests using only synthetic pictures under work/."""
import importlib.util
import hashlib
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


def ingest(base, update, destination, title_id=""):
    """Test fixture: builds an icon source like the extract stage does (Rust: installer/extract/src/icons.rs)."""
    destination = icons.output_path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    variants = {}
    titles = {}
    version = ""
    for directory in (base, update):
        if not directory:
            continue
        localized_titles, display_version = icons.read_nacp(directory)
        titles.update(localized_titles)
        version = display_version or version
        for name, (locale, label) in icons.LANGUAGES.items():
            path = Path(directory) / ("icon_" + name + ".dat")
            if not path.is_file():
                continue
            try:
                data = icons.normalize(path.read_bytes())
            except (OSError, ValueError, SyntaxError) as error:
                print("Notice: invalid icon variant %s (%s)" % (locale, type(error).__name__), file=sys.stderr)
                continue
            digest = hashlib.sha256(data).hexdigest()
            image = digest + ".png"
            (destination / image).write_bytes(data)
            variants[locale] = {"id": locale, "label": label, "image": image,
                                "sha256": digest, "icon": "BDSP_" + digest[:24]}
    entries = sorted(variants.values(), key=lambda v: v["id"])
    manifest = {"schema": 1, "title_id": title_id, "default": icons.default_variant(entries), "variants": entries,
                "titles": titles, "display_version": version}
    icons.write_json(destination / "icons.json", manifest)
    print("Original icons: %d language variants" % len(entries))
    return manifest


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
        return ingest(self.base, self.update, self.source, "0000000000000000")

    def test_windows_ico_and_qt_variants_reuse_original_pipeline(self):
        source = self.fixture()
        output = self.root / "windows"
        result = icons.build_windows(self.source, output)
        self.assertEqual(source, result)
        self.assertEqual((output / "app.rc").read_text(), '1 ICON "app.ico"\n')
        with Image.open(output / "app.ico") as image:
            self.assertEqual(image.format, "ICO")
            self.assertEqual(image.ico.sizes(), {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)})
        for variant in source["variants"]:
            self.assertEqual((output / variant["image"]).read_bytes(),
                             (self.source / variant["image"]).read_bytes())

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

    def test_embedded_mod_logos_can_be_skipped_without_the_unity_reader(self):
        self.fixture()
        mod = self.root / "Embedded Without Reader"
        logos = mod / "romfs/Data/StreamingAssets/AssetAssistant/Dpr/movie/dia/logo"
        logos.mkdir(parents=True)
        (logos / "logo_dia_en").write_bytes(b"unity bundle")
        with patch.dict(sys.modules, {"UnityPy": None}):
            with self.assertRaisesRegex(ValueError, "UnityPy"):
                icons.check_mod_artwork(mod)
            result = icons.prepared(self.source, self.root / "badge-icons", mod, mod.name, embedded_logos=False)
        self.assertTrue(result["mod_icon_fallback"])
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
                manifest = ingest(self.base, self.update, self.source)
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
                content = (resources / (locale + ".lproj/InfoPlist.strings")).read_text(encoding="utf-8")
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
        self.assertIn('"CFBundleTypeName" = "Partida";', path.read_text(encoding="utf-8"))
        self.assertEqual(path.read_text(encoding="utf-8").count('"CFBundleDisplayName"'), 1)
        self.assertIn("España", path.read_text(encoding="utf-8"))
        self.assertIn("América", (resources / "es-419.lproj/InfoPlist.strings").read_text(encoding="utf-8"))

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
        ingest(None, None, self.source)
        for source in (self.source, self.root / "missing-source"):
            with self.assertRaisesRegex(ValueError, "No original game icon"):
                icons.build_linux(source, self.root / "linux", self.root / "game")
        self.assertEqual(icons.load_source(self.root / "missing-source")["variants"], [])

    @unittest.skipIf(sys.platform == "win32", "Runs bash scripts / POSIX tools; covered on Linux and macOS")
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
        with patch.object(icon_composer, "compile_icons", side_effect=compile_icons), \
                patch.object(icon_composer, "use_classic", return_value=False):
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
        ingest(self.base, self.update, self.source)
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

    def tools(self, version, calls=None):
        """Fake xcrun actool and iconutil; `version` None means actool cannot be read."""
        self.calls = calls if calls is not None else []
        self.iconsets = []
        plist = plistlib.dumps({"com.apple.actool.version": {"short-bundle-version": version or "x"}}).decode()

        def run(command, **kwargs):
            command = [str(part) for part in command]
            self.calls.append(command)
            if command[1:3] == ["actool", "--version"]:
                return subprocess.CompletedProcess(command, 0 if version else 1, plist if version else "no actool", "")
            if command[:2] == ["xcrun", "actool"]:
                option = lambda name: command[command.index(name) + 1]
                output, platform, primary = Path(option("--compile")), option("--platform"), option("--app-icon")
                if version and version.split(".")[0].isdigit() and int(version.split(".")[0]) >= 26:
                    (output / "Assets.car").write_bytes(b"synthetic archive")
                    if platform == "macosx":
                        (output / (primary + ".icns")).write_bytes(b"icns")
                    Path(option("--output-partial-info-plist")).write_bytes(plistlib.dumps(
                        {"CFBundleIconName": primary} if platform == "macosx" else
                        {"CFBundleIcons": {"CFBundlePrimaryIcon": {"CFBundleIconName": primary}}}))
                return subprocess.CompletedProcess(command, 0, "")
            if command[0] == "iconutil":
                iconset = Path(command[-1])
                sizes = {}
                for file in sorted(iconset.iterdir()):
                    with Image.open(file) as image:
                        sizes[file.name] = image.size
                self.iconsets.append(sizes)
                Path(command[command.index("--output") + 1]).write_bytes(b"icns")
                return subprocess.CompletedProcess(command, 0, "")
            raise AssertionError(command)
        return run

    def mac_app(self, version, legacy=""):
        self.fixture()
        resources = self.root / ("mac-%s-%s" % (version or "unreadable", legacy or "auto")) / "Contents/Resources"
        resources.mkdir(parents=True)
        (resources.parent / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIconFile": "BDSP"}))
        with patch.dict(os.environ, {"BDSP_LEGACY_ICONS": legacy}), patch.object(icons.subprocess, "run", side_effect=self.tools(version)), \
                patch("builtins.print"):
            icons.build_mac(self.source, resources)
        return resources, plistlib.loads((resources.parent / "Info.plist").read_bytes())

    def test_mac_icon_path_follows_the_actool_version(self):
        for version, legacy, classic in (("15.4", "", True), ("16.2", "", True), (None, "", True), ("26.0", "", False),
                                         ("27.1", "", False), ("27.1", "1", True)):
            with self.subTest(version=version, legacy=legacy):
                resources, info = self.mac_app(version, legacy)
                compiled = [c for c in self.calls if c[:3] == ["xcrun", "actool", "--compile"]]
                self.assertEqual(bool(self.iconsets), classic)
                self.assertEqual(bool(compiled), not classic)
                self.assertEqual((resources / "Assets.car").exists(), not classic)
                self.assertEqual("CFBundleIconName" in info, not classic)
                self.assertEqual(info["CFBundleIconFile"], "BDSP")
                self.assertTrue((resources / "BDSP.icns").is_file())
                manifest = json.loads((resources / "AppIcons/icons.json").read_text())
                self.assertEqual(manifest["mac_style"], "classic-v1" if classic else "liquid-glass-full-bleed-v1")
                for variant in manifest["variants"]:
                    self.assertTrue((resources / "AppIcons" / variant["mac_image"]).is_file())
                self.assertFalse(list((resources / "AppIcons").glob("*.icon")))
                if classic:
                    # 3 languages, but red and red share one artwork
                    self.assertEqual(len(self.iconsets), 2)
                    self.assertEqual(self.iconsets[0]["icon_16x16.png"], (16, 16))
                    self.assertEqual(self.iconsets[0]["icon_512x512@2x.png"], (1024, 1024))
                    self.assertEqual(len(self.iconsets[0]), 10)

    def test_classic_mac_tile_keeps_the_system_margin_and_rounded_corners(self):
        self.fixture()
        data = (self.source / icons.load_source(self.source)["variants"][0]["image"]).read_bytes()
        import icon_composer
        sizes = {}

        def iconutil(command, **kwargs):
            iconset = Path(command[-1])
            for name in ("icon_512x512@2x.png", "icon_32x32.png"):
                with Image.open(iconset / name) as image:
                    sizes[name] = (image.size, image.getpixel((0, 0))[3], image.getpixel((image.width // 2, image.height // 2))[3])
            Path(command[command.index("--output") + 1]).write_bytes(b"icns")
            return subprocess.CompletedProcess(command, 0, "")
        with patch.object(icons.subprocess, "run", side_effect=iconutil):
            icon_composer.classic_icns(data, self.root / "tile.icns")
        self.assertEqual(sizes["icon_512x512@2x.png"], ((1024, 1024), 0, 255))
        self.assertEqual(sizes["icon_32x32.png"], ((32, 32), 0, 255))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("iconutil"), "iconutil required")
    def test_classic_icns_is_accepted_by_the_real_iconutil(self):
        import icon_composer
        self.fixture()
        data = (self.source / icons.load_source(self.source)["variants"][0]["image"]).read_bytes()
        icon_composer.classic_icns(data, self.root / "real.icns")
        with Image.open(self.root / "real.icns") as image:
            self.assertEqual(image.format, "ICNS")
            self.assertEqual(image.size, (1024, 1024))
            self.assertEqual(image.convert("RGBA").getpixel((0, 0))[3], 0)

    def test_classic_ios_icons_are_loose_files_without_actool(self):
        self.fixture()
        for version, legacy in (("16.2", ""), (None, ""), ("27.1", "1")):
            with self.subTest(version=version, legacy=legacy):
                bundle = self.root / ("classic-ios-%s-%s/BDSP.app" % (version, legacy or "auto"))
                bundle.mkdir(parents=True)
                (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "synthetic.icons"}))
                (bundle / "Assets.car").write_bytes(b"stale")
                (bundle / "BDSP_old60x60@2x.png").write_bytes(b"stale")
                with patch.dict(os.environ, {"BDSP_LEGACY_ICONS": legacy}), \
                        patch.object(icons.subprocess, "run", side_effect=self.tools(version)), patch("builtins.print"):
                    icons.build_ios(str(self.source), str(self.root / "classic-ios-out"), str(bundle),
                                    str(APP.parent / "ios/app/Settings.bundle"))
                self.assertFalse([c for c in self.calls if "--compile" in c], "no actool run in the classic path")
                self.assertFalse((bundle / "Assets.car").exists())
                self.assertFalse((bundle / "BDSP_old60x60@2x.png").exists())
                manifest = json.loads((bundle / "AppIcons/icons.json").read_text())
                names = {v["icon"] for v in manifest["variants"]}
                self.assertEqual(len(names), 2)   # red and red share one artwork
                for name in names:
                    for suffix, pixels in (("60x60@2x", 120), ("60x60@3x", 180), ("76x76~ipad", 76), ("76x76@2x~ipad", 152),
                                           ("83.5x83.5@2x~ipad", 167)):
                        with Image.open(bundle / (name + suffix + ".png")) as image:
                            self.assertEqual((image.size, image.mode), ((pixels, pixels), "RGB"))
                info = plistlib.loads((bundle / "Info.plist").read_bytes())
                primary = manifest["primary_icon"]
                self.assertEqual(info["CFBundleIcons"]["CFBundlePrimaryIcon"]["CFBundleIconFiles"], [primary + "60x60"])
                self.assertEqual(info["CFBundleIcons~ipad"]["CFBundlePrimaryIcon"]["CFBundleIconFiles"],
                                 [primary + "60x60", primary + "76x76", primary + "83.5x83.5"])
                for key, files in (("CFBundleIcons", ["60x60"]), ("CFBundleIcons~ipad", ["60x60", "76x76", "83.5x83.5"])):
                    alternates = info[key]["CFBundleAlternateIcons"]
                    self.assertEqual(set(alternates), names - {primary})
                    for name, entry in alternates.items():
                        self.assertEqual(entry["CFBundleIconFiles"], [name + f for f in files])
                self.assertNotIn("CFBundleIconName", str(info))
                self.assertEqual(manifest["ios_style"], "classic-v1")

    def test_actool_without_icon_composer_support_is_named(self):
        # Xcode 16 actool skips .icon documents, exits 0 and writes only an empty partial Info.plist.
        import icon_composer
        document = self.root / "docs/BDSP_test.icon"
        document.mkdir(parents=True)

        def actool(command, **kwargs):
            if "--version" in command:
                version = {"com.apple.actool.version": {"short-bundle-version": "16.2"}}
                return subprocess.CompletedProcess(command, 0, plistlib.dumps(version).decode(), "")
            Path(command[command.index("--output-partial-info-plist") + 1]).write_bytes(plistlib.dumps({}))
            return subprocess.CompletedProcess(command, 0, "")

        with patch.object(icon_composer.subprocess, "run", side_effect=actool):
            with self.assertRaises(ValueError) as raised:
                icon_composer.compile_icons({"BDSP_test": document}, "BDSP_test", self.root / "out", "macosx")
        self.assertIn("BDSP_test.icns", str(raised.exception))
        self.assertIn("actool 16.2", str(raised.exception))
        self.assertIn("Xcode 26 or newer", str(raised.exception))

    def test_outputs_cannot_write_into_tracked_source_tree(self):
        with self.assertRaises(ValueError):
            icons.output_path(ROOT / "scripts/AppIcon.png")

    def test_ios_catalog_and_settings_include_all_variants(self):
        self.nacp(self.base, {"de": "Diamant", "ja": "ダイヤモンド"})
        self.fixture()
        bundle = self.root / "BDSP.app"
        bundle.mkdir()
        (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "synthetic.icons"}))
        output = self.root / "ios"

        with patch.dict(os.environ, {"BDSP_LEGACY_ICONS": ""}), patch.object(icons.subprocess, "run", side_effect=self.tools("26.0")):
            # exactly the arguments the command line passes: all four are plain strings, not Path objects
            icons.build_ios(str(self.source), str(output), str(bundle), str(APP.parent / "ios/app/Settings.bundle"))
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
        self.assertIn("empfohlen", (bundle / "Settings.bundle/de.lproj/Root.strings").read_text(encoding="utf-8"))
        self.assertIn("recommended", (bundle / "Settings.bundle/ja.lproj/Root.strings").read_text(encoding="utf-8"))
        # Every locale folder must carry every Settings text: iOS uses the folder of the device language without a per-key
        # fallback to English, so a folder that only holds the icon keys turns the other rows into raw keys (DATA_GROUP ...).
        import re
        keys = {p.parent.name: set(re.findall(r'^"([A-Za-z0-9_-]+)"\s*=', p.read_text(encoding="utf-8"), re.M))
                for p in (bundle / "Settings.bundle").glob("*.lproj/Root.strings")}
        self.assertIn("ja.lproj", keys)
        self.assertIn("DATA_GROUP", keys["ja.lproj"])
        self.assertIn("FPS_TITLE", keys["en-US.lproj"])
        for locale, found in keys.items():
            self.assertEqual(found, keys["en.lproj"], locale)
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
