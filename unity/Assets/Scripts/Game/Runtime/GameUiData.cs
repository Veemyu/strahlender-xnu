using System;
using System.Collections.Generic;
using Xnu.Text;
using Xnu.UI;

namespace Xnu.Game.Unity
{
    // Daten der Original-Fenster aus Spielstand und lokalen Textdateien (Namen, Beschriftungen). Keine eigenen Spieltexte.
    public sealed class GameUiData : IUiGameData
    {
        // Taschenreihenfolge der Original-Prefabs: Item-Taschen 0..6 und 8 (Medizin, Bälle, Kampf, Beeren, Training, TM, Schätze, Basis-Items).
        public static readonly int[] PocketOrder = { 0, 1, 2, 3, 4, 5, 6, 8 };

        readonly GameSession _session;
        readonly MessageComposer _composer = new MessageComposer();

        public GameUiData(GameSession session)
        {
            _session = session ?? throw new ArgumentNullException(nameof(session));
        }

        public int Money => _session.Money;

        string Get(string msbt, string label)
        {
            if (!_session.Data.Messages.TryGetLabel(msbt, label, _session.Language, out var l)) return null;
            return _composer.Compose(l, new TagWordBuffer()).FlatText;
        }

        public string Label(string msbt, string label) => Get(msbt, label);

        public string Label(string msbt, string label, long number)
        {
            if (!_session.Data.Messages.TryGetLabel(msbt, label, _session.Language, out var l)) return null;
            var words = new TagWordBuffer();
            for (var i = 0; i < 4; i++) words.SetNumber(i, number);
            return _composer.Compose(l, words).FlatText;
        }

        public string SpeciesName(int monsNo) => Get("ss_monsname", "MONSNAME_" + monsNo.ToString("000")) ?? "#" + monsNo;
        public string ItemName(int itemNo) => Get("ss_itemname", "ITEMNAME_" + itemNo.ToString("000")) ?? "#" + itemNo;
        public string ItemInfo(int itemNo) => Get("ss_iteminfo", "ITEMINFO_" + itemNo.ToString("000")) ?? "";

        public IReadOnlyList<PartyRow> PartyRows()
        {
            var rows = new List<PartyRow>();
            var n = _session.PartyCount;
            for (var i = 0; i < n && i < 6; i++)
            {
                var p = _session.GetPartyMember(i);
                if (p == null || p.Core.IsEmpty) continue;
                var core = p.Core;
                var name = core.HasNickname && !string.IsNullOrEmpty(core.Nickname) ? core.Nickname : SpeciesName(core.SpeciesNo);
                var hp = core.CurrentHp;
                rows.Add(new PartyRow
                {
                    Slot = i,
                    MonsNo = core.SpeciesNo,
                    Form = core.FormNo,
                    Name = core.IsEgg ? Get("ss_pokelist", "SS_pokelist_30") ?? name : name,
                    Level = p.Level,
                    Hp = hp,
                    MaxHp = p.MaxHp,
                    Gender = core.Sex,
                    ItemName = core.HeldItem > 0 ? ItemName(core.HeldItem) : "",
                    IsEgg = core.IsEgg,
                    Status = hp == 0 ? "KO" : core.Sick != 0 ? "!" : "",
                });
            }
            return rows;
        }

        public IReadOnlyList<BagPocket> BagPockets()
        {
            var pockets = new List<BagPocket>();
            for (var i = 0; i < PocketOrder.Length; i++)
                pockets.Add(new BagPocket { PocketId = PocketOrder[i], Name = Get("ss_bag_pocket", "SS_bag_pocket_" + (i + 1).ToString("000")) ?? "Tasche " + (i + 1) });
            var battle = _session.Data.Battle;
            for (var no = 1; no < Xnu.Save.SavePlayerLayout.ItemSlotCount; no++)
            {
                var count = _session.GetItemCount(no);
                if (count <= 0) continue;
                var rec = battle.GetItem(no);
                if (rec == null) continue;
                var idx = Array.IndexOf(PocketOrder, rec.FieldPocket);
                if (idx < 0) continue;
                pockets[idx].Entries.Add(new BagEntry { ItemNo = no, Name = ItemName(no), Count = count, Description = ItemInfo(no) });
            }
            foreach (var p in pockets) p.Entries.Sort((a, b) => SortKey(battle, a).CompareTo(SortKey(battle, b)));
            return pockets;
        }

        static int SortKey(Xnu.Battle.Flow.IBattleData battle, BagEntry e)
        {
            var rec = battle.GetItem(e.ItemNo);
            return rec != null && rec.Sort > 0 ? rec.Sort : 100000 + e.ItemNo;
        }
    }
}
