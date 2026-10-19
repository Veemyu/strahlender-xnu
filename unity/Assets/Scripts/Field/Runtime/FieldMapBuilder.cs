using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xnu.Field
{
    public sealed class MapBuildStats
    {
        public int NodesVisited;
        public int NodesCreated;
        public int SkippedBranches;
        public int Renderers;
        public int UniqueMeshes;
        public long Vertices;
        public int Colliders;
        public int MissingComponents;
        public int OriginalMaterialRefs;
        public int ReplacedMaterialSlots;
        public Bounds Bounds;
        public bool HasBounds;

        public override string ToString() =>
            "Knoten " + NodesCreated + "/" + NodesVisited + " (übersprungene Zweige " + SkippedBranches + "), Renderer " + Renderers +
            ", Meshes " + UniqueMeshes + ", Vertices " + Vertices + ", Collider " + Colliders +
            ", Materialslots ersetzt " + ReplacedMaterialSlots + ", fehlende Komponenten " + MissingComponents;
    }

    // Baut aus einem Karten-Prefab (Asset aus dem Bundle, wird NICHT instanziiert) eine eigene Hierarchie auf:
    // Transform, Mesh, Collider werden übernommen; Materialien werden durch Fallback-Materialien ersetzt,
    // andere Komponenten (Skripte der Spiel-Assembly) fehlen ohnehin und werden nicht kopiert.
    public sealed class FieldMapBuilder
    {
        readonly IMapMaterialSource _materials;
        readonly HashSet<Mesh> _meshes = new HashSet<Mesh>();
        readonly List<Component> _compBuffer = new List<Component>();

        public MapBuildStats Stats { get; } = new MapBuildStats();

        // Entscheidet je Kindknoten (Tiefe 1 = direktes Kind der Prefab-Wurzel), ob der Zweig gebaut wird.
        public Func<Transform, int, bool> IncludeBranch { get; set; }

        public FieldMapBuilder(IMapMaterialSource materials)
        {
            _materials = materials ?? throw new ArgumentNullException(nameof(materials));
        }

        public GameObject Build(GameObject sourcePrefab, Transform parent)
        {
            var root = Clone(sourcePrefab.transform, parent, 0);
            return root.gameObject;
        }

        // Baut nur den Zweig ab src (Streaming: ein Blockcontainer) unter parent; IncludeBranch gilt weiter für dessen Kinder.
        public Transform CloneBranch(Transform src, Transform parent) => Clone(src, parent, 2);

        Transform Clone(Transform src, Transform parent, int depth)
        {
            Stats.NodesVisited++;
            var go = new GameObject(src.name);
            go.hideFlags = HideFlags.DontSave;
            var t = go.transform;
            t.SetParent(parent, false);
            t.localPosition = src.localPosition;
            t.localRotation = src.localRotation;
            t.localScale = src.localScale;
            go.layer = src.gameObject.layer;
            Stats.NodesCreated++;

            src.GetComponents(_compBuffer);
            var comps = _compBuffer.ToArray();
            MeshFilter mf = null; Renderer rend = null;
            foreach (var c in comps)
            {
                if (c == null) { Stats.MissingComponents++; continue; }
                if (c is MeshFilter f) mf = f;
                else if (c is MeshRenderer r) rend = r;
                else if (c is BoxCollider bc)
                {
                    var n = go.AddComponent<BoxCollider>();
                    n.center = bc.center; n.size = bc.size; n.isTrigger = bc.isTrigger;
                    Stats.Colliders++;
                }
                else if (c is SphereCollider sc)
                {
                    var n = go.AddComponent<SphereCollider>();
                    n.center = sc.center; n.radius = sc.radius; n.isTrigger = sc.isTrigger;
                    Stats.Colliders++;
                }
                else if (c is MeshCollider mc && mc.sharedMesh != null)
                {
                    var n = go.AddComponent<MeshCollider>();
                    n.sharedMesh = mc.sharedMesh; n.convex = mc.convex; n.isTrigger = mc.isTrigger;
                    Stats.Colliders++;
                }
            }

            if (mf != null && mf.sharedMesh != null && rend != null)
            {
                var mesh = mf.sharedMesh;
                go.AddComponent<MeshFilter>().sharedMesh = mesh;
                var nr = go.AddComponent<MeshRenderer>();
                var src2 = rend.sharedMaterials;
                var dst = new Material[src2.Length];
                for (var i = 0; i < dst.Length; i++)
                {
                    if (src2[i] != null) Stats.OriginalMaterialRefs++;
                    dst[i] = _materials.For(src2[i]);
                }
                nr.sharedMaterials = dst;
                Stats.ReplacedMaterialSlots += dst.Length;
                nr.enabled = rend.enabled;
                Stats.Renderers++;
                if (_meshes.Add(mesh)) { Stats.UniqueMeshes++; Stats.Vertices += mesh.vertexCount; }
                var wb = nr.bounds;
                if (!Stats.HasBounds) { Stats.Bounds = wb; Stats.HasBounds = true; }
                else Stats.Bounds.Encapsulate(wb);
            }

            go.SetActive(src.gameObject.activeSelf);
            for (var i = 0; i < src.childCount; i++)
            {
                var child = src.GetChild(i);
                if (IncludeBranch != null && !IncludeBranch(child, depth + 1)) { Stats.SkippedBranches++; continue; }
                Clone(child, t, depth + 1);
            }
            return t;
        }

        // Anzahl der Renderer unter root, deren Material nicht den Fallback-Shader benutzt (muss 0 sein).
        public int CountForeignMaterials(GameObject root)
        {
            var bad = 0;
            foreach (var r in root.GetComponentsInChildren<Renderer>(true))
                foreach (var m in r.sharedMaterials)
                    if (!_materials.IsAllowed(m)) bad++;
            return bad;
        }
    }
}
