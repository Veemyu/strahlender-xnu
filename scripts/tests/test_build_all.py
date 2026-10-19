"""Tests für scripts/build_all.sh (Stufenauswahl, Dry-run, Marker, Assets-Stufe) – nur synthetische Daten.

Es werden weder Unity noch Xcode noch hactool gestartet; der Preflight ist abgeschaltet (--no-preflight).
"""
import os
import shutil
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
        for stage in ("tools", "extract", "il2cpp", "masterdata", "shaders", "video", "audio", "assets", "stubs",
                      "unity-build", "deploy"):
            self.assertIn("  %-12s" % stage, out, stage)
        self.assertIn("nicht implementiert", out)
        self.assertFalse(os.path.exists(self.work), "Dry-run darf nichts anlegen")

    def test_stubs_stage_dry_run_plans_scan_gen_and_conflicts(self):
        rc, out, err = self.dry(["--only", "stubs"])
        self.assertEqual(rc, 0, err)
        self.assertIn("stub_gen.py scan", out)
        self.assertIn("stub_gen.py gen", out)
        self.assertIn("stub_gen.py conflicts", out)
        self.assertIn("unity/Assets/XnuStubs", out)
        self.assertFalse(os.path.exists(self.work), "Dry-run darf nichts anlegen")

    def test_stubs_run_before_unity_build(self):
        self.assertLess(bs.STAGES.index("assets"), bs.STAGES.index("stubs"))
        self.assertLess(bs.STAGES.index("stubs"), bs.STAGES.index("unity-build"))
        rc, out, _ = self.dry(["--from", "assets", "--to", "unity-build"])
        self.assertIn("Stufen: assets stubs unity-build ", out)

    def test_from_to_and_only(self):
        rc, out, _ = self.dry(["--from", "video", "--to", "audio"])
        self.assertEqual(rc, 0)
        self.assertIn("Stufen: video audio ", out)
        rc, out, _ = self.dry(["--only", "shaders,video"])
        self.assertIn("Stufen: shaders video ", out)

    def test_audio_is_a_placeholder_without_marker(self):
        rc, out, _ = run(["--only", "audio", "--no-preflight", "--work", self.work])
        self.assertEqual(rc, 0)
        self.assertIn("NICHT IMPLEMENTIERT", out)
        self.assertIn("nie Ton", out)
        self.assertFalse(os.path.exists(os.path.join(self.work, ".stages", "audio.json")))

    def test_usage_errors(self):
        self.assertEqual(run([])[0], 2)
        self.assertEqual(run(["--only", "nix", "--dry-run"])[0], 2)
        self.assertEqual(run(["--target", "windows", "--dry-run", "all"])[0], 2)
        self.assertEqual(run(["--from", "assets", "--to", "video", "--dry-run"])[0], 2)
        self.assertEqual(run(["--only", "video", "--from", "tools", "--dry-run"])[0], 2)
        rc, _, err = run(["extract", "--no-preflight", "--work", self.work])
        self.assertEqual(rc, 2)
        self.assertIn("--xci fehlt", err)

    def test_missing_input_file_has_german_message(self):
        rc, _, err = run(["extract", "--no-preflight", "--work", self.work, "--xci", "/nicht/da.xci"])
        self.assertEqual(rc, 3)
        self.assertIn("XCI nicht gefunden", err)

    def test_team_id_is_never_printed(self):
        rc, out, err = self.dry(["--only", "deploy", "--target", "ios"], env={"TEAM_ID": "GEHEIM12345"})
        self.assertEqual(rc, 0, err)
        self.assertNotIn("GEHEIM12345", out + err)
        self.assertIn("ios_deploy.sh", out)

    def test_deploy_without_team_id_only_builds(self):
        write(os.path.join(self.work, "builds", "ios", "xnu", "Unity-iPhone.xcodeproj", "x"))
        env = {"HOME": self.tmp.name, "XNU_LOCAL_ENV": os.path.join(self.tmp.name, "gibt-es-nicht.env")}
        rc, out, _ = run(["--only", "deploy", "--target", "ios", "--no-preflight", "--work", self.work], env)
        self.assertEqual(rc, 0)
        self.assertIn("nur gebaut, nicht installiert", out)

    def test_dry_run_shows_unity_commands(self):
        rc, out, _ = self.dry(["--only", "unity-build"])
        self.assertEqual(rc, 0)
        self.assertIn("Xnu.Build.Editor.BuildScript.BuildMacOS", out)
        self.assertIn("Xnu.Build.Editor.BuildScript.BuildIos", out)
        self.assertIn("StandaloneOSX", out)
        rc, out, _ = self.dry(["--only", "unity-build", "--target", "ios"])
        self.assertNotIn("BuildMacOS", out)

    def test_dry_run_respects_marker(self):
        write(os.path.join(self.work, "exefs", "main"), "m")
        write(os.path.join(self.work, "romfs", "Data", "x"), "r")
        write(os.path.join(self.work, "masterdata", "_counts.json"), "{}")
        digest, _ = bs.stage_hash("masterdata", ROOT, self.work, "all")
        bs.write_marker(self.work, "masterdata", digest)
        rc, out, _ = self.dry(["--only", "masterdata"])
        self.assertEqual(rc, 0)
        self.assertIn("Marker passt", out)
        rc, out, _ = self.dry(["--only", "masterdata", "--force"])
        self.assertIn("würde ausgeführt", out)


class AssetsStageTests(unittest.TestCase):
    """Echte Assets-Stufe mit synthetischen Bundles; Ziel liegt unter work/ (gitignoriert)."""

    def setUp(self):
        base = os.path.join(ROOT, "work")
        os.makedirs(base, exist_ok=True)
        self.work = tempfile.mkdtemp(prefix="test-build-all-", dir=base)
        self.dest = os.path.join(self.work, "streaming", "GameData")
        aa = os.path.join(self.work, "romfs", "Data", "StreamingAssets", "AssetAssistant")
        write(os.path.join(aa, "Dpr", "masterdatas"), "bundle-a")
        write(os.path.join(aa, "Effects", "fx"), "bundle-b")
        write(os.path.join(self.work, "exefs", "main"), "m")
        write(os.path.join(self.work, "video", "dia", "op.mp4"), "mp4")
        write(os.path.join(self.work, "masterdata", "dpr", "Tab.json"), "{}")
        self.env = {"ASSETS_DEST": self.dest}

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def assets(self, extra=()):
        return run(["--only", "assets", "--no-preflight", "--work", self.work] + list(extra), self.env)

    def test_copy_skip_and_rerun(self):
        rc, out, err = self.assets()
        self.assertEqual(rc, 0, err)
        rel = os.path.join("romfs", "Data", "StreamingAssets")
        self.assertTrue(os.path.isfile(os.path.join(self.dest, rel, "AssetAssistant", "Dpr", "masterdatas")))
        self.assertTrue(os.path.isfile(os.path.join(self.dest, rel, "Movie", "dia", "op.mp4")))
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "masterdata", "dpr", "Tab.json")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, rel, "Audio")))
        self.assertIn("Dateien", out)
        self.assertTrue(os.path.isfile(os.path.join(self.work, ".stages", "assets.json")))

        rc, out, _ = self.assets()
        self.assertIn("Marker passt", out)

        write(os.path.join(self.work, "romfs", "Data", "StreamingAssets", "AssetAssistant", "neu"), "n")
        rc, out, _ = self.assets()
        self.assertNotIn("Marker passt", out)
        self.assertTrue(os.path.isfile(os.path.join(self.dest, rel, "AssetAssistant", "neu")))

        rc, out, _ = self.assets(["--force"])
        self.assertNotIn("Marker passt", out)

    def test_destination_must_be_gitignored(self):
        self.env = {"ASSETS_DEST": os.path.join(ROOT, "docs", "nicht-ignoriert")}
        rc, _, err = self.assets()
        self.assertEqual(rc, 2)
        self.assertIn("nicht gitignoriert", err)
        self.assertFalse(os.path.exists(self.env["ASSETS_DEST"]))

    def test_missing_extract_gives_clear_error(self):
        shutil.rmtree(os.path.join(self.work, "exefs"))
        rc, _, err = self.assets()
        self.assertEqual(rc, 10)
        self.assertIn("extract", err)


if __name__ == "__main__":
    unittest.main()
