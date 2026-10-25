"""The native installer compiler must not require Python image packages."""
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest


class InstallerIconTests(unittest.TestCase):
    def test_packaging_entrypoint_imports_without_site_packages(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "-S", "-c",
             "import runpy,sys; runpy.run_path(sys.argv[1]); "
             "assert 'PIL' not in sys.modules; assert 'icon_artwork' not in sys.modules",
             str(root / "installer/scripts/package_icons_macos.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_vendored_icons_reject_stale_source_and_damaged_catalog(self):
        root = Path(__file__).resolve().parents[2]
        compiler = runpy.run_path(str(root / "installer/scripts/package_icons_macos.py"))
        assets = root / "installer/assets/brand/macos"
        source = root / "installer/assets/brand/icon.svg"
        compiler["verify"](assets, source)
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            edited = temporary / "icon.svg"
            edited.write_text(source.read_text() + "\n<!-- edited -->\n")
            with self.assertRaisesRegex(ValueError, "stale"):
                compiler["verify"](assets, edited)
            damaged = temporary / "macos"
            shutil.copytree(assets, damaged)
            (damaged / "Assets.car").write_bytes(b"damaged catalog")
            with self.assertRaisesRegex(ValueError, "checksum mismatch: Assets.car"):
                compiler["verify"](damaged, source)
