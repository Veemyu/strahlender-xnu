using System.Collections.Generic;
using UnityEngine;

namespace Xnu.Field
{
    // Blockweises Streaming einer Feldkarte. Das Prefab (Asset aus dem Bundle, bleibt geladen) wird nicht instanziiert:
    // Das Gerüst (alles außer den Blockcontainern unter "Offset") entsteht einmal, die Container je Block werden bei Bedarf
    // mit FieldMapBuilder.CloneBranch gebaut und wieder zerstört. Die Blockcontainer liegen bei (-32 * Spalte, 0, 32 * Zeile).
    public sealed class FieldAreaStreamer
    {
        readonly FieldMapBuilder _builder;
        readonly Transform _skeletonOffset;
        readonly Dictionary<BlockId, List<Transform>> _sources = new Dictionary<BlockId, List<Transform>>();
        readonly Dictionary<BlockId, List<GameObject>> _built = new Dictionary<BlockId, List<GameObject>>();
        readonly HashSet<BlockId> _loaded = new HashSet<BlockId>();

        public GameObject Root { get; }
        public bool IsStreaming => _sources.Count > 0;
        public IEnumerable<BlockId> Available => _sources.Keys;
        public ISet<BlockId> Loaded => _loaded;
        public int LoadCount { get; private set; }
        public int UnloadCount { get; private set; }
        public int PeakLoaded { get; private set; }
        public int ContainersAvailable { get; private set; }

        // builder.Stats zählt kumulativ (alle je gebauten Knoten), nicht den aktuellen Bestand.
        public FieldAreaStreamer(GameObject prefab, FieldMapBuilder builder, Transform parent, string name)
        {
            _builder = builder;
            var srcOffset = prefab.transform.Find("Offset");
            var previous = builder.IncludeBranch;
            // Gerüst: alles bauen, nur die Kinder von "Offset" auslassen (sie kommen als Blöcke).
            builder.IncludeBranch = (node, depth) =>
                !(node.parent != null && node.parent.name == "Offset") && (previous == null || previous(node, depth));
            Root = builder.Build(prefab, parent);
            builder.IncludeBranch = previous;
            Root.name = name;
            if (srcOffset == null) return;

            _skeletonOffset = Root.transform.Find("Offset");
            for (var i = 0; i < srcOffset.childCount; i++)
            {
                var c = srcOffset.GetChild(i);
                var p = c.localPosition;
                var id = new BlockId(FieldCoords.BlockColumnOfOriginX(p.x), FieldCoords.BlockRowOfOriginZ(p.z));
                if (!_sources.TryGetValue(id, out var l)) _sources[id] = l = new List<Transform>();
                l.Add(c);
                ContainersAvailable++;
            }
        }

        // Baut einen Block (alle Container dieser Zelle des Rasters). Ohne Offset-Gerüst passiert nichts.
        public bool LoadBlock(BlockId id)
        {
            if (_skeletonOffset == null || _loaded.Contains(id) || !_sources.TryGetValue(id, out var list)) return false;
            var objs = new List<GameObject>(list.Count);
            foreach (var src in list) objs.Add(_builder.CloneBranch(src, _skeletonOffset).gameObject);
            _built[id] = objs;
            _loaded.Add(id);
            LoadCount++;
            if (_loaded.Count > PeakLoaded) PeakLoaded = _loaded.Count;
            return true;
        }

        public bool UnloadBlock(BlockId id)
        {
            if (!_loaded.Remove(id)) return false;
            if (_built.TryGetValue(id, out var objs))
            {
                foreach (var go in objs) if (go != null) FieldDestroy.Kill(go);
                _built.Remove(id);
            }
            UnloadCount++;
            return true;
        }

        // Lädt/entlädt nach Auswahl; zuerst entladen (Speicherspitze), dann laden. Rückgabe: die Auswahl.
        public BlockSelection Update(int gx, int gy, int loadDistance, int unloadDistance)
        {
            var sel = BlockStreamingMath.Select(gx, gy, _sources.Keys, _loaded, loadDistance, unloadDistance);
            foreach (var b in sel.Unload) UnloadBlock(b);
            foreach (var b in sel.Load) LoadBlock(b);
            return sel;
        }

        // Alles laden (ohne Streaming, z. B. Innenräume) – nutzt dieselben Container.
        public void LoadAll() { foreach (var b in new List<BlockId>(_sources.Keys)) LoadBlock(b); }
    }
}
