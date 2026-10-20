"""System-package preflight tests; no package installation, network, or game data."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/recomp/linux/deps.sh"


class LinuxDependenciesTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work/tests").mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="linux-deps-", dir=ROOT / "work/tests")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tools = self.root / "bin"
        self.tools.mkdir()
        self.tool("pkg-config", '''#!/bin/bash
case "$1" in
  --exists)
    case " ${AVAILABLE_MODULES:-} " in *" $2 "*) exit 0;; *) exit 1;; esac;;
  --cflags) echo -I/system-development-prefix/include;;
  --libs) echo -lvulkan -lSDL3 -lshaderc_shared;;
  *) exit 1;;
esac
''')
        self.tool("cxx-check", '#!/bin/bash\nexit "${FAKE_VMA_FAIL:-0}"\n')
        self.env = dict(os.environ, PATH=str(self.tools) + os.pathsep + os.environ["PATH"],
                        CXX=str(self.tools / "cxx-check"), BDSP_NO_MOVIE="",
                        AVAILABLE_MODULES="vulkan sdl3 shaderc Qt6Widgets libavcodec libavformat libavutil")

    def tool(self, name, source):
        path = self.tools / name
        path.write_text(source)
        path.chmod(0o755)

    def run_check(self, command, **changes):
        return subprocess.run(["/bin/bash", "-c", 'source "$1"; ' + command, "check", str(HELPER)],
                              env=dict(self.env, **changes), capture_output=True, text=True)

    def test_installed_modules_supply_cflags_and_link_flags(self):
        result = self.run_check("linux_require_runtime && linux_require_qt && linux_vulkan_cflags && linux_vulkan_libs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/system-development-prefix/include", result.stdout)
        self.assertIn("-lshaderc_shared", result.stdout)
        self.assertNotIn("include-vk", result.stdout)

    def test_missing_sdl_development_package_is_an_actionable_failure(self):
        result = self.run_check("linux_require_runtime", AVAILABLE_MODULES="vulkan shaderc")
        self.assertEqual(result.returncode, 3)
        self.assertIn("sdl3", result.stderr)
        self.assertIn("docs/BUILD.md", result.stderr)

    def test_vma_header_check_fails_without_downloading_a_replacement(self):
        result = self.run_check("linux_require_runtime", FAKE_VMA_FAIL="1")
        self.assertEqual(result.returncode, 3)
        self.assertIn("VulkanMemoryAllocator-devel", result.stderr)

    def test_movie_support_requires_matching_ffmpeg_devel_modules(self):
        modules = "vulkan sdl3 shaderc Qt6Widgets"
        result = self.run_check("linux_require_runtime", AVAILABLE_MODULES=modules)
        self.assertEqual(result.returncode, 3)
        self.assertIn("libavcodec", result.stderr)
        result = self.run_check("linux_require_runtime", AVAILABLE_MODULES=modules, BDSP_NO_MOVIE="1")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_qt_and_shaderc_modules_are_checked_independently(self):
        result = self.run_check("linux_require_qt", AVAILABLE_MODULES="vulkan sdl3 shaderc")
        self.assertEqual(result.returncode, 3)
        result = self.run_check("linux_shaderc_module", AVAILABLE_MODULES="shaderc shaderc_shared")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "shaderc_shared")


if __name__ == "__main__":
    unittest.main()
