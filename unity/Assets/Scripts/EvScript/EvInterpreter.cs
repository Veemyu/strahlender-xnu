using System;
using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.EvScript
{
    public enum EvStatus
    {
        Idle,      // kein Ereignis aktiv
        Waiting,   // ein Befehl wartet auf den Host (nächstes Update erneut aufrufen)
        Ended,     // Ereignis beendet
        Error,     // Fehler (LastError), Ereignis abgebrochen
    }

    // Zähler für einen Lauf (Abdeckung: welche Befehle wurden ausgeführt, in welcher Kategorie).
    public sealed class EvRunStats
    {
        public int CommandsExecuted;
        public int CoreCommands;
        public int NoOpCommands;
        public int HostCommands;
        public int MissingLabels;
        public int EmptyCommands;
        public readonly Dictionary<int, int> HostIds = new Dictionary<int, int>();
        public readonly Dictionary<int, int> CoreIds = new Dictionary<int, int>();
        public readonly Dictionary<int, int> NoOpIds = new Dictionary<int, int>();

        public void Clear()
        {
            CommandsExecuted = CoreCommands = NoOpCommands = HostCommands = MissingLabels = EmptyCommands = 0;
            HostIds.Clear();
            CoreIds.Clear();
            NoOpIds.Clear();
        }
    }

    // Zustandsmaschine für Ereignisskripte (Original: EvDataManager.UpdateEvdata/RunEvCmd).
    // Update(dt) führt Befehle aus, bis einer wartet (Rückgabe false des Handlers) oder das Ereignis endet.
    // Nach jedem fertigen Befehl rückt die Position vor, außer der Befehl hat gesprungen/aufgerufen/zurückgekehrt (Original:
    // "Label unverändert -> CommandIndex + 1"). Je Update höchstens MaxStepsPerUpdate Befehle (Original: 5000, MUGEN_LOOP).
    public sealed class EvInterpreter
    {
        struct Frame
        {
            public int File, Script, Cmd;
        }

        // Sprungziel von FLD_ITEM_EVENT: im Original eine String-Konstante (nicht direkt aufgelöst); das einzige passende
        // Label in den Daten ist "ev_fld_item2" (Annahme).
        public const string FldItemLabel = "ev_fld_item2";

        readonly EvScriptBook _book;
        readonly IEvHost _host;
        readonly Stack<Frame> _stack = new Stack<Frame>();
        readonly EvCommandCall _call = new EvCommandCall();
        readonly EvTalkRequest _talk = new EvTalkRequest();

        int _file = -1, _script, _cmd;
        bool _jumped;
        int _stage;              // Zwischenzustand mehrstufiger Befehle (Original: _talkStart/_macroCmd)
        int _sub;                // Aufrufzähler für Host-Abfragen innerhalb einer Stufe
        int _talkSub;
        float _timeWait;
        int _switchWork;         // Original: _switch_work_index
        int _cmpFlag;            // Original: _cmp_flag (0 kleiner, 1 gleich, 2 größer)
        float _dt;
        string _cwMsbt = "";
        readonly List<string> _cwLabels = new List<string>();
        readonly List<int> _cwRet = new List<int>();

        public EvInterpreter(EvScriptBook book, IEvVariables variables, IEvHost host)
        {
            _book = book ?? throw new ArgumentNullException(nameof(book));
            Vars = variables ?? throw new ArgumentNullException(nameof(variables));
            _host = host ?? throw new ArgumentNullException(nameof(host));
            _call.Owner = this;
        }

        public IEvVariables Vars { get; }
        public EvRunStats Stats { get; } = new EvRunStats();
        public int MaxStepsPerUpdate { get; set; } = 5000;
        public bool IsRunning => _file >= 0;
        public string LastError { get; private set; } = "";
        public int LastErrorCommandId { get; private set; }
        public int CurrentFile => _file;
        public int CurrentScript => _script;
        public int CurrentCommandIndex => _cmd;
        public int CallDepth => _stack.Count;

        // Startet ein Ereignis am Label (Original: JumpLabel von außen). false, wenn das Label fehlt.
        public bool Start(string label)
        {
            if (!_book.TryFind(label, out var f, out var s)) return false;
            ResetState();
            _file = f;
            _script = s;
            _cmd = 0;
            LastError = "";
            return true;
        }

        public void Abort()
        {
            if (_file >= 0) FinishEvent(false);
        }

        public EvStatus Update(float deltaTime)
        {
            if (_file < 0) return EvStatus.Idle;
            _dt = deltaTime;
            try
            {
                for (var step = 0; ; step++)
                {
                    if (step >= MaxStepsPerUpdate)
                    {
                        FinishEvent(true);
                        return EvStatus.Ended;
                    }
                    var script = _book.Files[_file].Scripts[_script];
                    if (_cmd >= script.Commands.Count)
                    {
                        FinishEvent(true);
                        return EvStatus.Ended;
                    }
                    var cmd = script.Commands[_cmd];
                    if (cmd.Args.Count == 0)
                    {
                        Stats.EmptyCommands++;
                        _cmd++;
                        continue;
                    }
                    var id = cmd.Args[0].Data;
                    _jumped = false;
                    if (!Execute(id, cmd))
                        return EvStatus.Waiting;
                    ResetCommandState();
                    if (_file < 0) return EvStatus.Ended;
                    if (!_jumped) _cmd++;
                }
            }
            catch (EvScriptException ex)
            {
                LastError = ex.Message;
                LastErrorCommandId = CurrentCommandId();
                FinishEvent(false);
                return EvStatus.Error;
            }
            catch (ArgumentOutOfRangeException ex)
            {
                LastError = "Argument fehlt oder ungültig: " + ex.Message;
                LastErrorCommandId = CurrentCommandId();
                FinishEvent(false);
                return EvStatus.Error;
            }
        }

        // Kennung des Befehls an der aktuellen Position (0, wenn kein Ereignis läuft).
        public int CurrentCommandId()
        {
            if (_file < 0) return 0;
            var s = _book.Files[_file].Scripts[_script];
            if (_cmd < 0 || _cmd >= s.Commands.Count || s.Commands[_cmd].Args.Count == 0) return 0;
            return s.Commands[_cmd].Args[0].Data;
        }

        void ResetState()
        {
            _stack.Clear();
            ResetCommandState();
            _switchWork = 0;
            _cmpFlag = 0;
            _cwMsbt = "";
            _cwLabels.Clear();
            _cwRet.Clear();
        }

        // Original: VariableReset nach jedem fertigen Befehl.
        void ResetCommandState()
        {
            _stage = 0;
            _sub = 0;
            _talkSub = 0;
            _timeWait = 0f;
        }

        void FinishEvent(bool notify)
        {
            _file = -1;
            _stack.Clear();
            ResetCommandState();
            if (notify) _host.EventEnded();
        }

        // ---- Argumente ----

        internal int ArgValue(IReadOnlyList<EventArgument> a, int i)
        {
            Need(a, i);
            var t = a[i].Type;
            if (t == (int)EventArgType.Work) return Vars.GetWork(a[i].Data);
            if (t == (int)EventArgType.Float) return (int)a[i].AsFloat();
            return 0;
        }

        internal string ArgString(IReadOnlyList<EventArgument> a, int i)
        {
            Need(a, i);
            if (a[i].Type != (int)EventArgType.String) return "";
            var strings = _book.Files[_file].Strings;
            var idx = a[i].Data;
            if ((uint)idx >= (uint)strings.Count) throw new EvScriptException("Stringindex außerhalb der Stringtabelle: " + idx);
            return strings[idx] ?? "";
        }

        static void Need(IReadOnlyList<EventArgument> a, int i)
        {
            if (i >= a.Count) throw new EvScriptException("Argument " + i + " fehlt");
        }

        // ---- Sprünge ----

        bool JumpLabel(string label)
        {
            if (!_book.TryFind(label, out var f, out var s))
            {
                if (!string.IsNullOrEmpty(label)) Stats.MissingLabels++;
                return false;
            }
            _file = f;
            _script = s;
            _cmd = 0;
            _jumped = true;
            return true;
        }

        bool CallLabel(string label)
        {
            if (!_book.TryFind(label, out _, out _))
            {
                if (!string.IsNullOrEmpty(label)) Stats.MissingLabels++;
                return false;
            }
            _stack.Push(new Frame { File = _file, Script = _script, Cmd = _cmd + 1 });
            return JumpLabel(label);
        }

        bool ReturnFromCall()
        {
            if (_stack.Count == 0) return false;
            var fr = _stack.Pop();
            _file = fr.File;
            _script = fr.Script;
            _cmd = fr.Cmd;
            _jumped = true;
            return true;
        }

        // Original: EvCmdEnd/EvCmdNop setzen die Ereignisliste auf -1; das Ereignis endet nach diesem Befehl.
        void EndEvent()
        {
            FinishEvent(true);
        }

        void IfJumpCall(bool jump, string cmpType, string label)
        {
            if (!CompareFlag(Normalize(cmpType))) return;
            if (jump) JumpLabel(label); else CallLabel(label);
        }

        // Original: IfJump_Call prüft _cmp_flag (0 kleiner, 1 gleich, 2 größer) gegen die normalisierte Vergleichsart.
        bool CompareFlag(string t)
        {
            switch (t)
            {
                case "EQ": return _cmpFlag == 1;
                case "NE": return _cmpFlag != 1;
                case "GT": return _cmpFlag == 2;
                case "GE": return (uint)(_cmpFlag - 1) <= 1u;
                case "LT": return _cmpFlag == 0;
                case "LE": return (uint)_cmpFlag <= 1u;
                default: return false;
            }
        }

        // Annahme: Aliase der ReEQType-Tabelle (in den Daten kommen nur EQ, NE, GT, GE, LT, LE vor).
        static string Normalize(string t)
        {
            switch (t)
            {
                case "EQ": case "==": case "ON": return "EQ";
                case "NE": case "!=": return "NE";
                case "GT": case ">": return "GT";
                case "GE": case ">=": return "GE";
                case "LT": case "<": case "OFF": return "LT";
                case "LE": case "<=": return "LE";
                default: return t ?? "";
            }
        }

        // Original: CommandEquals(Vergleichsart, a, b).
        static bool Compare(string type, int a, int b)
        {
            switch (Normalize(type))
            {
                case "EQ": return a == b;
                case "NE": return a != b;
                case "GT": return b < a;
                case "GE": return b <= a;
                case "LT": return a < b;
                case "LE": return a <= b;
                default: return false;
            }
        }

        // Flag-Argument: Typ 3 = Flag, Typ 4 = Systemflag; andere Typen: Befehl ohne Wirkung (null).
        // Original: Index < 0 oder 4000 zählt bei Flags als nicht gesetzt.
        bool? ReadFlagArg(IReadOnlyList<EventArgument> a, int i)
        {
            Need(a, i);
            var idx = a[i].Data;
            if (a[i].Type == (int)EventArgType.SysFlag) return Vars.GetSysFlag(idx);
            if (a[i].Type != (int)EventArgType.Flag) return null;
            if (idx < 0 || idx == EvMemoryVariables.FlagCount) return false;
            return Vars.GetFlag(idx);
        }

        int TrainerArg(IReadOnlyList<EventArgument> a, int i)
        {
            Need(a, i);
            var t = a[i].Type;
            if (t == (int)EventArgType.Float) return (int)a[i].AsFloat();
            if (t == (int)EventArgType.Work) return Vars.GetWork(a[i].Data);
            if (t == (int)EventArgType.String)
            {
                var id = _host.ResolveTrainerId(ArgString(a, i));
                return id < 0 ? 0 : id;
            }
            return 0;
        }

        // ---- Befehle ----

        bool Execute(int id, EventCommand cmd)
        {
            var a = cmd.Args;
            var kind = EvCommandTable.Classify(id);
            switch (kind)
            {
                case EvCmdKind.NoOp:
                    Count(Stats.NoOpIds, id);
                    Stats.NoOpCommands++;
                    Stats.CommandsExecuted++;
                    return true;
                case EvCmdKind.Host:
                    return ExecuteHost(id, a, Stats.HostIds, ref Stats.HostCommands);
            }
            var done = ExecuteCore(id, a);
            if (done)
            {
                Count(Stats.CoreIds, id);
                Stats.CoreCommands++;
                Stats.CommandsExecuted++;
            }
            return done;
        }

        static void Count(Dictionary<int, int> d, int id)
        {
            d.TryGetValue(id, out var n);
            d[id] = n + 1;
        }

        bool ExecuteHost(int id, IReadOnlyList<EventArgument> a, Dictionary<int, int> ids, ref int total)
        {
            _call.Id = id;
            _call.Args = a;
            _call.Phase = _sub;
            if (!_host.ExecuteCommand(_call))
            {
                _sub++;
                return false;
            }
            Count(ids, id);
            total++;
            Stats.CommandsExecuted++;
            return true;
        }

        // Einzelner Host-Schritt für zusammengesetzte Befehle (EASY_OBJ_MSG): synthetische Kennung, gleiche Argumente.
        bool HostStep(int id, IReadOnlyList<EventArgument> a)
        {
            _call.Id = id;
            _call.Args = a;
            _call.Phase = _sub;
            if (!_host.ExecuteCommand(_call))
            {
                _sub++;
                return false;
            }
            _sub = 0;
            return true;
        }

        bool ExecuteCore(int id, IReadOnlyList<EventArgument> a)
        {
            switch (id)
            {
                case EvCmdId.Nop:
                case EvCmdId.End:
                case EvCmdId.SpEventDataEnd:
                case EvCmdId.SceneChangeEnd:
                    EndEvent();
                    return true;

                case EvCmdId.TimeWait:
                {
                    if (a.Count < 3) throw new EvScriptException("TIME_WAIT braucht zwei Argumente");
                    // Wartezeit in Frames (30 je Sekunde); Float-Argumente sind Bitmuster eines float.
                    var frames = a[1].Type == 2 ? (float)Vars.GetWork(a[1].Data) : a[1].Type == 1 ? a[1].AsFloat() : 0f;
                    if (_timeWait <= frames * 0.033333335f)
                    {
                        Vars.SetWork(a[2].Data, 1);
                        _timeWait += _dt;
                        return false;
                    }
                    Vars.SetWork(a[2].Data, 0);
                    return true;
                }

                case EvCmdId.Jump:
                    JumpLabel(ArgString(a, 1));
                    return true;
                case EvCmdId.Call:
                case EvCmdId.ChgCommonScr:
                    CallLabel(ArgString(a, 1));
                    return true;
                case EvCmdId.Ret:
                case EvCmdId.ChgLocalScr:
                    // RET bei leerem Stapel beendet das Ereignis (Handler fällt auf den END-Pfad zurück).
                    if (!ReturnFromCall()) EndEvent();
                    return true;
                case EvCmdId.SceneChangeLabel:
                case EvCmdId.FlagChangeLabel:
                case EvCmdId.ObjChangeLabel:
                case EvCmdId.InitChangeLabel:
                    JumpLabel(ArgString(a, 1));
                    return true;

                case EvCmdId.IfJump:
                    IfJumpCall(true, ArgString(a, 1), ArgString(a, 2));
                    return true;
                case EvCmdId.IfCall:
                    IfJumpCall(false, ArgString(a, 1), ArgString(a, 2));
                    return true;

                case EvCmdId.IfValJump:
                case EvCmdId.IfWkJump:
                case EvCmdId.IfValCall:
                case EvCmdId.IfWkCall:
                {
                    var v1 = ArgValue(a, 1);
                    var type = ArgString(a, 2);
                    var v2 = ArgValue(a, 3);
                    var label = ArgString(a, 4);
                    if (Compare(type, v1, v2))
                    {
                        if (id == EvCmdId.IfValJump || id == EvCmdId.IfWkJump) JumpLabel(label); else CallLabel(label);
                    }
                    return true;
                }

                case EvCmdId.Switch:
                    Need(a, 1);
                    _switchWork = a[1].Data;
                    return true;
                case EvCmdId.CaseJump:
                {
                    var cur = Vars.GetWork(_switchWork);
                    var want = ArgValue(a, 1);
                    var label = ArgString(a, 2);
                    if (cur == want) JumpLabel(label);
                    return true;
                }

                case EvCmdId.FlagSet:
                    Need(a, 1);
                    if (a[1].Data >= 0 && a[1].Data < EvMemoryVariables.FlagCount) Vars.SetFlag(a[1].Data, true);
                    return true;
                case EvCmdId.FlagReset:
                    Need(a, 1);
                    if (a[1].Data >= 0 && a[1].Data < EvMemoryVariables.FlagCount) Vars.SetFlag(a[1].Data, false);
                    return true;
                case EvCmdId.FlagSetWk:
                {
                    var idx = ArgValue(a, 1);
                    if (idx >= 0 && idx < EvMemoryVariables.FlagCount) Vars.SetFlag(idx, true);
                    return true;
                }
                case EvCmdId.ArriveFlagSet:
                case EvCmdId.SetSysFlag:
                    Need(a, 1);
                    Vars.SetSysFlag(a[1].Data, true);
                    SyncBadges();
                    return true;
                case EvCmdId.ResetSysFlag:
                    Need(a, 1);
                    Vars.SetSysFlag(a[1].Data, false);
                    SyncBadges();
                    return true;

                case EvCmdId.IfFlagOnJump:
                case EvCmdId.IfFlagOnCall:
                case EvCmdId.IfFlagOffJump:
                case EvCmdId.IfFlagOffCall:
                {
                    Need(a, 2);
                    var label = ArgString(a, 2);
                    var v = ReadFlagArg(a, 1);
                    if (v == null) return true;
                    var wantOn = id == EvCmdId.IfFlagOnJump || id == EvCmdId.IfFlagOnCall;
                    if (v.Value == wantOn)
                    {
                        if (id == EvCmdId.IfFlagOnJump || id == EvCmdId.IfFlagOffJump) JumpLabel(label); else CallLabel(label);
                    }
                    return true;
                }

                case EvCmdId.TrainerFlagSet:
                {
                    var t = TrainerArg(a, 1);
                    Vars.SetTrainerWin(t, true);
                    Vars.SetTrainerSearcher(t, false);
                    return true;
                }
                case EvCmdId.TrainerFlagReset:
                {
                    var t = TrainerArg(a, 1);
                    Vars.SetTrainerWin(t, false);
                    Vars.SetTrainerSearcher(t, false);
                    return true;
                }
                case EvCmdId.TrainerFlagCheck:
                {
                    var t = TrainerArg(a, 1);
                    _cmpFlag = t != 0 && Vars.GetTrainerWin(t) && !Vars.GetTrainerSearcher(t) ? 1 : 0;
                    return true;
                }
                case EvCmdId.IfTrFlagOnJump:
                case EvCmdId.IfTrFlagOnCall:
                case EvCmdId.IfTrFlagOffJump:
                case EvCmdId.IfTrFlagOffCall:
                {
                    var t = TrainerArg(a, 1);
                    var win = t != 0 && Vars.GetTrainerWin(t);
                    _cmpFlag = win ? 1 : 0;
                    var on = id == EvCmdId.IfTrFlagOnJump || id == EvCmdId.IfTrFlagOnCall;
                    var jump = id == EvCmdId.IfTrFlagOnJump || id == EvCmdId.IfTrFlagOffJump;
                    IfJumpCall(jump, on ? "EQ" : "LT", ArgString(a, 2));
                    return true;
                }

                case EvCmdId.CaseCancel:
                {
                    // CASE_CANCEL: vergleicht Work 0xF2 mit Work 0xF8 (Abbruchwert) und springt bei Gleichheit [P; Vergleichsart "EQ" ist Annahme]
                    var x = Vars.GetWork(EvCmdId.WorkItemEventA);
                    var y = Vars.GetWork(EvCmdId.WorkCaseCancel);
                    _cmpFlag = x < y ? 0 : x == y ? 1 : 2;
                    IfJumpCall(true, "EQ", ArgString(a, 1));
                    return true;
                }
                case EvCmdId.CmpWk:
                {
                    // CMPWK: beide Argumente werden als Arbeitswert-Index genommen, danach noch einmal nachgeschlagen [P]
                    Need(a, 2);
                    var x = Vars.GetWork(ArgValue(a, 1));
                    var y = Vars.GetWork(ArgValue(a, 2));
                    _cmpFlag = x < y ? 0 : x == y ? 1 : 2;
                    return true;
                }
                case EvCmdId.LdVal:
                case EvCmdId.LdWk:
                case EvCmdId.LdWkVal:
                    Need(a, 2);
                    Vars.SetWork(a[1].Data, ArgValue(a, 2));
                    return true;
                case EvCmdId.AddWk:
                {
                    var x = ArgValue(a, 1);
                    var y = ArgValue(a, 2);
                    Vars.SetWork(a[1].Data, x + y);
                    return true;
                }
                case EvCmdId.SubWk:
                {
                    var x = ArgValue(a, 1);
                    var y = ArgValue(a, 2);
                    Vars.SetWork(a[1].Data, x - y);
                    return true;
                }

                case EvCmdId.TalkMsg:
                case EvCmdId.TalkKeyWait:
                    return RunTalk(a);
                case EvCmdId.TalkClose:
                case EvCmdId.TalkCloseNoClear:
                    Vars.SetWork(EvCmdId.WorkTalkWindow, 0);
                    _host.TalkClose(id == EvCmdId.TalkClose);
                    return true;
                case EvCmdId.EasyMsg:
                    return RunEasyMsg(a, false);
                case EvCmdId.EasyObjMsg:
                    return RunEasyMsg(a, true);

                case EvCmdId.YesNoWin:
                    return RunYesNo(a);
                case EvCmdId.AddCustumWinLabel:
                    AddCustomWindowLabel(a);
                    return true;
                case EvCmdId.OpenCustumWin:
                    return RunCustomWindow(a);

                case EvCmdId.ObjAnime:
                    RunObjAnime(a);
                    return true;
                case EvCmdId.ObjAnimeWait:
                    return _host.ObjectAnimationIsDone(a.Count > 1 ? ArgString(a, 1) : "");

                case EvCmdId.SceneChangeData:
                {
                    var v1 = ArgValue(a, 1);
                    var v2 = ArgValue(a, 2);
                    var label = ArgString(a, 3);
                    if (v1 == v2) CallLabel(label);
                    return true;
                }

                case EvCmdId.AddGold:
                    _host.AddMoney(ArgValue(a, 1));
                    return true;
                case EvCmdId.SubGold:
                    _host.AddMoney(-ArgValue(a, 1));
                    return true;
                case EvCmdId.CompGold:
                {
                    Need(a, 2);
                    var amount = ArgValue(a, 2);
                    Vars.SetWork(a[1].Data, amount <= _host.GetMoney() ? 1 : 0);
                    return true;
                }
                case EvCmdId.GetGold:
                    Need(a, 1);
                    Vars.SetWork(a[1].Data, _host.GetMoney());
                    return true;

                case EvCmdId.AddItem:
                {
                    var item = ArgValue(a, 1);
                    var count = ArgValue(a, 2);
                    _host.AddItem(item, count);
                    if (a.Count > 3) Vars.SetWork(a[3].Data, 1);
                    return true;
                }
                case EvCmdId.SubItem:
                {
                    var item = ArgValue(a, 1);
                    var count = ArgValue(a, 2);
                    _host.SubItem(item, count);
                    if (a.Count > 3) Vars.SetWork(a[3].Data, 1);
                    return true;
                }
                case EvCmdId.AddItemChk:
                {
                    var item = ArgValue(a, 1);
                    var count = ArgValue(a, 2);
                    var ok = _host.CanAddItem(item, count);
                    if (a.Count > 3) Vars.SetWork(a[3].Data, ok ? 1 : 0);
                    return true;
                }
                case EvCmdId.ItemChk:
                {
                    var item = ArgValue(a, 1) & 0xFFFF;
                    var have = _host.GetItemCount(item);
                    var need = ArgValue(a, 2);
                    Need(a, 3);
                    Vars.SetWork(a[3].Data, need <= have ? 1 : 0);
                    return true;
                }
                case EvCmdId.FldItemEvent:
                {
                    var p1 = ArgValue(a, 1);
                    var p2 = ArgValue(a, 2);
                    Vars.SetWork(EvCmdId.WorkItemEventA, p1);
                    Vars.SetWork(EvCmdId.WorkItemEventB, p2);
                    JumpLabel(FldItemLabel);
                    return true;
                }

                case EvCmdId.GetRnd:
                case EvCmdId.GetRndNext:
                {
                    Need(a, 2);
                    var max = ArgValue(a, 2);
                    Vars.SetWork(a[1].Data, _host.RandomRange(max));
                    return true;
                }

                case EvCmdId.MapChange:
                case EvCmdId.MapChangeNoneFade:
                    if (_stage == 0)
                    {
                        _host.ChangeMap(ArgString(a, 1), ArgValue(a, 2));
                        _stage = 1;
                        return false;
                    }
                    return _host.MapChangeIsDone();

                case EvCmdId.TrainerBtlSet:
                    if (_stage == 0)
                    {
                        var t1 = TrainerArg(a, 1);
                        var t2 = a.Count > 2 ? TrainerArg(a, 2) : 0;
                        _host.StartTrainerBattle(t1, t2);
                        _stage = 1;
                        return false;
                    }
                    return _host.BattleIsDone();
            }
            throw new EvScriptException("Kernbefehl ohne Implementierung: " + id);
        }

        void SyncBadges()
        {
            // SetSysFlag im Original: Abzeichenzahl = Summe der Systemflags 0x7C..0x83.
            var n = 0;
            for (var i = 0x7C; i <= 0x83; i++) if (Vars.GetSysFlag(i)) n++;
            _host.SetBadgeCount(n);
        }

        bool RunTalk(IReadOnlyList<EventArgument> a)
        {
            if (_stage == 0)
            {
                var s = ArgString(a, 1);
                var pct = s.IndexOf('%');
                _talk.Msbt = pct < 0 ? s : s.Substring(0, pct);
                _talk.Label = pct < 0 ? "" : s.Substring(pct + 1);
                _talk.Value = 0;
                _talk.Flag = a.Count > 2 && ArgValue(a, 2) == 1;
                _host.TalkBegin(_talk);
                _stage = 1;
                return false;
            }
            if (!_host.TalkIsDone()) return false;
            _stage = 0;
            return true;
        }

        // EASY_MSG: TALKMSG, Text schließen. EASY_OBJ_MSG: davor TALK_OBJ_START, danach TALK_OBJ_END. Jede Stufe kostet einen Frame.
        bool RunEasyMsg(IReadOnlyList<EventArgument> a, bool withObject)
        {
            // Stufen: 0 TALK_OBJ_START (nur mit Objekt), 1 Text, 2 schließen, 3 TALK_OBJ_END (nur mit Objekt)
            if (_stage == 0 && !withObject) _stage = 1;
            switch (_stage)
            {
                case 0:
                    if (HostStep(EvCmdId.TalkObjStart, a)) _stage = 1;
                    return false;
                case 1:
                    if (RunTalkStage(a)) _stage = 2;
                    return false;
                case 2:
                    Vars.SetWork(EvCmdId.WorkTalkWindow, 0);
                    _host.TalkClose(true);
                    if (!withObject) return true;
                    _stage = 3;
                    return false;
                default:
                    if (HostStep(EvCmdId.TalkObjEnd, a)) return true;
                    return false;
            }
        }

        bool RunTalkStage(IReadOnlyList<EventArgument> a)
        {
            if (_talkSub == 0)
            {
                var s = ArgString(a, 1);
                var pct = s.IndexOf('%');
                _talk.Msbt = pct < 0 ? s : s.Substring(0, pct);
                _talk.Label = pct < 0 ? "" : s.Substring(pct + 1);
                _talk.Value = 0;
                _talk.Flag = false;
                _host.TalkBegin(_talk);
                _talkSub = 1;
                return false;
            }
            if (!_host.TalkIsDone()) return false;
            _talkSub = 0;
            return true;
        }

        bool RunYesNo(IReadOnlyList<EventArgument> a)
        {
            Need(a, 1);
            if (_stage == 0)
            {
                var defaultYes = a.Count < 3 || ArgValue(a, 2) == 1;
                _host.YesNoBegin(defaultYes);
                _stage = 1;
                return false;
            }
            if (!_host.YesNoTryGetResult(out var index)) return false;
            Vars.SetWork(a[1].Data, index);
            return true;
        }

        void AddCustomWindowLabel(IReadOnlyList<EventArgument> a)
        {
            var s = ArgString(a, 1);
            var parts = s.Split('%');
            if (string.IsNullOrEmpty(_cwMsbt))
            {
                if (parts.Length == 0) throw new EvScriptException("Leere Auswahlzeile");
                _cwMsbt = parts[0];
            }
            if (parts.Length < 2) throw new EvScriptException("Auswahlzeile ohne Label");
            _cwLabels.Add(parts[1]);
            _cwRet.Add(a.Count < 3 ? _cwLabels.Count - 1 : ArgValue(a, 2));
        }

        bool RunCustomWindow(IReadOnlyList<EventArgument> a)
        {
            Need(a, 1);
            if (_stage == 0)
            {
                _host.CustomWindowBegin(_cwMsbt, _cwLabels);
                _stage = 1;
                return false;
            }
            if (!_host.CustomWindowTryGetResult(out var index)) return false;
            if ((uint)index >= (uint)_cwRet.Count) throw new EvScriptException("Auswahlindex außerhalb der Liste: " + index);
            Vars.SetWork(a[1].Data, _cwRet[index]);
            _cwMsbt = "";
            _cwLabels.Clear();
            _cwRet.Clear();
            return true;
        }

        void RunObjAnime(IReadOnlyList<EventArgument> a)
        {
            Need(a, 2);
            var label = ArgString(a, 2);
            string name = null;
            var index = -1;
            if (a[1].Type == (int)EventArgType.String) name = ArgString(a, 1);
            else index = ArgValue(a, 1);
            var speed = 0f;
            if (a.Count > 3)
            {
                if (a[3].Type == (int)EventArgType.Work) speed = Vars.GetWork(a[3].Data);
                else if (a[3].Type == (int)EventArgType.Float) speed = a[3].AsFloat();
            }
            var script = _book.FindInFile(_file, label);
            if (script == null)
            {
                Stats.MissingLabels++;
                return;
            }
            _host.ObjectAnimate(name, index, label, script.Commands, speed);
        }
    }
}
