// Menu texts of the Linux Qt host from Localizable.strings (format and keys as in scripts/recomp/app/lproj of the Mac app).
// Port of bdsp_l10n.py (the rules are described there; the tests in scripts/tests/test_bdsp_l10n.py check the same lproj files):
// locale from LC_ALL, LC_MESSAGES, LANG; chain locale, language, en (so pt_BR -> pt, es_419 -> es); en_UK = en_GB; keys without an entry stay as they are.
#pragma once
#include <QDir>
#include <QFile>
#include <QHash>
#include <QRegularExpression>
#include <QString>
#include <QStringList>

namespace bdsp {

inline QString unescapeStrings(const QString &s) {
    QString out;
    out.reserve(s.size());
    for (int i = 0; i < s.size(); i++) {
        if (s[i] == QLatin1Char('\\') && i + 1 < s.size()) {
            QChar c = s[++i];
            out += c == QLatin1Char('n') ? QLatin1Char('\n') : c == QLatin1Char('t') ? QLatin1Char('\t') : c;
        } else {
            out += s[i];
        }
    }
    return out;
}

inline QHash<QString, QString> parseStrings(QString text) {
    static const QRegularExpression comment(QStringLiteral("/\\*.*?\\*/"), QRegularExpression::DotMatchesEverythingOption);
    static const QRegularExpression pair(QStringLiteral("^\\s*\"((?:[^\"\\\\]|\\\\.)*)\"\\s*=\\s*\"((?:[^\"\\\\]|\\\\.)*)\"\\s*;"),
                                         QRegularExpression::MultilineOption);
    text.remove(comment);
    QHash<QString, QString> table;
    for (auto it = pair.globalMatch(text); it.hasNext();) {
        QRegularExpressionMatch m = it.next();
        table.insert(unescapeStrings(m.captured(1)), unescapeStrings(m.captured(2)));
    }
    return table;
}

// LC_ALL, LC_MESSAGES, LANG (first one set, not C/POSIX), without .UTF-8 / @variant
inline QString systemLocale() {
    for (const char *var : {"LC_ALL", "LC_MESSAGES", "LANG"}) {
        QString v = qEnvironmentVariable(var);
        if (!v.isEmpty() && v != QLatin1String("C") && v != QLatin1String("POSIX"))
            return v.section(QRegularExpression(QStringLiteral("[.@]")), 0, 0);
    }
    return QString();
}

inline QStringList localeChain(QString locale) {
    locale.replace(QLatin1Char('-'), QLatin1Char('_'));
    const QStringList parts = locale.split(QLatin1Char('_'));
    const QString lang = parts.value(0).toLower();
    QString region = parts.value(1).toUpper();
    if (lang == QLatin1String("en") && region == QLatin1String("UK")) region = QStringLiteral("GB");
    QStringList out;
    if (!lang.isEmpty() && !region.isEmpty()) out << lang + QLatin1Char('_') + region;
    if (!lang.isEmpty()) out << lang;
    if (!out.contains(QLatin1String("en"))) out << QStringLiteral("en");
    return out;
}

class Translator {
public:
    Translator(const QString &locale, const QString &lprojDir) : locale_(locale) {
        const QStringList chain = localeChain(locale);
        for (int i = chain.size() - 1; i >= 0; i--) {  // en first, more specific locales override
            QFile f(QDir(lprojDir).filePath(chain[i] + QStringLiteral(".lproj/Localizable.strings")));
            if (f.open(QIODevice::ReadOnly)) {
                const QHash<QString, QString> h = parseStrings(QString::fromUtf8(f.readAll()));
                for (auto it = h.cbegin(); it != h.cend(); ++it) table_.insert(it.key(), it.value());
            }
        }
    }
    QString operator()(const char *key) const {
        const QString k = QString::fromUtf8(key);
        return table_.value(k, k);
    }
    const QString &locale() const { return locale_; }

private:
    QString locale_;
    QHash<QString, QString> table_;
};

}  // namespace bdsp
