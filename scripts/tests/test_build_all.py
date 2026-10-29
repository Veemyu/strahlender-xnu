"""Tests for scripts/build_all.sh (stage selection, dry run, markers, error paths), synthetic data only.

Neither Unity nor Xcode nor hactool is started; the preflight is switched off (--no-preflight).
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPT = os.path.join(ROOT, "scripts", "build_all.sh")
sys.path.insert(0, os.path.join(HERE, ".."))
import build_stages as bs  # noqa: E402


def write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def run(args, env=None):
    full = dict(os.environ)
    full.pop("TEAM_ID", None)
    full.update(env or {})
    p = subprocess.run(["bash", SCRIPT] + args, capture_output=True, text=True, env=full, timeout=120)
    return p.returncode, p.stdout, p.stderr


class DryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = os.path.join(self.tmp.name, "work")
        self.xci = os.path.join(self.tmp.name, "game.xci")
        self.keys = os.path.join(self.tmp.name, "keys")
        write(self.xci, "synthetic")
        write(os.path.join(self.keys, "prod.keys"), "synthetic")

    def tearDown(self):
        self.tmp.cleanup()

    def dry(self, extra, env=None):
        return run(["--dry-run", "--no-preflight", "--work", self.work] + extra, env)

    def test_all_stages_listed_and_nothing_written(self):
        rc, out, err = self.dry(["all", "--xci", self.xci, "--keys", self.keys])
        self.assertEqual(rc, 0, err)
        for stage in ("tools", "extract", "recomp"):
            self.assertIn("  %-12s" % stage, out, stage)
        for stage in ("il2cpp", "masterdata", "video", "audio"):
            self.assertNotIn("  %-12s" % stage, out, stage)
        self.assertFalse(os.path.exists(self.work), "dry run must not create anything")

    def test_recomp_dry_run_plans_all_steps_and_writes_nothing(self):
        rc, out, err = self.dry(["--only", "recomp"])
        self.assertEqual(rc, 0, err)
        self.assertIn("Stage recomp", out)
        for part in ("generator", "compile", "module images", "BDSP.app", "RomFS"):
            self.assertIn(part, out)
        self.assertIn("-O0 from 300 KB", out)
        self.assertFalse(os.path.exists(self.work), "dry run must not create anything")

    def test_recomp_options_reach_the_plan(self):
        rc, out, err = self.dry(["--only", "recomp", "--recomp-o0-kb", "500", "--hardened", "--no-install-data"])
        self.assertEqual(rc, 0, err)
        self.assertIn("-O0 from 500 KB", out)
        self.assertNotIn("RomFS into Application Support", out)

    def test_recomp_skipped_for_ios_target(self):
        rc, out, err = self.dry(["--only", "recomp", "--target", "ios"])
        self.assertEqual(rc, 0, err)
        self.assertIn("skipped", out)

    def test_from_to_and_only(self):
        rc, out, _ = self.dry(["--from", "recomp"])
        self.assertEqual(rc, 0)
        self.assertIn("Stages: recomp ", out)
        rc, out, _ = self.dry(["--only", "recomp,tools"])
        self.assertIn("Stages: tools recomp ", out)

    def test_removed_stages_and_options_are_rejected(self):
        for stage in ("il2cpp", "masterdata", "video", "audio", "shaders"):
            self.assertEqual(run(["--only", stage, "--dry-run"])[0], 2, stage)
        for option in ("--video-profile", "--movie-src", "--bundle-platform", "--bundle-subset", "--texture-format", "--launch"):
            self.assertEqual(run([option, "x", "--dry-run", "--only", "tools"])[0], 2, option)

    def test_usage_errors(self):
        self.assertEqual(run([])[0], 2)
        self.assertEqual(run(["--only", "nix", "--dry-run"])[0], 2)
        self.assertEqual(run(["--target", "windows", "--dry-run", "all"])[0], 2)
        self.assertEqual(run(["--from", "recomp", "--to", "tools", "--dry-run"])[0], 2)
        self.assertEqual(run(["--only", "recomp", "--from", "tools", "--dry-run"])[0], 2)
        rc, _, err = run(["extract", "--no-preflight", "--work", self.work])
        self.assertEqual(rc, 2)
        self.assertIn("--xci missing", err)

    def test_missing_input_file_has_clear_message(self):
        rc, _, err = run(["extract", "--no-preflight", "--work", self.work, "--xci", "/not/there.xci"])
        self.assertEqual(rc, 3)
        self.assertIn("XCI not found", err)

    def test_dry_run_respects_marker(self):
        write(os.path.join(self.work, "exefs", "main"), "m")
        write(os.path.join(self.work, "romfs", "Data", "x"), "r")
        write(os.path.join(self.work, "builds", "macos-recomp", "BDSP.app", "Contents", "MacOS", "BDSP"), "x")
        env = {"XNU_RECOMP_OPTS": "o0kb=300 hardened=0 data=1"}
        digest, _ = bs.stage_hash("recomp", ROOT, self.work, "all", env=env)
        bs.write_marker(self.work, "recomp", digest)
        rc, out, _ = self.dry(["--only", "recomp"])
        self.assertEqual(rc, 0)
        self.assertIn("marker matches", out)
        rc, out, _ = self.dry(["--only", "recomp", "--force"])
        self.assertIn("would run", out)



if __name__ == "__main__":
    unittest.main()
