"""Menütexte der Linux-Qt-Hülle aus Localizable.strings (Format und Schlüssel wie scripts/recomp/app/lproj der Mac-App).

Die Schlüssel sind die deutschen Texte (Entwicklungssprache wie am Mac, NSLocalizedString). Je Sprache ein Ordner <loc>.lproj/Localizable.strings
neben dieser Datei: de, en (Standard und Rückfall), en_US, en_GB. Die Auswahl folgt LC_ALL, LC_MESSAGES, LANG; Kette: Ort (z. B. en_GB), Sprache (en),
dann en; en_UK gilt als en_GB; de_DE ist de. Fehlt ein Schlüssel überall, bleibt der Schlüssel selbst stehen. Kein Qt nötig (testbar).
"""
import os
import re

LPROJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lproj")
FALLBACK = "en"
_PAIR = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', re.M)
_ESC = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unescape(s):
    return re.sub(r"\\(.)", lambda m: _ESC.get(m.group(1), m.group(1)), s)


def parse_strings(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return {_unescape(k): _unescape(v) for k, v in _PAIR.findall(text)}


def system_locale(env=None):
    """LC_ALL, LC_MESSAGES, LANG (erste gesetzte, nicht C/POSIX) -> "de_DE", "en_GB", ... ; leer = unbekannt."""
    env = os.environ if env is None else env
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = env.get(var, "")
        if v and v not in ("C", "POSIX"):
            return re.split(r"[.@]", v)[0]
    return ""


def chain(locale):
    """Suchreihenfolge der Sprachordner, immer mit en am Ende."""
    loc = (locale or "").replace("-", "_")
    parts = loc.split("_")
    lang = parts[0].lower()
    region = parts[1].upper() if len(parts) > 1 else ""
    if lang == "en" and region == "UK":
        region = "GB"
    out = []
    if lang and region:
        out.append("%s_%s" % (lang, region))
    if lang:
        out.append(lang)
    if FALLBACK not in out:
        out.append(FALLBACK)
    return out


def load(locale=None, base=LPROJ):
    """Tabelle mit allen Schlüsseln: spezifisch überschreibt allgemein, en liegt darunter."""
    table = {}
    for name in reversed(chain(system_locale() if locale is None else locale)):
        path = os.path.join(base, name + ".lproj", "Localizable.strings")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                table.update(parse_strings(f.read()))
    return table


class Translator:
    def __init__(self, locale=None, base=LPROJ):
        self.locale = system_locale() if locale is None else locale
        self.table = load(self.locale, base)

    def __call__(self, key):
        return self.table.get(key, key)
