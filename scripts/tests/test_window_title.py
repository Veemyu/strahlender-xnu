"""Runs the C test of the window title helper (runtime/window_title.c) wherever a C compiler exists."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "scripts/recomp/runtime"
COMPILER = next((path for name in (os.environ.get("CC"), "cc", "clang", "gcc") if name for path in [shutil.which(name)] if path), None)


@unittest.skipUnless(COMPILER, "C compiler required")
class WindowTitleTests(unittest.TestCase):
    def test_title_composition_locale_matching_and_titles_json(self):
        work = ROOT / "work/tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="window-title-", dir=work) as directory:
            binary = Path(directory) / ("window_title_test" + (".exe" if sys.platform == "win32" else ""))
            libraries = ["-framework", "CoreFoundation"] if sys.platform == "darwin" else []
            subprocess.run([COMPILER, "-O1", "-Wall", "-Wextra", "-I", str(RUNTIME), str(RUNTIME / "test/window_title_test.c"),
                            str(RUNTIME / "window_title.c"), *libraries, "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
