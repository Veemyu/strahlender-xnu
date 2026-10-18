using System;

namespace Xnu.Battle
{
    // Quelle aller Zufallszuege der Kampflogik; ein Zug entspricht einem Aufruf des Originals (Random.GetValue(max)).
    public interface IBattleRandom
    {
        // Gleichverteilt in [0, max) (64-Bit-Modulo wie im Original); max == 0 liefert den ungekuerzten 64-Bit-Wert.
        ulong GetValue(ulong max);
    }

    // Reproduzierbarer Kampf-Zufall: Xoroshiro128+ ab einem gegebenen Seed (Spezifikation Abschnitt 4).
    public sealed class BattleRandom : IBattleRandom
    {
        readonly Xoroshiro128Plus _engine;

        public BattleRandom(ulong seed)
        {
            Seed = seed;
            _engine = new Xoroshiro128Plus(seed);
        }

        public ulong Seed { get; }

        public Xoroshiro128Plus Engine => _engine;

        // Seeds, die das Original aus UnityEngine.Random.Range(int.MinValue, int.MaxValue) gewinnt, werden vorzeichenerweitert.
        public static ulong SeedFromInt(int value) => unchecked((ulong)(long)value);

        public ulong GetValue(ulong max)
        {
            ulong r = _engine.NextULong();
            return max == 0 ? r : r % max;
        }

        // calc.IsOccurPer: GetValue(100) < percent.
        public bool IsOccurPercent(uint percent) => GetValue(100) < percent;

        // calc.RandRange: Grenzen werden geordnet, Ergebnis in [min, max] (inklusive).
        public uint RandRange(uint a, uint b)
        {
            uint lo = Math.Min(a, b);
            uint hi = Math.Max(a, b);
            return unchecked(lo + (uint)GetValue(unchecked(hi - lo + 1)));
        }

        static readonly byte[] HitCountThresholds = { 0, 0, 35, 70, 85, 100 };

        // calc.HitCountStd: nur Attacken mit "2-5 Treffer" (Typ 5) ziehen eine Zahl 0..99 und bekommen 2..5 Treffer
        // (35 % / 35 % / 15 % / 15 %); andere Werte werden unveraendert zurueckgegeben, ohne Zufallszug.
        public int HitCountStandard(int hitCountKind)
        {
            if ((hitCountKind & 0xFF) != 5) return hitCountKind;
            byte roll = (byte)GetValue(100);
            for (int i = 0; i < HitCountThresholds.Length; i++)
                if (roll < HitCountThresholds[i]) return i;
            return 5;
        }
    }
}
