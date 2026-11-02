"""install-linux.sh architecture check: x86-64 and aarch64 pass (aarch64 with an experimental notice), others stop."""
from pathlib import Path
import os
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "install-linux.sh"
LANGUAGES = ("en", "de", "es", "pt")


@unittest.skipIf(sys.platform == "win32", "Runs bash scripts / POSIX tools; covered on Linux and macOS")
class LinuxInstallArchitectureTests(unittest.TestCase):
    def dry_run(self, arch, lang="en"):
        env = dict(os.environ, BDSP_INSTALL_FAKE_OS="1", BDSP_INSTALL_ARCH=arch, BDSP_LANG=lang)
        return subprocess.run(["/bin/bash", str(SCRIPT), "--dry-run"], env=env, cwd=ROOT, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=120)

    def test_aarch64_passes_the_system_step_with_a_notice_in_every_language(self):
        for lang in LANGUAGES:
            result = self.dry_run("aarch64", lang)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("aarch64", result.stdout)
            self.assertIn("Vulkan 1.3", result.stdout, lang)
            self.assertIn("6/6", result.stdout)
            self.assertNotIn("AVX2", result.stdout)
        self.assertIn("is experimental", self.dry_run("aarch64", "en").stdout)
        self.assertIn("experimentell", self.dry_run("aarch64", "de").stdout)

    def test_x86_64_has_no_experimental_notice(self):
        result = self.dry_run("x86_64")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("experimental", result.stdout)
        self.assertNotIn("Vulkan 1.3", result.stdout)

    def test_other_architectures_stop_with_the_found_name(self):
        result = self.dry_run("riscv64")
        self.assertEqual(result.returncode, 1)
        self.assertIn("riscv64", result.stdout)
        self.assertNotIn("2/6", result.stdout)


if __name__ == "__main__":
    unittest.main()
