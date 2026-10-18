using System;
using System.Collections.Generic;

namespace Xnu.Battle
{
    // Wachstumsraten und Level aus Erfahrung (Spezifikation Abschnitt 3.3/3.4).
    public static class GrowthRate
    {
        public const int MaxLevel = 100;

        // Zeile der GrowTable -> Kurve: 0 mittel-schnell, 1 unregelmaessig, 2 schwankend, 3 mittel-langsam, 4 schnell, 5 langsam;
        // 6 und 7 entsprechen 0.
        public static int CurveForRow(int growRow)
        {
            switch (growRow)
            {
                case 0: case 6: case 7: return 0;
                case 1: return 1;
                case 2: return 2;
                case 3: return 3;
                case 4: return 4;
                case 5: return 5;
                default: throw new ArgumentOutOfRangeException(nameof(growRow), "Wachstumszeile ausserhalb 0..7");
            }
        }

        // Erfahrung fuer Level n nach der Formel der Kurve (Ganzzahldivision); Level 1 ist 0. Maßgeblich bleibt die GrowTable aus den
        // Stammdaten; diese Formeln stimmen mit ihr fuer Level 2..100 ueberein (siehe scripts/battle_oracle.py --verify-growth).
        public static long ExpForLevel(int curve, int level)
        {
            if (level <= 1) return 0;
            long n = level;
            long c = n * n * n;
            long v;
            switch (curve)
            {
                case 0: v = c; break;
                case 1:
                    if (n <= 50) v = c * (100 - n) / 50;
                    else if (n <= 68) v = c * (150 - n) / 100;
                    else if (n <= 98) v = c * ((1911 - 10 * n) / 3) / 500;
                    else v = c * (160 - n) / 100;
                    break;
                case 2:
                    if (n <= 15) v = c * ((n + 1) / 3 + 24) / 50;
                    else if (n <= 35) v = c * (n + 14) / 50;
                    else v = c * (n / 2 + 32) / 50;
                    break;
                case 3: v = 6 * c / 5 - 15 * n * n + 100 * n - 140; break;
                case 4: v = 4 * c / 5; break;
                case 5: v = 5 * c / 4; break;
                default: throw new ArgumentOutOfRangeException(nameof(curve), "Kurve ausserhalb 0..5");
            }
            return Math.Max(v, 0);
        }

        // CalcTool.CalcLevel: groesstes Level L in 1..100 mit exps[L] <= exp; exps hat 101 Eintraege (Index = Level).
        public static int LevelFromExp(IReadOnlyList<uint> exps, uint exp)
        {
            int level = 1;
            for (int i = 2; i <= MaxLevel; i++)
            {
                if (exp < exps[i]) break;
                level = i;
            }
            return level;
        }

        // GrowTable.GetMinExp: Erfahrung, ab der ein Level erreicht ist; Level ueber 100 wird auf 100 gesetzt.
        public static uint MinExp(IReadOnlyList<uint> exps, int level)
        {
            if (level > MaxLevel) level = MaxLevel;
            return exps[level];
        }
    }

    // Wetterschaden am Zugende (calc.RecvWeatherDamage).
    public static class WeatherChip
    {
        // Hagel: Eis ist immun; Sand: Gestein, Stahl und Boden sind immun; sonst maxHp/16, mindestens 1.
        public static uint Damage(BattleWeather weather, uint maxHp, bool isIce, bool isRock, bool isSteel, bool isGround)
        {
            if (weather == BattleWeather.Hail)
            {
                if (isIce) return 0;
            }
            else if (weather == BattleWeather.Sandstorm)
            {
                if (isRock || isSteel || isGround) return 0;
            }
            else
            {
                return 0;
            }
            uint d = maxHp >> 4;
            return (d & 0xFFFF) == 0 ? 1u : d;
        }
    }
}
