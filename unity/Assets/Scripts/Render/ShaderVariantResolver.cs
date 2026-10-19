using System;
using System.Collections.Generic;
using System.Linq;

namespace Xnu.Render
{
    public enum PassRole { Forward, ShadowCaster, ForwardAdd }

    public enum ResolveQuality
    {
        Exact,               // Keyword-Menge der Variante == angeforderte Menge (nach Abzug fremder Keywords)
        EnvironmentRelaxed,  // exakt, nachdem Umgebungs-Keywords (Instancing, Bildschirmschatten) weggelassen wurden
        Nearest,             // keine exakte Variante: nächstliegende nach Rangfolge (siehe ShaderVariantResolver)
        Unavailable,         // Shader/Pass hat keine erzeugte Variante (nicht verpackbar oder gestrichen)
    }

    // Keywords, die nicht das Material, sondern der Zeichenaufruf bestimmt (Licht, Schatten, Instancing).
    public sealed class RenderEnvironment
    {
        public string[] Forward = { "DIRECTIONAL", "SHADOWS_SCREEN" };
        public string[] ShadowCaster = { "SHADOWS_DEPTH" };
        // Reihenfolge, in der Umgebungs-Keywords weggelassen werden, wenn keine exakte Variante existiert.
        public string[] RelaxOrder = { "INSTANCING_ON", "SHADOWS_SCREEN" };
        // Zeichnen mit Instancing (INSTANCING_ON). Standard aus: gemessen ist nur DrawMeshInstanced (docs/material-remap.md),
        // nicht das automatische Batching von MeshRenderern.
        public bool Instancing;

        public static RenderEnvironment Default => new RenderEnvironment();

        internal IEnumerable<string> For(PassRole role)
        {
            if (role == PassRole.ForwardAdd) return new string[0];
            var l = new List<string>(role == PassRole.Forward ? Forward : ShadowCaster);
            if (Instancing) l.Add("INSTANCING_ON");
            return l;
        }
    }

    public sealed class PassResolution
    {
        public int Pass;
        public PassRole Role;
        public VariantEntry Entry;                        // null bei Unavailable
        public ResolveQuality Quality;
        public string[] Requested = Array.Empty<string>();       // angeforderte Menge (nur Keywords des Passes)
        public string[] IgnoredMaterialKeywords = Array.Empty<string>(); // Material-Keywords, die der Pass nicht kennt
        public string[] MissingKeywords = Array.Empty<string>(); // angefordert, aber nicht in der Variante
        public string[] ExtraKeywords = Array.Empty<string>();   // in der Variante, aber nicht angefordert

        public bool IsExact => Quality == ResolveQuality.Exact;
    }

    // Wählt je Shader, Pass und Keyword-Menge die erzeugte Variante. Rein (ohne UnityEngine).
    //
    // Regeln (docs/material-remap.md, Abschnitt 3):
    //  1. Angefordert = (Material-Keywords + Umgebungs-Keywords) ∩ Keywords, die der Pass überhaupt kennt.
    //     Fremde Material-Keywords (z. B. _ALPHABLEND_ON beim Standard-Shader) haben im Original keine Wirkung.
    //  2. Exakte Übereinstimmung der Mengen.
    //  3. Sonst Umgebungs-Keywords in RelaxOrder schrittweise weglassen (kumulativ), jeweils exakt.
    //  4. Sonst nächstliegende Variante: kleinste Zahl fehlender Material-Keywords, dann fehlender Umgebungs-
    //     Keywords, dann überzähliger Keywords, dann kleinste Menge, dann Name (ordinal).
    //  5. Kein Eintrag für Shader/Pass: Unavailable (Aufrufer nimmt das Ersatzmaterial).
    public sealed class ShaderVariantResolver
    {
        readonly ShaderVariantIndex _index;

        public ShaderVariantResolver(ShaderVariantIndex index)
        {
            _index = index ?? throw new ArgumentNullException(nameof(index));
        }

        public ShaderVariantIndex Index => _index;

        // LightMode (aus dem Inventar) entscheidet; ohne Angabe die Schlüsselwörter des Passes.
        public static PassRole RoleOf(IReadOnlyCollection<string> universe, string lightMode)
        {
            switch ((lightMode ?? "").ToUpperInvariant())
            {
                case "SHADOWCASTER": return PassRole.ShadowCaster;
                case "FORWARDADD": return PassRole.ForwardAdd;
                case "": break;
                default: return PassRole.Forward;
            }
            return universe.Contains("SHADOWS_DEPTH") || universe.Contains("SHADOWS_CUBE") ? PassRole.ShadowCaster : PassRole.Forward;
        }

        public PassRole RoleOf(string shader, int pass) => RoleOf(_index.Universe(shader, pass), _index.LightMode(shader, pass));

        // Alle erzeugten Pässe des Shaders (aufsteigend nach Passnummer).
        public List<PassResolution> ResolveAll(string shader, IEnumerable<string> materialKeywords, RenderEnvironment env = null)
        {
            var res = new List<PassResolution>();
            foreach (var p in _index.Passes(shader)) res.Add(Resolve(shader, p, materialKeywords, env));
            return res;
        }

        public PassResolution Resolve(string shader, int pass, IEnumerable<string> materialKeywords, RenderEnvironment env = null)
        {
            env = env ?? RenderEnvironment.Default;
            var variants = _index.Variants(shader, pass);
            var universe = _index.Universe(shader, pass);
            var role = RoleOf(shader, pass);
            var r = new PassResolution { Pass = pass, Role = role };
            if (variants.Count == 0) { r.Quality = ResolveQuality.Unavailable; return r; }

            var matAll = new HashSet<string>(materialKeywords ?? Array.Empty<string>(), StringComparer.Ordinal);
            var mat = new HashSet<string>(matAll.Where(universe.Contains), StringComparer.Ordinal);
            r.IgnoredMaterialKeywords = matAll.Where(k => !universe.Contains(k)).OrderBy(k => k, StringComparer.Ordinal).ToArray();
            var envKw = new List<string>(env.For(role).Where(universe.Contains));

            var full = new HashSet<string>(mat, StringComparer.Ordinal);
            foreach (var k in envKw) full.Add(k);

            // Schritt 2 und 3: exakt, dann mit schrittweise gelockerter Umgebung (gemeldet wird gegen die volle Anforderung).
            var cur = new List<string>(envKw);
            for (var step = 0; ; step++)
            {
                var want = new HashSet<string>(mat, StringComparer.Ordinal);
                foreach (var k in cur) want.Add(k);
                var hit = variants.FirstOrDefault(v => SameSet(v.Keywords, want));
                if (hit != null)
                {
                    Fill(r, hit, full, step == 0 ? ResolveQuality.Exact : ResolveQuality.EnvironmentRelaxed);
                    return r;
                }
                if (step >= env.RelaxOrder.Length) break;
                cur.Remove(env.RelaxOrder[step]);
            }

            // Schritt 4: nächstliegende Variante, gemessen an der vollen Anforderung.
            var envSet = new HashSet<string>(envKw, StringComparer.Ordinal);
            var best = variants
                .Select(v => new
                {
                    v,
                    mm = mat.Count(k => !v.Keywords.Contains(k)),
                    me = envSet.Count(k => !v.Keywords.Contains(k)),
                    ex = v.Keywords.Count(k => !full.Contains(k)),
                })
                .OrderBy(x => x.mm).ThenBy(x => x.me).ThenBy(x => x.ex)
                .ThenBy(x => x.v.Keywords.Length).ThenBy(x => x.v.UnityName, StringComparer.Ordinal)
                .First().v;
            Fill(r, best, full, ResolveQuality.Nearest);
            return r;
        }

        static void Fill(PassResolution r, VariantEntry v, HashSet<string> want, ResolveQuality q)
        {
            r.Entry = v;
            r.Quality = q;
            r.Requested = want.OrderBy(k => k, StringComparer.Ordinal).ToArray();
            r.MissingKeywords = want.Where(k => !v.Keywords.Contains(k)).OrderBy(k => k, StringComparer.Ordinal).ToArray();
            r.ExtraKeywords = v.Keywords.Where(k => !want.Contains(k)).ToArray();
        }

        static bool SameSet(string[] a, HashSet<string> b)
        {
            if (a.Length != b.Count) return false;
            foreach (var k in a) if (!b.Contains(k)) return false;
            return true;
        }
    }
}
