using Xnu.Data;

namespace Xnu.Battle
{
    // Statuswerte aus Basiswerten, IV, EV, Level und Wesen (Spezifikation Abschnitt 3.3).
    public static class StatCalculator
    {
        // Art 292 hat immer 1 KP.
        public const int FixedHpSpecies = 292;

        // Eingaben werden wie im Original maskiert: Basiswert/IV 16 Bit, Level 8 Bit, EV als (ev & 0xfffc) >> 2.
        static uint Core(int level, int baseStat, int iv, int ev)
        {
            uint lv = (uint)level & 0xFF;
            uint raw = unchecked(((uint)baseStat & 0xFFFF) * 2 + ((uint)iv & 0xFFFF) + (((uint)ev & 0xFFFC) >> 2));
            return unchecked(raw * lv);
        }

        public static ushort CalcMaxHp(int speciesNo, int level, int baseStat, int iv, int ev)
        {
            if (speciesNo == FixedHpSpecies) return 1;
            uint lv = (uint)level & 0xFF;
            return unchecked((ushort)(Core(level, baseStat, iv, ev) / 100 + lv + 10));
        }

        public static ushort CalcStat(PowerId power, int level, int baseStat, int iv, int ev, int nature)
        {
            uint raw = Core(level, baseStat, iv, ev) / 100 + 5;
            return unchecked((ushort)Nature.Correct(raw, nature, (int)power));
        }

        public static ushort CalcAttack(int level, int baseStat, int iv, int ev, int nature) => CalcStat(PowerId.Attack, level, baseStat, iv, ev, nature);

        public static ushort CalcDefense(int level, int baseStat, int iv, int ev, int nature) => CalcStat(PowerId.Defense, level, baseStat, iv, ev, nature);

        public static ushort CalcSpAttack(int level, int baseStat, int iv, int ev, int nature) => CalcStat(PowerId.SpAttack, level, baseStat, iv, ev, nature);

        public static ushort CalcSpDefense(int level, int baseStat, int iv, int ev, int nature) => CalcStat(PowerId.SpDefense, level, baseStat, iv, ev, nature);

        public static ushort CalcSpeed(int level, int baseStat, int iv, int ev, int nature) => CalcStat(PowerId.Speed, level, baseStat, iv, ev, nature);

        // Alle sechs Werte einer Art (Stammdaten) fuer ein konkretes Exemplar.
        public static BattleStats Calc(SpeciesRecord species, int level, StatSpread iv, StatSpread ev, int nature)
        {
            return new BattleStats
            {
                Hp = CalcMaxHp(species.Id, level, species.BaseHp, iv.Hp, ev.Hp),
                Attack = CalcAttack(level, species.BaseAttack, iv.Attack, ev.Attack, nature),
                Defense = CalcDefense(level, species.BaseDefense, iv.Defense, ev.Defense, nature),
                SpAttack = CalcSpAttack(level, species.BaseSpAttack, iv.SpAttack, ev.SpAttack, nature),
                SpDefense = CalcSpDefense(level, species.BaseSpDefense, iv.SpDefense, ev.SpDefense, nature),
                Speed = CalcSpeed(level, species.BaseSpeed, iv.Speed, ev.Speed, nature),
            };
        }
    }

    // IV oder EV je Statuswert.
    public struct StatSpread
    {
        public int Hp;
        public int Attack;
        public int Defense;
        public int SpAttack;
        public int SpDefense;
        public int Speed;
    }

    public struct BattleStats
    {
        public ushort Hp;
        public ushort Attack;
        public ushort Defense;
        public ushort SpAttack;
        public ushort SpDefense;
        public ushort Speed;
    }
}
