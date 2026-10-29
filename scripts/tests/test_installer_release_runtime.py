"""Runtime release checks use synthetic wheels and never install host packages."""
import importlib.util
import hashlib
import stat
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer/scripts"))
import assemble_runtime


class ReleaseRuntimeTests(unittest.TestCase):
    def test_windows_inventory_rejects_reparse_points_and_existing_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "python.exe"
            path.write_bytes(b"fixture")
            lstat = Path.lstat
            def reparse(candidate, *args, **kwargs):
                if candidate == path:
                    return SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
                return lstat(candidate, *args, **kwargs)
            with patch.object(Path, "lstat", reparse), self.assertRaisesRegex(ValueError, "reparse"):
                assemble_runtime.windows_inventory(root)
            (root / "runtime.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "already contains"):
                assemble_runtime.windows_inventory(root)

    def test_windows_inventory_does_not_skip_unreadable_subtrees(self):
        with tempfile.TemporaryDirectory() as temporary:
            def unreadable(*args, **kwargs):
                kwargs["onerror"](PermissionError("unreadable"))
                return iter(())
            with patch.object(assemble_runtime.os, "walk", unreadable):
                with self.assertRaisesRegex(PermissionError, "unreadable"):
                    assemble_runtime.windows_inventory(Path(temporary))

    def test_windows_inventory_covers_python_extensions_and_notices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("python/python.exe", "python/DLLs/test.pyd", "python/LICENSE.txt"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            expected = {name: hashlib.sha256(name.encode()).hexdigest() for name in (
                "python/python.exe", "python/DLLs/test.pyd", "python/LICENSE.txt")}
            self.assertEqual(assemble_runtime.windows_inventory(root), expected)
            (root / "python/DLLs/test.pyd").write_bytes(b"changed")
            self.assertNotEqual(assemble_runtime.windows_inventory(root), expected)

    def test_shader_lock_covers_four_native_release_hosts(self):
        lock = json.loads((ROOT / "installer/runtime/shader-wheels.lock.json").read_text())
        base = json.loads(assemble_runtime.LOCK.read_text())
        self.assertEqual(lock["python"], base["python"])
        self.assertEqual(set(lock["targets"]), {
            "macos-aarch64", "macos-x86_64", "linux-aarch64", "linux-x86_64"})
        for target, wheels in lock["targets"].items():
            self.assertEqual(len(wheels), 7)
            self.assertEqual(sum(w.startswith("unitypy-") for w in wheels), 1)
            for name, digest in {**lock["common"], **wheels}.items():
                self.assertTrue(name.endswith(".whl"))
                self.assertEqual(len(digest), 64)
                self.assertTrue(all(c in "0123456789abcdef" for c in digest))

    def test_corrupt_wheel_is_rejected_before_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "fake.whl").write_bytes(b"changed wheel")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                assemble_runtime.verify_wheels(folder, {
                    "fake": {"wheel": "fake.whl", "sha256": "0" * 64}})

    def test_catalog_has_no_system_python_dependency(self):
        catalog = json.loads((ROOT / "installer/assets/dependencies.json").read_text())
        self.assertEqual(catalog["schema"], 1)
        identifiers = [item["id"] for item in catalog["components"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for item in catalog["components"]:
            for manager in ("brew", "apt", "dnf", "pacman"):
                self.assertFalse(any("python" in package for package in item.get(manager, [])))


if __name__ == "__main__":
    unittest.main()
