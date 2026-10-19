using System;
using System.Collections.Generic;
using System.Globalization;
using Xnu.Data;

namespace Xnu.Field
{
    // CharacterGraphics (dpr_masterdatas/CharacterGraphics.json): Index = PlaceData.ObjectGraphicIndex einer Figur (0 bis 141),
    // FieldGraphic = Name des Modellbundles unter Characters/persons/field (z. B. fc2005_00), Scale = Größenfaktor.
    // Platzierungen mit größerem Index (500 Item-Ball, 501 Fällbaum, 556 Wand …) sind keine Figuren.
    public sealed class CharacterGraphicsTable
    {
        public const string RelativePath = "dpr_masterdatas/CharacterGraphics.json";
        public const string BundleFolder = "Characters/persons/field/";

        public sealed class Entry
        {
            public string Id = "";
            public string FieldGraphic = "";
            public float Scale = 1f;

            public string BundleName => BundleFolder + FieldGraphic;
        }

        readonly List<Entry> _entries = new List<Entry>();

        public int Count => _entries.Count;

        public static CharacterGraphicsTable Parse(string json)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object> ?? throw new FormatException("Wurzel ist kein JSON-Objekt");
            if (!(root.TryGetValue("instances", out var io) && io is List<object> insts && insts.Count > 0 && insts[0] is Dictionary<string, object> inst))
                throw new FormatException("instances fehlt");
            if (!(inst.TryGetValue("data", out var d) && d is Dictionary<string, object> data && data.TryGetValue("Data", out var lo) && lo is List<object> list))
                throw new FormatException("Data fehlt");
            var t = new CharacterGraphicsTable();
            foreach (var o in list)
            {
                var r = o as Dictionary<string, object> ?? throw new FormatException("Eintrag ist kein Objekt");
                var e = new Entry();
                if (r.TryGetValue("ID", out var id) && id is string s1) e.Id = s1;
                if (r.TryGetValue("FieldGraphic", out var fg) && fg is string s2) e.FieldGraphic = s2;
                if (r.TryGetValue("Scale", out var sc) && sc != null) e.Scale = (float)Convert.ToDouble(sc, CultureInfo.InvariantCulture);
                t._entries.Add(e);
            }
            return t;
        }

        // true: Index gehört zu einer Figur mit Modellnamen.
        public bool TryGet(int graphicIndex, out Entry entry)
        {
            entry = null;
            if (graphicIndex < 0 || graphicIndex >= _entries.Count) return false;
            entry = _entries[graphicIndex];
            return !string.IsNullOrEmpty(entry.FieldGraphic);
        }
    }
}
