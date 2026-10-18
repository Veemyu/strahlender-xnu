using System;

namespace Xnu.Core.Display
{
    // Zielseitenverhältnisse der Darstellung. MVP ist 16:9 (1080p nativ, 1920x1080).
    public enum AspectMode
    {
        Aspect16x9,
        Aspect4x3,
        Aspect16x10,
    }

    // Normalisiertes Rechteck (0..1) wie UnityEngine.Rect, ohne Unity-Abhängigkeit.
    public readonly struct NormalizedRect
    {
        public readonly float X, Y, Width, Height;

        public NormalizedRect(float x, float y, float width, float height)
        {
            X = x; Y = y; Width = width; Height = height;
        }
    }

    public static class AspectMath
    {
        // Referenz-Renderauflösung des MVP (1080p, 16:9).
        public const int RefWidth = 1920;
        public const int RefHeight = 1080;

        public static float Ratio(AspectMode mode)
        {
            switch (mode)
            {
                case AspectMode.Aspect16x9: return 16f / 9f;
                case AspectMode.Aspect4x3: return 4f / 3f;
                case AspectMode.Aspect16x10: return 16f / 10f;
                default: throw new ArgumentOutOfRangeException(nameof(mode));
            }
        }

        // Größtes Rechteck mit dem Zielverhältnis, zentriert (Letter-/Pillarbox) im Bildschirm.
        public static NormalizedRect Fit(float screenWidth, float screenHeight, float targetRatio)
        {
            if (screenWidth <= 0f || screenHeight <= 0f) throw new ArgumentException("Bildschirmgröße muss positiv sein.");
            if (targetRatio <= 0f) throw new ArgumentException("Zielverhältnis muss positiv sein.", nameof(targetRatio));

            var screenRatio = screenWidth / screenHeight;
            if (Math.Abs(screenRatio - targetRatio) < 1e-4f) return new NormalizedRect(0f, 0f, 1f, 1f);

            if (screenRatio > targetRatio)
            {
                // Bildschirm breiter als Ziel: Balken links/rechts.
                var w = targetRatio / screenRatio;
                return new NormalizedRect((1f - w) * 0.5f, 0f, w, 1f);
            }

            // Bildschirm schmaler als Ziel: Balken oben/unten.
            var h = screenRatio / targetRatio;
            return new NormalizedRect(0f, (1f - h) * 0.5f, 1f, h);
        }

        public static NormalizedRect Fit(float screenWidth, float screenHeight, AspectMode mode)
            => Fit(screenWidth, screenHeight, Ratio(mode));

        // Renderauflösung in Pixeln bei fester Höhe (Standard 1080) und Zielverhältnis, auf gerade Werte gerundet.
        public static (int Width, int Height) RenderSize(AspectMode mode, int height = RefHeight)
        {
            var w = (int)Math.Round(Ratio(mode) * height);
            if ((w & 1) != 0) w++;
            return (w, height);
        }
    }
}
