using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xnu.Field
{
    // Einfache Darstellung der Platzierungen: sichtbare NPCs als Kapsel mit Blickmarke (Trainer orange, sonst blau).
    // Unsichtbare Objekte (Schilder, Fernseher, Auslöseflächen) werden nicht gezeichnet. Nur Marker im Umkreis des Spielers.
    // Es gibt keine Laufmuster: NPCs stehen in der Grundstellung (MoveCode wird nicht ausgewertet).
    public sealed class FieldNpcView
    {
        readonly Transform _root;
        readonly Shader _shader;
        readonly Dictionary<PlacementRecord, GameObject> _live = new Dictionary<PlacementRecord, GameObject>();
        readonly Dictionary<Color, Material> _materials = new Dictionary<Color, Material>();
        readonly List<PlacementRecord> _drop = new List<PlacementRecord>();
        readonly Dictionary<GameObject, PlayerAvatar> _avatars = new Dictionary<GameObject, PlayerAvatar>();

        // Liefert das Charaktermodell einer Platzierung (null: Marker). Ohne Fabrik zeigt die Ansicht nur Marker.
        public Func<PlacementRecord, Transform, PlayerAvatar> ModelFactory { get; set; }
        public int ModelCount => _avatars.Count;

        public int LiveCount => _live.Count;

        public FieldNpcView(Transform parent, Shader shader)
        {
            _shader = shader != null ? shader : throw new ArgumentNullException(nameof(shader));
            _root = new GameObject("Npcs").transform;
            _root.SetParent(parent, false);
        }

        public void Refresh(IEnumerable<PlacementRecord> candidates, int playerX, int playerY, int radius, IFieldFlags flags,
            Func<int, int, float> groundHeight)
        {
            _drop.Clear();
            foreach (var kv in _live)
            {
                var p = kv.Key;
                if (!PlacementDirectory.IsActive(p, flags) || Math.Max(Math.Abs(p.GridX - playerX), Math.Abs(p.GridY - playerY)) > radius + 8)
                    _drop.Add(p);
            }
            foreach (var p in _drop) { Remove(_live[p]); _live.Remove(p); }

            foreach (var p in candidates)
            {
                if (!p.IsVisibleNpc || _live.ContainsKey(p) || !PlacementDirectory.IsActive(p, flags)) continue;
                if (Math.Max(Math.Abs(p.GridX - playerX), Math.Abs(p.GridY - playerY)) > radius) continue;
                _live[p] = Create(p, groundHeight(p.GridX, p.GridY));
            }
        }

        void Remove(GameObject go)
        {
            if (go == null) return;
            if (_avatars.TryGetValue(go, out var av)) { _avatars.Remove(go); av.Destroy(); }
            else FieldDestroy.Kill(go);
        }

        GameObject Create(PlacementRecord p, float groundY)
        {
            var av = ModelFactory?.Invoke(p, _root);
            if (av != null)
            {
                var t = av.Root.transform;
                t.position = new Vector3(FieldCoords.WorldX(p.GridX), groundY, FieldCoords.WorldZ(p.GridY));
                t.rotation = Quaternion.Euler(0f, p.Facing.YawDegrees(), 0f);
                _avatars[av.Root] = av;
                return av.Root;
            }
            var go = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            go.name = "Npc_" + p.Id;
            go.hideFlags = HideFlags.DontSave;
            UnityEngine.Object.DestroyImmediate(go.GetComponent<Collider>());
            go.transform.SetParent(_root, false);
            go.transform.localScale = new Vector3(0.6f, 0.45f, 0.6f);
            go.transform.position = new Vector3(FieldCoords.WorldX(p.GridX), groundY + 0.45f, FieldCoords.WorldZ(p.GridY));
            go.transform.rotation = Quaternion.Euler(0f, p.Facing.YawDegrees(), 0f);
            go.GetComponent<MeshRenderer>().sharedMaterial = MaterialFor(p.TrainerId > 0 ? new Color(0.95f, 0.55f, 0.1f) : new Color(0.2f, 0.45f, 0.95f));

            var nose = GameObject.CreatePrimitive(PrimitiveType.Cube);
            nose.name = "Facing";
            UnityEngine.Object.DestroyImmediate(nose.GetComponent<Collider>());
            nose.transform.SetParent(go.transform, false);
            nose.transform.localScale = new Vector3(0.3f, 0.3f, 0.5f);
            nose.transform.localPosition = new Vector3(0f, 0.4f, 0.7f);
            nose.GetComponent<MeshRenderer>().sharedMaterial = MaterialFor(Color.white);
            return go;
        }

        Material MaterialFor(Color c)
        {
            if (_materials.TryGetValue(c, out var m)) return m;
            m = new Material(_shader) { color = c, hideFlags = HideFlags.HideAndDontSave };
            _materials[c] = m;
            return m;
        }

        public void Clear()
        {
            foreach (var go in _live.Values) Remove(go);
            _live.Clear();
        }

        public void Destroy()
        {
            Clear();
            foreach (var m in _materials.Values) if (m != null) UnityEngine.Object.DestroyImmediate(m);
            _materials.Clear();
            if (_root != null) FieldDestroy.Kill(_root.gameObject);
        }
    }
}
