using System;

namespace Xnu.Core.Display
{
    // Wählbare Bildrate. Original: 30 FPS auf der Switch (VSync-Zähler 2 bei 60 Hz).
    public enum FrameRateMode
    {
        Original30,
        Fixed60,
        Fixed120,
        // ProMotion: bis 120 FPS, das System darf die Rate variabel senken.
        Variable120,
    }

    // Ergebnis der Planung: wie Unity zu konfigurieren ist.
    public readonly struct FrameRatePlan
    {
        public readonly int TargetFrameRate;
        public readonly int VSyncCount;
        public readonly bool Variable;

        public FrameRatePlan(int targetFrameRate, int vSyncCount, bool variable)
        {
            TargetFrameRate = targetFrameRate;
            VSyncCount = vSyncCount;
            Variable = variable;
        }
    }

    public static class FrameRatePlanner
    {
        public static int TargetFps(FrameRateMode mode)
        {
            switch (mode)
            {
                case FrameRateMode.Original30: return 30;
                case FrameRateMode.Fixed60: return 60;
                case FrameRateMode.Fixed120: return 120;
                case FrameRateMode.Variable120: return 120;
                default: throw new ArgumentOutOfRangeException(nameof(mode));
            }
        }

        // Plan für eine Anzeige mit gegebener Bildwiederholrate (Hz).
        // Teilt die Anzeigerate das Ziel ohne Rest, wird per VSync-Zähler getaktet (gleichmäßige Frames);
        // sonst bleibt VSync aus und Application.targetFrameRate begrenzt.
        public static FrameRatePlan Plan(FrameRateMode mode, int displayRefreshHz)
        {
            if (displayRefreshHz <= 0) throw new ArgumentOutOfRangeException(nameof(displayRefreshHz));

            var target = TargetFps(mode);
            var variable = mode == FrameRateMode.Variable120;

            if (variable)
            {
                // Variable Rate: nur oberes Limit setzen, Takt übernimmt das System.
                return new FrameRatePlan(Math.Min(target, displayRefreshHz), 0, true);
            }

            if (target > displayRefreshHz)
            {
                // Anzeige kann das Ziel nicht liefern: Anzeigerate verwenden.
                return new FrameRatePlan(displayRefreshHz, 1, false);
            }

            if (displayRefreshHz % target == 0)
            {
                return new FrameRatePlan(target, displayRefreshHz / target, false);
            }

            return new FrameRatePlan(target, 0, false);
        }
    }
}
