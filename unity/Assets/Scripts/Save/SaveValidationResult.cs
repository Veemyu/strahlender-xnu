using System.Collections.Generic;

namespace Xnu.Save
{
    // Ergebnis von SaveValidator.Validate: alle Befunde, ohne Ausnahmen.
    public sealed class SaveValidationResult
    {
        readonly List<string> _problems = new List<string>();

        // False, wenn nicht einmal die Version lesbar war (Datei < 4 Byte).
        public bool HasHeader { get; internal set; }
        public int Version { get; internal set; }
        public int Size { get; internal set; }
        public int? ExpectedSize { get; internal set; }
        // null: keine Erwartung (Version unbekannt oder < 0x25).
        public bool? SizeOk { get; internal set; }
        // null: nicht prüfbar (Version < 0x25, unbekannt oder Datei abgeschnitten).
        public bool? HashValid { get; internal set; }

        public IReadOnlyList<string> Problems => _problems;

        public bool IsValid => HasHeader && HashValid == true && SizeOk == true;

        internal void AddProblem(string message) => _problems.Add(message);
    }
}
