using System.Collections.Generic;
using UnityEngine;

namespace Xnu.Render
{
    // Findet die Textur zu einem Materialverweis des Exports über Name und Größe (Textur-Objekte tragen im Player
    // keine PathID). Namensgleiche Texturen gleicher Größe sind in den geprüften Bundles inhaltsgleich oder kommen nicht vor.
    public sealed class LoadedTextureIndex
    {
        readonly Dictionary<string, Texture> _byKey = new Dictionary<string, Texture>();

        public int Count => _byKey.Count;
        public int Misses { get; private set; }

        static string Key(string name, int w, int h) => name + "|" + w + "x" + h;

        public void Add(Texture t)
        {
            if (t != null) _byKey[Key(t.name, t.width, t.height)] = t;
        }

        // Alle derzeit geladenen 2D-Texturen aufnehmen (nach dem Laden des Bundles, vor dem Umbau).
        public void AddAllLoaded()
        {
            foreach (var t in Resources.FindObjectsOfTypeAll<Texture2D>()) Add(t);
        }

        public Texture Find(MaterialTextureRef r)
        {
            if (r != null && !r.IsNull && _byKey.TryGetValue(Key(r.TextureName, r.Width, r.Height), out var t)) return t;
            Misses++;
            return null;
        }
    }
}
