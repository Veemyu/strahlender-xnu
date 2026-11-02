import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.install import driver  # noqa: E402


def covered(source, portions):
    """Every file a portion copies, relative to the source."""
    found = []
    for rel, kind, names, _files, _size in portions:
        if kind == "loose":
            found += [(rel / name).as_posix() for name in names]
        else:
            found += [p.relative_to(source).as_posix() for p in (source / rel).rglob("*") if p.is_file()]
    return sorted(found)


class IosCopyPlanTests(unittest.TestCase):
    def tree(self, files):
        folder = Path(tempfile.mkdtemp(prefix="copy-plan-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        for name, size in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * size)
        return folder

    def test_every_file_is_copied_exactly_once_and_the_totals_match(self):
        source = self.tree({"top.bin": 10, "Data/a.bin": 100, "Data/Big/x/1.bin": 300, "Data/Big/x/2.bin": 300,
                            "Data/Big/y/3.bin": 300, "Data/Big/loose.bin": 5, "Data/Small/4.bin": 20})
        portions = driver._copy_portions(source, limit=350)
        expected = sorted(p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file())
        self.assertEqual(covered(source, portions), expected)
        self.assertEqual(sum(p[3] for p in portions), len(expected))
        self.assertEqual(sum(p[4] for p in portions), driver._tree_stats(source)[1])

    def test_a_big_folder_is_split_but_a_small_one_stays_whole(self):
        source = self.tree({"Big/x/1.bin": 300, "Big/y/2.bin": 300, "Small/3.bin": 50})
        whole = driver._copy_portions(source, limit=10_000)
        self.assertEqual([(p[0].as_posix(), p[1]) for p in whole], [(".", "tree")])
        split = driver._copy_portions(source, limit=400)
        self.assertEqual(sorted(p[0].as_posix() for p in split), ["Big/x", "Big/y", "Small"])
        self.assertTrue(all(kind == "tree" for _, kind, *_ in split))

    def test_loose_files_are_staged_as_a_folder_with_hard_links(self):
        source = self.tree({"Big/a.bin": 5, "Big/x/1.bin": 300, "Big/y/2.bin": 300})
        portions = driver._copy_portions(source, limit=400)
        loose = [p for p in portions if p[1] == "loose"]
        self.assertEqual([(p[0].as_posix(), p[2]) for p in loose], [("Big", ("a.bin",))])
        stage = driver._stage_loose_files(source / "Big", ("a.bin",), source.parent / (source.name + "-stage") / "0")
        self.addCleanup(lambda: __import__("shutil").rmtree(stage.parent, ignore_errors=True))
        self.assertEqual([p.name for p in stage.iterdir()], ["a.bin"])

    def test_sizes_are_written_for_people(self):
        self.assertEqual(driver._format_bytes(5 << 20), "5 MB")
        self.assertEqual(driver._format_bytes(3 << 30), "3.0 GB")


if __name__ == "__main__":
    unittest.main()
