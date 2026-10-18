using System;

namespace Xnu.Battle
{
    // Wirkungs-IDs (Spezifikation Abschnitt 2.2): 0 = x0, 7 = x1, 8 = x2 ... Jede Stufe halbiert/verdoppelt.
    public static class AffinityId
    {
        public const int Zero = 0;
        public const int Quarter = 5;
        public const int Half = 6;
        public const int Normal = 7;
        public const int Double = 8;
        public const int Quadruple = 9;
        public const int Max = 13;
        public const int Null = 14;
    }

    // Typentabelle und Typenwirkung (docs/kampf-spezifikation-1.md, Abschnitt 2).
    public static class TypeAffinity
    {
        public const int TypeCount = 18;
        const int NoType = 18;

        // Zeile = Angriffstyp, Spalte = Verteidigertyp; 0 = wirkungslos, 2 = halb, 4 = normal, 8 = doppelt.
        static readonly byte[][] Chart =
        {
            new byte[] { 4, 4, 4, 4, 4, 2, 4, 0, 2, 4, 4, 4, 4, 4, 4, 4, 4, 4 },
            new byte[] { 8, 4, 2, 2, 4, 8, 2, 0, 8, 4, 4, 4, 4, 2, 8, 4, 8, 2 },
            new byte[] { 4, 8, 4, 4, 4, 2, 8, 4, 2, 4, 4, 8, 2, 4, 4, 4, 4, 4 },
            new byte[] { 4, 4, 4, 2, 2, 2, 4, 2, 0, 4, 4, 8, 4, 4, 4, 4, 4, 8 },
            new byte[] { 4, 4, 0, 8, 4, 8, 2, 4, 8, 8, 4, 2, 8, 4, 4, 4, 4, 4 },
            new byte[] { 4, 2, 8, 4, 2, 4, 8, 4, 2, 8, 4, 4, 4, 4, 8, 4, 4, 4 },
            new byte[] { 4, 2, 2, 2, 4, 4, 4, 2, 2, 2, 4, 8, 4, 8, 4, 4, 8, 2 },
            new byte[] { 0, 4, 4, 4, 4, 4, 4, 8, 4, 4, 4, 4, 4, 8, 4, 4, 2, 4 },
            new byte[] { 4, 4, 4, 4, 4, 8, 4, 4, 2, 2, 2, 4, 2, 4, 8, 4, 4, 8 },
            new byte[] { 4, 4, 4, 4, 4, 2, 8, 4, 8, 2, 2, 8, 4, 4, 8, 2, 4, 4 },
            new byte[] { 4, 4, 4, 4, 8, 8, 4, 4, 4, 8, 2, 2, 4, 4, 4, 2, 4, 4 },
            new byte[] { 4, 4, 2, 2, 8, 8, 2, 4, 2, 2, 8, 2, 4, 4, 4, 2, 4, 4 },
            new byte[] { 4, 4, 8, 4, 0, 4, 4, 4, 4, 4, 8, 2, 2, 4, 4, 2, 4, 4 },
            new byte[] { 4, 8, 4, 8, 4, 4, 4, 4, 2, 4, 4, 4, 4, 2, 4, 4, 0, 4 },
            new byte[] { 4, 4, 8, 4, 8, 4, 4, 4, 2, 2, 2, 8, 4, 4, 2, 8, 4, 4 },
            new byte[] { 4, 4, 4, 4, 4, 4, 4, 4, 2, 4, 4, 4, 4, 4, 4, 8, 4, 0 },
            new byte[] { 4, 2, 4, 4, 4, 4, 4, 8, 4, 4, 4, 4, 4, 8, 4, 4, 2, 2 },
            new byte[] { 4, 8, 4, 2, 4, 4, 4, 4, 2, 2, 4, 4, 4, 4, 4, 8, 8, 4 },
        };

        // ID -> 64 * Faktor (ID 7 = 64 = x1).
        static readonly uint[] ValueTable = { 0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096 };

        public static byte RawEntry(int attackType, int defenderType)
        {
            CheckType(attackType);
            CheckType(defenderType);
            return Chart[attackType][defenderType];
        }

        // Einzelner Verteidigertyp. Typ 18 (kein Typ) auf einer der Seiten ergibt immer "normal".
        public static int Calc(int attackType, int defenderType, bool inverse)
        {
            if (attackType == NoType || defenderType == NoType) return AffinityId.Normal;
            switch (RawEntry(attackType, defenderType))
            {
                case 0: return inverse ? AffinityId.Double : AffinityId.Zero;
                case 2: return inverse ? AffinityId.Double : AffinityId.Half;
                case 4: return AffinityId.Normal;
                case 8: return inverse ? AffinityId.Half : AffinityId.Double;
                default: throw new InvalidOperationException("Ungueltiger Tabelleneintrag");
            }
        }

        // Pml-Variante: beide Einzelwerte ohne Duplikatpruefung multipliziert.
        public static int CalcDual(int attackType, int type1, int type2, bool inverse)
        {
            return Mul(Calc(attackType, type1, inverse), Calc(attackType, type2, inverse));
        }

        // Kampf-Variante (calc.TypeAffPair): Typ 2 und Zusatztyp zaehlen nur, wenn sie von 18 und den vorigen verschieden sind.
        public static int CalcPair(int attackType, int type1, int type2, int extraType, bool inverse)
        {
            int result = Calc(attackType, type1, inverse);
            if (type2 != NoType && type2 != type1)
                result = Mul(result, Calc(attackType, type2, inverse));
            if (extraType != NoType && extraType != type1 && extraType != type2)
                result = Mul(result, Calc(attackType, extraType, inverse));
            return result;
        }

        // Multipliziert zwei Wirkungs-IDs; kleiner als 1/64 wird auf ID 1 angehoben, ab x64 gesaettigt.
        public static int Mul(int a, int b)
        {
            if (a < 0 || b < 0 || a >= ValueTable.Length || b >= ValueTable.Length)
                throw new ArgumentOutOfRangeException(nameof(a), "Wirkungs-ID ausserhalb 0..13");
            uint product = ValueTable[a] * ValueTable[b];
            uint v;
            if (product < 0x40040)
            {
                v = product >> 6;
                if (a != 0 && b != 0 && v == 0) v = 1;
            }
            else
            {
                v = 0x1000;
            }
            if (v == 0) return 0;
            int bit = 0;
            while ((v & (1u << bit)) == 0) bit++;
            return bit > 12 ? 13 : bit + 1;
        }

        // Grobe Einstufung fuer die Anzeige: 0 wirkungslos, 1 normal, 2 sehr effektiv, 3 nicht sehr effektiv.
        public static int ConvAbout(int id)
        {
            if (id > AffinityId.Normal) return 2;
            if (id == AffinityId.Normal) return 1;
            return id == 0 ? 0 : 3;
        }

        static void CheckType(int type)
        {
            if (type < 0 || type >= TypeCount)
                throw new ArgumentOutOfRangeException(nameof(type), "Typ ausserhalb 0..17");
        }
    }
}
