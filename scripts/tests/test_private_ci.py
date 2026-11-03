import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from scripts.ci import full_build, private_data, smoke

ROOT = Path(__file__).resolve().parents[2]
TRIGGER = (ROOT / ".github/workflows/private-full-test.yml").read_text(encoding="utf-8")
KEY = "k" * 48
try:
    import cryptography  # noqa: F401
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False


def encrypt(plain, key, salt=b"12345678"):
    """The blob format of the data set: Salted__ + salt, AES-256-CTR, PBKDF2-SHA256 with 600000 rounds."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    derived = hashlib.pbkdf2_hmac("sha256", key.encode(), salt, private_data.ITERATIONS, 48)
    encryptor = Cipher(algorithms.AES(derived[:32]), modes.CTR(derived[32:])).encryptor()
    return b"Salted__" + salt + encryptor.update(plain) + encryptor.finalize()


def plain_for(role):
    if role == "game.xci":
        return b"\0" * 256 + b"HEAD" + b"x" * 100
    if role == "update.nsp":
        return b"PFS0" + b"y" * 100
    if role == "prod.keys":
        return b"master_key_00 = 00\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr("top/romfs/a.txt", "a")
    return buffer.getvalue()


class WorkflowShapeTests(unittest.TestCase):
    """The public side only dispatches the private runner; the runner itself never lives in this repository."""

    def test_the_full_build_workflow_is_not_public(self):
        self.assertFalse((ROOT / ".github/workflows/full-build.yml").exists())

    def test_trigger_secret_and_permissions(self):
        self.assertIn("on:\n  push:\n    branches: [main]\n  workflow_dispatch:\n", TRIGGER)
        for forbidden in ("pull_request", "schedule:", "workflow_run", "repository_dispatch"):
            self.assertNotIn(forbidden, TRIGGER)
        self.assertEqual(set(re.findall(r"secrets\.(\w+)", TRIGGER)), {"PRIVATE_CI_TOKEN"})
        self.assertIn("permissions:\n  contents: read\n", TRIGGER)
        self.assertEqual(len(re.findall(r"\n  \w[\w-]*:\n    runs-on:", TRIGGER)), 1)
        self.assertNotRegex(TRIGGER, r"\n\s+permissions:")

    def test_dispatch_is_quiet_and_sends_only_the_sha(self):
        self.assertIn('[ -n "$GH_TOKEN" ] || exit 0', TRIGGER)
        self.assertIn("repos/Veemyu/str-xnu-tests/actions/workflows/full-build.yml/dispatches", TRIGGER)
        self.assertIn("inputs[sha]=$GITHUB_SHA", TRIGGER)
        self.assertEqual(len(re.findall(r"inputs\[", TRIGGER)), 1)
        self.assertIn("> /dev/null 2>&1", TRIGGER)
        for forbidden in ("gh run", "watch", "--jq", "set -x", "echo \"$", "actions/checkout", "upload-artifact", "https://", "http://"):
            self.assertNotIn(forbidden, TRIGGER)

    def test_no_forbidden_characters_or_data_source_names(self):
        for path in (ROOT / "scripts/ci").glob("*.py"):
            self.assertFalse({"\u2013", "\u2014"} & set(path.read_text(encoding="utf-8")), path.name)
        self.assertFalse({"\u2013", "\u2014"} & set(TRIGGER))
        self.assertNotIn("CI_DATA", TRIGGER)


@unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
class PrivateDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, True)

    def serve(self, key=KEY, tamper=False):
        blobs, lines = {}, []
        for index, role in enumerate(private_data.ROLES):
            blob = encrypt(plain_for(role), key, bytes([65 + index]) * 8)
            name = "%032x.bin" % (index + 1)
            digest = hashlib.sha256(blob + (b"!" if tamper and index == 0 else b"")).hexdigest()
            lines.append(digest + "  " + name)
            blobs[name] = blob
        return blobs, "\n".join(lines)

    def run_fetch(self, blobs, manifest, key=KEY, with_mod=True):
        calls = []

        def fake_run(command, input, **_kwargs):
            calls.append((command, input))
            url = re.search(r'url = "(.*)"', input).group(1)
            Path(re.search(r'output = "(.*)"', input).group(1)).write_bytes(blobs[url.rsplit("/", 1)[1]])
            return SimpleNamespace(returncode=0)

        environ = {"CI_DATA_URL": "https://example.invalid", "CI_DATA_EDGE_KEY": "edge", "CI_DATA_BEARER": "b" * 64,
                   "CI_DATA_KEY": key, "CI_DATA_MANIFEST": manifest}
        private_data.fetch(self.temp / "data", environ, fake_run, with_mod=with_mod)
        return calls

    def test_fetch_decrypts_all_roles_and_leaves_no_blob(self):
        blobs, manifest = self.serve()
        calls = self.run_fetch(blobs, manifest)
        data = self.temp / "data"
        self.assertEqual(sorted(path.name for path in data.iterdir()), sorted(private_data.ROLES))
        self.assertEqual((data / "prod.keys").read_bytes(), plain_for("prod.keys"))
        for command, config in calls:
            self.assertNotIn("edge", " ".join(command))
            self.assertNotIn("b" * 64, " ".join(command))
            self.assertIn("X-CI-Edge: edge", config)
        self.assertNotIn("--location", " ".join(calls[0][0]))

    def test_fetch_skips_the_mod_archive_unless_asked(self):
        blobs, manifest = self.serve()
        calls = self.run_fetch(blobs, manifest, with_mod=False)
        names = sorted(path.name for path in (self.temp / "data").iterdir())
        self.assertEqual(names, sorted(set(private_data.ROLES) - {"mod.zip"}))
        self.assertEqual(len(calls), len(private_data.ROLES) - 1)

    def test_wrong_key_and_damaged_download_are_refused(self):
        blobs, manifest = self.serve(key="z" * 48)
        with self.assertRaisesRegex(private_data.DataError, "Sanity check failed for game.xci"):
            self.run_fetch(blobs, manifest)
        self.assertFalse((self.temp / "data/game.xci").exists())
        blobs, manifest = self.serve(tamper=True)
        with self.assertRaisesRegex(private_data.DataError, "Hash mismatch for game.xci"):
            self.run_fetch(blobs, manifest)
        self.assertFalse((self.temp / "data/game.xci").exists())

    @unittest.skipUnless(shutil.which("openssl"), "openssl is not installed")
    def test_decrypt_matches_openssl(self):
        plain = self.temp / "plain"
        plain.write_bytes(os.urandom(100000))
        blob = self.temp / "blob"
        command = ["openssl", "enc", "-aes-256-ctr", "-pbkdf2", "-iter", "600000", "-salt", "-pass", "env:K", "-in", str(plain), "-out", str(blob)]
        if subprocess.run(command, env={**os.environ, "K": KEY}, capture_output=True).returncode:
            self.skipTest("this openssl lacks -pbkdf2")
        private_data.decrypt(blob, self.temp / "out", KEY)
        self.assertEqual((self.temp / "out").read_bytes(), plain.read_bytes())

    def test_manifest_and_masks(self):
        _, manifest = self.serve()
        self.assertEqual(len(private_data.parse_manifest(manifest)), 5)
        for bad in ("", "x  y", manifest.splitlines()[0]):
            with self.assertRaises(private_data.DataError):
                private_data.parse_manifest(bad)
        with self.assertRaises(private_data.DataError):
            private_data.parse_manifest(manifest.replace("00000001.bin", "../a"))
        masks = private_data.mask_lines({"CI_DATA_URL": "https://host.invalid/", "CI_DATA_MANIFEST": manifest, "CI_DATA_KEY": KEY})
        self.assertIn("::add-mask::host.invalid", masks)
        self.assertIn("::add-mask::" + KEY, masks)
        self.assertIn("::add-mask::" + manifest.splitlines()[1].split()[0], masks)

    def test_mod_unpack_flattens_and_refuses_escapes(self):
        data = self.temp / "data"
        data.mkdir()
        (data / "mod.zip").write_bytes(plain_for("mod.zip"))
        private_data.prepare_mod(data, self.temp / "mods")
        self.assertTrue((self.temp / "mods/ci-mod/romfs/a.txt").is_file())
        self.assertFalse((data / "mod.zip").exists())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zipped:
            zipped.writestr("../escape.txt", "x")
        (data / "mod.zip").write_bytes(buffer.getvalue())
        with self.assertRaises(private_data.DataError):
            private_data.prepare_mod(data, self.temp / "mods")

    def test_wipe_removes_read_only_trees(self):
        folder = self.temp / "w/a"
        folder.mkdir(parents=True)
        (folder / "f").write_text("x")
        os.chmod(folder / "f", 0o400)
        os.chmod(folder, 0o500)
        private_data.wipe([str(self.temp / "w"), str(self.temp / "missing")])
        self.assertFalse((self.temp / "w").exists())

    def test_wipe_retries_while_a_cancelled_build_still_writes(self):
        folder = self.temp / "w"
        folder.mkdir()
        real = shutil.rmtree
        calls = []

        def flaky(path, **kwargs):
            calls.append(path)
            if len(calls) < 3:
                raise OSError(39, "Directory not empty")
            return real(path, **kwargs)

        with mock.patch.object(shutil, "rmtree", flaky), mock.patch.object(private_data.time, "sleep"):
            private_data.wipe([str(folder)])
        self.assertEqual(len(calls), 3)
        self.assertFalse(folder.exists())


class BuildReportTests(unittest.TestCase):
    def args(self, target, mod=False):
        return SimpleNamespace(target=target, root="/src", base="/b", python=None, mod=mod, windows_catalog="/c.json",
                               ips_helper="/ips", firmware_helper="/fw", extract="/ex", extract_prefix="--cli")

    def test_command_and_environment(self):
        command = full_build.build_command(self.args("windows", True), "py")
        self.assertEqual(command[:4], ["py", "-I", "-B", str(Path("/src/scripts/install/driver.py"))])
        for option in ("--windows-catalog", "--ips-helper", "--firmware-helper", "--mod-root", "--update", "--firmware"):
            self.assertIn(option, command)
        self.assertEqual(command[command.index("--work") + 1], str(Path("/b/work")))
        environment = full_build.build_environment(self.args("windows", True), {"PYTHONHOME": "x"})
        self.assertEqual(environment["BDSP_INSTALLER_PRIVATE_RUNTIME"], "1")
        self.assertNotIn("PYTHONHOME", environment)
        self.assertEqual(environment["BDSP_EXTRACT_PREFIX"], "--cli")
        plain = full_build.build_command(self.args("linux"), "py")
        self.assertNotIn("-I", plain)
        self.assertEqual(plain[plain.index("--work") + 1], str(Path("/src/work")))
        self.assertNotIn("--mod-root", plain)
        self.assertEqual(full_build.build_environment(self.args("linux"), {})["BDSP_MOD"], "none")

    @unittest.skipIf(os.name == "nt", "symlinks need extra rights on Windows and the link is not used there")
    def test_checkout_work_folder_points_to_the_big_disk(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as base:
            args = self.args("linux")
            args.root, args.base = root, base
            full_build.link_work(args)
            self.assertEqual((Path(root) / "work").resolve(), (Path(base) / "work").resolve())
            full_build.link_work(args)

    def test_summary_redacts_paths_and_hex(self):
        lines = [json.dumps({"event": "step", "id": "extract", "status": "complete"}),
                 "not json",
                 json.dumps({"event": "error", "code": 4, "message": "cannot open /b/data/game.xci " + "a" * 40}),
                 json.dumps({"event": "artifact", "kind": "installed_application", "path": "/b/install/BDSP.app"}),
                 json.dumps({"event": "result", "ok": False, "code": 4})]
        summary, installed = full_build.summarize(lines, ["/b"])
        self.assertEqual(summary["steps"], {"extract": "complete"})
        self.assertEqual(summary["errors"][0]["message"], "cannot open <path>/data/game.xci <hex>")
        self.assertEqual(summary["result"], {"ok": False, "code": 4})
        self.assertEqual(installed, "/b/install/BDSP.app")


class SmokeTests(unittest.TestCase):
    def test_launch_commands(self):
        self.assertEqual(smoke.launch_command("macos", "/i/BDSP.app"), [str(Path("/i/BDSP.app/Contents/MacOS/BDSP"))])
        self.assertEqual(smoke.launch_command("windows", "C:/i/BDSP.exe"), [str(Path("C:/i/BDSP.exe"))])
        self.assertEqual(smoke.launch_command("linux", "/r/share/strahlender-xnu/app")[-1], str(Path("/r/bin/strahlender-xnu")))

    def test_alive_and_early_exit(self):
        class Alive:
            def poll(self):
                return None

            def kill(self):
                pass

            def wait(self):
                pass

        class Dead(Alive):
            def poll(self):
                return 3

        self.assertEqual(smoke.run(["x"], 0, lambda *a, **k: Alive(), lambda _s: None)[1], True)
        self.assertEqual(smoke.run(["x"], 5, lambda *a, **k: Dead(), lambda _s: None), ("exited early with code 3", False))


if __name__ == "__main__":
    unittest.main()
