using System;

namespace Xnu.Battle.Flow
{
    // Geldformeln aus calc.CalcWinMoney / calcWinMoney_Sub / CalcPenaltyMoney.
    public static class PrizeFormula
    {
        // (Gold & 0xFF) * Stufe des letzten Mitglieds der Trainer-Party * 4 (je Trainer; Einzelkampf = ein Trainer).
        public static int Win(int gold, int lastMemberLevel) => (gold & 0xFF) * lastMemberLevel * 4;

        // Standard-Tabelle (Abzug je Abzeichenzahl) – im Original eine Byte-Tabelle der Laenge 9 aus dem Binaer-Datenblock; Werte hier NICHT gelesen,
        // sondern aus der bekannten Reihe der Vorgaenger-Spiele uebernommen [P].
        public static readonly int[] DefaultPenaltyTable = { 2, 4, 6, 9, 12, 16, 20, 24, 36 };

        // hoechste Stufe der Party * Tabelle[Abzeichen] * 4, begrenzt auf das vorhandene Geld.
        public static uint Penalty(int maxLevel, int badges, uint money, int[] table = null)
        {
            table = table ?? DefaultPenaltyTable;
            if (badges < 0 || badges >= table.Length) throw new ArgumentOutOfRangeException(nameof(badges));
            uint v = (uint)(maxLevel * table[badges] * 4);
            return Math.Min(v, money);
        }
    }
}
