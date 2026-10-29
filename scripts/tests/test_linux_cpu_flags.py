"""CPU profiles must optimize local builds without requiring AVX2 everywhere."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(sys.platform == "win32", "Runs bash scripts / POSIX tools; covered on Linux and macOS")
class LinuxCpuFlagsTests(unittest.TestCase):
    def flags(self, arch, profile):
        return subprocess.run(
            ['bash', '-c', 'source scripts/recomp/linux/cpu_flags.sh; bdsp_cpu_flags'],
            cwd=ROOT, env=dict(os.environ, BDSP_CPU_ARCH=arch, BDSP_CPU_TARGET=profile),
            text=True, capture_output=True,
        )

    def test_profiles(self):
        for arch, native, portable in [
            ('x86_64', '-march=native', '-march=x86-64 -mtune=generic'),
            ('aarch64', '-mcpu=native', '-march=armv8-a'),
        ]:
            for profile, expected in [('native', native), ('portable', portable)]:
                with self.subTest(arch=arch, profile=profile):
                    result = self.flags(arch, profile)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)
        self.assertNotEqual(self.flags('x86_64', 'typo').returncode, 0)

    @unittest.skipUnless(shutil.which('clang'), 'requires Clang target feature checks')
    def test_old_and_new_x86_features(self):
        # Sandy Bridge (i7-2600K) supports AVX, but not AVX2. Portable uses neither.
        for cpu, avx, avx2 in [('sandybridge', True, False), ('haswell', True, True),
                               ('x86-64', False, False)]:
            with self.subTest(cpu=cpu):
                macros = subprocess.check_output(
                    ['clang', '--target=x86_64-linux-gnu', f'-march={cpu}',
                     '-dM', '-E', '-x', 'c', '/dev/null'], text=True)
                self.assertEqual('#define __AVX__ 1' in macros, avx)
                self.assertEqual('#define __AVX2__ 1' in macros, avx2)


if __name__ == '__main__':
    unittest.main()
