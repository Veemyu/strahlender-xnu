using System;
using System.Collections.Generic;
using System.Linq;
using Xnu.Data;

namespace Xnu.Render
{
    public sealed class MaterialTextureRef
    {
        public string Property;
        public bool IsNull;          // Eigenschaft ohne Textur
        public string TextureName;   // Name der Textur im Bundle (Auflösung zur Laufzeit über Name + Größe)
        public int Width, Height, Format;
        public float ScaleX = 1, ScaleY = 1, OffsetX, OffsetY;
    }

    // Ein Material aus dem Export (scripts/material_export.py), rein (ohne UnityEngine).
    public sealed class MaterialRecord
    {
        public string Bundle;
        public string Name;
        public long PathId;
        public string Shader;                    // Original-Shadername, null = nicht aufgelöst
        public string[] Keywords = Array.Empty<string>();   // m_ShaderKeywords, sortiert
        public int RenderQueue = -1;             // m_CustomRenderQueue, -1 = Shader-Standard
        public bool Instancing;
        public Dictionary<string, string> Tags = new Dictionary<string, string>();
        public string[] DisabledPasses = Array.Empty<string>();
        public Dictionary<string, float> Floats = new Dictionary<string, float>();
        public Dictionary<string, float[]> Colors = new Dictionary<string, float[]>();
        public Dictionary<string, MaterialTextureRef> Textures = new Dictionary<string, MaterialTextureRef>();

        public string Key => Bundle + "/" + Name;
    }

    // Alle Materialdaten eines oder mehrerer Bundles; Suche nach (Bundle, Name[, Keywords]).
    public sealed class MaterialCatalog
    {
        readonly Dictionary<string, List<MaterialRecord>> _byKey = new Dictionary<string, List<MaterialRecord>>(StringComparer.Ordinal);

        public int Count { get; private set; }
        public int Duplicates { get; private set; }

        public void Add(MaterialRecord r)
        {
            if (!_byKey.TryGetValue(r.Key, out var l)) _byKey[r.Key] = l = new List<MaterialRecord>();
            if (l.Count > 0) Duplicates++;
            l.Add(r);
            Count++;
        }

        // Bei doppeltem Namen im Bundle entscheidet die Keyword-Menge, sonst der erste Eintrag (Reihenfolge der Datei).
        public MaterialRecord Find(string bundle, string name, IEnumerable<string> keywords = null)
        {
            if (!_byKey.TryGetValue(bundle + "/" + name, out var l)) return null;
            if (l.Count == 1 || keywords == null) return l[0];
            var want = new HashSet<string>(keywords, StringComparer.Ordinal);
            return l.FirstOrDefault(r => r.Keywords.Length == want.Count && r.Keywords.All(want.Contains)) ?? l[0];
        }

        public IEnumerable<MaterialRecord> All => _byKey.Values.SelectMany(l => l);

        public void LoadJson(string json)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object> ?? throw new FormatException("Materialexport: Objekt erwartet");
            var bundle = (string)root["bundle"];
            foreach (var o in (List<object>)root["materials"])
            {
                var d = (Dictionary<string, object>)o;
                if (d.ContainsKey("error")) continue;
                Add(Parse(bundle, d));
            }
        }

        static float F(object o) => Convert.ToSingle(o, System.Globalization.CultureInfo.InvariantCulture);

        static MaterialRecord Parse(string bundle, Dictionary<string, object> d)
        {
            var r = new MaterialRecord
            {
                Bundle = bundle,
                Name = (string)d["name"],
                PathId = d.TryGetValue("pathId", out var pid) ? Convert.ToInt64(pid) : 0,
                Shader = d.TryGetValue("shader", out var sh) ? sh as string : null,
                RenderQueue = d.TryGetValue("renderQueue", out var rq) ? Convert.ToInt32(rq) : -1,
                Instancing = d.TryGetValue("instancing", out var ins) && ins is bool b && b,
            };
            if (d.TryGetValue("keywords", out var ko) && ko is List<object> kl)
            {
                r.Keywords = kl.Select(x => (string)x).OrderBy(x => x, StringComparer.Ordinal).ToArray();
            }
            if (d.TryGetValue("tags", out var to) && to is Dictionary<string, object> td)
                foreach (var kv in td) r.Tags[kv.Key] = (string)kv.Value;
            if (d.TryGetValue("disabledPasses", out var dp) && dp is List<object> dl)
                r.DisabledPasses = dl.Select(x => (string)x).ToArray();
            if (d.TryGetValue("floats", out var fo) && fo is Dictionary<string, object> fd)
                foreach (var kv in fd) r.Floats[kv.Key] = F(kv.Value);
            if (d.TryGetValue("colors", out var co) && co is Dictionary<string, object> cd)
                foreach (var kv in cd) r.Colors[kv.Key] = ((List<object>)kv.Value).Select(F).ToArray();
            if (d.TryGetValue("textures", out var xo) && xo is Dictionary<string, object> xd)
                foreach (var kv in xd)
                {
                    var t = (Dictionary<string, object>)kv.Value;
                    var tr = new MaterialTextureRef { Property = kv.Key, IsNull = !t.ContainsKey("pathId") };
                    if (t.TryGetValue("texName", out var tn)) tr.TextureName = tn as string;
                    if (t.TryGetValue("width", out var w)) tr.Width = Convert.ToInt32(w);
                    if (t.TryGetValue("height", out var h)) tr.Height = Convert.ToInt32(h);
                    if (t.TryGetValue("format", out var f)) tr.Format = Convert.ToInt32(f);
                    if (t.TryGetValue("scale", out var s) && s is List<object> sl && sl.Count == 2) { tr.ScaleX = F(sl[0]); tr.ScaleY = F(sl[1]); }
                    if (t.TryGetValue("offset", out var of) && of is List<object> ol && ol.Count == 2) { tr.OffsetX = F(ol[0]); tr.OffsetY = F(ol[1]); }
                    r.Textures[kv.Key] = tr;
                }
            return r;
        }
    }
}
