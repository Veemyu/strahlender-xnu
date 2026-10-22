"""Menu texts of the Linux Qt host from Localizable.strings (format and keys as in scripts/recomp/app/lproj of the Mac app).

The keys are the English texts (development language as on the Mac, NSLocalizedString). One folder <loc>.lproj/Localizable.strings per language
next to this file: de, es, pt; English (default and fallback) needs no texts of its own. The choice follows LC_ALL, LC_MESSAGES, LANG; chain:
locale (e.g. pt_BR), language (pt), then en; so pt_BR uses pt, es_MX/es_419 use es, and every English variant (en_US, en_GB, en_AU, …) is
plain English. If a key is missing everywhere, the key itself is shown. No Qt needed (testable).
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
    """LC_ALL, LC_MESSAGES, LANG (first one set, not C/POSIX) -> "de_DE", "en_GB", ... ; empty = unknown."""
    env = os.environ if env is None else env
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = env.get(var, "")
        if v and v not in ("C", "POSIX"):
            return re.split(r"[.@]", v)[0]
    return ""


def chain(locale):
    """Search order of the language folders, always with en at the end."""
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
    """Table with all keys: specific overrides general, en is underneath."""
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
