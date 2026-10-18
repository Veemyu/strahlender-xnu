namespace Xnu.Battle
{
    // Eingaben der Schadensformel (Spezifikation Abschnitt 5). Kraft, Angriff, Abwehr, STAB-Verhaeltnis und Endfaktor sind
    // die Ergebnisse der Handler-Ereignisse des Originals und werden hier von aussen vorgegeben.
    public sealed class DamageInput
    {
        public uint Power { get; set; }
        public uint Attack { get; set; }
        public uint Defense { get; set; }
        public uint Level { get; set; }

        // Festkomma-Faktor x/4096 fuer Mehrfachziele u. ae. (0x1000 = keiner).
        public uint TargetRatio { get; set; } = 0x1000;

        public BattleWeather Weather { get; set; }
        public int MoveType { get; set; }
        public DamageCategory Category { get; set; }
        public bool IsCritical { get; set; }

        // Fester Zufallsfaktor 85 statt eines Zuges (setzt im Original nur der KI-Simulator).
        public bool FixedRoll { get; set; }

        // Wirkungs-ID (Abschnitt 2); 7 = normal.
        public int Affinity { get; set; } = AffinityId.Normal;

        // STAB-Verhaeltnis (0x1000 kein STAB, 0x1800 STAB, 0x2000 Anpassung).
        public uint StabRatio { get; set; } = 0x1000;

        public bool AttackerBurned { get; set; }

        // Brand-Halbierung ausser Kraft (Handler setzt das Flag).
        public bool IgnoreBurn { get; set; }

        // Endfaktor aus den Handlern der letzten Schadensstufe (0x1000 = keiner).
        public uint FinalRatio { get; set; } = 0x1000;
    }

    public struct DamageResult
    {
        public ushort Damage;

        // Zufallsfaktor in Prozent (85..100); bei festem Faktor 85.
        public uint Roll;
    }

    public static class DamageCalculator
    {
        // Reihenfolge wie Event_CalcDamage: Grundschaden, Mehrfachziel, Wetter, Volltreffer, Zufall, STAB, Typenwirkung, Brand, Endfaktor, Minimum 1.
        public static DamageResult Calc(DamageInput input, IBattleRandom random)
        {
            uint s = BattleMath.DamageBase(input.Power, input.Attack, input.Level, input.Defense);

            if (input.TargetRatio != 0x1000) s = BattleMath.MulRatio(s, input.TargetRatio);

            uint weather = BattleMath.WeatherDamageRatio((int)input.Weather, input.MoveType);
            if (weather != 0x1000) s = BattleMath.MulRatio(s, weather);

            if (input.IsCritical) s = unchecked(s * 15) / 10;

            uint roll = input.FixedRoll ? 85u : unchecked((uint)(100 - (long)random.GetValue(16))) & 0xFFFF;
            s = unchecked(roll * s) / 100;

            if (input.MoveType != (int)PokeType.None) s = BattleMath.MulRatio(s, input.StabRatio);

            s = BattleMath.AffDamage(s, input.Affinity);

            if (input.Category == DamageCategory.Physical && input.AttackerBurned && !input.IgnoreBurn)
                s = unchecked(s * 50) / 100;

            s = BattleMath.MulRatio(s, input.FinalRatio);
            if (s == 0) s = 1;

            return new DamageResult { Damage = unchecked((ushort)s), Roll = roll };
        }

        // Section_CalcDamage.roundDamage: nie mehr als die aktuellen KP (bzw. die KP des Delegators).
        public static uint ClampToHp(uint damage, uint currentHp) => damage <= currentHp ? damage : currentHp;
    }
}
