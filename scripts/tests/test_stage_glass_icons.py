"""Liquid Glass staging checks; only synthetic artwork is used."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/recomp/app"))

try:
    from PIL import Image, ImageChops
    import stage_glass_icons as glass
except ImportError:
    Image = None


@unittest.skipUnless(Image, "Pillow required")
class GlassStagingTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work/tests").mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="glass-", dir=ROOT / "work/tests")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        stream = io.BytesIO()
        Image.new("RGB", (256, 256), "red").save(stream, "PNG")
        self.data = stream.getvalue()

    def source(self):
        base = self.root / "control"
        base.mkdir()
        (base / "icon_AmericanEnglish.dat").write_bytes(self.data)
        source = self.root / "source"
        glass.game_icons.ingest(base, None, source)
        return source

    def test_foreground_has_rounded_inset_without_baked_lighting(self):
        first = glass.foreground(self.data)
        self.assertEqual(first.tobytes(), glass.foreground(self.data).tobytes())
        self.assertEqual(first.size, (1024, 1024))
        self.assertEqual(first.getpixel((64, 64))[3], 0)
        self.assertEqual(first.getpixel((64, 512)), (255, 0, 0, 255))
        self.assertEqual(first.getpixel((512, 512)), (255, 0, 0, 255))
        self.assertEqual(first.getpixel((63, 512))[3], 0)
        doc = glass.document(self.data)
        group = doc["groups"][0]
        self.assertTrue(group["specular"])
        self.assertEqual(group["blur-material"], 0)
        self.assertFalse(group["translucency"]["enabled"])
        self.assertEqual(len(group["layers"]), 1)

    def test_stage_writes_review_only_and_preserves_existing_output(self):
        source = self.source()
        output = self.root / "staging"

        def fake_render(renderer, bundle, target, appearance, angle):
            Image.new("RGB", (1024, 1024), "red").save(target)

        with patch.object(glass, "render", side_effect=fake_render), \
                patch.object(glass.subprocess, "check_output", return_value='{"test":true}'):
            glass.stage(source, output, renderer=Path(sys.executable))
        self.assertTrue((output / "review.png").is_file())
        self.assertTrue((output / "en-US/review.png").is_file())
        self.assertTrue((output / "en-US.icon/Assets/artwork.png").is_file())
        meta = json.loads((output / "staging.json").read_text())
        self.assertIn("not integrated", meta["status"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            glass.stage(source, output, renderer=Path(sys.executable))
        with self.assertRaisesRegex(ValueError, "work/"):
            glass.stage(source, ROOT / "forbidden-staging")
        with self.assertRaisesRegex(ValueError, "Unavailable"):
            glass.stage(source, self.root / "missing", locales=["ja"])

    def test_full_bleed_source_has_no_border_or_corner_mask(self):
        first = glass.foreground(self.data, layout="full-bleed")
        self.assertEqual(first.size, (1024, 1024))
        self.assertEqual(first.tobytes(), glass.foreground(self.data, layout="full-bleed").tobytes())
        self.assertEqual(first.getchannel("A").getextrema(), (255, 255))
        self.assertEqual(first.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(glass.document(self.data)["groups"][0]["layers"][0]["position"],
                         {"scale": 1, "translation-in-points": [0, 0]})
        with self.assertRaisesRegex(ValueError, "layout"):
            glass.foreground(self.data, layout="unknown")

    @unittest.skipUnless(sys.platform == "darwin", "Apple renderer requires macOS")
    def test_native_renderer_accepts_document_and_changes_lighting(self):
        try:
            renderer = glass.find_renderer()
        except (ValueError, OSError, subprocess.SubprocessError):
            self.skipTest("Icon Composer renderer unavailable")
        bundle = self.root / "Synthetic.icon"
        (bundle / "Assets").mkdir(parents=True)
        glass.foreground(self.data).save(bundle / "Assets/artwork.png")
        glass.game_icons.write_json(bundle / "icon.json", glass.document(self.data))
        a, b = self.root / "a.png", self.root / "b.png"
        glass.render(renderer, bundle, a, "Light", 0)
        glass.render(renderer, bundle, b, "Light", 120)
        with Image.open(a) as first, Image.open(b) as second:
            self.assertIsNotNone(ImageChops.difference(first.convert("RGB"), second.convert("RGB")).getbbox())


if __name__ == "__main__":
    unittest.main()
