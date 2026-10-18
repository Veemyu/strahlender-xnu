using System;

namespace Xnu.Battle
{
    // Kraft-IDs des Originals fuer die Wesenskorrektur; Tabellenspalte = ID - 1.
    public enum PowerId
    {
        Attack = 1,
        Defense = 2,
        SpAttack = 3,
        SpDefense = 4,
        Speed = 5,
    }

    // Wesenstabelle (Spezifikation Abschnitt 3.1): 25 Wesen, je Zeile hoechstens ein +1 (Staerke) und ein -1 (Schwaeche).
    // Spalten: Angriff, Verteidigung, Sp.-Angriff, Sp.-Verteidigung, Initiative.
    public static class Nature
    {
        public const int Count = 25;

        static readonly sbyte[][] Table =
        {
            new sbyte[] {  0,  0,  0,  0,  0 },
            new sbyte[] {  1, -1,  0,  0,  0 },
            new sbyte[] {  1,  0,  0,  0, -1 },
            new sbyte[] {  1,  0, -1,  0,  0 },
            new sbyte[] {  1,  0,  0, -1,  0 },
            new sbyte[] { -1,  1,  0,  0,  0 },
            new sbyte[] {  0,  0,  0,  0,  0 },
            new sbyte[] {  0,  1,  0,  0, -1 },
            new sbyte[] {  0,  1, -1,  0,  0 },
            new sbyte[] {  0,  1,  0, -1,  0 },
            new sbyte[] { -1,  0,  0,  0,  1 },
            new sbyte[] {  0, -1,  0,  0,  1 },
            new sbyte[] {  0,  0,  0,  0,  0 },
            new sbyte[] {  0,  0, -1,  0,  1 },
            new sbyte[] {  0,  0,  0, -1,  1 },
            new sbyte[] { -1,  0,  1,  0,  0 },
            new sbyte[] {  0, -1,  1,  0,  0 },
            new sbyte[] {  0,  0,  1,  0, -1 },
            new sbyte[] {  0,  0,  0,  0,  0 },
            new sbyte[] {  0,  0,  1, -1,  0 },
            new sbyte[] { -1,  0,  0,  1,  0 },
            new sbyte[] {  0, -1,  0,  1,  0 },
            new sbyte[] {  0,  0,  0,  1, -1 },
            new sbyte[] {  0,  0, -1,  1,  0 },
            new sbyte[] {  0,  0,  0,  0,  0 },
        };

        public static int Modifier(int nature, int powerId)
        {
            if (powerId < 1 || powerId > 5) return 0;
            if (nature < 0 || nature >= Count) throw new ArgumentOutOfRangeException(nameof(nature), "Wesen ausserhalb 0..24");
            return Table[nature][powerId - 1];
        }

        // Entspricht Pml.PokePara.CalcTool.GetPowerTransformBySeikaku.
        public static int Modifier(int nature, PowerId power) => Modifier(nature, (int)power);

        // CalcCorrectedPowerBySeikaku: +10 % bzw. -10 %, mit 0xfffe maskiertes Produkt vor der Division durch 100.
        public static uint Correct(uint value, int nature, int powerId)
        {
            int mod = Modifier(nature, powerId);
            if (mod == 0) return value;
            uint factor = mod < 0 ? 90u : 110u;
            return (unchecked(value * factor) & 0xFFFE) / 100;
        }
    }
}
