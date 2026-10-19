using System;
using System.IO;
using UnityEngine;
using UnityEngine.U2D;
using Xnu.Core;

namespace Xnu.UI
{
    // Grafiken der Textbox: 9-Slice-Rahmen und Weiter-Symbol. Original-Sprites werden nur zur Laufzeit aus dem lokalen
    // Dump geladen (nie im Repo); fehlt er, entsteht ein einfacher Platzhalter aus eigenen Pixeln.
    public sealed class TextboxSkin
    {
        public Sprite Frame;
        public Sprite KeyIcon;
        public bool IsOriginal;
        public string Source = "Platzhalter";

        // Höhe des Rahmens in Referenzpixeln (Original-Sprites sind 144 hoch).
        public float FrameHeight = 144f;

        const string SharedUiBundle = "UIs/shareduiassets/sharedui";

        static TextboxSkin _placeholder;
        static readonly System.Collections.Generic.Dictionary<int, TextboxSkin> OriginalCache = new System.Collections.Generic.Dictionary<int, TextboxSkin>();

        public static string FrameSpriteName(int style) => "cmn_wd_message_01_" + style.ToString("00") + "_l";

        public static TextboxSkin Placeholder()
        {
            if (_placeholder != null && _placeholder.Frame != null) return _placeholder;
            _placeholder = new TextboxSkin { Frame = MakeFrame(), KeyIcon = MakeArrow() };
            return _placeholder;
        }

        // Rahmen 1..24 aus dem lokalen Dump (assets cmn_wd_message_01_NN_l); sonst Platzhalter. Ergebnis wird gemerkt.
        public static TextboxSkin LoadOriginalOrPlaceholder(int style, out string note)
        {
            if (OriginalCache.TryGetValue(style, out var cached) && cached.Frame != null)
            {
                note = "Original (Cache)";
                return cached;
            }
            try
            {
                var skin = TryLoadOriginal(style, out note);
                if (skin != null)
                {
                    OriginalCache[style] = skin;
                    return skin;
                }
            }
            catch (Exception e)
            {
                note = "Fehler: " + e.Message;
            }
            return Placeholder();
        }

        static TextboxSkin TryLoadOriginal(int style, out string note)
        {
            var path = Path.Combine(GameDataPaths.AssetAssistant, "UIs", "shareduiassets", "sharedui");
            if (!File.Exists(path))
            {
                note = "Spieldaten nicht vorhanden: Platzhalter";
                return null;
            }
            var bundle = AssetBundle.LoadFromFile(path);
            if (bundle == null)
            {
                note = "Bundle nicht ladbar (schon geladen?): Platzhalter";
                return null;
            }
            try
            {
                SpriteAtlas atlas = null;
                foreach (var a in bundle.LoadAllAssets<SpriteAtlas>()) { atlas = a; break; }
                if (atlas == null)
                {
                    note = "Kein SpriteAtlas im Bundle: Platzhalter";
                    return null;
                }
                var frame = atlas.GetSprite(FrameSpriteName(style));
                var icon = atlas.GetSprite("cmn_ico_messagenext_01");
                if (frame == null)
                {
                    note = "Rahmen " + FrameSpriteName(style) + " fehlt: Platzhalter";
                    return null;
                }
                note = "Original (" + SharedUiBundle + ")";
                return new TextboxSkin { Frame = frame, KeyIcon = icon != null ? icon : MakeArrow(), IsOriginal = true, Source = note };
            }
            finally
            {
                // Objekte (Atlas-Textur, Sprites) bleiben im Speicher, nur das Bundle-Handle wird frei.
                bundle.Unload(false);
            }
        }

        static Sprite MakeFrame()
        {
            const int size = 64, radius = 20, border = 24;
            var tex = NewTexture(size, size, "XnuTextboxFrame");
            var px = new Color32[size * size];
            for (var y = 0; y < size; y++)
                for (var x = 0; x < size; x++)
                {
                    var d = CornerDistance(x, y, size, radius);
                    Color32 c;
                    if (d > radius) c = new Color32(0, 0, 0, 0);
                    else if (d > radius - 3) c = new Color32(70, 90, 140, 255);
                    else c = new Color32(245, 247, 252, 255);
                    px[y * size + x] = c;
                }
            tex.SetPixels32(px);
            tex.Apply(false, false);
            return Sprite.Create(tex, new Rect(0, 0, size, size), new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect, new Vector4(border, border, border, border));
        }

        static float CornerDistance(int x, int y, int size, int radius)
        {
            var cx = x < radius ? radius : x >= size - radius ? size - radius - 1 : x;
            var cy = y < radius ? radius : y >= size - radius ? size - radius - 1 : y;
            var dx = x - cx;
            var dy = y - cy;
            return Mathf.Sqrt(dx * dx + dy * dy);
        }

        static Sprite MakeArrow()
        {
            const int size = 32;
            var tex = NewTexture(size, size, "XnuTextboxKeyIcon");
            var px = new Color32[size * size];
            for (var y = 0; y < size; y++)
                for (var x = 0; x < size; x++)
                {
                    // Dreieck nach unten: Breite nimmt mit y ab (y = 0 ist unten).
                    var inside = y >= 4 && y <= 26 && Mathf.Abs(x - (size - 1) / 2f) <= (y - 4) * 0.6f + 1f;
                    px[y * size + x] = inside ? new Color32(70, 90, 140, 255) : new Color32(0, 0, 0, 0);
                }
            tex.SetPixels32(px);
            tex.Apply(false, false);
            return Sprite.Create(tex, new Rect(0, 0, size, size), new Vector2(0.5f, 0.5f), 100f);
        }

        static Texture2D NewTexture(int w, int h, string name) =>
            new Texture2D(w, h, TextureFormat.RGBA32, false) { name = name, filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp, hideFlags = HideFlags.HideAndDontSave };
    }
}
