"""The minimum macOS and iOS live in scripts/recomp/macos_target.sh; every literal copy has to agree with it."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/recomp/app"))
sys.path.insert(0, str(ROOT / "scripts"))

TARGET_FILE = ROOT / "scripts/recomp/macos_target.sh"
SUFFIXES = {".sh", ".pbxproj", ".in", ".plist", ".inc"}
LITERALS = [
    re.compile(r"-target arm64-apple-ios(\d+(?:\.\d+)*)"),
    re.compile(r"air64-apple-ios(\d+(?:\.\d+)*)"),
    re.compile(r"IPHONEOS_DEPLOYMENT_TARGET = (\d+(?:\.\d+)*)"),
    re.compile(r"MinimumOSVersion</key>\s*<string>(\d+(?:\.\d+)*)"),
]


def setting(name):
    return re.search(r"^%s=(\d+(?:\.\d+)*)\s*$" % name, TARGET_FILE.read_text(encoding="utf-8"), re.MULTILINE).group(1)


class DeploymentTargetTests(unittest.TestCase):
    def test_every_literal_ios_target_matches_the_shared_setting(self):
        expected = setting("BDSP_IOS_MIN")
        checked = 0
        for path in sorted((ROOT / "scripts").rglob("*")):
            if path.suffix not in SUFFIXES or not path.is_file() or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in LITERALS:
                for found in pattern.findall(text):
                    checked += 1
                    self.assertEqual(found, expected, "%s names iOS %s, macos_target.sh says %s" % (path.relative_to(ROOT), found, expected))
        self.assertGreater(checked, 3)

    def test_the_icon_compiler_reads_the_same_values(self):
        import icon_composer
        self.assertEqual(icon_composer.macos_min(), setting("BDSP_MACOS_MIN"))
        self.assertEqual(icon_composer.ios_min(), setting("BDSP_IOS_MIN"))


if __name__ == "__main__":
    unittest.main()
