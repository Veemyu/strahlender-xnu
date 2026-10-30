"""Release publication is explicit, complete and tied to one source revision."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("installer_release", ROOT / "installer/scripts/release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
SHA = "a" * 40


class InstallerReleaseTests(unittest.TestCase):
    def plan(self, channel="artifacts", event="workflow_dispatch", ref="main"):
        return release.plan("0.1.0", event, ref, channel, SHA, "123", "1")

    def test_ordinary_push_can_never_publish(self):
        with self.assertRaisesRegex(ValueError, "tag must match"):
            self.plan(event="push")
        with self.assertRaisesRegex(ValueError, "manual run"):
            self.plan(event="pull_request")

    def test_release_tag_must_match_cargo_version(self):
        self.assertEqual(self.plan(event="push", ref="installer-v0.1.0")["channel"], "release")
        with self.assertRaisesRegex(ValueError, "tag must match"):
            self.plan(event="push", ref="installer-v0.2.0")

    def test_nightly_and_stable_have_distinct_immutable_tags(self):
        self.assertEqual(self.plan("nightly")["tag"], "installer-nightly-123-1")
        self.assertEqual(self.plan("release")["tag"], "installer-v0.1.0")
        self.assertEqual(self.plan()["tag"], "")

    def artifacts(self, root):
        files = []
        for index, name in enumerate(release.PACKAGES):
            directory = root / str(index)
            directory.mkdir(parents=True)
            lines = []
            path = directory / name
            path.write_bytes(b"synthetic package " + name.encode())
            lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
            files.append(path)
            (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n")
        return files

    def test_collect_requires_universal_mac_and_both_linux_architectures_with_verified_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.artifacts(root / "artifacts")
            files[0].write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                release.collect(root / "artifacts", root / "output", self.plan())
            self.assertFalse((root / "output").exists())
            files[0].unlink()
            with self.assertRaisesRegex(ValueError, "exactly one"):
                release.collect(root / "artifacts", root / "output", self.plan())

    def test_collect_includes_all_downloads_and_a_combined_checksum_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.artifacts(root / "artifacts")
            release.collect(root / "artifacts", root / "output", self.plan())
            self.assertEqual(len(list((root / "output").iterdir())), 6)
            self.assertEqual(len((root / "output/SHA256SUMS").read_text().splitlines()), 4)
            self.assertFalse((root / "output/installer-build.json").exists())
            self.assertTrue((root / "output/.internal/installer-build.json").is_file())

    def test_artifact_only_run_never_calls_github(self):
        with patch.object(release.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "must never publish"):
                release.publish(Path("unused"), self.plan(), "Veemyu/strahlender-xnu")
            run.assert_not_called()

    def test_published_tag_is_never_moved(self):
        with patch.object(release.subprocess, "run", return_value=SimpleNamespace(
                stdout="b" * 40 + "\trefs/tags/installer-v0.1.0\n")) as run:
            with self.assertRaisesRegex(ValueError, "different commit"):
                release.publish(Path("unused"), self.plan("release"), "Veemyu/strahlender-xnu")
            self.assertEqual(run.call_count, 1)

    def test_nightly_publishes_only_after_upload_and_does_not_replace_stable_latest(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(release.subprocess, "run", return_value=SimpleNamespace(stdout="")) as run:
            (Path(temporary) / "installer-build.json").write_text("{}")
            (Path(temporary) / "installer-linux-x86_64.tar.gz").write_bytes(b"not a public download")
            release.publish(Path(temporary), self.plan("nightly"), "Veemyu/strahlender-xnu")
            create, edit = run.call_args_list[-2].args[0], run.call_args_list[-1].args[0]
            self.assertIn("--draft", create)
            self.assertIn("--prerelease", create)
            self.assertIn("--draft=false", edit)
            self.assertIn("--latest=false", edit)
            self.assertNotIn(str(Path(temporary) / "installer-build.json"), create)
            self.assertNotIn(str(Path(temporary) / "installer-linux-x86_64.tar.gz"), create)
            self.assertTrue(all(str(Path(temporary) / name) in create for name in release.PACKAGES))

    def test_draft_uploads_downloads_without_publishing(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(release.subprocess, "run", return_value=SimpleNamespace(stdout="")) as run:
            draft = self.plan("release")
            draft["draft"] = True
            release.publish(Path(temporary), draft, "Veemyu/strahlender-xnu")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][:3], ["gh", "release", "create"])
            self.assertIn("--draft", run.call_args.args[0])

    def test_release_message_comes_from_versioned_markdown(self):
        notes = release.release_notes(self.plan("nightly"), "Veemyu/strahlender-xnu")
        self.assertIn("Luminescent Platinum", notes)
        self.assertIn("Full Lumi playthrough validation remains in progress", notes)
        self.assertIn(SHA, notes)
        self.assertIn("**nightly**", notes)
        self.assertIn("/releases/download/installer-nightly-123-1/installer-linux-aarch64.AppImage", notes)


if __name__ == "__main__":
    unittest.main()
