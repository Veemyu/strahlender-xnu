"""The native installer compiler must not require Python image packages."""
from pathlib import Path
import subprocess
import sys
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
