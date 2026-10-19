using System;
using System.Collections.Generic;
using Xnu.Battle.Events;
using Xnu.Data;
using Xnu.PokePara;

namespace Xnu.Battle.Flow
{
    // Ein Pokemon im Kampf: Kampfwerte fuer das Ereignissystem (BattlePoke), Zustandsdauern, Attacken-PP und Rueckverweis auf die Quelldaten.
    public sealed class BattleMon
    {
        public const int MoveCount = 4;

        public BattlePoke Poke { get; }
        public PokemonParam Source { get; }
        public SpeciesRecord Species { get; private set; }
        public int Side { get; }
        public int PartyIndex { get; }
        public int PokeId => Poke.Id;

        public ushort[] Moves { get; } = new ushort[MoveCount];
        public byte[] Pp { get; } = new byte[MoveCount];
        public byte[] MaxPp { get; } = new byte[MoveCount];

        // Dauer jedes Zustands (BTL_SICKCONT) und sein Zaehler (Runden, Giftstufe).
        public ulong[] SickContents { get; } = new ulong[Sick.Count];
        public byte[] SickCounters { get; } = new byte[Sick.Count];

        public uint Exp { get; set; }
        public int GrowthRow { get; private set; }

        // Gegner-IDs, denen dieses Pokemon gleichzeitig auf dem Feld gegenueberstand (CONFRONT_REC).
        public HashSet<int> Confronted { get; } = new HashSet<int>();

        // BtlSpecialPri des Pokemon in dieser Runde (1 = normal).
        public uint SpecialPri { get; set; } = SpecialPri_Default;

        const uint SpecialPri_Default = 1;

        public bool ExpHandedOut { get; set; }

        public ushort LastMove { get; set; }

        public int Level => Poke.Level;

        public bool IsFainted => Poke.Hp == 0;

        BattleMon(PokemonParam source, int side, int partyIndex)
        {
            Source = source;
            Side = side;
            PartyIndex = partyIndex;
            Poke = new BattlePoke((byte)(side * 6 + partyIndex));
            for (int i = 0; i < Sick.Count; i++) SickContents[i] = SickCont.MakeNull();
        }

        public static BattleMon Create(PokemonParam p, IBattleData data, int side, int partyIndex)
        {
            var core = p.Core;
            var m = new BattleMon(p, side, partyIndex);
            m.Species = data.GetSpecies(core.SpeciesNo, core.FormNo);
            m.GrowthRow = m.Species.GrowthCurve;
            m.Exp = core.Exp;
            var exps = data.GetGrowth(m.GrowthRow);
            int level = GrowthRate.LevelFromExp(exps, core.Exp);
            var stats = p.CalcStats(m.Species, level);
            var bp = m.Poke;
            bp.Level = (byte)level;
            bp.MonsNo = core.SpeciesNo;
            bp.Sex = core.Sex;
            bp.Tokusei = core.Ability;
            bp.Item = core.HeldItem;
            bp.Type1 = (byte)m.Species.Type1;
            bp.Type2 = (byte)m.Species.Type2;
            m.ApplyStats(stats);
            bp.Hp = (ushort)Math.Min(core.CurrentHp, stats.Hp);
            for (int i = 0; i < MoveCount; i++)
            {
                m.Moves[i] = core.GetMove(i);
                var rec = m.Moves[i] != 0 ? data.GetMove(m.Moves[i]) : null;
                m.MaxPp[i] = rec == null ? (byte)0 : (byte)PokemonParam.MaxPp(rec.BasePp, core.GetPpUps(i));
                m.Pp[i] = (byte)Math.Min(core.GetPp(i), (int)m.MaxPp[i]);
            }
            return m;
        }

        void ApplyStats(BattleStats stats)
        {
            Poke.MaxHp = stats.Hp;
            Poke.Attack = stats.Attack;
            Poke.Defence = stats.Defense;
            Poke.SpAttack = stats.SpAttack;
            Poke.SpDefence = stats.SpDefense;
            Poke.Agility = stats.Speed;
        }

        // Nach einem Stufenanstieg: Werte neu rechnen; die KP steigen um die Differenz der Maximal-KP (wie RecalculateCalcData).
        public void Relevel(IBattleData data, int newLevel)
        {
            int oldMax = Poke.MaxHp;
            var stats = Source.CalcStats(Species, newLevel);
            Poke.Level = (byte)newLevel;
            ApplyStats(stats);
            if (Poke.Hp != 0) Poke.Hp = (ushort)Math.Min(stats.Hp, Poke.Hp + Math.Max(0, stats.Hp - oldMax));
        }

        // Hauptzustand (PokeSick): erste aktive Nummer 1..5, sonst 0.
        public int PokeSick
        {
            get
            {
                for (int i = Sick.Paralysis; i <= Sick.Poison; i++)
                    if (Poke.CheckSick(i)) return i;
                return 0;
            }
        }

        public bool HasSick(int sickId) => Poke.CheckSick(sickId);

        public void AddSick(int sickId, ulong cont)
        {
            SickContents[sickId] = cont;
            SickCounters[sickId] = 0;
            Poke.SetSick(sickId, SickCont.GetType(cont));
        }

        public void CureSick(int sickId)
        {
            SickContents[sickId] = SickCont.MakeNull();
            SickCounters[sickId] = 0;
            Poke.SetSick(sickId, SickCont.TypeNone);
        }

        // Beim Auswechseln verfallen Zustaende ausser den Hauptzustaenden; Stufen werden zurueckgesetzt.
        public void ClearOnSwitchOut()
        {
            for (int i = 0; i < Sick.Count; i++)
            {
                if (i >= Sick.Paralysis && i <= Sick.Poison)
                {
                    // Gift-Zaehler faellt auf den Anfang zurueck; die Hauptzustaende bleiben.
                    if (i == Sick.Poison && SickCont.IsMoudokuCont(SickContents[i])) SickCounters[i] = 0;
                    continue;
                }
                CureSick(i);
            }
            for (int r = 1; r <= BattlePoke.RankCount; r++) Poke.SetRank((PokeValueId)r, BattlePoke.NeutralRank);
            for (int f = 0; f < BattlePoke.TurnFlagCount; f++) Poke.SetTurnFlag(f, false);
            SpecialPri = SpecialPri_Default;
        }

        public int FindMove(ushort moveNo)
        {
            for (int i = 0; i < MoveCount; i++) if (Moves[i] == moveNo) return i;
            return MoveCount;
        }

        // Aenderungen in die Quelldaten zurueckschreiben (KP, Erfahrung, PP, Zustand), z. B. nach dem Kampf.
        public void WriteBack()
        {
            var core = Source.Core;
            core.CurrentHp = Poke.Hp;
            core.Exp = Exp;
            for (int i = 0; i < MoveCount; i++) core.SetPp(i, Pp[i]);
            Source.Level = Poke.Level;
            Source.MaxHp = Poke.MaxHp;
            Source.Atk = Poke.Attack;
            Source.Def = Poke.Defence;
            Source.SpAtk = Poke.SpAttack;
            Source.SpDef = Poke.SpDefence;
            Source.Speed = Poke.Agility;
        }
    }
}
