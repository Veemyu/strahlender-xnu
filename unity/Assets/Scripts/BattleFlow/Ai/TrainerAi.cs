using System;
using System.Collections.Generic;
using Xnu.Battle.Events;

namespace Xnu.Battle.Flow
{
    // AIBit-Flags der Trainerdaten (BtlAiscriptBit des Originals).
    public static class AiBit
    {
        public const uint Basic = 1, Strong = 2, Expert = 4, Double = 8, Allowance = 16, Item = 32, PokeChange = 64;
    }

    public enum AiActionKind
    {
        Move = 0,
        Item = 1,
        Change = 2,
        Escape = 3,
        Struggle = 4,
    }

    public sealed class AiResult
    {
        public AiActionKind Action;
        public int MoveSlot;
        public int ItemId;
        public int ChangeIndex;
        public int[] Scores = new int[4];     // Wertung je Attackenplatz (100 + Skriptsumme); 0 = nicht bewertet
    }

    // Entscheidet fuer eine Seite (Einzelkampf). Der Standardgegner (RandomEnemyBrain) bleibt bestehen; diese KI ist optional pro Trainer.
    public interface IBattleAi
    {
        AiResult Decide(BattleEngine engine, int side);

        int ChooseReplacement(BattleEngine engine, int side);
    }

    // Brueckenklasse: IBattleAi als IEnemyBrain der Engine (BattleSetup.EnemyBrain bzw. BattleSetup.EnemyAi).
    public sealed class BattleAiBrain : IEnemyBrain
    {
        readonly IBattleAi _ai;

        public AiResult LastResult { get; private set; }

        public BattleAiBrain(IBattleAi ai) => _ai = ai ?? throw new ArgumentNullException(nameof(ai));

        public BattleCommand Decide(BattleEngine engine, BattleMon actor, BattleMon foe)
        {
            var r = _ai.Decide(engine, actor.Side);
            LastResult = r;
            switch (r.Action)
            {
                case AiActionKind.Item: return BattleCommand.Item(r.ItemId);
                case AiActionKind.Change: return BattleCommand.Change(r.ChangeIndex);
                default: return BattleCommand.Fight(r.MoveSlot);
            }
        }

        public int ChooseReplacement(BattleEngine engine) => _ai.ChooseReplacement(engine, BattleEngine.EnemySide);
    }

    // Trainer-KI: BattleAi (Aktionswahl) + AiWazaJudge (Wertung je Attacke) + AiItemJudge + AiPokeChangeJudge des Originals.
    // Wertungsablauf [P]: je Attacke Startwert 100, dazu die Summe der Skriptwertungen aller gesetzten Waza-Skripte (Basic/Strong/Expert/Double/Allowance);
    // gewaehlt wird zufaellig unter den Attacken mit der hoechsten Wertung. Item (Wertung 100 + Item-Skript) und Wechsel konkurrieren als
    // gleichrangige Aktionen um die hoechste Wertung. Nicht umgesetzte Skripte (Strong, Expert, Double) tragen nichts bei.
    public sealed class TrainerAi : IBattleAi
    {
        public const int StartScore = 100;

        readonly uint _bits;
        readonly int[] _items;
        readonly ulong _seed;
        AiWorld _world;
        readonly Dictionary<int, AiScriptBase> _scripts = new Dictionary<int, AiScriptBase>();

        public uint Bits => _bits;

        // Wechselfreigabe des zuletzt gelaufenen Skripts (p_PokeChangeEnable).
        internal bool LastEnable;

        public TrainerAi(uint aiBits, ulong seed, int[] useItems = null)
        {
            _bits = aiBits;
            _seed = seed;
            _items = useItems == null ? new int[4] : (int[])useItems.Clone();
            if (_items.Length < 4) Array.Resize(ref _items, 4);
        }

        // Trainerdaten -> KI; Trainer ohne gesetzte Bits bekommen keine KI (null).
        public static TrainerAi ForTrainer(uint aiBits, ulong seed, int[] useItems) => aiBits == 0 ? null : new TrainerAi(aiBits, seed, useItems);

        AiScriptBase Script(int no)
        {
            if (_scripts.TryGetValue(no, out var s)) return s;
            switch (no)
            {
                case 0: s = new AiScriptBasic(); break;
                case 1: s = AiGenerated.Create("AiScriptStrongFull") ?? new AiScriptStrong(); break;
                case 2: s = AiGenerated.Create("AiScriptExpert"); break;
                case 3: s = AiGenerated.Create("AiScriptDouble"); break;
                case 4: s = new AiScriptAllowance(); break;
                case 5: s = new AiScriptItem(); break;
                case 6: s = new AiScriptPokeChange(); break;
                default: s = null; break;
            }
            _scripts[no] = s;
            return s;
        }

        bool Has(int scriptNo) => (_bits >> scriptNo & 1) != 0;

        // Gesetzte KI-Bits, für die keine Skriptklasse vorliegt (Expert/Double fehlen ohne die erzeugten Klassen).
        public int UnimplementedScriptBits
        {
            get
            {
                int n = 0;
                for (int no = 0; no < 7; no++) if (Has(no) && Script(no) == null) n++;
                return n;
            }
        }

        static int AliveCount(BattleEngine e, int side)
        {
            int n = 0;
            foreach (var m in e.Parties[side]) if (!m.IsFainted) n++;
            return n;
        }

        // Waehlbare Attacken (PP, Wahl-Item-Sperre); eine gesperrte Attacke ohne PP hebt die Sperre auf.
        bool[] UsableMoves(BattleMon mon)
        {
            var f = new bool[BattleMon.MoveCount];
            int lockSlot = mon.ChoiceLock == 0 ? BattleMon.MoveCount : mon.FindMove(mon.ChoiceLock);
            bool locked = lockSlot < BattleMon.MoveCount && mon.Pp[lockSlot] > 0;
            for (int i = 0; i < f.Length; i++)
                f[i] = mon.Moves[i] != 0 && mon.Pp[i] > 0 && (!locked || i == lockSlot);
            return f;
        }

        // AIItem_CheckUse [P/A]: Heil-Item, wenn KP <= 1/4; Platz i nur, wenn lebende Pokemon <= {6,4,2,1}[i]; bei mehreren hoechste Prioritaet [A: Heilmenge].
        int OfferItem(BattleEngine e, BattleMon mon, out int slot)
        {
            slot = -1;
            if (mon.HasSick(0x13)) return 0;
            int alive = AliveCount(e, mon.Side);
            int[] limit = { 6, 4, 2, 1 };
            int bestPri = -1, bestItem = 0;
            for (int i = 0; i < 4; i++)
            {
                if (limit[i] < alive) break;
                int item = _items[i];
                if (item == 0) continue;
                var rec = e.Data.GetItem(item);
                if (rec == null || !rec.Effects.TryGetValue("wk_prm_hp_rcv", out int heal) || heal <= 0) continue;
                if (mon.Poke.Hp > mon.Poke.MaxHp / 4) continue;
                int pri = heal;
                if (pri > bestPri) { bestPri = pri; bestItem = item; slot = i; }
            }
            return bestItem;
        }

        public AiResult Decide(BattleEngine engine, int side)
        {
            // [P] BattleAi.ctor: eigener Random (Xoroshiro128+), mit dem randSeed des Kampf-Setups initialisiert (Random.Initialize(setup.+0x28)) - kein XOR, eigene Folge.
            if (_world == null) _world = new AiWorld(engine, engine.Setup.Seed != 0 ? engine.Setup.Seed : _seed);
            _world.Begin(side);
            var mon = engine.Active(side);
            var result = new AiResult();
            // Aktionstabelle: [Attacke, Item, Wechsel, Flucht, Verzweiflung] -> (bewertet?, Wertung).
            var scored = new bool[5];
            var score = new int[] { StartScore, StartScore, StartScore, StartScore, StartScore };

            int itemSlot;
            int item = OfferItem(engine, mon, out itemSlot);
            if (item != 0)
            {
                int s = StartScore;
                if (Has(5)) s += RunScript(5, mon, -1, 0, (ushort)item);
                scored[1] = true;
                score[1] = s;
            }

            int bench = FirstBench(engine, side);
            if (!engine.IsWild && Has(6) && bench >= 0 && engine.IsCommandValid(side, BattleCommand.Change(bench), out _))
            {
                var chg = new AiPokeChangeJudge(engine, _world).Judge(mon, Script(6) as AiScriptPokeChange, this, out int index);
                if (chg.HasValue)
                {
                    scored[2] = true;
                    score[2] = chg.Value;
                    result.ChangeIndex = index;
                }
            }

            var flags = UsableMoves(mon);
            bool any = false;
            foreach (bool f in flags) any |= f;
            int moveSlot = -1;
            if (!any)
            {
                scored[4] = true;
                score[4] = StartScore;
            }
            else
            {
                var wazaScore = new int[BattleMon.MoveCount];
                var normal = new bool[BattleMon.MoveCount];
                for (int i = 0; i < wazaScore.Length; i++) wazaScore[i] = StartScore;
                for (int sc = 0; sc <= 4; sc++)
                {
                    if (!Has(sc)) continue;
                    for (int i = 0; i < BattleMon.MoveCount; i++)
                    {
                        if (!flags[i]) continue;
                        normal[i] = true;
                        wazaScore[i] += RunScript(sc, mon, i, mon.Moves[i], (ushort)(scored[1] ? item : 0));
                    }
                }
                moveSlot = DecideBest(wazaScore, normal, flags);
                for (int i = 0; i < 4; i++) result.Scores[i] = normal[i] ? wazaScore[i] : 0;
                scored[0] = true;
                score[0] = moveSlot >= 0 && normal[moveSlot] ? wazaScore[moveSlot] : StartScore;
            }

            // DecideAction: hoechste Wertung unter den bewerteten Aktionen, bei Gleichstand Zufall (Random.GetValue(n)).
            var cands = new List<int>();
            int best = 0;
            for (int a = 0; a < 5; a++)
            {
                if (!scored[a]) continue;
                if (cands.Count == 0 || score[a] > best) { best = score[a]; cands.Clear(); cands.Add(a); }
                else if (score[a] == best) cands.Add(a);
            }
            int pick = cands.Count == 0 ? 0 : cands.Count == 1 ? cands[0] : cands[(int)_world.Rng.GetValue((ulong)cands.Count)];
            result.Action = (AiActionKind)pick;
            if (result.Action == AiActionKind.Item) { result.ItemId = item; _items[itemSlot] = 0; }
            else if (result.Action == AiActionKind.Move) result.MoveSlot = moveSlot;
            else if (result.Action == AiActionKind.Struggle) result.MoveSlot = 0;
            return result;
        }

        static int FirstBench(BattleEngine e, int side)
        {
            for (int i = 0; i < e.Parties[side].Count; i++)
                if (i != e.ActiveIndex(side) && !e.Parties[side][i].IsFainted) return i;
            return -1;
        }

        internal int RunScript(int scriptNo, BattleMon mon, int slot, ushort moveNo, ushort itemNo)
        {
            var script = Script(scriptNo);
            if (script == null) return 0;
            _world.MoveSlot = slot;
            _world.MoveNo = moveNo;
            _world.ItemNo = itemNo;
            script.Host = _world;
            script.Score = 0;
            script.PokeChangeEnable = 0;
            script.Run(scriptNo == 5 || scriptNo == 6 || scriptNo == 3 ? "main" : "main_proc");
            LastEnable = script.PokeChangeEnable != 0;
            return script.Score;
        }

        // wazaScore_DecideBest (Einzelkampf): hoechste Wertung, Zufall unter Gleichen; ohne bewertete Attacke zufaellig unter den nutzbaren.
        int DecideBest(int[] score, bool[] normal, bool[] usable)
        {
            int best = 0, count = 0;
            bool first = true;
            for (int i = 0; i < score.Length; i++)
            {
                if (!normal[i]) continue;
                if (first || score[i] > best) { best = score[i]; count = 1; first = false; }
                else if (score[i] == best) count++;
            }
            if (count == 0)
            {
                var list = new List<int>();
                for (int i = 0; i < usable.Length; i++) if (usable[i]) list.Add(i);
                return list.Count == 0 ? -1 : list[(int)_world.Rng.GetValue((ulong)list.Count)];
            }
            int r = (int)_world.Rng.GetValue((ulong)count);
            for (int i = 0; i < score.Length; i++)
            {
                if (!normal[i] || score[i] != best) continue;
                if (r == 0) return i;
                r--;
            }
            return -1;
        }

        // Ersatz nach einem besiegten Pokemon: erstes kampffaehiges (BTL_CLIENT waehlt ohne Skript) [A].
        public int ChooseReplacement(BattleEngine engine, int side)
        {
            var party = engine.Parties[side];
            for (int i = 0; i < party.Count; i++) if (!party[i].IsFainted) return i;
            return -1;
        }
    }
}
