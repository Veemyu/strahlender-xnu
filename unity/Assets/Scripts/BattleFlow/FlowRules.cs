using System;
using System.Collections.Generic;

namespace Xnu.Battle.Flow
{
    // Zustandsnummern (WazaSick) und Hauptzustaende (PokeSick = Nummern 1..5).
    public static class Sick
    {
        public const int None = 0;
        public const int Paralysis = 1;
        public const int Sleep = 2;
        public const int Freeze = 3;
        public const int Burn = 4;
        public const int Poison = 5;
        public const int Confusion = 6;
        public const int Infatuation = 7;
        public const int Bind = 8;
        public const int Nightmare = 9;
        public const int Curse = 10;
        public const int Flinch = -1;       // kein Zustand des Originals: Zug-Flag 4
        public const int MeanLook = 22;
        public const int Count = 45;
    }

    // Reine Regeln des Kampfablaufs, ohne Zustand: Fluchtformel, Sortierung, Zustandszaehler (Spezifikation 4, Abschnitte 3-5).
    public static class FlowRules
    {
        // Section_Escape_Sub.checkEscapeEnableByAgi @0x22b73c0: nur wenn die eigene Basis-Initiative <= der des Gegners ist, wird gewuerfelt.
        // Zug GetRand(256); Erfolg, wenn tries*0x50 + (own<<12)/foe*128>>12 > Zug. tries = Zaehler ESCAPE_TRIED_COUNT.
        public static bool EscapeByAgility(uint ownBaseAgility, uint foeBaseAgility, uint tries, IBattleRandom random)
        {
            uint own = ownBaseAgility & 0xFFFF;
            uint foe = foeBaseAgility & 0xFFFF;
            if (own > foe) return true;
            uint roll = (uint)random.GetValue(0x100);
            uint ratio = foe == 0 ? 0u : (own << 12) / foe;
            uint threshold = unchecked((tries & 0xFF) * 0x50 + (uint)((int)(ratio << 7) >> 12));
            return threshold > roll;
        }

        // Section_SortActionOrder.sort @0x22cd470: Auswahlsortierung absteigend; bei Gleichstand ein Zug GetRand(2), Tausch bei 1.
        public static void SortActionOrder<T>(IList<T> items, Func<T, uint> priority, IBattleRandom random)
        {
            int n = items.Count;
            if (n < 2) return;
            for (int i = 0; i < n - 1; i++)
            {
                for (int j = i + 1; j < n; j++)
                {
                    uint a = priority(items[i]);
                    uint b = priority(items[j]);
                    if (a > b) continue;
                    if (a == b && random.GetValue(2) == 0) continue;
                    (items[i], items[j]) = (items[j], items[i]);
                }
            }
        }

        // Section_SortByAgility.Execute @0x22cd6a0 (Rundenende-Reihenfolge): absteigend nach Initiative, Gleichstand ein Zug GetRand(2).
        public static void SortByAgility<T>(IList<T> items, Func<T, uint> agility, IBattleRandom random)
        {
            int n = items.Count;
            if (n < 2) return;
            var keys = new uint[n];
            for (int i = 0; i < n; i++) keys[i] = agility(items[i]);
            for (int i = 0; i < n - 1; i++)
            {
                for (int j = i + 1; j < n; j++)
                {
                    bool swap;
                    if (keys[i] < keys[j]) swap = true;
                    else if (keys[i] == keys[j]) swap = random.GetValue(2) != 0;
                    else swap = false;
                    if (!swap) continue;
                    (items[i], items[j]) = (items[j], items[i]);
                    (keys[i], keys[j]) = (keys[j], keys[i]);
                }
            }
        }

        // calc.QuotMaxHP: max_hp / teiler, mindestens 1.
        public static uint QuotMaxHp(uint maxHp, uint divisor)
        {
            if (divisor == 0) divisor = 1;
            return maxHp < divisor ? 1u : maxHp / divisor;
        }

        // tables.GetTurnCheckWazaSickByOrder (echte .cctor, Fixture "tables"): Reihenfolge der Zustaende beim Rundenende.
        public static readonly int[] TurnCheckSickOrder =
        {
            36, 21, 18, 5, 4, 9, 10, 8, 43, 11, 12, 23, 13, 31, 33, 15, 19, 29, 30, 38, 37, 39, 40, 41, 24, 14, 20, 1, 2, 3, 7, 6, 16, 17, 22, 25, 26, 27, 28, 32, 34, 35,
        };

        // BTL_POKEPARAM.CalcSickDamage @0x20de0c0. sleepCont = Dauer des Schlafs (Alptraum wirkt nur bei Schlaf, ausser Fähigkeit 213).
        public static uint CalcSickDamage(int sickId, ulong cont, byte counter, uint maxHp, ushort effectiveTokusei = 0, ulong sleepCont = 0)
        {
            if (SickCont.GetType(cont) == SickCont.TypeNone) return 0;
            switch (sickId)
            {
                case Sick.Burn:
                    return QuotMaxHp(maxHp, 16);
                case Sick.Poison:
                    if (SickCont.IsMoudokuCont(cont)) return unchecked(QuotMaxHp(maxHp, 16) * counter);
                    return QuotMaxHp(maxHp, 8);
                case Sick.Nightmare:
                    if (effectiveTokusei != 213 && (sleepCont & 7) == 0) return 0;
                    return QuotMaxHp(maxHp, 4);
                case Sick.Curse:
                    return QuotMaxHp(maxHp, 4);
                default:
                    return 0;
            }
        }

        // Section_ConfDamage.calcDamage @0x22b56a0: Kraft 40, ein Zug GetRand(16) vor der Rechnung, Mindestschaden 1.
        public static uint ConfusionDamage(uint attack, uint defense, uint level, IBattleRandom random)
        {
            uint rand = (uint)random.GetValue(16);
            uint baseDamage = BattleMath.DamageBase(40, attack, level, defense);
            uint dmg = unchecked((baseDamage & 0xFFFF) * (100 - rand)) / 100;
            return (dmg & 0xFFFF) == 0 ? 1u : dmg;
        }

        // Rest von Event_CalcAgility @0x1e179a0 nach dem Ereignis: Verhaeltnis, Paralyse (halbiert, wenn das Flag noch gesetzt ist), Deckel 10000, Bereich der Ordnung.
        public static uint FinishAgility(uint value, uint ratio, bool paralyzed, bool paralysisFlag, bool trickRoomAware, bool trickFlag)
        {
            uint result = BattleMath.MulRatio(value, ratio);
            if (paralyzed && paralysisFlag) result = unchecked(result * 50) / 100;
            if (result >> 4 > 0x270) result = 10000;
            if (trickRoomAware && trickFlag) result = 10000 - result;
            return result;
        }

        // BTL_POKEPARAM.WazaSick_TurnCheck @0x20e10f0 (ohne Sonderfall 0x1c): Zaehler fortschreiben.
        // Rueckgabe: Zustand aktiv. cured = Zustand lief gerade ab (cont wird auf Null gesetzt, Zaehler 0).
        // contBefore = Dauer vor dem Ablauf (fuer Meldungen).
        public static bool WazaSickTurnCheck(int sickId, ref ulong cont, ref byte counter, out bool cured, out ulong contBefore)
        {
            cured = false;
            contBefore = SickCont.MakeNull();
            if ((sickId | 4) == 6) return false;                   // Schlaf und Verwirrung zaehlen bei der Aktion, nicht am Rundenende
            if ((cont & 7) == 0) return false;
            contBefore = cont;
            uint turnMax = SickCont.GetTurnMax(cont);
            if (turnMax == 0)
            {
                if (SickCont.GetType(cont) == SickCont.TypePermanent)
                {
                    uint max = SickCont.GetPermanentCountMax(cont);
                    if (max != 0 && counter < max) counter++;
                }
                return true;
            }
            counter = unchecked((byte)(counter + 1));
            if (counter < turnMax) return true;
            cont = SickCont.MakeNull();
            counter = 0;
            cured = true;
            return true;
        }

        // BTL_POKEPARAM.CheckNemuriWakeUp @0x20e1370: Zaehler +1 (+2 bei Fruehaufsteher, Fahigkeit 48, wenn sie wirkt), Aufwachen ab Zaehler >= Dauer.
        public static bool CheckSleepWakeUp(ulong cont, ref byte counter, ushort effectiveTokusei)
        {
            if ((cont & 7) == 0) return false;
            uint turnMax = SickCont.GetTurnMax(cont);
            if (turnMax == 0) return false;
            counter = unchecked((byte)(counter + (effectiveTokusei == 0x30 ? 2 : 1)));
            return counter >= turnMax;
        }

        // BTL_POKEPARAM.CheckKonranWakeUp @0x20e1520.
        public static bool CheckConfusionWakeUp(ulong cont, ref byte counter)
        {
            if ((cont & 7) == 0) return false;
            uint turnMax = SickCont.GetTurnMax(cont);
            if (turnMax == 0) return false;
            counter = unchecked((byte)(counter + 1));
            return counter >= turnMax;
        }

        // calc.MakeDefaultPokeSickCont @0x2074d20: Schlaf = Runden 2..4 (ein Zug RandRange), Paralyse/Frost/Brand/Gift dauerhaft, sonst Art 0 mit Verursacher.
        public static ulong MakeDefaultSickCont(int sickId, uint cause, bool fixedSleep, BattleRandom random)
        {
            if (sickId == 2)
            {
                uint turns = fixedSleep ? 3u : random.RandRange(2, 4);
                return SickCont.MakeTurn(cause, turns);
            }
            bool permanent = sickId == 1 || sickId >= 3 && sickId <= 5;
            return permanent ? SickCont.MakePermanent(cause) : SickCont.MakeNone(cause);
        }
    }
}
