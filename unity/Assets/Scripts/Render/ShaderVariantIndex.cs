using System;
using System.Collections.Generic;
using System.Linq;
using Xnu.Data;

namespace Xnu.Render
{
    // Eine erzeugte Shader-Variante (Eintrag aus variants.json von scripts/shader_wrap_all.py).
    public sealed class VariantEntry
    {
        public string Shader;        // Name des Original-Shaders
        public int SubShader;
        public int Pass;
        public string[] Keywords;    // sortiert, ordinal
        public string UnityName;     // Name für Shader.Find
        public string LightMode;     // LIGHTMODE-Tag des Passes oder null
        public string[] EmbeddedShadowKeywords;   // Schattenwurf-Pass im selben Shader (variants.json: "shadow"), sonst null

        public override string ToString() => UnityName;
    }

    // Verzeichnis aller erzeugten Varianten: Shader -> Pass -> Liste. Rein (ohne UnityEngine).
    public sealed class ShaderVariantIndex
    {
        public const string DefaultNamePrefix = "XNU/Generated/";

        sealed class PassData
        {
            public readonly List<VariantEntry> Variants = new List<VariantEntry>();
            public readonly HashSet<string> Universe = new HashSet<string>(StringComparer.Ordinal);
            public string LightMode;
        }

        readonly Dictionary<string, SortedDictionary<int, PassData>> _byShader =
            new Dictionary<string, SortedDictionary<int, PassData>>(StringComparer.Ordinal);

        public int Count { get; private set; }

        public IEnumerable<string> ShaderNames => _byShader.Keys;

        public void Add(VariantEntry e)        {
            if (!_byShader.TryGetValue(e.Shader, out var passes))
                _byShader[e.Shader] = passes = new SortedDictionary<int, PassData>();
            if (!passes.TryGetValue(e.Pass, out var pd)) passes[e.Pass] = pd = new PassData();
            pd.Variants.Add(e);
            if (e.LightMode != null && pd.LightMode == null) pd.LightMode = e.LightMode;
            foreach (var k in e.Keywords) pd.Universe.Add(k);
            Count++;
        }

        public bool HasShader(string shader) => shader != null && _byShader.ContainsKey(shader);

        public IReadOnlyList<int> Passes(string shader)
        {
            var l = new List<int>();
            if (shader != null && _byShader.TryGetValue(shader, out var p)) l.AddRange(p.Keys);
            return l;
        }

        public IReadOnlyList<VariantEntry> Variants(string shader, int pass) =>
            TryPass(shader, pass, out var pd) ? pd.Variants : (IReadOnlyList<VariantEntry>)Array.Empty<VariantEntry>();

        // Alle Keywords, die in irgendeiner Variante dieses Passes vorkommen.
        public IReadOnlyCollection<string> Universe(string shader, int pass) =>
            TryPass(shader, pass, out var pd) ? pd.Universe : (IReadOnlyCollection<string>)Array.Empty<string>();

        // LIGHTMODE-Tag des Passes aus dem Inventar (FORWARDBASE, FORWARDADD, SHADOWCASTER) oder null.
        public string LightMode(string shader, int pass) => TryPass(shader, pass, out var pd) ? pd.LightMode : null;

        bool TryPass(string shader, int pass, out PassData pd)
        {
            pd = null;
            return shader != null && _byShader.TryGetValue(shader, out var p) && p.TryGetValue(pass, out pd);
        }

        // Liest variants.json: {"variants":[{"file","shader","sub","pass","keywords":[..],"status":"ok"}]}.
        // Nur SubShader 0 und Status "ok" (nicht verpackbare Varianten gibt es zur Laufzeit nicht).
        public static ShaderVariantIndex FromJson(string json, string namePrefix = DefaultNamePrefix)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object>
                       ?? throw new FormatException("variants.json: Objekt erwartet");
            var idx = new ShaderVariantIndex();
            if (!root.TryGetValue("variants", out var vo) || !(vo is List<object> list)) return idx;
            foreach (var o in list)
            {
                var d = o as Dictionary<string, object>;
                if (d == null) continue;
                if (d.TryGetValue("status", out var st) && (st as string) != "ok") continue;
                var sub = d.TryGetValue("sub", out var so) ? Convert.ToInt32(so) : 0;
                if (sub != 0) continue;
                var kw = new List<string>();
                if (d.TryGetValue("keywords", out var ko) && ko is List<object> kl)
                    foreach (var k in kl) kw.Add((string)k);
                kw.Sort(StringComparer.Ordinal);
                var file = (string)d["file"];
                if (file.EndsWith(".shader", StringComparison.Ordinal)) file = file.Substring(0, file.Length - 7);
                idx.Add(new VariantEntry
                {
                    Shader = (string)d["shader"],
                    SubShader = sub,
                    Pass = Convert.ToInt32(d["pass"]),
                    Keywords = kw.ToArray(),
                    UnityName = namePrefix + file,
                    LightMode = d.TryGetValue("lightMode", out var lm) ? lm as string : null,
                    EmbeddedShadowKeywords = d.TryGetValue("shadow", out var sho) && sho is Dictionary<string, object> shd
                                             && shd.TryGetValue("keywords", out var shk) && shk is List<object> shl
                        ? shl.Select(x => (string)x).ToArray() : null,
                });
            }
            return idx;
        }
    }
}
