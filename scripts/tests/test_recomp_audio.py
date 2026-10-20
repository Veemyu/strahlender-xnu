"""Compile and exercise the actual audio service using synthetic IPC buffers."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("clang"), "clang is required for the audio service harness")
class AudioServiceTests(unittest.TestCase):
    def test_pacing_bounds_and_lifetime(self):
        work = ROOT / "work" / "tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="audio-", dir=work) as directory:
            binary = Path(directory) / "audio_service_test"
            command = [
                "clang", "-std=gnu11", "-DBDSP_REBASE32", "-pthread",
                "-I", str(ROOT / "scripts/recomp/rt32"),
                "-I", str(ROOT / "scripts/recomp/rt"),
                "-I", str(ROOT / "scripts/recomp/upstream/runtime"),
                str(ROOT / "scripts/tests/audio_service_harness.c"), "-o", str(binary),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
