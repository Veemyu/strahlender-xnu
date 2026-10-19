using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using UnityEngine;
using UnityEngine.Profiling;

namespace Xnu.Field
{
    // Speichermessung beim Laden einer Zone: Unitys Zähler (nativ + Grafiktreiber + Texturen) und Prozess-Arbeitsspeicher.
    // Im Editor enthalten die Werte auch Editor-Anteile; nur Differenzen zwischen den Stufen sind aussagekräftig.
    public sealed class FieldMemoryLog
    {
        public readonly struct Entry
        {
            public readonly string Stage;
            public readonly long ElapsedMs;
            public readonly long AllocatedMB;
            public readonly long GraphicsMB;
            public readonly long TextureMB;
            public readonly long ProcessMB;

            public Entry(string stage, long elapsedMs, long allocated, long graphics, long texture, long process)
            {
                Stage = stage; ElapsedMs = elapsedMs;
                AllocatedMB = allocated >> 20; GraphicsMB = graphics >> 20; TextureMB = texture >> 20; ProcessMB = process >> 20;
            }

            public override string ToString() =>
                Stage + ": " + ElapsedMs + " ms, Unity " + AllocatedMB + " MB, Grafik " + GraphicsMB + " MB, Texturen " + TextureMB + " MB, Prozess " + ProcessMB + " MB";
        }

        readonly Stopwatch _clock = Stopwatch.StartNew();
        readonly List<Entry> _entries = new List<Entry>();

        public IReadOnlyList<Entry> Entries => _entries;

        // Höchster beobachteter Wert über alle Stufen (Stichproben, kein echter Spitzenwert zwischen den Stufen).
        public long PeakAllocatedMB { get; private set; }
        public long PeakProcessMB { get; private set; }

        public void Mark(string stage)
        {
            long process = 0;
            try { process = Process.GetCurrentProcess().WorkingSet64; } catch { }
            var e = new Entry(stage, _clock.ElapsedMilliseconds, Profiler.GetTotalAllocatedMemoryLong(),
                Profiler.GetAllocatedMemoryForGraphicsDriver(), (long)Texture.currentTextureMemory, process);
            _entries.Add(e);
            if (e.AllocatedMB > PeakAllocatedMB) PeakAllocatedMB = e.AllocatedMB;
            if (e.ProcessMB > PeakProcessMB) PeakProcessMB = e.ProcessMB;
        }

        public override string ToString()
        {
            var sb = new StringBuilder();
            foreach (var e in _entries) sb.AppendLine(e.ToString());
            sb.Append("Spitze (Stichproben): Unity " + PeakAllocatedMB + " MB, Prozess " + PeakProcessMB + " MB");
            return sb.ToString();
        }
    }
}
