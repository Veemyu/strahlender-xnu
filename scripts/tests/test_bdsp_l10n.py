import sys
import unittest
from pathlib import Path

LINUX = Path(__file__).resolve().parent.parent / "recomp" / "rt-bdsp" / "app" / "linux"
sys.path.insert(0, str(LINUX))
import bdsp_l10n as l10n  # noqa: E402

LANGUAGES = ("de", "es", "pt")


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
        self.assertEqual(l10n.chain("pt_BR"), ["pt_BR", "pt", "en"])
        self.assertEqual(l10n.chain("es_419"), ["es_419", "es", "en"])
        self.assertEqual(l10n.chain("en-us"), ["en_US", "en"])
        self.assertEqual(l10n.chain(""), ["en"])


class Tables(unittest.TestCase):
    def test_all_languages_have_the_same_keys(self):
        for loc in LANGUAGES[1:]:
            self.assertEqual(keys(LANGUAGES[0]), keys(loc), loc)

    def test_english_ids_exist_in_every_language(self):
        self.assertLessEqual(keys("en"), keys("de"))

    def test_languages(self):
        t = {x: l10n.Translator(x) for x in ("de_DE", "es_MX", "pt_BR", "pt_PT", "en_US", "en_AU")}
        self.assertEqual(t["de_DE"]("File"), "Datei")
        self.assertEqual(t["es_MX"]("File"), "Archivo")
        self.assertEqual(t["pt_BR"]("File"), "Arquivo")
        self.assertEqual(t["pt_PT"]("File"), "Arquivo")
        self.assertEqual(t["en_US"]("File"), "File")
        self.assertEqual(t["en_AU"]("Frame Rate"), "Frame Rate")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(l10n.Translator("fr_FR")("View"), "View")
        self.assertEqual(l10n.Translator("")("Window"), "Window")
        self.assertIn("Enter/Space", l10n.Translator("fr_FR")("KEYS_HELP"))

    def test_format_keys(self):
        self.assertEqual(l10n.Translator("de")("Window Size %d × %d") % (960, 540), "Fenstergröße 960 × 540")

    def test_parser_escapes_and_comments(self):
        t = l10n.parse_strings('/* c */\n"a\\"b" = "x\\ny";\n')
        self.assertEqual(t, {'a"b': "x\ny"})


if __name__ == "__main__":
    unittest.main()
