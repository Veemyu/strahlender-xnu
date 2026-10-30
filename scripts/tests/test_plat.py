"""Host test of the shared platform helpers (scripts/recomp/runtime/plat.c)."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNTIME = Path(__file__).resolve().parents[1] / "recomp/runtime"


@unittest.skipIf(sys.platform == "win32" or not (shutil.which("cc") or shutil.which("clang")),
                 "POSIX host compiler required; the Win32 branch is built by the Windows pipeline")
class PlatTests(unittest.TestCase):
    def test_random_environment_directories_and_atomic_writes(self):
        compiler = shutil.which("cc") or shutil.which("clang")
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "plat_test"
            subprocess.run([compiler, "-std=gnu17", "-Wall", "-Wextra", "-Werror", "-I", str(RUNTIME),
                            str(RUNTIME / "test/plat_test.c"), str(RUNTIME / "plat.c"), "-o", str(binary)], check=True)
            result = subprocess.run([str(binary), temporary], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("plat ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
