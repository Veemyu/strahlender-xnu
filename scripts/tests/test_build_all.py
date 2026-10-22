"""Tests für scripts/build_all.sh (Stufenauswahl, Dry-run, Marker, Fehlerwege) – nur synthetische Daten.

Es werden weder Unity noch Xcode noch hactool gestartet; der Preflight ist abgeschaltet (--no-preflight).
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
        self.xci = os.path.join(self.tmp.name, "spiel.xci")
        self.keys = os.path.join(self.tmp.name, "keys")
        write(self.xci, "synthetisch")
        write(os.path.join(self.keys, "prod.keys"), "synthetisch")

    def tearDown(self):
        self.tmp.cleanup()

    def dry(self, extra, env=None):
        return run(["--dry-run", "--no-preflight", "--work", self.work] + extra, env)

    def test_all_stages_listed_and_nothing_written(self):
        rc, out, err = self.dry(["all", "--xci", self.xci, "--keys", self.keys])
        self.assertEqual(rc, 0, err)
        for stage in ("tools", "extract", "recomp", "shaders"):
            self.assertIn("  %-12s" % stage, out, stage)
        for stage in ("il2cpp", "masterdata", "video", "audio"):
            self.assertNotIn("  %-12s" % stage, out, stage)
        self.assertFalse(os.path.exists(self.work), "Dry-run darf nichts anlegen")

    def test_recomp_dry_run_plans_all_steps_and_writes_nothing(self):
        rc, out, err = self.dry(["--only", "recomp"])
        self.assertEqual(rc, 0, err)
        self.assertIn("Stufe recomp", out)
        for part in ("Generator", "Übersetzen", "Modulbilder", "BDSP.app", "RomFS"):
            self.assertIn(part, out)
        self.assertIn("-O0 ab 300 KB", out)
        self.assertFalse(os.path.exists(self.work), "Dry-run darf nichts anlegen")

    def test_recomp_options_reach_the_plan(self):
        rc, out, err = self.dry(["--only", "recomp", "--recomp-o0-kb", "500", "--hardened", "--no-install-data"])
        self.assertEqual(rc, 0, err)
        self.assertIn("-O0 ab 500 KB", out)
        self.assertNotIn("RomFS nach Application Support", out)

    def test_recomp_skipped_for_ios_target(self):
        rc, out, err = self.dry(["--only", "recomp", "--target", "ios"])
        self.assertEqual(rc, 0, err)
        self.assertIn("übersprungen", out)

    def test_from_to_and_only(self):
        rc, out, _ = self.dry(["--from", "recomp", "--to", "shaders"])
        self.assertEqual(rc, 0)
        self.assertIn("Stufen: recomp shaders ", out)
        rc, out, _ = self.dry(["--only", "shaders,tools"])
        self.assertIn("Stufen: tools shaders ", out)

    def test_removed_stages_and_options_are_rejected(self):
        for stage in ("il2cpp", "masterdata", "video", "audio"):
            self.assertEqual(run(["--only", stage, "--dry-run"])[0], 2, stage)
        for option in ("--video-profile", "--movie-src", "--bundle-platform", "--bundle-subset", "--texture-format", "--launch"):
            self.assertEqual(run([option, "x", "--dry-run", "--only", "tools"])[0], 2, option)

    def test_usage_errors(self):
        self.assertEqual(run([])[0], 2)
        self.assertEqual(run(["--only", "nix", "--dry-run"])[0], 2)
        self.assertEqual(run(["--target", "windows", "--dry-run", "all"])[0], 2)
        self.assertEqual(run(["--from", "shaders", "--to", "tools", "--dry-run"])[0], 2)
        self.assertEqual(run(["--only", "shaders", "--from", "tools", "--dry-run"])[0], 2)
        rc, _, err = run(["extract", "--no-preflight", "--work", self.work])
        self.assertEqual(rc, 2)
        self.assertIn("--xci fehlt", err)

    def test_missing_input_file_has_german_message(self):
        rc, _, err = run(["extract", "--no-preflight", "--work", self.work, "--xci", "/nicht/da.xci"])
        self.assertEqual(rc, 3)
        self.assertIn("XCI nicht gefunden", err)

    def test_dry_run_respects_marker(self):
        write(os.path.join(self.work, "exefs", "main"), "m")
        write(os.path.join(self.work, "romfs", "Data", "x"), "r")
        write(os.path.join(self.work, "build", "shaders", "x"), "{}")
        digest, _ = bs.stage_hash("shaders", ROOT, self.work, "all")
        bs.write_marker(self.work, "shaders", digest)
        rc, out, _ = self.dry(["--only", "shaders"])
        self.assertEqual(rc, 0)
        self.assertIn("Marker passt", out)
        rc, out, _ = self.dry(["--only", "shaders", "--force"])
        self.assertIn("würde ausgeführt", out)



if __name__ == "__main__":
    unittest.main()
