using UnityEngine;

namespace Xnu.Input
{
    // Zur Laufzeit erzeugte, weiche Formen für das Touch-Overlay (keine Sprites oder Schriften aus Spieldaten).
    internal static class TouchSprites
    {
        private static Sprite _circle, _roundRect, _triangle;

        public static Sprite Circle => _circle != null ? _circle : _circle = Build(128, (x, y) => Disc(x, y, 0.5f, 0.5f, 0.5f), Vector4.zero);

        public static Sprite RoundRect => _roundRect != null ? _roundRect : _roundRect = Build(64, (x, y) => Rounded(x, y, 0.3f), new Vector4(22, 22, 22, 22));

        public static Sprite Triangle => _triangle != null ? _triangle : _triangle = Build(64, Tri, Vector4.zero);

        private static bool Disc(float x, float y, float cx, float cy, float r)
        {
            var dx = x - cx; var dy = y - cy;
            return dx * dx + dy * dy <= r * r;
        }

        // Abgerundetes Rechteck auf dem Einheitsquadrat, Radius r (relativ).
        private static bool Rounded(float x, float y, float r)
        {
            var qx = Mathf.Abs(x - 0.5f) - (0.5f - r);
            var qy = Mathf.Abs(y - 0.5f) - (0.5f - r);
            if (qx <= 0f || qy <= 0f) return Mathf.Abs(x - 0.5f) <= 0.5f && Mathf.Abs(y - 0.5f) <= 0.5f;
            return qx * qx + qy * qy <= r * r;
        }

        // Dreieck mit Spitze nach oben.
        private static bool Tri(float x, float y)
        {
            if (y < 0.15f || y > 0.85f) return false;
            var half = 0.40f * (0.85f - y) / 0.70f;
            return Mathf.Abs(x - 0.5f) <= half;
        }

        private static Sprite Build(int size, System.Func<float, float, bool> inside, Vector4 border)
        {
            const int ss = 4;
            var pixels = new Color32[size * size];
            for (var py = 0; py < size; py++)
            {
                for (var px = 0; px < size; px++)
                {
                    var hit = 0;
                    for (var sy = 0; sy < ss; sy++)
                        for (var sx = 0; sx < ss; sx++)
                            if (inside((px + (sx + 0.5f) / ss) / size, (py + (sy + 0.5f) / ss) / size)) hit++;
                    pixels[py * size + px] = new Color32(255, 255, 255, (byte)(255 * hit / (ss * ss)));
                }
            }

            var tex = new Texture2D(size, size, TextureFormat.RGBA32, false)
            {
                wrapMode = TextureWrapMode.Clamp,
                filterMode = FilterMode.Bilinear,
                hideFlags = HideFlags.HideAndDontSave,
            };
            tex.SetPixels32(pixels);
            tex.Apply(false, false);

            var sprite = Sprite.Create(tex, new Rect(0, 0, size, size), new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect, border);
            sprite.hideFlags = HideFlags.HideAndDontSave;
            return sprite;
        }
    }
}
