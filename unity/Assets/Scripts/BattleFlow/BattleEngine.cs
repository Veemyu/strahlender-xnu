using System;
using System.Collections.Generic;
using Xnu.Battle.Events;
using Xnu.PokePara;

namespace Xnu.Battle.Flow
{
    public sealed class BattleSetup
    {
        public IBattleData Data;
        public BattleCompetitor Competitor = BattleCompetitor.Wild;
        public ulong Seed = 1;
        public List<PokemonParam> PlayerParty = new List<PokemonParam>();
        public List<PokemonParam> EnemyParty = new List<PokemonParam>();

        // Erfahrungs-Teiler vorhanden (HasPlayerGakusyuSouti): nicht beteiligte Pokemon bekommen die halbe Erfahrung.
        public bool HasExpShare;
        public uint ExpLevelCap = 100;
        public bool Inverse;
        public bool SameLanguage = true;
        public bool GiveEffort = true;

        // Beutel des Spielers: Item-Nr. -> Anzahl.
        public Dictionary<int, int> Bag = new Dictionary<int, int>();

        // null = RandomEnemyBrain.
        public IEnemyBrain EnemyBrain;
    }

    // Entscheidet fuer die Gegnerseite. Die Original-KI (BtlAiExpert, Trainer-KI-Bits) ist nicht umgesetzt.
    public interface IEnemyBrain
    {
        BattleCommand Decide(BattleEngine engine, BattleMon actor, BattleMon foe);

        int ChooseReplacement(BattleEngine engine);
    }

    // Waehlt gleichverteilt eine Attacke mit PP (ohne Wirkung auf den Kampf-Zufall: eigener Generator).
    public sealed class RandomEnemyBrain : IEnemyBrain
    {
        readonly BattleRandom _random;

        public RandomEnemyBrain(ulong seed) => _random = new BattleRandom(seed ^ 0x5DEECE66DUL);

        public BattleCommand Decide(BattleEngine engine, BattleMon actor, BattleMon foe)
        {
            var usable = new List<int>();
            for (int i = 0; i < BattleMon.MoveCount; i++)
                if (actor.Moves[i] != 0 && actor.Pp[i] > 0) usable.Add(i);
            if (usable.Count == 0) return BattleCommand.Fight(0);
            return BattleCommand.Fight(usable[(int)_random.GetValue((ulong)usable.Count)]);
        }

        public int ChooseReplacement(BattleEngine engine)
        {
            var party = engine.Parties[1];
            for (int i = 0; i < party.Count; i++)
                if (!party[i].IsFainted) return i;
            return -1;
        }
    }

    public sealed class WeatherState
    {
        public const int Permanent = 0xFF;

        public BattleWeather Weather;
        public int TurnMax;
        public int Counter;

        public bool Active => Weather != BattleWeather.None;
    }

    // Kampfumgebung fuer das Ereignissystem.
    sealed class FlowEnv : IEventBattleEnv
    {
        readonly BattleEngine _e;

        public FlowEnv(BattleEngine e) => _e = e;

        public BattlePoke GetPoke(int pokeId) => _e.FindMon(pokeId)?.Poke;

        public bool IsFieldEffectActive(int effect) => effect == FieldEffects.Weather && _e.Weather.Active;

        public bool OmmitAfterTransform(ushort tokuseiId) => false;

        public bool OmmitOnGMode(ushort tokuseiId) => false;

        public int GetItemAttackValue(ushort itemId) => _e.Data.GetItem(itemId)?.HoldPower ?? 0;

        public int GetWeather() => (int)_e.Weather.Weather;

        public int GetLocalWeather(int pokeId) => (int)_e.Weather.Weather;

        public bool WazaHasFlag(ushort wazaId, int flag)
        {
            var m = _e.Data.GetMove(wazaId);
            return m != null && flag >= 0 && flag < 32 && (m.Flags >> flag & 1) != 0;
        }

        public bool IsFriend(int pokeIdA, int pokeIdB) => pokeIdA / 6 == pokeIdB / 6;
    }

    // 1:1-Einzelkampf (Wild und Trainer) ohne UnityEngine. Zustandsmaschine: AwaitCommands -> (Runde) -> AwaitReplacement -> ... -> Finished.
    public sealed partial class BattleEngine
    {
        public const int PlayerSide = 0;
        public const int EnemySide = 1;

        readonly FlowEnv _env;
        readonly IEnemyBrain _brain;
        readonly int[] _active = new int[2];
        readonly Dictionary<int, int> _bag;
        bool _turnEndPending;

        public BattleSetup Setup { get; }
        public IBattleData Data { get; }
        public BattleRandom Random { get; }
        public EventSystem Events { get; }
        public BattleEventLauncher Launcher { get; }
        public List<BattleMon>[] Parties { get; } = { new List<BattleMon>(), new List<BattleMon>() };
        public WeatherState Weather { get; } = new WeatherState();
        public List<LogEvent> Log { get; } = new List<LogEvent>();
        public BattlePhase Phase { get; private set; } = BattlePhase.NotStarted;
        public BattleResult Result { get; private set; } = BattleResult.None;
        public int Turn { get; private set; }

        // ESCAPE_TRIED_COUNT: Fluchtversuche (nur Fehlversuche zaehlen hoch).
        public int EscapeTries { get; private set; }

        public IReadOnlyDictionary<int, int> Bag => _bag;

        public BattleEngine(BattleSetup setup)
        {
            Setup = setup ?? throw new ArgumentNullException(nameof(setup));
            Data = setup.Data ?? throw new ArgumentException("Data fehlt", nameof(setup));
            if (setup.PlayerParty.Count == 0 || setup.EnemyParty.Count == 0) throw new ArgumentException("Beide Seiten brauchen mindestens ein Pokemon");
            Random = new BattleRandom(setup.Seed);
            _brain = setup.EnemyBrain ?? new RandomEnemyBrain(setup.Seed);
            _bag = new Dictionary<int, int>(setup.Bag);
            _env = new FlowEnv(this);
            Events = new EventSystem(_env);
            Launcher = new BattleEventLauncher(Events);
            for (int i = 0; i < setup.PlayerParty.Count; i++) Parties[PlayerSide].Add(BattleMon.Create(setup.PlayerParty[i], Data, PlayerSide, i));
            for (int i = 0; i < setup.EnemyParty.Count; i++) Parties[EnemySide].Add(BattleMon.Create(setup.EnemyParty[i], Data, EnemySide, i));
        }

        public BattleMon FindMon(int pokeId)
        {
            int side = pokeId / 6;
            int idx = pokeId % 6;
            if (side < 0 || side > 1 || idx >= Parties[side].Count) return null;
            return Parties[side][idx];
        }

        public BattleMon Active(int side) => Parties[side][_active[side]];

        public int ActiveIndex(int side) => _active[side];

        public bool IsWild => Setup.Competitor == BattleCompetitor.Wild;

        public bool HasAlive(int side)
        {
            foreach (var m in Parties[side]) if (!m.IsFainted) return true;
            return false;
        }

        LogEvent Add(LogKind kind, int poke = -1, int target = -1, int id = 0, int value = 0, int value2 = 0)
        {
            var e = new LogEvent { Kind = kind, Turn = Turn, Poke = poke, Target = target, Id = id, Value = value, Value2 = value2 };
            Log.Add(e);
            return e;
        }

        // Beginn: erste kampffaehige Pokemon beider Seiten treten ein.
        public void Start()
        {
            if (Phase != BattlePhase.NotStarted) throw new InvalidOperationException("Kampf bereits gestartet");
            Add(LogKind.BattleStart, value: (int)Setup.Competitor);
            for (int side = 0; side < 2; side++)
            {
                int first = FirstAlive(side);
                if (first < 0) throw new InvalidOperationException("Seite " + side + " hat kein kampffaehiges Pokemon");
                _active[side] = first;
            }
            for (int side = 0; side < 2; side++) EnterField(side, _active[side]);
            Phase = BattlePhase.AwaitCommands;
        }

        int FirstAlive(int side)
        {
            for (int i = 0; i < Parties[side].Count; i++) if (!Parties[side][i].IsFainted) return i;
            return -1;
        }

        // Faktoren (Faehigkeit, Item) registrieren und Gegenueber-Eintraege fuer die Erfahrungsverteilung setzen.
        void EnterField(int side, int index)
        {
            _active[side] = index;
            var mon = Parties[side][index];
            var foe = Active(1 - side);
            TokuseiHandlers.Add(Events, mon.Poke);
            ItemHandlers.Add(Events, mon.Poke);
            mon.SpecialPri = 1;
            if (!foe.IsFainted)
            {
                mon.Confronted.Add(foe.PokeId);
                foe.Confronted.Add(mon.PokeId);
            }
            Add(LogKind.SendOut, mon.PokeId, id: mon.Poke.MonsNo, value: mon.Level, value2: mon.Poke.Hp);
        }

        void LeaveField(int side)
        {
            var mon = Active(side);
            TokuseiHandlers.Remove(Events, mon.Poke);
            ItemHandlers.Remove(Events, mon.Poke);
            mon.ClearOnSwitchOut();
        }

        // ------------------------------------------------------------------------------------------------------
        // Befehlsphase
        // ------------------------------------------------------------------------------------------------------

        public bool IsCommandValid(int side, BattleCommand cmd, out string reason)
        {
            reason = null;
            var mon = Active(side);
            switch (cmd.Kind)
            {
                case CommandKind.Fight:
                    if (cmd.MoveSlot < 0 || cmd.MoveSlot >= BattleMon.MoveCount || mon.Moves[cmd.MoveSlot] == 0) { reason = "Attackenplatz leer"; return false; }
                    if (mon.Pp[cmd.MoveSlot] == 0 && AnyPp(mon)) { reason = "Keine PP"; return false; }
                    return true;
                case CommandKind.Change:
                    if (cmd.PartyIndex < 0 || cmd.PartyIndex >= Parties[side].Count) { reason = "Ungueltiger Platz"; return false; }
                    if (cmd.PartyIndex == _active[side] || Parties[side][cmd.PartyIndex].IsFainted) { reason = "Pokemon nicht einsatzbereit"; return false; }
                    return true;
                case CommandKind.Run:
                    if (!IsWild) { reason = "Flucht im Trainerkampf nicht erlaubt"; return false; }
                    return side == PlayerSide;
                case CommandKind.Item:
                    if (side != PlayerSide) { reason = "Nur der Spieler benutzt Items"; return false; }
                    if (!_bag.TryGetValue(cmd.ItemId, out int count) || count <= 0) { reason = "Item nicht im Beutel"; return false; }
                    if (ItemHealAmount(cmd.ItemId) <= 0) { reason = "Item hier ohne Wirkung"; return false; }
                    return true;
                default:
                    return false;
            }
        }

        static bool AnyPp(BattleMon m)
        {
            for (int i = 0; i < BattleMon.MoveCount; i++) if (m.Moves[i] != 0 && m.Pp[i] > 0) return true;
            return false;
        }

        // Spielerbefehl; die Gegnerseite entscheidet die KI.
        public void Submit(BattleCommand player)
        {
            if (Phase != BattlePhase.AwaitCommands) throw new InvalidOperationException("Keine Befehle erwartet (Phase " + Phase + ")");
            Submit(player, _brain.Decide(this, Active(EnemySide), Active(PlayerSide)));
        }

        public void Submit(BattleCommand player, BattleCommand enemy)
        {
            if (Phase != BattlePhase.AwaitCommands) throw new InvalidOperationException("Keine Befehle erwartet (Phase " + Phase + ")");
            if (!IsCommandValid(PlayerSide, player, out string r1)) throw new ArgumentException("Spielerbefehl ungueltig: " + r1);
            if (enemy.Kind == CommandKind.Run || enemy.Kind == CommandKind.Item) throw new ArgumentException("Gegnerbefehl ungueltig: Flucht/Item nicht unterstuetzt");
            if (!IsCommandValid(EnemySide, enemy, out string r2) && AnyPp(Active(EnemySide))) throw new ArgumentException("Gegnerbefehl ungueltig: " + r2);
            RunTurn(player, enemy);
        }

        // Ersatz nach einem besiegten Pokemon (Phase AwaitReplacement).
        public void SubmitReplacement(int partyIndex)
        {
            if (Phase != BattlePhase.AwaitReplacement) throw new InvalidOperationException("Kein Ersatz erwartet (Phase " + Phase + ")");
            var cmd = BattleCommand.Change(partyIndex);
            if (partyIndex < 0 || partyIndex >= Parties[PlayerSide].Count || Parties[PlayerSide][partyIndex].IsFainted)
                throw new ArgumentException("Ersatz nicht einsatzbereit");
            SwapIn(PlayerSide, partyIndex, replacement: true);
            AfterReplacement();
        }

        void AfterReplacement()
        {
            Phase = BattlePhase.AwaitCommands;
            if (_turnEndPending) FinishTurn();
        }

        void Finish(BattleResult result)
        {
            Result = result;
            Phase = BattlePhase.Finished;
            Add(LogKind.BattleEnd, value: (int)result);
            foreach (var side in Parties) foreach (var m in side) m.WriteBack();
        }

        // Alle Pokemon einer Seite besiegt?
        bool CheckShowdown()
        {
            bool playerDown = !HasAlive(PlayerSide);
            bool enemyDown = !HasAlive(EnemySide);
            if (!playerDown && !enemyDown) return false;
            Finish(playerDown && enemyDown ? BattleResult.Draw : playerDown ? BattleResult.Lose : BattleResult.Win);
            return true;
        }

        // ------------------------------------------------------------------------------------------------------
        // Runde
        // ------------------------------------------------------------------------------------------------------

        sealed class PendingAction
        {
            public BattleMon Actor;
            public BattleCommand Command;
            public ActionKind Kind;
            public uint Priority;
        }

        void RunTurn(BattleCommand playerCmd, BattleCommand enemyCmd)
        {
            Turn++;
            Add(LogKind.TurnStart, value: Turn);
            Events.WakeAllFactors();
            Events.VarCheckStackCleared();
            foreach (int side in new[] { PlayerSide, EnemySide }) Active(side).SpecialPri = 1;

            var actions = new List<PendingAction>
            {
                MakeAction(PlayerSide, playerCmd),
                MakeAction(EnemySide, enemyCmd),
            };
            // Section_Root_ProcessActions: sortieren, Sonderprioritaet setzen, noch einmal sortieren (Gleichstaende ziehen jedes Mal).
            SortActions(actions);
            foreach (var a in actions)
                if (a.Kind == ActionKind.Fight) a.Actor.SpecialPri = CheckSpecialPriority(a.Actor);
            SortActions(actions);
            Add(LogKind.ActionOrder, actions[0].Actor.PokeId, actions[1].Actor.PokeId, value: (int)actions[0].Priority, value2: (int)actions[1].Priority);

            foreach (var a in actions)
            {
                if (Phase == BattlePhase.Finished) return;
                ProcessAction(a);
                if (Phase == BattlePhase.Finished) return;
            }

            if (CheckShowdown()) return;
            TurnCheck();
            if (Phase == BattlePhase.Finished) return;
            CoverCheck();
        }

        PendingAction MakeAction(int side, BattleCommand cmd)
        {
            ActionKind kind;
            switch (cmd.Kind)
            {
                case CommandKind.Fight: kind = ActionKind.Fight; break;
                case CommandKind.Item: kind = ActionKind.Item; break;
                case CommandKind.Change: kind = ActionKind.Change; break;
                default: kind = ActionKind.Escape; break;
            }
            return new PendingAction { Actor = Active(side), Command = cmd, Kind = kind };
        }

        void SortActions(List<PendingAction> actions)
        {
            foreach (var a in actions) a.Priority = CalcActionPriority(a);
            FlowRules.SortActionOrder(actions, a => a.Priority, Random);
        }

        // Section_CalcActionPriority.Execute @0x22ad570.
        uint CalcActionPriority(PendingAction a)
        {
            uint operation;
            switch (a.Kind)
            {
                case ActionKind.Item: operation = 4; break;
                case ActionKind.Change: operation = 5; break;
                case ActionKind.Escape: operation = IsWild && a.Actor.Side == EnemySide ? 1u : 6u; break;
                default: operation = 1; break;
            }
            uint wazaPri = 0;
            if (a.Kind == ActionKind.Fight) wazaPri = GetWazaPriority(a.Actor, a.Actor.Moves[a.Command.MoveSlot]);
            return ActPri.Make(0, operation, wazaPri, a.Actor.SpecialPri, CalcAgility(a.Actor));
        }

        // Event_GetWazaPriority @0x1e178a0: Attackenprioritaet + 7, Handler (Ereignis 17) duerfen sie aendern.
        uint GetWazaPriority(BattleMon mon, ushort moveNo)
        {
            var rec = Data.GetMove(moveNo);
            int pri = (rec?.Priority ?? 0) + 7;
            Events.VarPush();
            Events.SetConstValue(EventVarLabel.POKEID_ATK, mon.PokeId);
            Events.SetConstValue(EventVarLabel.WAZAID, moveNo);
            Events.SetConstValue(EventVarLabel.WAZA_TYPE, rec?.Type ?? 0);
            Events.SetValue(EventVarLabel.WAZA_PRI, pri);
            Events.CallEvent(EventId.GET_WAZA_PRI);
            int result = Events.GetValue(EventVarLabel.WAZA_PRI);
            Events.VarPop();
            return (uint)result;
        }

        // Event_CheckSpecialActPriority @0x1e1c7f0.
        uint CheckSpecialPriority(BattleMon mon)
        {
            Events.VarPush();
            Events.SetConstValue(EventVarLabel.POKEID, mon.PokeId);
            Events.SetRewriteOnceValue(EventVarLabel.SP_PRIORITY, (int)mon.SpecialPri);
            Events.CallEvent(EventId.CHECK_SP_PRIORITY);
            int result = Events.GetValue(EventVarLabel.SP_PRIORITY);
            Events.VarPop();
            return (uint)result;
        }

        // Event_CalcAgility @0x1e179a0 (mit Bereichsumkehr "Bereich der Ordnung").
        public uint CalcAgility(BattleMon mon, bool trickRoomAware = true)
        {
            int agility = mon.Poke.GetValue(PokeValueId.AGILITY);
            Events.VarPush();
            Events.SetConstValue(EventVarLabel.POKEID, mon.PokeId);
            Events.SetConstValue(EventVarLabel.AGILITY, agility);
            Events.SetValue(EventVarLabel.GEN_FLAG, 1);
            Events.SetValue(EventVarLabel.TRICK_FLAG, 0);
            Events.SetMulValue(EventVarLabel.RATIO, 0x1000, 0x19A, 0x20000);
            Events.CallEvent(EventId.CALC_AGILITY);
            uint value = (uint)Events.GetValue(EventVarLabel.AGILITY);
            uint ratio = (uint)Events.GetValue(EventVarLabel.RATIO);
            uint result = FlowRules.FinishAgility(value, ratio, mon.PokeSick == Sick.Paralysis, Events.GetValue(EventVarLabel.GEN_FLAG) != 0,
                trickRoomAware, Events.GetValue(EventVarLabel.TRICK_FLAG) != 0);
            Events.VarPop();
            return result;
        }

        void ProcessAction(PendingAction a)
        {
            var actor = a.Actor;
            if (actor.IsFainted) return;
            // Nach einem Wechsel/Faint steht evtl. ein anderes Pokemon auf dem Platz: die Aktion gehoert dem Pokemon, das sie gewaehlt hat.
            if (Active(actor.Side) != actor) return;
            actor.Poke.SetTurnFlag(0, true);
            switch (a.Kind)
            {
                case ActionKind.Fight:
                    ExecuteFight(actor, a.Command.MoveSlot);
                    break;
                case ActionKind.Item:
                    ExecuteItem(actor, a.Command);
                    break;
                case ActionKind.Change:
                    SwapIn(actor.Side, a.Command.PartyIndex, replacement: false);
                    break;
                case ActionKind.Escape:
                    ExecuteRun(actor);
                    break;
            }
            if (Phase != BattlePhase.Finished && a.Kind == ActionKind.Fight) actor.Poke.SetTurnFlag(1, true);
        }

        void SwapIn(int side, int partyIndex, bool replacement)
        {
            var old = Active(side);
            if (!replacement || !old.IsFainted) LeaveField(side);
            else
            {
                TokuseiHandlers.Remove(Events, old.Poke);
                ItemHandlers.Remove(Events, old.Poke);
                old.ClearOnSwitchOut();
            }
            EnterField(side, partyIndex);
            Add(LogKind.Switch, old.PokeId, Active(side).PokeId);
        }

        // Section_CoverCheck: besiegte Pokemon auf dem Feld werden ersetzt. Die Gegnerseite waehlt die KI, der Spieler wird gefragt.
        void CoverCheck()
        {
            if (CheckShowdown()) return;
            if (Active(EnemySide).IsFainted)
            {
                int idx = _brain.ChooseReplacement(this);
                if (idx >= 0) SwapIn(EnemySide, idx, replacement: true);
            }
            if (Active(PlayerSide).IsFainted)
            {
                _turnEndPending = true;
                Phase = BattlePhase.AwaitReplacement;
                return;
            }
            FinishTurn();
        }

        // Section_TurnEnd.Execute (Einzelkampf): Rundenflags loeschen, Isolate-Faktoren entfernen, Ereignis, Zaehler.
        void FinishTurn()
        {
            _turnEndPending = false;
            foreach (var side in Parties)
                foreach (var m in side)
                    for (int f = 0; f < BattlePoke.TurnFlagCount; f++) m.Poke.SetTurnFlag(f, false);
            Events.RemoveIsolateFactors();
            Add(LogKind.TurnEnd, value: Turn);
            Phase = BattlePhase.AwaitCommands;
        }

        // ------------------------------------------------------------------------------------------------------
        // Flucht, Items
        // ------------------------------------------------------------------------------------------------------

        void ExecuteRun(BattleMon actor)
        {
            Add(LogKind.RunAttempt, actor.PokeId);
            if (actor.Side == EnemySide) return;
            var foe = Active(EnemySide);
            // Section_Escape_Sub.checkForceSucceed: Geist-Typ (Typ 7) oder Handler-Ereignis "Fluchtberechnung ueberspringen".
            bool forced = actor.Poke.IsMatchType((int)PokeType.Ghost) || SkipEscapeCalc(actor);
            bool success = true;
            if (!forced)
                success = FlowRules.EscapeByAgility((uint)actor.Poke.GetValueBase(PokeValueId.AGILITY), (uint)foe.Poke.GetValueBase(PokeValueId.AGILITY), (uint)EscapeTries, Random);
            if (success && EscapeForbidden(actor)) success = false;
            if (success)
            {
                Add(LogKind.RunSuccess, actor.PokeId);
                Finish(BattleResult.Run);
            }
            else
            {
                EscapeTries++;
                Add(LogKind.RunFailed, actor.PokeId);
            }
        }

        // Event_SkipNigeruCalc @0x1e16df0.
        bool SkipEscapeCalc(BattleMon mon)
        {
            if (mon.IsFainted) return false;
            Events.VarPush();
            Events.SetConstValue(EventVarLabel.POKEID, mon.PokeId);
            Events.SetRewriteOnceValue(EventVarLabel.GEN_FLAG, 0);
            Events.CallEvent(EventId.SKIP_NIGERU_CALC);
            bool skip = Events.GetValue(EventVarLabel.GEN_FLAG) != 0;
            Events.VarPop();
            return skip;
        }

        // Event_CheckNigeruForbid @0x1e17e80: Zustand 22 (Fluchtverbot) oder Bindung (8) verbieten die Flucht.
        bool EscapeForbidden(BattleMon mon)
        {
            if (mon.IsFainted) return false;
            Events.VarPush();
            Events.SetConstValue(EventVarLabel.POKEID, mon.PokeId);
            Events.SetRewriteOnceValue(EventVarLabel.FAIL_FLAG, 0);
            if (mon.HasSick(Sick.MeanLook) || mon.HasSick(Sick.Bind)) Events.RewriteValue(EventVarLabel.FAIL_FLAG, 1);
            Events.CallEvent(EventId.NIGERU_FORBID);
            bool forbidden = Events.GetValue(EventVarLabel.FAIL_FLAG) != 0;
            Events.VarPop();
            return forbidden;
        }

        // KP-Heilung eines Items (wk_prm_hp_rcv); 0 = kein Heil-Item. 255 = volle KP.
        int ItemHealAmount(int itemId)
        {
            var item = Data.GetItem(itemId);
            if (item == null) return 0;
            return item.Effects.TryGetValue("wk_prm_hp_rcv", out int v) ? v : 0;
        }

        void ExecuteItem(BattleMon actor, BattleCommand cmd)
        {
            if (!_bag.TryGetValue(cmd.ItemId, out int count) || count <= 0) return;
            int heal = ItemHealAmount(cmd.ItemId);
            if (heal <= 0) return;
            var target = cmd.ItemTarget >= 0 && cmd.ItemTarget < Parties[PlayerSide].Count ? Parties[PlayerSide][cmd.ItemTarget] : actor;
            if (target.IsFainted || target.Poke.IsHpFull) return;
            int amount = heal >= 255 ? target.Poke.MaxHp : heal;
            int before = target.Poke.Hp;
            target.Poke.Hp = (ushort)Math.Min(target.Poke.MaxHp, before + amount);
            _bag[cmd.ItemId] = count - 1;
            Add(LogKind.ItemUsed, target.PokeId, id: cmd.ItemId, value: target.Poke.Hp - before, value2: target.Poke.Hp);
        }
    }
}
