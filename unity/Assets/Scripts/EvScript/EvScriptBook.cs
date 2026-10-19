using System;
using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.EvScript
{
    // Menge geladener Skriptdateien mit globalem Label-Verzeichnis (Original: EvDataManager._eventList + _findAllLabel).
    // Bei doppelten Labels gewinnt die zuerst geladene Datei (Annahme; das Original lädt je Karte nur wenige Dateien).
    // Die Suche ignoriert Groß-/Kleinschreibung (Annahme aus docs/masterdata.md: 3849 von 3868 TalkLabel treffen so).
    public sealed class EvScriptBook
    {
        readonly List<EventScriptFile> _files = new List<EventScriptFile>();
        readonly Dictionary<string, KeyValuePair<int, int>> _labels = new Dictionary<string, KeyValuePair<int, int>>(StringComparer.OrdinalIgnoreCase);

        public IReadOnlyList<EventScriptFile> Files => _files;
        public int DuplicateLabelCount { get; private set; }
        public int LabelCount => _labels.Count;

        public int Add(EventScriptFile file)
        {
            if (file == null) throw new ArgumentNullException(nameof(file));
            var fileIndex = _files.Count;
            _files.Add(file);
            for (var i = 0; i < file.Scripts.Count; i++)
            {
                var label = file.Scripts[i].Label;
                if (string.IsNullOrEmpty(label)) continue;
                if (_labels.ContainsKey(label)) { DuplicateLabelCount++; continue; }
                _labels.Add(label, new KeyValuePair<int, int>(fileIndex, i));
            }
            return fileIndex;
        }

        public static EvScriptBook FromFiles(IEnumerable<EventScriptFile> files)
        {
            var book = new EvScriptBook();
            foreach (var f in files) book.Add(f);
            return book;
        }

        public bool TryFind(string label, out int fileIndex, out int scriptIndex)
        {
            fileIndex = -1;
            scriptIndex = -1;
            if (string.IsNullOrEmpty(label)) return false;
            if (!_labels.TryGetValue(label, out var kv)) return false;
            fileIndex = kv.Key;
            scriptIndex = kv.Value;
            return true;
        }

        public bool Contains(string label) => TryFind(label, out _, out _);

        // EvScriptData.FindLabelScript: Skript mit diesem Label in genau dieser Datei (für Bewegungsskripte AC_*).
        public EventScript FindInFile(int fileIndex, string label)
        {
            if (fileIndex < 0 || fileIndex >= _files.Count || string.IsNullOrEmpty(label)) return null;
            foreach (var s in _files[fileIndex].Scripts)
                if (string.Equals(s.Label, label, StringComparison.OrdinalIgnoreCase)) return s;
            return null;
        }
    }
}
