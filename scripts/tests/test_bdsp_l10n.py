import sys
import unittest
from pathlib import Path

LINUX = Path(__file__).resolve().parent.parent / "recomp" / "rt-bdsp" / "app" / "linux"
sys.path.insert(0, str(LINUX))
import bdsp_l10n as l10n  # noqa: E402


def keys(loc):
    return set(l10n.parse_strings((LINUX / "lproj" / (loc + ".lproj") / "Localizable.strings").read_text(encoding="utf-8")))


class LocaleChain(unittest.TestCase):
    def test_env_order_and_cleanup(self):
        self.assertEqual(l10n.system_locale({"LANG": "de_DE.UTF-8"}), "de_DE")
        self.assertEqual(l10n.system_locale({"LANG": "de_DE.UTF-8", "LC_ALL": "en_GB.UTF-8"}), "en_GB")
        self.assertEqual(l10n.system_locale({"LC_ALL": "C", "LANG": "en_US.UTF-8"}), "en_US")
        self.assertEqual(l10n.system_locale({"LANG": "sr_RS@latin"}), "sr_RS")
        self.assertEqual(l10n.system_locale({}), "")

    def test_chain(self):
        self.assertEqual(l10n.chain("de_DE"), ["de_DE", "de", "en"])
        self.assertEqual(l10n.chain("en_UK"), ["en_GB", "en"])
        self.assertEqual(l10n.chain("en-us"), ["en_US", "en"])
        self.assertEqual(l10n.chain("fr_FR"), ["fr_FR", "fr", "en"])
        self.assertEqual(l10n.chain(""), ["en"])


class Tables(unittest.TestCase):
    def test_de_and_en_have_the_same_keys(self):
        self.assertEqual(keys("de"), keys("en"))

    def test_variants_only_override_known_keys(self):
        for loc in ("en_US", "en_GB"):
            self.assertLessEqual(keys(loc), keys("en"))

    def test_languages(self):
        de, en, us, gb = (l10n.Translator(x) for x in ("de_DE", "en", "en_US", "en_GB"))
        self.assertEqual((de("Datei"), en("Datei")), ("Datei", "File"))
        self.assertEqual(de("Bildrate"), "Bildrate")
        self.assertEqual(en("Bildrate"), "Frame Rate")
        self.assertEqual((us("Minimieren"), gb("Minimieren")), ("Minimize", "Minimise"))
        self.assertEqual(us("Datei"), "File")
        self.assertEqual(l10n.Translator("en_UK")("Minimieren"), "Minimise")

    def test_unknown_language_falls_back_to_en(self):
        self.assertEqual(l10n.Translator("fr_FR")("Ansicht"), "View")
        self.assertEqual(l10n.Translator("")("Fenster"), "Window")
        self.assertEqual(l10n.Translator("fr_FR")("kein Schlüssel"), "kein Schlüssel")

    def test_format_keys(self):
        self.assertEqual(l10n.Translator("en")("Fenstergröße %d × %d") % (960, 540), "Window Size 960 × 540")

    def test_parser_escapes_and_comments(self):
        t = l10n.parse_strings('/* c */\n"a\\"b" = "x\\ny";\n')
        self.assertEqual(t, {'a"b': "x\ny"})


if __name__ == "__main__":
    unittest.main()
