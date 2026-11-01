import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.install import windows_setup as setup  # noqa: E402


class Clock:
    """A fake clock: sleeping advances it, so the retry logic runs without waiting."""
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


def locked(times, then=None):
    """An action that fails like a folder Windows still holds (WinError 145), `times` times."""
    state = {"calls": 0}

    def action(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] <= times:
            raise OSError(errno.ENOTEMPTY, "The directory is not empty", "llvm-mingw")
        return then
    action.state = state
    return action


class WindowsSetupLockTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="windows-setup-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.directory, ignore_errors=True))

    def test_a_locked_operation_is_retried_until_windows_lets_go(self):
        clock = Clock()
        action = locked(5, then="done")
        self.assertEqual(setup.retry(action, 90, sleep=clock.sleep, clock=clock), "done")
        self.assertEqual(action.state["calls"], 6)
        self.assertEqual(clock.now, 5.0)

    def test_a_lock_that_never_ends_is_reported_after_the_deadline(self):
        clock = Clock()
        action = locked(10 ** 6)
        with self.assertRaises(OSError):
            setup.retry(action, 20, sleep=clock.sleep, clock=clock)
        self.assertLessEqual(clock.now, 21)

    def test_remove_tree_waits_and_removes_the_whole_folder(self):
        tree = self.directory / "raw"
        (tree / "llvm-mingw/bin").mkdir(parents=True)
        (tree / "llvm-mingw/bin/clang.exe").write_bytes(b"x")
        real = __import__("shutil").rmtree
        calls = {"n": 0}

        def flaky(path, **kwargs):
            calls["n"] += 1
            if calls["n"] < 4:
                raise OSError(errno.ENOTEMPTY, "The directory is not empty", str(path))
            return real(path, **kwargs)
        clock = Clock()
        with mock.patch.object(setup.shutil, "rmtree", side_effect=flaky):
            self.assertTrue(setup.remove_tree(tree, 90, sleep=clock.sleep, clock=clock))
        self.assertFalse(tree.exists())
        self.assertEqual(calls["n"], 4)

    def test_remove_tree_never_raises_when_the_folder_stays_locked(self):
        tree = self.directory / "raw"
        tree.mkdir()
        clock = Clock()
        with mock.patch.object(setup.shutil, "rmtree", side_effect=OSError(errno.ENOTEMPTY, "locked")):
            self.assertFalse(setup.remove_tree(tree, 5, sleep=clock.sleep, clock=clock))
        self.assertFalse(tree.exists())   # moved out of the way: the next run starts clean
        self.assertTrue(any(p.name.startswith("raw.old-") for p in self.directory.iterdir()))

    def test_move_tree_renames_after_a_lock_and_copies_when_it_stays(self):
        source = self.directory / "raw/llvm"
        (source / "bin").mkdir(parents=True)
        (source / "bin/clang.exe").write_bytes(b"clang")
        clock = Clock()
        real = os.replace
        calls = {"n": 0}

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(errno.EACCES, "in use")
            return real(a, b)
        with mock.patch.object(setup.os, "replace", side_effect=flaky):
            setup.move_tree(source, self.directory / "out/toolchain", 90, sleep=clock.sleep, clock=clock)
        self.assertEqual((self.directory / "out/toolchain/bin/clang.exe").read_bytes(), b"clang")
        self.assertFalse(source.exists())
        # a folder that cannot be renamed at all is copied, and the source is cleaned up without failing
        second = self.directory / "raw2/llvm"
        (second / "bin").mkdir(parents=True)
        (second / "bin/clang.exe").write_bytes(b"clang2")
        with mock.patch.object(setup.os, "replace", side_effect=PermissionError(errno.EACCES, "in use")), \
                mock.patch.object(setup.shutil, "rmtree", side_effect=OSError(errno.ENOTEMPTY, "locked")):
            setup.move_tree(second, self.directory / "out2/toolchain", 3, sleep=clock.sleep, clock=clock)
        self.assertEqual((self.directory / "out2/toolchain/bin/clang.exe").read_bytes(), b"clang2")

    def test_leftovers_of_an_interrupted_setup_are_cleared(self):
        out = self.directory / "out"
        for name in ("downloads", "raw/toolchain", "toolchain/bin", "qt"):
            (out / name).mkdir(parents=True)
            (out / name / "file").write_text("x")
        (out / "catalog.json").write_text("{}")
        (out / "keep.txt").write_text("not ours")
        setup.clear_leftovers(out)
        self.assertEqual([p.name for p in out.iterdir()], ["keep.txt"])


if __name__ == "__main__":
    unittest.main()
