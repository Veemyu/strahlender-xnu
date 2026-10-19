using System;
using System.Collections.Generic;
using Xnu.Battle.Flow;
using Xnu.Data;
using Xnu.EvScript;
using Xnu.Text;

namespace Xnu.Game
{
    // Konkreter Host für EvScript: verbindet die Befehle mit Spielstand, Textfenster, Kampf und Feldschicht.
    // Die 599 Host-Kennungen laufen über HostCommands.Table; unbekannte Kennungen werden gezählt (Gaps) und gelten als fertig.
    public sealed partial class GameEvHost : IEvHost
    {
        readonly MessageComposer _composer = new MessageComposer();

        public GameSession Session { get; }
        public IFieldHost Field { get; }
        public DialogModel Dialog { get; } = new DialogModel();
        public ChoiceModel Choice { get; } = new ChoiceModel();
        // Eingabe des laufenden Ticks (setzt GameLoop vor jedem Update).
        public GameInput Input { get; set; } = GameInput.None;

        // Kampfwunsch, den die Spielschleife übernimmt; der Ereignisbefehl wartet, bis CompleteBattle() gerufen wird.
        public BattleRequest PendingBattle { get; private set; }
        bool _battleDone;
        bool _starterWaiting;

        public int EventsEnded { get; private set; }
        public int FadeSpeed { get; set; } = 1;
        public int GapCommandCalls { get; private set; }
        public readonly Dictionary<int, int> Gaps = new Dictionary<int, int>();
        public readonly Dictionary<int, int> HandledIds = new Dictionary<int, int>();
        public readonly List<string> Log = new List<string>();
        public bool Record;

        public GameEvHost(GameSession session, IFieldHost field)
        {
            Session = session ?? throw new ArgumentNullException(nameof(session));
            Field = field ?? throw new ArgumentNullException(nameof(field));
        }

        void Add(string s)
        {
            if (Record) Log.Add(s);
        }

        // Je Tick einmal vor dem Interpreter: Eingabe an offene Fenster geben.
        public void FeedInput(GameInput input)
        {
            Input = input;
            Dialog.Feed(input);
            Choice.Feed(input);
        }

        public void RequestBattle(BattleRequest request)
        {
            PendingBattle = request;
            _battleDone = false;
            Add("battle-request " + request.Kind);
        }

        // Die Spielschleife hat den Kampf übernommen (PendingBattle gehört jetzt dem Kampfzustand).
        public BattleRequest TakeBattleRequest()
        {
            var r = PendingBattle;
            PendingBattle = null;
            return r;
        }

        public void CompleteBattle() => _battleDone = true;

        bool ConsumeBattleDone()
        {
            if (!_battleDone) return false;
            _battleDone = false;
            return true;
        }

        // ---- Text ----

        public ComposedMessage ComposeLabel(string msbt, string label)
        {
            if (!Session.Data.Messages.TryGetLabel(msbt, label, Session.Language, out var l)) return null;
            return _composer.Compose(l, Session.Words);
        }

        public string LabelText(string msbt, string label) => ComposeLabel(msbt, label)?.FlatText ?? "";

        public void TalkBegin(EvTalkRequest request)
        {
            Dialog.Open(request.Msbt, request.Label, ComposeLabel(request.Msbt, request.Label));
            Add("talk " + request.Msbt + "%" + request.Label);
        }

        public bool TalkIsDone() => Dialog.IsFinished;

        public void TalkClose(bool clear)
        {
            Dialog.Close();
            Add(clear ? "talkclose" : "talkclose-noclear");
        }

        public void YesNoBegin(bool defaultYes)
        {
            // Zuordnung 0 = "Ja" ist Annahme [A] (docs/evscript-spezifikation.md); Abbruch (B) wählt "Nein" [A].
            Choice.Open(new[] { "yes", "no" }, defaultYes ? 0 : 1, 1);
        }

        public bool YesNoTryGetResult(out int index)
        {
            index = Choice.Result;
            if (index < 0) return false;
            Choice.Close();
            return true;
        }

        public void CustomWindowBegin(string msbt, IReadOnlyList<string> labels)
        {
            var texts = new List<string>();
            foreach (var l in labels) texts.Add(LabelText(msbt, l));
            Choice.Open(texts, 0, texts.Count - 1);
        }

        public bool CustomWindowTryGetResult(out int index)
        {
            index = Choice.Result;
            if (index < 0) return false;
            Choice.Close();
            return true;
        }

        // ---- Spielwelt ----

        public void StartTrainerBattle(int trainerId1, int trainerId2) => RequestBattle(BattleRequest.Trainer(trainerId1, trainerId2));

        public bool BattleIsDone() => ConsumeBattleDone();

        public void ChangeMap(string zoneName, int locator)
        {
            var id = Session.Data.ResolveZoneName(zoneName);
            Add("map " + zoneName + " " + locator);
            if (id < 0) id = Session.ZoneId;
            Session.BeforeZoneId = Session.ZoneId;
            Session.ZoneId = id;
            Field.ChangeZone(id, locator, true);
        }

        public bool MapChangeIsDone() => Field.ChangeZoneIsDone();

        public void ObjectAnimate(string objectName, int objectIndex, string label, IReadOnlyList<EventCommand> actions, float speed) =>
            Field.AnimateObject(objectName, objectIndex, label, actions, speed);

        public bool ObjectAnimationIsDone(string objectName) => Field.AnimationsDone(objectName);

        // ---- Beutel und Geld ----

        public void AddItem(int itemNo, int count) => Session.AddItem(itemNo, count);

        public bool CanAddItem(int itemNo, int count) => Session.CanAddItem(itemNo, count);

        public void SubItem(int itemNo, int count) => Session.SubItem(itemNo, count);

        public int GetItemCount(int itemNo) => Session.GetItemCount(itemNo);

        public int GetMoney() => Session.Money;

        public void AddMoney(int delta) => Session.AddMoney(delta);

        // Die Abzeichenzahl ist abgeleitet (Systemflags 0x7C..0x83, GameSession.BadgeCount), nichts zu speichern.
        public void SetBadgeCount(int count) { }

        // ---- Hilfen ----

        public int ResolveTrainerId(string name) => Session.Data.ResolveTrainerName(name);

        public int RandomRange(int maxExclusive) => maxExclusive <= 0 ? 0 : (int)Session.Rng.GetValue((ulong)maxExclusive);

        public void EventEnded()
        {
            EventsEnded++;
            Field.SetEventMode(false);
            Dialog.Close();
            Choice.Close();
            Session.Words.Clear();
            Add("end");
        }

        // ---- Hostbefehle ----

        public bool ExecuteCommand(EvCommandCall call)
        {
            if (!HostCommands.Table.TryGetValue(call.Id, out var cmd))
            {
                if (call.First)
                {
                    GapCommandCalls++;
                    Gaps.TryGetValue(call.Id, out var g);
                    Gaps[call.Id] = g + 1;
                }
                return true;
            }
            var done = cmd.Run(this, call);
            if (done)
            {
                HandledIds.TryGetValue(call.Id, out var n);
                HandledIds[call.Id] = n + 1;
            }
            return done;
        }

        // ---- Hilfen für die Handler ----

        internal bool WaitStarter(EvCommandCall call)
        {
            // FIRST_POKE_SELECT_PROC: Demo läuft, bis die Wahl vorliegt (Zustand 0 -> 1 -> 2, Rückgabe 0 bis dahin) [P].
            if (call.First) _starterWaiting = true;
            var idx = Input.StarterChoice;
            var starters = Session.StarterSpecies;
            if (_starterWaiting && idx >= 0 && idx < starters.Length)
            {
                Session.DefaultPokeNo = starters[idx];
                _starterWaiting = false;
                return true;
            }
            return false;
        }

        internal bool TalkOnce(EvCommandCall call)
        {
            // Tafel-/Hinweistext: Fenster öffnen, bis Bestätigung warten, schließen [N].
            if (call.First)
            {
                var s = call.Str(1);
                var pct = s.IndexOf('%');
                var request = new EvTalkRequest { Msbt = pct < 0 ? s : s.Substring(0, pct), Label = pct < 0 ? "" : s.Substring(pct + 1) };
                TalkBegin(request);
                return false;
            }
            if (!Dialog.IsFinished) return false;
            TalkClose(true);
            return true;
        }

        internal bool WaitConfirm(EvCommandCall call) => Input.Confirm || Input.Cancel;

        internal string ItemNameText(int itemNo) => LabelText("ss_itemname", "ITEMNAME_" + itemNo.ToString("000"));

        internal string SpeciesNameText(int monsNo) => LabelText("ss_monsname", "MONSNAME_" + monsNo.ToString("000"));
    }
}
