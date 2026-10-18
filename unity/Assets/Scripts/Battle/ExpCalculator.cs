using System;

namespace Xnu.Battle
{
    // Eingaben der Erfahrungsberechnung je Empfaenger (Spezifikation Abschnitt 8).
    public sealed class ExpInput
    {
        public uint LevelCap { get; set; } = 100;

        // Basis-Erfahrung der besiegten Art (PersonalTable give_exp).
        public uint FoeBaseExp { get; set; }
        public uint FoeLevel { get; set; }
        public uint ReceiverLevel { get; set; }
        public uint Friendship { get; set; }
        public uint PlayerLanguage { get; set; }
        public uint ReceiverLanguage { get; set; }

        // Hat gekaempft.
        public bool Participated { get; set; }

        // Erfahrungs-Teiler vorhanden.
        public bool HasExpShare { get; set; }

        public bool HasLuckyEgg { get; set; }

        // Entwicklung per Level gestoppt / Entwicklungsstein (Bonus x1.2).
        public bool EvolutionCanceled { get; set; }

        // Eigenes Pokemon (nicht getauscht).
        public bool IsOwnPokemon { get; set; }
    }

    public struct ExpResult
    {
        public uint Exp;
        public bool ByExpShare;
        public bool HasBonus;
    }

    public static class ExpCalculator
    {
        // Exp.CalcBaseExp: level * basis / 5, mindestens 1 (32 Bit).
        public static uint BaseExp(uint level, uint baseExp)
        {
            uint product = unchecked(level * baseExp);
            return product < 5 ? 1u : product / 5;
        }

        // Exp.CalcGakusyusoutiExp: Haelfte, mindestens 1.
        public static uint ShareExp(uint exp) => Math.Max(1u, exp >> 1);

        // Stufenausgleich in Gleitkomma einfacher Genauigkeit: ((2L+10)/(L+Lr+10))^2.5 * exp + 1, abgeschnitten.
        // Jede Zwischenstufe wird explizit auf float gerundet, damit die Reihenfolge der Original-Rechnung erhalten bleibt.
        public static int AdjustLevel(uint exp, uint receiverLevel, uint foeLevel)
        {
            float foe = (ushort)foeLevel;
            float x = (float)(foe + foe) + 10.0f;
            float y = (float)((float)(ushort)receiverLevel + foe) + 10.0f;
            float num = (float)((float)(x * x) * MathF.Sqrt(x));
            float den = (float)((float)(y * y) * MathF.Sqrt(y));
            float scaled = (float)((float)(num / den) * (float)exp);
            return (int)(float)(scaled + 1.0f);
        }

        // Exp.CalcExp.
        public static ExpResult Calc(ExpInput input)
        {
            var result = new ExpResult();
            if (!input.Participated && !input.HasExpShare) return result;

            uint foeLevel = Math.Min(input.FoeLevel, input.LevelCap);
            uint exp = BaseExp(foeLevel, input.FoeBaseExp);
            if (!input.Participated)
            {
                exp = ShareExp(exp);
                result.ByExpShare = true;
            }

            exp = unchecked((uint)AdjustLevel(exp, input.ReceiverLevel, foeLevel));

            if (!input.IsOwnPokemon)
            {
                exp = BattleMath.MulRatio(exp, input.PlayerLanguage == input.ReceiverLanguage ? 0x1800u : 0x1B33u);
                result.HasBonus = true;
            }
            if (input.HasLuckyEgg)
            {
                exp = BattleMath.MulRatio(exp, 0x1800);
                result.HasBonus = true;
            }
            if (input.EvolutionCanceled)
            {
                exp = BattleMath.MulRatio(exp, 0x1333);
                result.HasBonus = true;
            }
            if (input.Friendship > 0xDB)
            {
                exp = BattleMath.MulRatio(exp, 0x1333);
                result.HasBonus = true;
            }

            result.Exp = exp;
            return result;
        }
    }
}
