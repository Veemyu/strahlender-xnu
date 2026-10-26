"""Installer build paths: synthetic files only, including spaces and apostrophes."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstallerPathTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Bash build pipeline")
    def test_mac_build_driver_accepts_application_support_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Library/Application Support/O'Brien installer/source"
            script = root / "scripts/recomp/app/recomp_build.sh"
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "scripts/recomp/app/recomp_build.sh", script)
            for name in ("work/exefs/main", "work/exefs/main.npdm",
                         "scripts/recomp/native-generator/src/generator.c", "scripts/recomp/hot_o2.txt"):
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("synthetic\n")
            (root / "work/romfs/Data").mkdir(parents=True)
            (root / "scripts/build_stages.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "assert Path(sys.argv[sys.argv.index('--root')+1]).resolve() == Path(__file__).resolve().parents[1]\n"
                "print('synthetic-stage-hash')\n")
            environment = {key: value for key, value in os.environ.items()
                           if key not in ("WORK", "RECOMP_DIR", "BDSP_EXEFS_DIR", "BDSP_MOD_NAME")}
            result = subprocess.run(["bash", str(script), "--dry-run", "--jobs", "1", "--no-install-data"],
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1/6 generator:", result.stdout)
            self.assertIn("5/6 assembling", result.stdout)
            self.assertIn("6/6 data: skipped", result.stdout)
            self.assertFalse((root / "work/recomp/gen4").exists())

    @unittest.skipUnless(sys.platform == "darwin", "Mac compiler/time flags")
    def test_mac_compiler_preserves_spaced_and_quoted_source_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Library/Application Support/O'Brien installer"
            source = folder / "generated/main"
            objects = folder / "compiled objects"
            source.mkdir(parents=True)
            hot = next(line.strip() for line in (ROOT / "scripts/recomp/hot_o2.txt").read_text().splitlines()
                       if line.strip() and not line.startswith("#"))
            (source / "O'Brien hot chunk.c").write_text(f"void {hot}(void) {{\n}}\n")
            (source / "cold chunk.c").write_text("void cold_one(void) {\n}\nvoid cold_two(void) {\n}\n")
            environment = dict(os.environ, GEN=str(source.parent), OBJ=str(objects), O0_BYTES="1")
            result = subprocess.run(["bash", str(ROOT / "scripts/recomp/build_all.sh"), "1"],
                                    env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((objects / "main_O'Brien hot chunk.o").is_file())
            self.assertTrue((objects / "main_O'Brien hot chunk.o.o2").is_file())
            self.assertTrue((objects / "main_cold chunk.o").is_file())

    @unittest.skipUnless(sys.platform == "darwin", "Apple Objective-C compiler")
    def test_native_runtime_includes_preserve_application_support_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Library/Application Support/O'Brien installer"
            here = root / "scripts/recomp/rt-bdsp/nvn"
            here.mkdir(parents=True)
            for name in ("build_nvn.sh", "flags.inc.sh"):
                shutil.copyfile(ROOT / "scripts/recomp/rt-bdsp/nvn" / name, here / name)
            source = root / "work/native sources"
            (source / "nvn/maxwell").mkdir(parents=True)
            (source / "nvn/path_probe.h").write_text("#define PATH_PROBE 7\n")
            for name in ("objects.c", "cmdbuf.c", "formats.c", "tegra.c", "astc.c", "bctc.c",
                         "maxwell/translate.c", "renderer.m", "metal.m"):
                (source / "nvn" / name).write_text('#include "path_probe.h"\nint probe(void) { return PATH_PROBE; }\n')
            for name in ("nvn_glue.c", "swkbd_overlay.m", "debug_thread.c", "movie_glue.c"):
                (here / name).write_text('#include "path_probe.h"\nint probe(void) { return PATH_PROBE; }\n')
            objects = root / "work/native objects"
            environment = dict(os.environ, NVN_SRC=str(source), RT=str(objects), NVN_KEEP="1")
            result = subprocess.run(["bash", str(here / "build_nvn.sh")], env=environment,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list((objects / "nvn").glob("*.o"))), 13)
