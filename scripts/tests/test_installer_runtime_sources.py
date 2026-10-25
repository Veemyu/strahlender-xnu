"""Supply-chain checks for the source-wheel path; no network or compiler needed."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer" / "scripts"))
import build_source_wheel  # noqa: E402
import probe_runtime  # noqa: E402


class InstallerRuntimeSourceTests(unittest.TestCase):
    def test_manifest_and_source_versions_agree(self):
        manifest = json.loads(probe_runtime.MANIFEST.read_text())
        source = json.loads(build_source_wheel.SOURCE_LOCK.read_text())
        probe_runtime.validate_manifest(manifest)
        self.assertEqual(set(source["sources"]), {"capstone", "unicorn", "UnityPy", "tpk_ar"})
        pins = manifest["packages"]["base"] + manifest["packages"]["shaders"]
        for name, entry in source["sources"].items():
            if name != "tpk_ar":
                self.assertIn(f"{name}=={entry['version']}", pins)
            self.assertEqual(len(entry["sha256"]), 64)

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
