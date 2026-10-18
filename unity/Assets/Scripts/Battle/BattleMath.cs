using System;

namespace Xnu.Battle
{
    // Festkomma- und Hilfsrechnungen der Kampfmathematik (Spezifikation Abschnitte 1, 2.5 und 5.3).
    // Alle Rechnungen laufen wie im Original in 32 Bit mit Umlauf (unchecked).
    public static class BattleMath
    {
        public const uint One = 0x1000;

        // (a*b) / 4096, Rundung halb nach unten.
        public static uint MulRatio(uint a, uint b)
        {
            uint p = unchecked(a * b);
            uint r = p >> 12;
            if ((p & 0xFFF) > 0x800) r++;
            return r;
        }

        public static uint MulRatioOverZero(uint a, uint b)
        {
            uint r = MulRatio(a, b);
            return r == 0 ? 1u : r;
        }

        // (a*b) / 100, Rundung halb nach oben.
        public static uint MulRatioInt(uint a, uint b)
        {
            uint p = unchecked(a * b);
            uint r = p / 100;
            if (p % 100 > 49) r++;
            return r;
        }

        // Ereignis-Variable multiplizieren: (v*f + 0x800) >> 12 (64 Bit, halb nach oben), danach auf [min, max] geklemmt,
        // sofern eine der Grenzen von 0 verschieden ist.
        public static int EventVarMul(int value, int ratio, int min, int max)
        {
            long v = ((long)value * ratio + 0x800) >> 12;
            if (min != 0 || max != 0) v = Math.Min(max, Math.Max(min, v));
            return unchecked((int)v);
        }

        // Klemmt value auf [lo, hi]; bei lo > hi gewinnt hi (Reihenfolge wie im Original).
        public static int RoundValue(int value, int lo, int hi)
        {
            return Math.Min(hi, Math.Max(value, lo));
        }

        // Typenwirkung auf den Rohschaden: ID 0 = 0, 1..6 = Rechtsschieben, 8..13 = Linksschieben, sonst unveraendert.
        public static uint AffDamage(uint raw, int affinityId)
        {
            if (affinityId == 0) return 0;
            if (affinityId >= 1 && affinityId <= 6) return raw >> (7 - affinityId);
            if (affinityId >= 8 && affinityId <= 13) return unchecked(raw << (affinityId - 7));
            return raw;
        }

        // Grundschaden: ((atk * kraft * (2*level/5 + 2)) / abwehr) / 50 + 2; abwehr 0 ergibt 0 im inneren Quotienten.
        public static uint DamageBase(uint power, uint attack, uint level, uint defense)
        {
            uint inner = 0;
            if (defense != 0)
                inner = unchecked(attack * power * (unchecked(level * 2) / 5 + 2)) / defense;
            return inner / 50 + 2;
        }

        // Wetterfaktor auf den Schaden (Sonne 1/6, Regen 2/5).
        public static uint WeatherDamageRatio(int weather, int moveType)
        {
            switch (weather)
            {
                case 1:
                case 6:
                    if (moveType == (int)PokeType.Fire) return 0x1800;
                    if (moveType == (int)PokeType.Water) return 0x800;
                    return 0x1000;
                case 2:
                case 5:
                    if (moveType == (int)PokeType.Water) return 0x1800;
                    if (moveType == (int)PokeType.Fire) return 0x800;
                    return 0x1000;
                default:
                    return 0x1000;
            }
        }

        // Stufen 0..12 (6 = neutral): Zaehler/Nenner fuer Statuswerte.
        static readonly byte[][] RankNumDen =
        {
            new byte[] { 2, 8 }, new byte[] { 2, 7 }, new byte[] { 2, 6 }, new byte[] { 2, 5 }, new byte[] { 2, 4 },
            new byte[] { 2, 3 }, new byte[] { 2, 2 }, new byte[] { 3, 2 }, new byte[] { 4, 2 }, new byte[] { 5, 2 },
            new byte[] { 6, 2 }, new byte[] { 7, 2 }, new byte[] { 8, 2 },
        };

        // Stufen 0..12 (6 = neutral): Zaehler/Nenner fuer die Trefferwahrscheinlichkeit.
        static readonly byte[][] HitNumDen =
        {
            new byte[] { 6, 18 }, new byte[] { 6, 16 }, new byte[] { 6, 14 }, new byte[] { 6, 12 }, new byte[] { 6, 10 },
            new byte[] { 6, 8 }, new byte[] { 6, 6 }, new byte[] { 8, 6 }, new byte[] { 10, 6 }, new byte[] { 12, 6 },
            new byte[] { 14, 6 }, new byte[] { 16, 6 }, new byte[] { 18, 6 },
        };

        public const int StageCount = 13;

        public static (int Numerator, int Denominator) RankFraction(int index) => (RankNumDen[index][0], RankNumDen[index][1]);

        public static (int Numerator, int Denominator) HitFraction(int index) => (HitNumDen[index][0], HitNumDen[index][1]);

        // Statuswert mit Stufe: ((zaehler * wert) & 0xffff) / nenner; Index ausserhalb 0..12 -> unveraendert.
        public static uint StatusRank(uint value, int rankIndex)
        {
            if (rankIndex < 0 || rankIndex >= StageCount) return value;
            uint scaled = unchecked(RankNumDen[rankIndex][0] * value) & 0xFFFF;
            return scaled / RankNumDen[rankIndex][1];
        }

        // Trefferwert nach Stufe: (zaehler * (wert & 0xff)) / nenner, ab 100 auf 100 gedeckelt; Index ausserhalb 0..12 -> unveraendert.
        public static uint HitPercentByStage(uint hitPer, int stageIndex)
        {
            if (stageIndex < 0 || stageIndex >= StageCount) return hitPer;
            uint r = HitNumDen[stageIndex][0] * (hitPer & 0xFF) / HitNumDen[stageIndex][1];
            return r > 99 ? 100u : r;
        }
    }
}
