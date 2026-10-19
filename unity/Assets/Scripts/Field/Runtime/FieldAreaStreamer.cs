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
        readonly Dictionary<Transform, GameObject> _builtContainers = new Dictionary<Transform, GameObject>();
        readonly Dictionary<Transform, int> _refs = new Dictionary<Transform, int>();
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
            var offsetMatrix = Matrix4x4.TRS(srcOffset.localPosition, srcOffset.localRotation, srcOffset.localScale);
            for (var i = 0; i < srcOffset.childCount; i++)
            {
                var c = srcOffset.GetChild(i);
                var p = c.localPosition;
                // Ein Container ist nicht auf einen Block begrenzt (Routen und Städte reichen über mehrere Blöcke, sein Ursprung liegt
                // nicht einmal auf dem 32er-Raster): Er gehört zu allen Blöcken, die seine Meshes berühren, und zu seinem Ursprungsblock.
                var blocks = new HashSet<BlockId> { new BlockId(FieldCoords.BlockColumnOfOriginX(p.x), FieldCoords.BlockRowOfOriginZ(p.z)) };
                if (TryWorldBounds(c, offsetMatrix, out var b))
                    foreach (var id in BlockStreamingMath.BlocksCovering(b.min.x, b.max.x, b.min.z, b.max.z)) blocks.Add(id);
                foreach (var id in blocks)
                {
                    if (!_sources.TryGetValue(id, out var l)) _sources[id] = l = new List<Transform>();
                    l.Add(c);
                }
                ContainersAvailable++;
            }
        }

        // Weltrechteck aller Meshes unter dem Container (aus Mesh-Bounds und Transform-Kette; das Prefab wird nicht instanziiert).
        static bool TryWorldBounds(Transform container, Matrix4x4 offsetMatrix, out Bounds bounds)
        {
            bounds = new Bounds();
            var any = false;
            foreach (var mf in container.GetComponentsInChildren<MeshFilter>(true))
            {
                var mesh = mf.sharedMesh;
                if (mesh == null) continue;
                var m = Matrix4x4.identity;
                for (var t = mf.transform; t != null && t != container.parent; t = t.parent)
                    m = Matrix4x4.TRS(t.localPosition, t.localRotation, t.localScale) * m;
                m = offsetMatrix * m;
                var mb = mesh.bounds;
                for (var k = 0; k < 8; k++)
                {
                    var corner = mb.center + Vector3.Scale(mb.extents, new Vector3((k & 1) == 0 ? -1 : 1, (k & 2) == 0 ? -1 : 1, (k & 4) == 0 ? -1 : 1));
                    var w = m.MultiplyPoint3x4(corner);
                    if (!any) { bounds = new Bounds(w, Vector3.zero); any = true; }
                    else bounds.Encapsulate(w);
                }
            }
            return any;
        }

        // Baut einen Block (alle Container, die ihn berühren; ein Container steht nur einmal, auch wenn mehrere Blöcke geladen sind).
        // Ohne Offset-Gerüst passiert nichts.
        public bool LoadBlock(BlockId id)
        {
            if (_skeletonOffset == null || _loaded.Contains(id) || !_sources.TryGetValue(id, out var list)) return false;
            foreach (var src in list)
            {
                if (_refs.TryGetValue(src, out var n)) { _refs[src] = n + 1; continue; }
                _builtContainers[src] = _builder.CloneBranch(src, _skeletonOffset).gameObject;
                _refs[src] = 1;
            }
            _loaded.Add(id);
            LoadCount++;
            if (_loaded.Count > PeakLoaded) PeakLoaded = _loaded.Count;
            return true;
        }

        public bool UnloadBlock(BlockId id)
        {
            if (!_loaded.Remove(id)) return false;
            if (_sources.TryGetValue(id, out var list))
            {
                foreach (var src in list)
                {
                    if (!_refs.TryGetValue(src, out var n)) continue;
                    if (n > 1) { _refs[src] = n - 1; continue; }
                    _refs.Remove(src);
                    if (_builtContainers.TryGetValue(src, out var go) && go != null) FieldDestroy.Kill(go);
                    _builtContainers.Remove(src);
                }
            }
            UnloadCount++;
            return true;
        }

        public int BuiltContainers => _builtContainers.Count;

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
