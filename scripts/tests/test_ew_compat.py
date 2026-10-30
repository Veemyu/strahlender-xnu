"""The __builtin_elementwise_* fallbacks in rt/cpu.h (for Clang before 16) must agree with the real builtins."""
import shutil
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = r"""
#include "cpu.h"
#include <math.h>
#include <stdio.h>
typedef float vf __attribute__((vector_size(16)));
typedef double vd __attribute__((vector_size(16)));
typedef int8_t vs8 __attribute__((vector_size(16)));
typedef uint8_t vu8 __attribute__((vector_size(16)));
typedef int16_t vs16 __attribute__((vector_size(16)));
typedef uint32_t vu32 __attribute__((vector_size(16)));
typedef int32_t vs32 __attribute__((vector_size(16)));
static void pf(vf v) { for (int i = 0; i < 4; i++) printf("%a ", v[i]); puts(""); }
static void pd(vd v) { for (int i = 0; i < 2; i++) printf("%a ", v[i]); puts(""); }
static void pi(const int64_t *p, int n) { for (int i = 0; i < n; i++) printf("%lld ", (long long)p[i]); puts(""); }
int main(void) {
    vf a = {-2.5f, 0.5f, 1.5f, -0.0f}, b = {4.0f, -9.0f, 2.25f, 16.0f}, c = {0.5f, 1.0f, -1.0f, 3.0f};
    vd d = {-2.5, 6.25};
    pf(__builtin_elementwise_abs(a)); pf(__builtin_elementwise_sqrt(__builtin_elementwise_abs(b)));
    pf(__builtin_elementwise_fma(a, b, c)); pf(__builtin_elementwise_rint(a)); pf(__builtin_elementwise_ceil(a));
    pf(__builtin_elementwise_floor(a)); pf(__builtin_elementwise_trunc(a)); pf(__builtin_elementwise_round(a));
    pf(__builtin_elementwise_max(a, b)); pf(__builtin_elementwise_min(a, b));
    pd(__builtin_elementwise_sqrt(__builtin_elementwise_abs(d))); pd(__builtin_elementwise_round(d));
    vs8 s = {127, -128, 100, -100, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}, t = {1, -1, 100, -100, 127, -128, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1};
    vu8 u = {255, 0, 200, 100, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}, w = {1, 1, 100, 200, 255, 255, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1};
    vs8 r;
    int64_t out[16];
    r = __builtin_elementwise_add_sat(s, t); for (int i = 0; i < 16; i++) out[i] = r[i]; pi(out, 16);
    r = __builtin_elementwise_sub_sat(s, t); for (int i = 0; i < 16; i++) out[i] = r[i]; pi(out, 16);
    vu8 q = __builtin_elementwise_add_sat(u, w); for (int i = 0; i < 16; i++) out[i] = q[i]; pi(out, 16);
    q = __builtin_elementwise_sub_sat(u, w); for (int i = 0; i < 16; i++) out[i] = q[i]; pi(out, 16);
    q = __builtin_elementwise_max(u, w); for (int i = 0; i < 16; i++) out[i] = q[i]; pi(out, 16);
    vs32 x = {2147483647, -2147483647 - 1, -5, 5}, y = {1, -1, 7, -7};
    vs32 z = __builtin_elementwise_add_sat(x, y); for (int i = 0; i < 4; i++) out[i] = z[i]; pi(out, 4);
    z = __builtin_elementwise_abs(y); for (int i = 0; i < 4; i++) out[i] = z[i]; pi(out, 4);
    vs16 h = {-32768, 32767, -1, 5, 0, 0, 0, 0}, g = {-1, 1, -32768, -5, 0, 0, 0, 0};
    vs16 k = __builtin_elementwise_add_sat(h, g); for (int i = 0; i < 8; i++) out[i] = k[i]; pi(out, 8);
    return 0;
}
"""


@unittest.skipUnless(shutil.which("clang"), "needs Clang")
class ElementwiseCompatTests(unittest.TestCase):
    def run_program(self, directory, extra):
        source = directory / "ew.c"
        source.write_text(PROGRAM)
        binary = directory / ("ew-" + ("fallback" if extra else "builtin"))
        build = subprocess.run(["clang", "-std=c17", "-O1", "-Wno-everything", *extra, "-I", str(ROOT / "scripts/recomp/rt"),
                                "-I", str(ROOT / "scripts/recomp/upstream/runtime"), str(source), "-o", str(binary), *([] if sys.platform == "win32" else ["-lm"])],
                               capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, build.stderr)
        return subprocess.run([str(binary)], capture_output=True, text=True, check=True).stdout

    def test_fallbacks_match_the_compiler_builtins(self):
        probe = subprocess.run(["clang", "-x", "c", "-fsyntax-only", "-"], input="int x[__has_builtin(__builtin_elementwise_sqrt) ? 1 : -1];",
                               capture_output=True, text=True)
        if probe.returncode != 0:
            self.skipTest("this Clang has no __builtin_elementwise_* to compare against")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            real = self.run_program(directory, [])
            fallback = self.run_program(directory, ["-DBDSP_EW_FORCE_FALLBACK"])
            self.assertEqual(fallback, real)
            self.assertIn("0x1p+1", real)


if __name__ == "__main__":
    unittest.main()
