using System;
using System.Collections.Generic;
using UnityEngine;
using Xnu.Boot;

namespace Xnu.Field
{
    // Charaktermodelle der Platzierungen (NPCs): PlaceData.ObjectGraphicIndex → CharacterGraphics → Bundle
    // Characters/persons/field/fcNNNN_00 → Prefab mit Materialumbau und Ruhe-Animation (idling_f) über PlayerAvatar.
    // Nicht auflösbare Platzierungen (Index außerhalb der Tabelle, Bundle fehlt, Fehler) liefern null: der Aufrufer zeigt den Marker.
    public sealed class NpcModels
    {
        readonly BundleProvider _provider;
        readonly CharacterGraphicsTable _table;
        readonly Func<string, IMapMaterialSource> _materialsFor;
        readonly Dictionary<string, IMapMaterialSource> _sources = new Dictionary<string, IMapMaterialSource>(StringComparer.Ordinal);
        readonly HashSet<string> _failed = new HashSet<string>(StringComparer.Ordinal);

        public int Created { get; private set; }
        public int Unresolved { get; private set; }
        public readonly List<string> Notes = new List<string>();

        public NpcModels(BundleProvider provider, CharacterGraphicsTable table, Func<string, IMapMaterialSource> materialsFor)
        {
            _provider = provider ?? throw new ArgumentNullException(nameof(provider));
            _table = table ?? throw new ArgumentNullException(nameof(table));
            _materialsFor = materialsFor ?? throw new ArgumentNullException(nameof(materialsFor));
        }

        public PlayerAvatar Create(PlacementRecord p, Transform parent)
        {
            if (!_table.TryGet(p.GraphicIndex, out var e)) { Unresolved++; return null; }
            var bundle = e.BundleName;
            if (_failed.Contains(bundle)) { Unresolved++; return null; }
            if (!_sources.TryGetValue(bundle, out var src)) _sources[bundle] = src = _materialsFor(bundle);
            var av = PlayerAvatar.Create(_provider, src, bundle, parent, out var note, "Npc_" + p.Id, e.Scale);
            if (av == null)
            {
                _failed.Add(bundle);
                Unresolved++;
                if (Notes.Count < 20) Notes.Add(p.Id + ": " + note);
                return null;
            }
            Created++;
            return av;
        }

        // Gibt die Materialumbauten der Modelle frei (der gemeinsame Ersatzspeicher gehört dem FieldController).
        public void Destroy()
        {
            foreach (var s in _sources.Values) if (s is RemappedMaterials) s.Destroy();
            _sources.Clear();
        }
    }
}
