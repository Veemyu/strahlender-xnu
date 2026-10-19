using System;
using System.Collections.Generic;

namespace Xnu.Field
{
    public readonly struct BlockId : IEquatable<BlockId>
    {
        public readonly int Column, Row;
        public BlockId(int column, int row) { Column = column; Row = row; }
        public bool Equals(BlockId o) => Column == o.Column && Row == o.Row;
        public override bool Equals(object obj) => obj is BlockId b && Equals(b);
        public override int GetHashCode() => Column * 73856093 ^ Row * 19349663;
        public override string ToString() => "(" + Column + ", " + Row + ")";
    }

    public sealed class BlockSelection
    {
        public readonly List<BlockId> Load = new List<BlockId>();
        public readonly List<BlockId> Unload = new List<BlockId>();
        public bool IsEmpty => Load.Count == 0 && Unload.Count == 0;
    }

    // Auswahl der Rasterblöcke (32 x 32 Zellen) um den Spieler. Abstände in Zellen (Chebyshev) zum Blockrechteck;
    // Laden ab loadDistance, Entladen erst jenseits unloadDistance (Hysterese gegen Flackern an der Blockgrenze).
    public static class BlockStreamingMath
    {
        // Abstand der Zelle zum Rechteck des Blocks in Zellen; 0 = Zelle liegt im Block.
        public static int DistanceToBlock(int gx, int gy, BlockId b)
        {
            var minX = b.Column * FieldCoords.BlockSize;
            var maxX = minX + FieldCoords.BlockSize - 1;
            var minY = b.Row * FieldCoords.BlockSize;
            var maxY = minY + FieldCoords.BlockSize - 1;
            var dx = gx < minX ? minX - gx : (gx > maxX ? gx - maxX : 0);
            var dy = gy < minY ? minY - gy : (gy > maxY ? gy - maxY : 0);
            return Math.Max(dx, dy);
        }

        // Alle Blöcke, die das Weltrechteck [minX, maxX] x [minZ, maxZ] berühren (Zelle gx = floor(0,5 - x), gy = floor(z + 0,5); Block = Zelle >> 5).
        // Strecken über mehr als maxSpan Blöcke je Achse werden auf maxSpan um die Mitte begrenzt (Ausreißer wie Himmelskuppeln).
        public static List<BlockId> BlocksCovering(float minX, float maxX, float minZ, float maxZ, int maxSpan = 16)
        {
            var c0 = FieldCoords.BlockOf((int)Math.Floor(0.5 - maxX));
            var c1 = FieldCoords.BlockOf((int)Math.Floor(0.5 - minX));
            var r0 = FieldCoords.BlockOf((int)Math.Floor(minZ + 0.5));
            var r1 = FieldCoords.BlockOf((int)Math.Floor(maxZ + 0.5));
            Clamp(ref c0, ref c1, maxSpan);
            Clamp(ref r0, ref r1, maxSpan);
            var list = new List<BlockId>((c1 - c0 + 1) * (r1 - r0 + 1));
            for (var c = c0; c <= c1; c++)
                for (var r = r0; r <= r1; r++) list.Add(new BlockId(c, r));
            return list;
        }

        static void Clamp(ref int a, ref int b, int maxSpan)
        {
            if (b - a + 1 <= maxSpan) return;
            var mid = (a + b) / 2;
            a = mid - maxSpan / 2;
            b = a + maxSpan - 1;
        }

        public static BlockSelection Select(int gx, int gy, IEnumerable<BlockId> available, ISet<BlockId> loaded, int loadDistance, int unloadDistance)
        {
            if (unloadDistance < loadDistance) unloadDistance = loadDistance;
            var sel = new BlockSelection();
            var present = new HashSet<BlockId>();
            foreach (var b in available)
            {
                present.Add(b);
                var d = DistanceToBlock(gx, gy, b);
                var isLoaded = loaded.Contains(b);
                if (!isLoaded && d <= loadDistance) sel.Load.Add(b);
                else if (isLoaded && d > unloadDistance) sel.Unload.Add(b);
            }
            // Geladene Blöcke, die es nicht mehr gibt (Zonenwechsel), werden entladen.
            foreach (var b in loaded) if (!present.Contains(b)) sel.Unload.Add(b);
            return sel;
        }

        // Sichtweite der Feldkamera in Zellen vom Brennpunkt: Strahlen durch die Bildränder gegen die Bodenebene.
        // pitch = Neigung (Grad), fov = vertikaler Sichtwinkel (Grad), range = Abstand Kamera–Brennpunkt, aspect = Breite/Höhe.
        // Rückgabe: größte Entfernung (Zellen) vom Brennpunkt bis zum Bildrand (vorn, hinten, seitlich).
        public static float VisibleRadius(float pitch, float fov, float range, float aspect)
        {
            var p = pitch * (float)Math.PI / 180f;
            var half = fov * 0.5f * (float)Math.PI / 180f;
            var h = range * (float)Math.Sin(p);
            var d = range * (float)Math.Cos(p);
            var top = p - half;
            var ahead = top > 0.05f ? h / (float)Math.Tan(top) - d : 200f;
            var bottom = p + half;
            var behind = d - h / (float)Math.Tan(Math.Min(bottom, 1.5f));
            var halfWidth = (float)Math.Tan(half) * aspect * range * 1.25f;   // Breite am Brennpunkt, 25 % Zuschlag für die Perspektive
            return Math.Max(Math.Max(ahead, Math.Abs(behind)), halfWidth);
        }

        // Ladeabstand: sichtbarer Radius plus Vorlauf (Zellen), damit ein Block fertig gebaut ist, bevor er ins Bild kommt.
        public static int LoadDistanceFor(float visibleRadius, int marginCells = 8) =>
            (int)Math.Ceiling(visibleRadius) + marginCells;
    }

    public enum BudgetState
    {
        Ok,         // unter der Warnschwelle
        Warning,    // Ladeabstand verkleinern
        Critical,   // nur Blöcke im Sichtbereich, Unload zuerst
    }

    // Speicherbudget des Feldes (Ziel: höchstens 2,5 GB gesamt auf dem iPad, docs/ios-speicher-entitlements.md).
    // Die Auswertung nutzt gemessene Bytes (Unity-Zähler); reine Logik.
    public sealed class MemoryBudget
    {
        public long TotalBytes { get; }
        public double WarnFraction { get; }
        public double CriticalFraction { get; }

        public MemoryBudget(long totalBytes = 2500L * 1024 * 1024, double warnFraction = 0.75, double criticalFraction = 0.92)
        {
            if (totalBytes <= 0) throw new ArgumentOutOfRangeException(nameof(totalBytes));
            TotalBytes = totalBytes; WarnFraction = warnFraction; CriticalFraction = criticalFraction;
        }

        public BudgetState Evaluate(long usedBytes)
        {
            var f = (double)usedBytes / TotalBytes;
            if (f >= CriticalFraction) return BudgetState.Critical;
            if (f >= WarnFraction) return BudgetState.Warning;
            return BudgetState.Ok;
        }

        public int AdjustLoadDistance(int loadDistance, BudgetState state)
        {
            switch (state)
            {
                case BudgetState.Warning: return Math.Max(12, loadDistance * 3 / 4);
                case BudgetState.Critical: return Math.Max(8, loadDistance / 2);
                default: return loadDistance;
            }
        }
    }
}
