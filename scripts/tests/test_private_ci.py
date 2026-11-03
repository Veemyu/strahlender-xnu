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
from pathlib import Path
from types import SimpleNamespace

from scripts.ci import full_build, private_data, smoke

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/full-build.yml").read_text(encoding="utf-8")
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
    def jobs(self):
        body = WORKFLOW.split("\njobs:\n", 1)[1]
        parts = re.split(r"\n  (\w+):\n", "\n" + body)
        return dict(zip(parts[1::2], parts[2::2]))

    def test_manual_only_and_private_only(self):
        triggers = WORKFLOW.split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        for forbidden in ("push:", "pull_request", "schedule:", "workflow_run", "repository_dispatch"):
            self.assertNotIn(forbidden, triggers)
        self.assertEqual(set(self.jobs()), {"linux", "macos", "windows"})
        for name, job in self.jobs().items():
            self.assertIn("if: ${{ github.event.repository.private == true }}", job, name)

    def test_every_job_wipes_always_and_uploads_only_the_summary(self):
        for name, job in self.jobs().items():
            self.assertRegex(job, r"if: \$\{\{ always\(\) \}\}\n\s+run: \|\n\s+python3? src/scripts/ci/private_data\.py wipe", name)
            self.assertEqual(len(re.findall(r"actions/upload-artifact@", job)), 1, name)
            self.assertIn("path: ${{ runner.temp }}/ci-summary/" + name + ".json", job)

    def test_no_cache_no_trace_secrets_only_in_fetch_step(self):
        self.assertNotIn("actions/cache", WORKFLOW)
        self.assertNotIn("set -x", WORKFLOW)
        self.assertNotIn("curl -v", WORKFLOW)
        for name, job in self.jobs().items():
            steps = re.split(r"\n      - ", job)
            holders = [step for step in steps if "secrets.CI_DATA" in step]
            self.assertEqual(len(holders), 1, name)
            self.assertIn("private_data.py mask", holders[0])
            self.assertEqual(len(re.findall(r"secrets\.CI_DATA_\w+", holders[0])), 5, name)
        self.assertNotRegex(WORKFLOW, r"echo[^\n]*(CI_DATA|secrets\.)")

    def test_actions_are_pinned_like_the_other_workflows(self):
        used = set(re.findall(r"uses: (actions/[\w-]+@v\d+)", WORKFLOW))
        known = set()
        for other in (ROOT / ".github/workflows").glob("*.yml"):
            if other.name != "full-build.yml":
                known |= set(re.findall(r"uses: (actions/[\w-]+@v\d+)", other.read_text(encoding="utf-8")))
        self.assertTrue(used and used <= known, used - known)

    def test_windows_uses_short_roots(self):
        windows = self.jobs()["windows"]
        self.assertIn("BASE: C:\\b\n", windows)
        self.assertIn("BDSP_INSTALLER_DATA_DIR: C:\\b\\d", windows)
        self.assertNotIn("RUNNER_TEMP/b", windows)

    def test_no_forbidden_characters(self):
        for path in (ROOT / "scripts/ci").glob("*.py"):
            self.assertFalse({"\u2013", "\u2014"} & set(path.read_text(encoding="utf-8")), path.name)
        self.assertFalse({"\u2013", "\u2014"} & set(WORKFLOW))


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

    def run_fetch(self, blobs, manifest, key=KEY):
        calls = []

        def fake_run(command, input, **_kwargs):
            calls.append((command, input))
            url = re.search(r'url = "(.*)"', input).group(1)
            Path(re.search(r'output = "(.*)"', input).group(1)).write_bytes(blobs[url.rsplit("/", 1)[1]])
            return SimpleNamespace(returncode=0)

        environ = {"CI_DATA_URL": "https://example.invalid", "CI_DATA_EDGE_KEY": "edge", "CI_DATA_BEARER": "b" * 64,
                   "CI_DATA_KEY": key, "CI_DATA_MANIFEST": manifest}
        private_data.fetch(self.temp / "data", environ, fake_run)
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
        self.assertNotIn("--mod-root", plain)
        self.assertEqual(full_build.build_environment(self.args("linux"), {})["BDSP_MOD"], "none")

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
        self.assertEqual(smoke.launch_command("macos", "/i/BDSP.app"), ["/i/BDSP.app/Contents/MacOS/BDSP"])
        self.assertEqual(smoke.launch_command("windows", "C:/i/BDSP.exe"), ["C:/i/BDSP.exe"])
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
