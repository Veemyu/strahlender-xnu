using System;
using System.Collections.Generic;
using Xnu.PokePara;

namespace Xnu.Battle.Flow
{
    public sealed partial class BattleEngine
    {
        public const int MachoBraceItem = 0xD7;
        public const int LuckyEggItem = 0xE7;
        public const int EvPerStatMax = 252;
        public const int EvTotalMax = 510;

        readonly HashSet<int> _faintLogged = new HashSet<int>();

        // Pokemon wurde besiegt: Meldung einmalig, bei einem Gegner Erfahrung und Fleisspunkte verteilen (Section_CheckExpGet / GetExp).
        void OnFaint(BattleMon mon)
        {
            if (!_faintLogged.Add(mon.PokeId)) return;
            Add(LogKind.Faint, mon.PokeId);
            for (int i = 0; i < Sick.Count; i++)
                if (i < Sick.Paralysis || i > Sick.Poison) mon.CureSick(i);
            if (mon.Side == EnemySide) HandOutRewards(mon);
        }

        // Erfahrungspunkte-Verteilung: alle kampffaehigen Pokemon der Spielerseite, Beteiligte voll, mit Teiler die uebrigen halb.
        void HandOutRewards(BattleMon dead)
        {
            if (dead.ExpHandedOut) return;
            dead.ExpHandedOut = true;
            foreach (var receiver in Parties[PlayerSide])
            {
                if (receiver.IsFainted) continue;
                var core = receiver.Source.Core;
                var input = new ExpInput
                {
                    LevelCap = Setup.ExpLevelCap,
                    FoeBaseExp = (uint)dead.Species.GiveExp,
                    FoeLevel = (uint)dead.Level,
                    ReceiverLevel = (uint)receiver.Level,
                    Friendship = core.Friendship,
                    PlayerLanguage = 1,
                    ReceiverLanguage = Setup.SameLanguage ? 1u : 2u,
                    Participated = receiver.Confronted.Contains(dead.PokeId),
                    HasExpShare = Setup.HasExpShare,
                    HasLuckyEgg = receiver.Poke.Item == LuckyEggItem,
                    EvolutionCanceled = false,
                    IsOwnPokemon = !core.OwnedByOthers,
                };
                var result = ExpCalculator.Calc(input);
                if (result.Exp == 0) continue;
                Add(LogKind.ExpGained, receiver.PokeId, dead.PokeId, value: (int)result.Exp, value2: result.HasBonus ? 1 : 0);
                receiver.Exp += result.Exp;
                if (Setup.GiveEffort) AddEffort(receiver, dead);
                GrantLevels(receiver);
            }
        }

        void GrantLevels(BattleMon mon)
        {
            var exps = Data.GetGrowth(mon.GrowthRow);
            int newLevel = GrowthRate.LevelFromExp(exps, mon.Exp);
            while (mon.Level < newLevel)
            {
                mon.Relevel(Data, mon.Level + 1);
                Add(LogKind.LevelUp, mon.PokeId, value: mon.Level);
            }
        }

        // EV-Ausbeute der Art steckt in PersonalTable.exp_value (je 2 Bit: KP, Angriff, Abwehr, Initiative, Sp.-Angriff, Sp.-Abwehr) [P].
        public static int[] EffortYield(int expValue)
        {
            var y = new int[6];
            y[(int)StatId.Hp] = expValue & 3;
            y[(int)StatId.Atk] = expValue >> 2 & 3;
            y[(int)StatId.Def] = expValue >> 4 & 3;
            y[(int)StatId.Speed] = expValue >> 6 & 3;
            y[(int)StatId.SpAtk] = expValue >> 8 & 3;
            y[(int)StatId.SpDef] = expValue >> 10 & 3;
            return y;
        }

        void AddEffort(BattleMon receiver, BattleMon dead)
        {
            var core = receiver.Source.Core;
            var yield = EffortYield(dead.Species.ExpValue);
            bool brace = receiver.Poke.Item == MachoBraceItem;
            int total = 0;
            for (int s = 0; s < 6; s++) total += core.GetEv((StatId)s);
            for (int s = 0; s < 6; s++)
            {
                int gain = yield[s] * (brace ? 2 : 1);
                if (gain == 0) continue;
                int cur = core.GetEv((StatId)s);
                gain = Math.Min(gain, Math.Min(EvPerStatMax - cur, EvTotalMax - total));
                if (gain <= 0) continue;
                core.SetEv((StatId)s, (byte)(cur + gain));
                total += gain;
                Add(LogKind.EvGained, receiver.PokeId, id: s, value: gain);
            }
        }
    }
}
