import json
from pathlib import Path
import tempfile
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.install import filesystem
from scripts.install.progress import GeneratorProgress


class InstallerFilesystemTests(unittest.TestCase):
    def test_copy_and_publish_refuse_nested_trees_without_touching_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "keep").write_bytes(b"untouched")
            for destination in (source, source / "nested"):
                with self.assertRaisesRegex(ValueError, "outside"):
                    filesystem.copy_tree(source, destination)
                with self.assertRaisesRegex(ValueError, "separate"):
                    filesystem.publish_tree(source, destination)
            self.assertEqual(list(source.iterdir()), [source / "keep"])

    def test_copy_refuses_destination_reparse_points_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "destination"
            (source / "romfs").mkdir(parents=True)
            (source / "romfs/data").write_bytes(b"new")
            (destination / "romfs").mkdir(parents=True)
            (destination / "romfs/data").write_bytes(b"old")
            original = Path.lstat
            for blocked in (destination, destination / "romfs", destination / "romfs/data"):
                def flagged(path, *args, **kwargs):
                    if path == blocked:
                        return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
                    return original(path, *args, **kwargs)
                with self.subTest(blocked=blocked), patch.object(Path, "lstat", flagged):
                    with self.assertRaisesRegex(ValueError, "reparse"):
                        filesystem.copy_tree(source, destination)
                self.assertEqual((destination / "romfs/data").read_bytes(), b"old")

    def test_inaccessible_subtree_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            def inaccessible(*args, **kwargs):
                kwargs["onerror"](PermissionError("unreadable directory"))
                return iter(())
            with patch.object(filesystem.os, "walk", inaccessible):
                with self.assertRaisesRegex(PermissionError, "unreadable"):
                    filesystem.copy_tree(source, root / "destination")
                with self.assertRaisesRegex(PermissionError, "unreadable"):
                    filesystem.verify_inventory(source, {"data": "0" * 64})

    def test_copy_and_inventory_reject_changed_extra_missing_and_escape_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, copied = root / "source", root / "copy"
            (source / "romfs").mkdir(parents=True)
            (source / "romfs/data.bin").write_bytes(b"synthetic data")
            files = {"romfs/data.bin": filesystem.sha256(source / "romfs/data.bin")}
            (source / "receipt.json").write_text(json.dumps(files))
            progress = []
            filesystem.copy_tree(source, copied, lambda: progress.append(1))
            self.assertEqual(len(progress), 2)
            filesystem.verify_inventory(copied, files, ignored=("receipt.json",))
            for name in ("../escape", "/absolute", "C:relative", "a\\b", "a//b"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    filesystem.verify_inventory(copied, {name: "0" * 64})
            data = copied / "romfs/data.bin"
            data.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                filesystem.verify_inventory(copied, files, ignored=("receipt.json",))
            data.unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                filesystem.verify_inventory(copied, files, ignored=("receipt.json",))
            data.write_bytes(b"synthetic data")
            (copied / "unexpected.exe").write_bytes(b"not inventoried")
            with self.assertRaisesRegex(ValueError, "added"):
                filesystem.verify_inventory(copied, files, ignored=("receipt.json",))

    def test_shared_publication_rolls_back_and_preserves_a_failed_restore(self):
        for rollback_fails in (False, True):
            with self.subTest(rollback_fails=rollback_fails), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                candidate, destination = root / "candidate", root / "app"
                for path, content in ((candidate, b"new"), (destination, b"old")):
                    path.mkdir()
                    (path / "data.bin").write_bytes(content)
                rename = Path.rename
                def fail(path, target):
                    if path == candidate or (rollback_fails and path.name == "app" and path != destination):
                        raise OSError("injected replacement error")
                    return rename(path, target)
                with patch.object(Path, "rename", fail), self.assertRaises(OSError):
                    filesystem.publish_tree(candidate, destination)
                if rollback_fails:
                    backups = list(root.glob(".app-backup-*/app/data.bin"))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(backups[0].read_bytes(), b"old")
                else:
                    self.assertEqual((destination / "data.bin").read_bytes(), b"old")
                    self.assertEqual(list(root.glob(".app-backup-*")), [])
                self.assertEqual((candidate / "data.bin").read_bytes(), b"new")

    def test_shared_generator_progress_deduplicates_completion_and_rejects_bad_counts(self):
        progress = GeneratorProgress(4)
        self.assertEqual(progress.feed("main: analyzing module")["phase"], "analyze")
        self.assertEqual(progress.feed("main: progress 3/10 files 1")["completed"], 3)
        self.assertIsNone(progress.feed("main: progress 11/10 files 1"))
        self.assertEqual(progress.feed("main: wrote 1 chunks")["completed"], 1)
        self.assertIsNone(progress.feed("module=main"))
        self.assertEqual(progress.feed("sdk: progress 1/2 files 1")["modules_completed"], 1)


if __name__ == "__main__":
    unittest.main()
