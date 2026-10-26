"""Compiler scheduling and invalidation; synthetic files and a recording compiler."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "darwin", "Darwin stat/time frontend")
class CompileQueueTests(unittest.TestCase):
    def test_levels_share_slots_and_headers_and_flags_invalidate_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "O'Brien build with spaces"
            for relative in ("scripts/recomp/build_all.sh", "scripts/recomp/test/compile_chunk.sh"):
                dst = root / relative
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, dst)
            for relative in ("scripts/recomp/rt/cpu.h", "scripts/recomp/upstream/runtime/cpu.h",
                             "scripts/recomp/upstream/runtime/simd.h", "scripts/recomp/upstream/runtime/simd_fp.h"):
                dst = root / relative
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text("/* synthetic header */\n")
            (root / "scripts/recomp/hot_o2.txt").write_text("")
            gen = root / "generated files/main"
            gen.mkdir(parents=True)
            (gen / "large.c").write_text("void f_large(void) {\n}\n" + " " * 100)
            (gen / "small.c").write_text("void f_small(void) {\n}\n")
            tools = root / "bin"
            tools.mkdir()
            compiler = tools / "clang"
            compiler.write_text("#!" + sys.executable + "\n" + r'''
import json, os, sys, time
from pathlib import Path
if '--version' in sys.argv:
    print('synthetic clang 1')
    raise SystemExit()
opt = next(arg for arg in sys.argv if arg.startswith('-O'))
fd = os.open(os.environ['RECORD'], os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
def record(event):
    os.write(fd, (json.dumps([event, opt, time.monotonic()])+'\n').encode())
record('start')
time.sleep(0.3 if opt == '-O0' else 0.03)
Path(sys.argv[sys.argv.index('-o')+1]).write_bytes(b'synthetic object')
record('finish')
os.close(fd)
''')
            compiler.chmod(0o755)
            record = root / "record.jsonl"
            env = dict(os.environ, PATH=str(tools) + ":" + os.environ["PATH"],
                       GEN=str(gen.parent), OBJ=str(root / "objects"), O0_BYTES="80", RECORD=str(record))
            def run():
                result = subprocess.run(["bash", "scripts/recomp/build_all.sh", "2"], cwd=root,
                                        env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return [json.loads(line) for line in record.read_text().splitlines()]
            first = run()
            self.assertEqual(len(first), 4)
            o1_start = next(t for event, opt, t in first if event == "start" and opt == "-O1")
            o0_end = next(t for event, opt, t in first if event == "finish" and opt == "-O0")
            self.assertLess(o1_start, o0_end)
            self.assertEqual(len(run()), 4, "unchanged objects must be reused")
            env["EXTRA"] = "-DSYNTHETIC_FLAG=1"
            self.assertEqual(len(run()), 8, "changed flags must rebuild")
            (root / "scripts/recomp/rt/cpu.h").write_text("/* changed header */\n")
            self.assertEqual(len(run()), 12, "changed headers must rebuild")
            alternate = root / "other generated files/main"
            shutil.copytree(gen, alternate)
            env["GEN"] = str(alternate.parent)
            self.assertEqual(len(run()), 16, "switching input trees must invalidate old objects")
