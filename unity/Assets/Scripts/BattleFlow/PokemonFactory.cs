using System;
using System.Collections.Generic;
using Xnu.Data;
using Xnu.PokePara;

namespace Xnu.Battle.Flow
{
    // Baut PokemonParam fuer Gegner (Trainerteam, Wildbegegnung). Die Zufallswerte der Wildgenerierung stammen aus dem uebergebenen
    // Generator, nicht aus dem Original (Pml.PokePara.InitialSpec ist nicht rekonstruiert).
    public static class PokemonFactory
    {
        public static PokemonParam Create(IBattleData data, int monsNo, int form, int level, int nature, int ability, IReadOnlyList<int> moves,
            int heldItem, IReadOnlyList<int> ivs, IReadOnlyList<int> evs, int sex)
        {
            var species = data.GetSpecies(monsNo, form);
            var p = PokemonParam.CreateEmpty();
            var core = p.Core;
            core.SpeciesNo = (ushort)monsNo;
            core.FormNo = (ushort)form;
            core.Exp = GrowthRate.MinExp(data.GetGrowth(species.GrowthCurve), level);
            core.Nature = (byte)nature;
            core.NatureAdjust = (byte)nature;
            core.Ability = (ushort)(ability != 0 ? ability : species.Ability1);
            core.HeldItem = (ushort)heldItem;
            core.Sex = (byte)sex;
            core.OriginalFriendship = (byte)species.InitialFriendship;
            for (int i = 0; i < 6; i++)
            {
                core.SetNativeIv((StatId)i, (uint)(ivs != null && i < ivs.Count ? ivs[i] : 0));
                core.SetEv((StatId)i, (byte)(evs != null && i < evs.Count ? evs[i] : 0));
            }
            for (int i = 0; i < BattleMon.MoveCount; i++)
            {
                int mv = moves != null && i < moves.Count ? moves[i] : 0;
                core.SetMove(i, (ushort)mv);
                var rec = mv != 0 ? data.GetMove(mv) : null;
                core.SetPp(i, rec == null ? (byte)0 : (byte)rec.BasePp);
            }
            p.RecalculateCalcData(species, data.GetGrowth(species.GrowthCurve));
            return p;
        }

        // Die letzten vier gelernten Attacken bis zur Stufe.
        public static List<int> DefaultMoves(IBattleData data, int monsNo, int form, int level)
        {
            var species = data.GetSpecies(monsNo, form);
            var learned = new List<int>();
            foreach (var lm in data.GetLearnset(species.Id))
                if (lm.Level <= level && !learned.Contains(lm.MoveNo)) learned.Add(lm.MoveNo);
            if (learned.Count > BattleMon.MoveCount) learned.RemoveRange(0, learned.Count - BattleMon.MoveCount);
            return learned;
        }

        public static PokemonParam FromTrainerPokemon(IBattleData data, TrainerPokemonRecord r)
        {
            var moves = new List<int>();
            foreach (int m in r.Moves) if (m != 0) moves.Add(m);
            if (moves.Count == 0) moves = DefaultMoves(data, r.MonsNo, r.FormNo, r.Level);
            return Create(data, r.MonsNo, r.FormNo, r.Level, r.Nature, r.Ability, moves, r.HeldItem, r.Talents, r.Efforts, r.Sex);
        }

        public static PokemonParam CreateWild(IBattleData data, int monsNo, int form, int level, IBattleRandom rng)
        {
            var species = data.GetSpecies(monsNo, form);
            int nature = (int)rng.GetValue(25);
            var ivs = new int[6];
            for (int i = 0; i < 6; i++) ivs[i] = (int)rng.GetValue(32);
            int ability = species.Ability1;
            if (species.Ability2 != 0 && species.Ability2 != species.Ability1 && rng.GetValue(2) == 1) ability = species.Ability2;
            int sex;
            if (species.GenderRatio == 255) sex = 2;
            else if (species.GenderRatio == 254) sex = 1;
            else if (species.GenderRatio == 0) sex = 0;
            else sex = (int)rng.GetValue(256) < species.GenderRatio ? 1 : 0;
            return Create(data, monsNo, form, level, nature, ability, DefaultMoves(data, monsNo, form, level), 0, ivs, null, sex);
        }
    }
}
