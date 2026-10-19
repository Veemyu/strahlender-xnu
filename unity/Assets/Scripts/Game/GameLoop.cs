using System;
using System.Collections.Generic;
using Xnu.Battle.Flow;
using Xnu.EvScript;

namespace Xnu.Game
{
    // Spielschleife als Zustandsmaschine Field <-> Event <-> Battle <-> Menu. Ein Tick = eine Eingabe-Momentaufnahme (GameInput) plus
    // optional eine Meldung der Feldschicht (FieldSignal). Keine Unity-Abhängigkeit, daher headless testbar.
    public sealed class GameLoop
    {
        public GameSession Session { get; }
        public GameEvHost Host { get; }
        public IFieldHost Field { get; }
        public EvInterpreter Interpreter { get; }
        public GameState State { get; private set; } = GameState.Field;
        public BattleSession Battle { get; private set; }
        public BattleOutcome LastOutcome { get; private set; }
        public EvStatus LastEventStatus { get; private set; } = EvStatus.Idle;
        public string LastEventError => Interpreter.LastError;

        public int Ticks { get; private set; }
        public int EventsStarted { get; private set; }
        public int EventsFinished { get; private set; }
        public int BattlesStarted { get; private set; }
        public int BattlesFinished { get; private set; }
        public int BattlesSkipped { get; private set; }
        public int Wipeouts { get; private set; }
        public int MissingLabels { get; private set; }
        public readonly List<string> Trace = new List<string>();
        public bool Record;

        public GameLoop(GameSession session, EvScriptBook book, IFieldHost field)
        {
            Session = session ?? throw new ArgumentNullException(nameof(session));
            Field = field ?? throw new ArgumentNullException(nameof(field));
            Host = new GameEvHost(session, field);
            Interpreter = new EvInterpreter(book ?? throw new ArgumentNullException(nameof(book)), session.Vars, Host);
        }

        void Add(string s)
        {
            if (Record) Trace.Add(s);
        }

        // Ereignis am Label starten (Talk-/Kontaktlabel, Szenenlabel). false: Label unbekannt.
        public bool StartEvent(string label)
        {
            if (State != GameState.Field)
            {
                Add("event-refused " + label);
                return false;
            }
            if (!Interpreter.Start(label))
            {
                MissingLabels++;
                Add("event-missing " + label);
                return false;
            }
            EventsStarted++;
            State = GameState.Event;
            Add("event-start " + label);
            return true;
        }

        public void Tick(float dt, GameInput input, FieldSignal? signal = null)
        {
            Ticks++;
            switch (State)
            {
                case GameState.Field:
                    if (signal.HasValue) HandleSignal(signal.Value);
                    if (State == GameState.Field && input.Menu) { State = GameState.Menu; Add("menu-open"); }
                    break;
                case GameState.Event:
                    RunEvent(dt, input);
                    break;
                case GameState.Battle:
                    StepBattle(input);
                    break;
                case GameState.Menu:
                    if (input.Cancel || input.Menu) { State = GameState.Field; Add("menu-close"); }
                    break;
            }
        }

        void HandleSignal(FieldSignal s)
        {
            switch (s.Kind)
            {
                case FieldSignalKind.Talk:
                case FieldSignalKind.Contact:
                    StartEvent(s.Label);
                    break;
                case FieldSignalKind.Warp:
                    Session.BeforeZoneId = Session.ZoneId;
                    Session.ZoneId = s.A;
                    Field.ChangeZone(s.A, s.B, true);
                    Add("warp " + s.A + " " + s.B);
                    break;
                case FieldSignalKind.Step:
                    var request = EncounterService.Roll(Session.Data, s.A, s.Encounter, Session.Rng);
                    if (request != null) StartBattle(request);
                    break;
            }
        }

        void RunEvent(float dt, GameInput input)
        {
            Host.FeedInput(input);
            var status = Interpreter.Update(dt);
            LastEventStatus = status;
            if (Host.PendingBattle != null)
            {
                StartBattle(Host.TakeBattleRequest());
                return;
            }
            if (status == EvStatus.Waiting) return;
            EventsFinished++;
            Add("event-" + status);
            State = GameState.Field;
        }

        // Kampf von außen auslösen (Prüfwerkzeuge, Begegnung der Feldschicht); nur im Zustand Field. false: abgelehnt oder nicht baubar.
        public bool BeginBattle(BattleRequest request)
        {
            if (request == null || State != GameState.Field) return false;
            StartBattle(request);
            return State == GameState.Battle;
        }

        void StartBattle(BattleRequest request)
        {
            BattlesStarted++;
            Battle = new BattleSession(Session, request);
            if (!Battle.Start())
            {
                LastOutcome = Battle.Outcome;
                BattlesSkipped++;
                Add("battle-skipped");
                AfterBattle(request, Battle.Outcome);
                return;
            }
            State = GameState.Battle;
            Add("battle-start " + request.Kind);
        }

        void StepBattle(GameInput input)
        {
            Battle.Step(input);
            if (Battle.IsFinished) AfterBattle(Battle.Request, Battle.Outcome);
        }

        void AfterBattle(BattleRequest request, BattleOutcome outcome)
        {
            LastOutcome = outcome;
            BattlesFinished++;
            Add("battle-end " + outcome.Result);
            if (outcome.PlayerLost)
            {
                Wipeout();
                return;
            }
            if (request.FromEvent && Interpreter.IsRunning)
            {
                Host.CompleteBattle();
                State = GameState.Event;
            }
            else
            {
                State = GameState.Field;
            }
        }

        // Rückkehr nach Niederlage: Ereignis abbrechen, Team heilen (wie im Pokécenter), zur Rücksetzzone (SET_WARP_ID). Das Geld hat BattleSession abgezogen.
        void Wipeout()
        {
            Wipeouts++;
            if (Interpreter.IsRunning) Interpreter.Abort();
            Session.HealAll();
            if (Session.WipeoutZone >= 0)
            {
                Session.BeforeZoneId = Session.ZoneId;
                Session.ZoneId = Session.WipeoutZone;
                Field.ChangeZone(Session.WipeoutZone, 0, true);
            }
            State = GameState.Field;
            Add("wipeout");
        }
    }

    // Spielt ohne Mensch: bestätigt Texte, wählt Auswahlzeilen und Starter, kämpft mit der ersten brauchbaren Attacke. Nur für Headless-Läufe und Tests.
    public sealed class AutoPlayer
    {
        public int StarterIndex = 1;
        public int ChoiceIndex = -1;       // -1: Auswahl bleibt auf dem Standardwert
        public int Pressed;
        bool _toggle;

        public GameInput Next(GameLoop loop)
        {
            _toggle = !_toggle;
            var input = GameInput.None;
            switch (loop.State)
            {
                case GameState.Event:
                    input.StarterChoice = StarterIndex;
                    // Tasten gelten nur in jedem zweiten Tick als "gerade gedrückt", damit Seitenwechsel einzeln erfolgen.
                    input.Confirm = _toggle;
                    if (loop.Host.Choice.IsOpen && ChoiceIndex >= 0 && loop.Host.Choice.Cursor != ChoiceIndex)
                    {
                        input.Down = _toggle;
                        input.Confirm = false;
                    }
                    if (input.Confirm) Pressed++;
                    break;
                case GameState.Battle:
                    var e = loop.Battle?.Engine;
                    if (e == null) break;
                    if (e.Phase == BattlePhase.AwaitCommands)
                    {
                        var mon = e.Active(BattleEngine.PlayerSide);
                        var slot = 0;
                        for (var i = 0; i < BattleMon.MoveCount; i++)
                            if (mon.Moves[i] != 0 && mon.Pp[i] > 0) { slot = i; break; }
                        input.Battle = BattleCommand.Fight(slot);
                    }
                    else if (e.Phase == BattlePhase.AwaitReplacement)
                    {
                        for (var i = 0; i < e.Parties[BattleEngine.PlayerSide].Count; i++)
                            if (!e.Parties[BattleEngine.PlayerSide][i].IsFainted) { input.Replacement = i; break; }
                    }
                    break;
            }
            return input;
        }

        // Treibt die Schleife, bis stop wahr wird oder maxTicks erreicht sind. Rückgabe: Anzahl Ticks.
        public int Run(GameLoop loop, Func<GameLoop, bool> stop, int maxTicks, float dt = 1f / 30f)
        {
            var n = 0;
            while (n < maxTicks && !stop(loop))
            {
                loop.Tick(dt, Next(loop));
                n++;
            }
            return n;
        }
    }
}
