import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import repo_check  # noqa: E402


class RepoCheckTests(unittest.TestCase):
    def test_verbotene_endungen(self):
        for name in ("a.nsp", "x/b.xci", "c.NCA", "d.keys", "e.webm", "f.wem", "g.bnk", "h.ipa"):
            self.assertTrue(name.lower().endswith(repo_check.FORBIDDEN_SUFFIXES), name)

    def test_erlaubte_dateien(self):
        for name in ("scripts/ios_deploy.sh", "docs/kernziel.md", "unity/Assets/Scripts/Core/GameDataPaths.cs"):
            self.assertFalse(name.lower().endswith(repo_check.FORBIDDEN_SUFFIXES), name)
            self.assertFalse(any(p in name for p in repo_check.FORBIDDEN_PARTS), name)

    def test_schluesseldateien(self):
        for name in ("prod.keys", "Ryujinx/system/title.keys", "work/local.env", ".env"):
            self.assertTrue(repo_check.FORBIDDEN_NAMES.search(name), name)
        self.assertFalse(repo_check.FORBIDDEN_NAMES.search("scripts/keyboard.py"))

    def test_lokale_pfade(self):
        for name in ("work/romfs/x", "research/LASRecomp/a.c", "tools/hactool/hactool"):
            self.assertTrue(any(p in name for p in repo_check.FORBIDDEN_PARTS), name)

    def test_aktuelles_repo_ist_sauber(self):
        result = subprocess.run([sys.executable, str(Path(repo_check.__file__))], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
