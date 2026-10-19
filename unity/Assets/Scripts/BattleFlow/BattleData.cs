using System;
using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.Battle.Flow
{
    // Stammdaten, die der Kampf braucht. Die Standardimplementierung liest die Listen des Masterdata-Readers.
    public interface IBattleData
    {
        SpeciesRecord GetSpecies(int monsNo, int formNo);
        MoveRecord GetMove(int moveNo);
        ItemRecord GetItem(int itemNo);

        // Erfahrungspunkte je Stufe (Index = Stufe) der Wachstumskurve (Zeile von PersonalTable.grow).
        IReadOnlyList<uint> GetGrowth(int growRow);

        // Attacken, die eine Art auf einer Stufe lernt (aufsteigend nach Stufe).
        IReadOnlyList<LevelMove> GetLearnset(int personalId);
    }

    public sealed class BattleData : IBattleData
    {
        readonly Dictionary<int, SpeciesRecord> _species = new Dictionary<int, SpeciesRecord>();
        readonly Dictionary<int, MoveRecord> _moves = new Dictionary<int, MoveRecord>();
        readonly Dictionary<int, ItemRecord> _items = new Dictionary<int, ItemRecord>();
        readonly List<uint[]> _growth = new List<uint[]>();
        readonly Dictionary<int, List<LevelMove>> _learnsets = new Dictionary<int, List<LevelMove>>();

        public BattleData(IEnumerable<SpeciesRecord> species, IEnumerable<MoveRecord> moves, IEnumerable<ItemRecord> items,
            IEnumerable<GrowthCurveRecord> growth, IEnumerable<LearnsetRecord> learnsets = null)
        {
            foreach (var s in species) _species[s.Id] = s;
            foreach (var m in moves) _moves[m.MoveNo] = m;
            if (items != null) foreach (var i in items) _items[i.ItemNo] = i;
            foreach (var g in growth)
            {
                var row = new uint[g.ExpByLevel.Length];
                for (int i = 0; i < row.Length; i++) row[i] = (uint)g.ExpByLevel[i];
                _growth.Add(row);
            }
            if (learnsets != null) foreach (var l in learnsets) _learnsets[l.Id] = l.Moves;
        }

        // Personal-Zeile: Form 0 = Zeile der Art; Formen ab 1 liegen ab form_index (Pml.Personal) [P].
        public SpeciesRecord GetSpecies(int monsNo, int formNo)
        {
            if (!_species.TryGetValue(monsNo, out var s)) throw new KeyNotFoundException("Art " + monsNo);
            if (formNo > 0 && s.FormCount > 1 && s.FormIndex > 0 && formNo < s.FormCount && _species.TryGetValue(s.FormIndex + formNo - 1, out var f))
                return f;
            return s;
        }

        public MoveRecord GetMove(int moveNo) => _moves.TryGetValue(moveNo, out var m) ? m : null;

        public ItemRecord GetItem(int itemNo) => _items.TryGetValue(itemNo, out var i) ? i : null;

        public IReadOnlyList<uint> GetGrowth(int growRow) => _growth[growRow < _growth.Count ? growRow : 0];

        public IReadOnlyList<LevelMove> GetLearnset(int personalId) => _learnsets.TryGetValue(personalId, out var l) ? l : new List<LevelMove>();
    }
}
