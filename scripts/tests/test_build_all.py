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


@unittest.skipIf(sys.platform == "win32", "Runs bash scripts / POSIX tools; covered on Linux and macOS")
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
        self.assertIn("Base game missing", err)

    def test_missing_input_file_has_clear_message(self):
        rc, _, err = run(["extract", "--no-preflight", "--work", self.work, "--xci", "/not/there.xci"])
        self.assertEqual(rc, 3)
        self.assertIn("Base game not found", err)

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



HACTOOL_HELP = "Usage: hactool [options...] <file>\n" + "\n".join(
    "  %s=dir" % option for option in bs.HACTOOL_OPTIONS)


@unittest.skipIf(sys.platform == "win32", "Runs bash scripts / POSIX tools; covered on Linux and macOS")
class SystemHactoolTests(unittest.TestCase):
    """A hactool already on PATH is used instead of being cloned and built (issue 39); synthetic scripts only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.work, self.tools = os.path.join(t, "work"), os.path.join(t, "tools")
        self.bin = os.path.join(t, "bin")
        write(os.path.join(t, "game.xci"), "synthetic")
        write(os.path.join(t, "keys", "prod.keys"), "synthetic")
        self.extract = os.path.join(self.bin, "fake-extract")
        write(self.extract, "#!/bin/sh\n[ \"$1\" = check ] && exit 1\nexit 0\n")
        os.chmod(self.extract, 0o755)
        self.env = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "TOOLS_DIR": self.tools,
                    "BDSP_EXTRACT": self.extract, "MIN_FREE_GB": "0"}

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, help_text):
        path = os.path.join(self.bin, "hactool")
        write(path, "#!/bin/sh\ncat <<'EOF'\n%sEOF\n" % help_text)
        os.chmod(path, 0o755)
        return path

    def extract_stage(self):
        return run(["--only", "extract", "--no-preflight", "--work", self.work, "--xci",
                    os.path.join(self.tmp.name, "game.xci"), "--prod-keys",
                    os.path.join(self.tmp.name, "keys", "prod.keys")], self.env)

    def test_usable_hactool_on_path_is_linked_and_not_downloaded(self):
        system = self.install(HACTOOL_HELP)
        rc, out, err = self.extract_stage()
        self.assertEqual(rc, 0, err)
        link = os.path.join(self.tools, "hactool", "hactool")
        self.assertEqual(os.path.realpath(link), os.path.realpath(system))
        self.assertFalse(os.path.exists(os.path.join(self.tools, "hactool-clone.log")))
        rc, out, _ = run(["--dry-run", "--no-preflight", "--only", "tools", "--work", self.work], self.env)
        self.assertIn("hactool present", out)

    def test_dry_run_reports_the_hactool_on_path(self):
        self.install(HACTOOL_HELP)
        rc, out, err = run(["--dry-run", "--no-preflight", "--only", "tools", "--work", self.work], self.env)
        self.assertEqual(rc, 0, err)
        self.assertIn("hactool found on PATH", out)
        self.assertNotIn("would clone", out)

    def test_hactool_on_path_without_the_needed_options_is_not_used(self):
        self.install("Usage: hactool [options...] <file>\n")
        rc, out, err = self.extract_stage()
        self.assertEqual(rc, 4)
        self.assertIn("hactool missing", err)
        self.assertFalse(os.path.lexists(os.path.join(self.tools, "hactool", "hactool")))
        rc, out, _ = run(["--dry-run", "--no-preflight", "--only", "tools", "--work", self.work], self.env)
        self.assertIn("would clone and build hactool", out)

    def test_preflight_accepts_a_usable_hactool_on_path(self):
        with tempfile.TemporaryDirectory() as tools:
            def run_help(cmd, env=None, timeout=60):
                return True, HACTOOL_HELP
            items = bs.preflight(["tools", "extract"], "linux", ROOT, self.work, tools, 0,
                                 which=lambda c: "/usr/bin/" + c if c == "hactool" else None, run=run_help,
                                 free=lambda p: 200.0)
            self.assertEqual([i["name"] for i in items if not i["ok"]], [])
            self.assertTrue(any(i["name"] == "hactool on PATH" for i in items))


if __name__ == "__main__":
    unittest.main()
