using System;

namespace Xnu.Probe
{
    // Reine Rechenlogik der Messung, ohne Unity-Aufrufe (testbar).
    public static class ProbeMath
    {
        public const long Mb = 1024L * 1024L;

        // Stoppbedingung der Speicherrampe: nächster Schritt würde die Reserve unterschreiten
        // oder der Footprint die Obergrenze erreichen. Unbekannter Wert (<= 0) stoppt sofort, damit nie blind alloziert wird.
        public static bool ShouldStop(long availableBytes, long footprintBytes, long stepBytes, long reserveBytes, long footprintCapBytes)
        {
            if (availableBytes <= 0) return true;
            if (availableBytes - stepBytes < reserveBytes) return true;
            return footprintBytes + stepBytes > footprintCapBytes;
        }

        // Kennzahlen aus Bilddauern (Sekunden). Ein leeres Feld liefert Nullwerte.
        public static FrameStats Summarize(double[] frameSeconds, int count)
        {
            if (count <= 0) return default;
            var sorted = new double[count];
            Array.Copy(frameSeconds, sorted, count);
            Array.Sort(sorted);
            double sum = 0;
            for (var i = 0; i < count; i++) sum += sorted[i];
            var p99 = sorted[Math.Min(count - 1, (int)Math.Ceiling(count * 0.99) - 1)];
            return new FrameStats
            {
                Count = count,
                AvgFps = count / sum,
                MinFps = 1.0 / sorted[count - 1],
                MaxFps = 1.0 / Math.Max(sorted[0], 1e-9),
                P99FrameMs = p99 * 1000.0,
                MaxFrameMs = sorted[count - 1] * 1000.0,
            };
        }
    }

    public struct FrameStats
    {
        public int Count;
        public double AvgFps;
        public double MinFps;
        public double MaxFps;
        public double P99FrameMs;
        public double MaxFrameMs;
    }
}
