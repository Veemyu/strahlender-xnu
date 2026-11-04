"""install-linux.sh architecture check (x86-64 and aarch64 pass, others stop) and the installed runtime layout."""
from pathlib import Path
import os
import re
import subprocess
import sys
import unittest

from scripts.install import driver

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


class LinuxRuntimeLayoutTests(unittest.TestCase):
    """The installed layout and the runtime's defaults for a start without the launcher (issue 26) name the same entries."""

    def test_runtime_defaults_match_the_launcher_and_the_installed_layout(self):
        launcher = driver._linux_launcher(Path("/data"), Path("/data/mods"), "")
        exported = dict(re.findall(r"export (BDSP_\w+)='([^']*)'", launcher))
        source = (ROOT / "scripts/recomp/runtime/exe_paths.c").read_text(encoding="utf-8")
        defaults = re.findall(r'default_path\("(BDSP_\w+)", dir, "([^"]+)"', source)
        self.assertEqual({name for name, _ in defaults}, {"BDSP_IMG", "BDSP_ROMFS", "BDSP_NPDM"})
        for name, entry in defaults:
            self.assertEqual(Path(exported[name]), Path("/data/app") / entry, name)

    def test_mod_launch_file_matches_what_the_runtime_parses(self):
        self.assertIsNone(driver._linux_mod_launch(Path("/data/mods"), "none", False))
        self.assertEqual(driver._linux_mod_launch(Path("/data/mods"), "Example", True), "Example\n%s\nexefs\n" % Path("/data/mods"))
        self.assertEqual(driver._linux_mod_launch(Path("/data/mods"), "Example", False), "Example\n%s\nromfs\n" % Path("/data/mods"))
        with self.assertRaises(ValueError):
            driver._linux_mod_launch(Path("/data/mods"), "bad\nname", True)
        source = (ROOT / "scripts/recomp/runtime/exe_paths.c").read_text(encoding="utf-8")
        self.assertIn('"%s/mod.txt"', source)

    def test_the_runtime_applies_the_defaults_before_it_reads_the_paths(self):
        source = (ROOT / "scripts/recomp/runtime/main.c").read_text(encoding="utf-8")
        self.assertLess(source.index("bdsp_exe_defaults();"), source.index('getenv("BDSP_IMG")'))


@unittest.skipIf(sys.platform == "win32", "Runs bash scripts / POSIX tools; covered on Linux and macOS")
class MissingGnuTimeTests(unittest.TestCase):
    def test_commands_run_untimed_when_gnu_time_is_missing(self):
        script = ('source scripts/recomp/linux/local/common.sh; GNU_TIME=""; '
                  'gtime -f "%e" -o "$1" sh -c "echo ran"; echo "rc=$?"; cat "$1"')
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(["/bin/bash", "-c", script, "x", str(Path(folder) / "t")], cwd=ROOT,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.stdout.split(), ["ran", "rc=0", "0", "0", "0", "0"], result.stderr)


@unittest.skipIf(sys.platform == "win32", "Runs bash scripts / POSIX tools; covered on Linux and macOS")
class CompileStampTests(unittest.TestCase):
    def test_the_compile_stamp_input_is_unchanged_without_the_level_switch(self):
        source = (ROOT / "scripts/recomp/linux/local/compile.sh").read_text(encoding="utf-8")
        line = next(item for item in source.splitlines() if item.startswith("STAMP=") and "echo" in item)
        expression = re.search(r'echo (".*?")', line).group(1)

        def stamp_input(**environment):
            result = subprocess.run(["/bin/bash", "-c", "FLAGS='-x -y'; THRESH_O0=300000; echo " + expression],
                                    capture_output=True, text=True, timeout=30,
                                    env={"PATH": os.environ.get("PATH", ""), **environment})
            return result.stdout.rstrip("\n")

        self.assertEqual(stamp_input(), "-x -y 300000")
        self.assertEqual(stamp_input(BDSP_COMPILE_OPT="-O0"), "-x -y 300000 -O0")
