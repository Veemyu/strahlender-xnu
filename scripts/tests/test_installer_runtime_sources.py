"""Supply-chain checks for the source-wheel path; no network or compiler needed."""

import hashlib
import json
import os
import zipfile
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer" / "scripts"))
import build_source_wheel  # noqa: E402
import probe_runtime  # noqa: E402
import assemble_runtime  # noqa: E402
import prepare_codegen_reference  # noqa: E402


class InstallerRuntimeSourceTests(unittest.TestCase):
    def test_manifest_and_source_versions_agree(self):
        manifest = json.loads(probe_runtime.MANIFEST.read_text())
        source = json.loads(build_source_wheel.SOURCE_LOCK.read_text())
        probe_runtime.validate_manifest(manifest)
        self.assertEqual(set(source["sources"]), {"capstone", "unicorn", "UnityPy", "tpk_ar"})
        pins = manifest["packages"]["base"] + manifest["packages"]["shaders"]
        for name, entry in source["sources"].items():
            if name not in ("tpk_ar", "capstone"):
                self.assertIn(f"{name}=={entry['version']}", pins)
            self.assertEqual(len(entry["sha256"]), 64)

    def test_native_assets_survive_removal_of_python_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "python/lib/python3.13/site-packages/unicorn"
            for name in ("__init__.py", "unicorn_py3/engine.py", "include/unicorn/unicorn.h", "lib/libunicorn.so.2", "lib/libunicorn.a", "lib/unicorn.lib"):
                path = package / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"native fixture")
            self.assertEqual(assemble_runtime.strip_unicorn_bindings(root), 2)
            self.assertFalse((package / "__init__.py").exists())
            self.assertEqual((package / "lib/libunicorn.a").exists(), os.name == "nt")
            self.assertTrue((package / "lib/unicorn.lib").is_file())
            self.assertTrue((package / "include/unicorn/unicorn.h").is_file())
            self.assertEqual((package / "lib/libunicorn.so.2").read_bytes(), b"native fixture")

    def test_reference_packages_are_separate_and_verified_before_extraction(self):
        runtime = ROOT / "installer/runtime"
        base = json.loads((runtime / "wheels.lock.json").read_text())
        oracle = json.loads((runtime / "reference-wheels.lock.json").read_text())
        for target, wheels in base["targets"].items():
            self.assertFalse(any(p.startswith("capstone==") for p in wheels))
            self.assertEqual(oracle["targets"][target]["unicorn==2.1.4"], wheels["unicorn==2.1.4"])
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            wheel = folder / "test.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("../escape.py", "untrusted")
            output = folder / "output"
            with self.assertRaisesRegex(ValueError, "checksum"):
                prepare_codegen_reference.extract_verified(wheel, "0" * 64, output)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                prepare_codegen_reference.extract_verified(wheel, hashlib.sha256(wheel.read_bytes()).hexdigest(), output)
            self.assertFalse(output.exists())
            self.assertFalse((folder / "escape.py").exists())

    def test_corrupt_source_is_rejected_before_output_is_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "tpk_ar-0.2.4.tar.gz"
            archive.write_bytes(b"not the pinned source")
            output = root / "wheelhouse"
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                build_source_wheel.build("tpk_ar", archive, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
