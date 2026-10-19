using System;

namespace Xnu.Text
{
    // Zuordnung Sprache <-> Bundle-Ordner, Dateipräfix, Varianten-Endung und Schriftbundle.
    // Die Werte stammen aus den Bundles (Message/<Ordner>, Präfixe der MsbtData-Namen) und dem Katalog (Varianten .en .fr ...).
    public static class MessageLanguages
    {
        // Ordner unter AssetAssistant/Message. Japanisch hat zwei Fassungen (Kana, Kanji).
        public static string BundleFolder(MessageLanguage lang, bool kanji = false)
        {
            switch (lang)
            {
                case MessageLanguage.Jpn: return kanji ? "jpn_kanji" : "jpn";
                case MessageLanguage.Usa: return "english";
                case MessageLanguage.Fra: return "french";
                case MessageLanguage.Ita: return "italian";
                case MessageLanguage.Deu: return "german";
                case MessageLanguage.Esp: return "spanish";
                case MessageLanguage.Kor: return "korean";
                case MessageLanguage.Sch: return "simp_chinese";
                case MessageLanguage.Tch: return "trad_chinese";
                default: throw new ArgumentOutOfRangeException(nameof(lang));
            }
        }

        // Präfix der Dateinamen innerhalb des Bundles (z. B. "german_", "simp_", "jpn_kanji_").
        public static string FilePrefix(MessageLanguage lang, bool kanji = false)
        {
            switch (lang)
            {
                case MessageLanguage.Jpn: return kanji ? "jpn_kanji_" : "jpn_";
                case MessageLanguage.Usa: return "english_";
                case MessageLanguage.Fra: return "french_";
                case MessageLanguage.Ita: return "italian_";
                case MessageLanguage.Deu: return "german_";
                case MessageLanguage.Esp: return "spanish_";
                case MessageLanguage.Kor: return "korean_";
                case MessageLanguage.Sch: return "simp_";
                case MessageLanguage.Tch: return "trad_";
                default: throw new ArgumentOutOfRangeException(nameof(lang));
            }
        }

        // Endung der Sprachvarianten im Katalog (Bundle-Name "<name>_lang.<endung>"); die Zuordnung ist aus den Namen abgeleitet.
        public static string VariantSuffix(MessageLanguage lang)
        {
            switch (lang)
            {
                case MessageLanguage.Jpn: return "jp";
                case MessageLanguage.Usa: return "en";
                case MessageLanguage.Fra: return "fr";
                case MessageLanguage.Ita: return "it";
                case MessageLanguage.Deu: return "ge";
                case MessageLanguage.Esp: return "sp";
                case MessageLanguage.Kor: return "ko";
                case MessageLanguage.Sch: return "si";
                case MessageLanguage.Tch: return "tr";
                default: throw new ArgumentOutOfRangeException(nameof(lang));
            }
        }

        // EFIGS = Englisch, Französisch, Italienisch, Deutsch, Spanisch (gemeinsame Schrift).
        public static bool IsEfigs(MessageLanguage lang) =>
            lang == MessageLanguage.Usa || lang == MessageLanguage.Fra || lang == MessageLanguage.Ita ||
            lang == MessageLanguage.Deu || lang == MessageLanguage.Esp;

        // Schriftbundle unter Dpr/font (TextMeshPro-Schriftassets).
        public static string FontBundle(MessageLanguage lang)
        {
            if (IsEfigs(lang)) return "efigs_font";
            switch (lang)
            {
                case MessageLanguage.Jpn: return "jpn_font";
                case MessageLanguage.Kor: return "kor_font";
                case MessageLanguage.Sch: return "sch_font";
                case MessageLanguage.Tch: return "tch_font";
                default: throw new ArgumentOutOfRangeException(nameof(lang));
            }
        }

        // Switch-Systemsprache (nn::settings::LanguageCode-Index, NXLangId) -> Spielsprache. Nicht unterstützte Sprachen: Englisch.
        public static MessageLanguage FromSystemLanguage(int nxLanguageId)
        {
            switch (nxLanguageId)
            {
                case 0: return MessageLanguage.Jpn;
                case 2: return MessageLanguage.Fra;
                case 3: return MessageLanguage.Deu;
                case 4: return MessageLanguage.Ita;
                case 5: return MessageLanguage.Esp;
                case 7: return MessageLanguage.Kor;
                case 15: return MessageLanguage.Sch;
                case 16: return MessageLanguage.Tch;
                default: return MessageLanguage.Usa;
            }
        }

        // Zerlegt "german_ss_bag" in Sprache, Kanji-Flag und Kurzname. Längere Präfixe zuerst ("jpn_kanji_" vor "jpn_").
        public static bool TrySplitFileName(string fileName, out MessageLanguage lang, out bool kanji, out string shortName)
        {
            lang = MessageLanguage.Usa;
            kanji = false;
            shortName = "";
            if (string.IsNullOrEmpty(fileName)) return false;
            var order = new[]
            {
                (MessageLanguage.Jpn, true), (MessageLanguage.Jpn, false), (MessageLanguage.Usa, false), (MessageLanguage.Fra, false),
                (MessageLanguage.Ita, false), (MessageLanguage.Deu, false), (MessageLanguage.Esp, false), (MessageLanguage.Kor, false),
                (MessageLanguage.Sch, false), (MessageLanguage.Tch, false),
            };
            foreach (var (l, k) in order)
            {
                var prefix = FilePrefix(l, k);
                if (fileName.Length > prefix.Length && fileName.StartsWith(prefix, StringComparison.Ordinal))
                {
                    lang = l;
                    kanji = k;
                    shortName = fileName.Substring(prefix.Length);
                    return true;
                }
            }
            return false;
        }
    }
}
