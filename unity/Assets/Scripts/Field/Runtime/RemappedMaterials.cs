using System;
using System.Collections.Generic;
using UnityEngine;
using Xnu.Render;

namespace Xnu.Field
{
    // Quelle der sichtbaren Materialien beim Kartenbau. Originalmaterialien (Fehlershader) werden nie zugewiesen.
    public interface IMapMaterialSource
    {
        Material For(Material original);
        // true = Material darf gezeichnet werden (Fallback- oder erzeugter Shader).
        bool IsAllowed(Material m);
        void Destroy();
    }

    // Material-Umbau über Xnu.Render (docs/material-remap.md): Exporteintrag des Bundles suchen, Variante wählen,
    // Material mit dem erzeugten Shader bauen; ohne Eintrag/Variante/Shader das Ersatzmaterial.
    // Nur erzeugte Shader ("XNU/Generated/…") und der Ersatz-Shader dürfen gezeichnet werden.
    public sealed class RemappedMaterials : IMapMaterialSource
    {
        readonly FallbackMaterials _fallback;
        readonly MaterialCatalog _catalog;
        readonly MaterialRemapper _remapper;
        readonly string _bundle;
        readonly Dictionary<int, Material> _cache = new Dictionary<int, Material>();
        readonly List<RemapResult> _results = new List<RemapResult>();
        readonly HashSet<Material> _fallbackMade = new HashSet<Material>();

        public int Remapped { get; private set; }
        public int FellBack { get; private set; }
        public int NoRecord { get; private set; }
        public int Incomplete { get; private set; }
        public List<string> Notes { get; } = new List<string>();

        public RemappedMaterials(FallbackMaterials fallback, MaterialCatalog catalog, ShaderVariantIndex index, string bundleName)
        {
            _fallback = fallback ?? throw new ArgumentNullException(nameof(fallback));
            _catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
            _bundle = bundleName ?? throw new ArgumentNullException(nameof(bundleName));
            _remapper = new MaterialRemapper(new ShaderVariantResolver(index));
        }

        public bool IsAllowed(Material m)
        {
            if (m == null) return false;
            if (_fallback.IsFallback(m)) return true;
            var s = m.shader;
            return s != null && s.name.StartsWith(ShaderVariantIndex.DefaultNamePrefix, StringComparison.Ordinal);
        }

        public Material For(Material original)
        {
            if (original == null) return _fallback.For(null);
            var id = original.GetInstanceID();
            if (_cache.TryGetValue(id, out var m)) return m;

            // Name und Keywords der Quelle: nur Name/Keywords werden gelesen (Eigenschaften über die Material-API nicht).
            var rec = _catalog.Find(_bundle, original.name, original.shaderKeywords);
            if (rec == null) { NoRecord++; m = Fallback(original); FellBack++; }
            else
            {
                var res = _remapper.Remap(original, rec);
                _results.Add(res);
                if (res.HasForward)
                {
                    m = res.Forward[0];
                    Remapped++;
                    if (!res.Complete) { Incomplete++; Notes.Add(original.name + ": " + string.Join("; ", res.Notes)); }
                }
                else { m = Fallback(original); FellBack++; Notes.Add(original.name + ": " + string.Join("; ", res.Notes)); }
            }
            _cache[id] = m;
            return m;
        }

        // Ersatzmaterial für ein Karten-Original; es wird beim Abbau der Karte freigegeben. Der Ersatzspeicher selbst gehört dem
        // Aufrufer (Spielerfigur und NPC-Marker teilen ihn: sie wurden früher beim Zonenwechsel magenta).
        Material Fallback(Material original)
        {
            var m = _fallback.For(original);
            if (m != null) _fallbackMade.Add(m);
            return m;
        }

        public void Destroy()
        {
            foreach (var r in _results) r.DestroyAll();
            _results.Clear();
            _cache.Clear();
            foreach (var m in _fallbackMade) _fallback.Release(m);
            _fallbackMade.Clear();
        }
    }
}
