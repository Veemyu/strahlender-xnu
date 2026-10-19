using System;
using System.Collections.Generic;

namespace Xnu.Text
{
    // Alle geladenen Textdateien. Schlüssel: (Sprache, Kanji-Flag, Kurzname). Die Sprache kommt aus dem Dateinamen-Präfix,
    // bei unbekanntem Präfix aus MsbtFile.LanguageId.
    public sealed class MessageBank
    {
        readonly Dictionary<string, MsbtFile> _files = new Dictionary<string, MsbtFile>(StringComparer.Ordinal);

        public int FileCount => _files.Count;

        public void Add(MsbtFile file)
        {
            if (file == null) throw new ArgumentNullException(nameof(file));
            var key = KeyOf(file);
            if (_files.ContainsKey(key)) throw new ArgumentException("Datei bereits vorhanden: " + file.Name);
            _files.Add(key, file);
        }

        public void AddRange(IEnumerable<MsbtFile> files)
        {
            foreach (var f in files) Add(f);
        }

        public bool TryGetFile(string shortName, MessageLanguage lang, out MsbtFile file, bool kanji = false) =>
            _files.TryGetValue(Key((int)lang, kanji, shortName), out file);

        public bool TryGetLabel(string shortName, string labelName, MessageLanguage lang, out MsbtLabel label, bool kanji = false)
        {
            label = null;
            return TryGetFile(shortName, lang, out var f, kanji) && f.TryGetLabel(labelName, out label);
        }

        public bool TryGetLabel(string shortName, int labelIndex, MessageLanguage lang, out MsbtLabel label, bool kanji = false)
        {
            label = null;
            return TryGetFile(shortName, lang, out var f, kanji) && f.TryGetLabel(labelIndex, out label);
        }

        static string KeyOf(MsbtFile f)
        {
            if (MessageLanguages.TrySplitFileName(f.Name, out var lang, out var kanji, out var shortName))
                return Key((int)lang, kanji, shortName);
            return Key(f.LanguageId, f.IsKanji, f.Name);
        }

        static string Key(int lang, bool kanji, string shortName) => lang + (kanji ? "k|" : "|") + shortName;
    }
}
