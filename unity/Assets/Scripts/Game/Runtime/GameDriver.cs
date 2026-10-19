using System;
using System.Collections.Generic;
using System.IO;
using TMPro;
using UnityEngine;
using Xnu.Battle.Flow;
using Xnu.Core;
using Xnu.Data;
using Xnu.Field;
using Xnu.Input;
using Xnu.Probe;
using Xnu.Text;
using Xnu.UI;
using GameFrame = Xnu.Game.GameInput;
using PadInput = Xnu.Input.GameInput;

namespace Xnu.Game.Unity
{
    // Treiber des vertikalen Durchstichs: Titel → Weiter → Spielstand laden → Feld (FieldController) mit Spielschleife (GameLoop, 30 Hz)
    // → Ereignisse (Textbox aus Xnu.UI) → Wild-/Trainerkampf (BattleView) → Speichern (SaveSlotService).
    // Eingabe: echte Geräte (GameInput) oder ein Eingabeskript (InputScript) – dann ohne Fokus und ohne Maus. Kein Ton.
    [DisallowMultipleComponent]
    public sealed class GameDriver : MonoBehaviour, IScriptWorld
    {
        public const float LogicStep = 1f / 30f;
        public enum Phase { Title, Loading, Playing, Error }

        [SerializeField] bool autoContinue;
        [SerializeField] string scriptPath = "";

        public Phase CurrentPhase { get; private set; } = Phase.Title;
        public GameOptions Options { get; private set; }
        public GameBundle Bundle { get; private set; }
        public GameSession Session { get; private set; }
        public GameLoop Loop { get; private set; }
        public FieldController Field { get; private set; }
        public FieldHostAdapter Adapter { get; private set; }
        public SaveSlotService Saves { get; private set; }
        public TextboxView Textbox { get; private set; }
        public UiWindowManager Windows { get; private set; }
        public BattleView Battle { get; private set; }
        public InputScriptRunner Runner { get; private set; }
        public string ErrorText { get; private set; } = "";
        public string StatusNote { get; private set; } = "";
        public int Ticks { get; private set; }
        public int ScriptTicks => Runner?.Ticks ?? 0;
        public int ShotsTaken { get; private set; }
        public int WildEncounters { get; private set; }
        public int SavesWritten => Saves?.Writes ?? 0;
        public readonly List<string> Report = new List<string>();

        Camera _camera;
        Canvas _titleCanvas;
        TextMeshProUGUI _titleText;
        GameObject _titleRoot;
        int _titleCursor;
        readonly ManualUiInput _manual = new ManualUiInput();
        readonly GameInputUiSource _realUi = new GameInputUiSource();
        InputOverride _override;
        float _accumulator;
        bool _latchConfirm, _latchCancel, _latchMenu, _latchHeld;
        int _latchMove, _latchMoveX;
        GameUiData _uiData;
        FieldSignal? _pendingStep;
        int _dialogToken = -1;
        bool _choiceShown;
        bool _menuAsked;
        bool _menuCancel;
        bool _quit;
        int _tickBudgetLog;
        string _lastLoopState = "";

        // Zeit in Sekunden je Zustand der Spielschleife (Messung).
        public readonly Dictionary<string, int> StateTicks = new Dictionary<string, int>();

        public void Configure(GameOptions options, string script)
        {
            Options = options;
            scriptPath = script ?? "";
        }

        void Awake()
        {
            AudioListener.pause = true;
            AudioListener.volume = 0f;
        }

        void Start()
        {
            Options = Options ?? GameOptions.Parse(Environment.GetCommandLineArgs(), Environment.GetEnvironmentVariable);
            if (Options.TargetFps > 0) Application.targetFrameRate = Options.TargetFps;
            Application.logMessageReceived += OnLogMessage;
            Application.lowMemory += OnLowMemory;
            Log("Start: Bildziel " + Application.targetFrameRate + " (vSync " + QualitySettings.vSyncCount + "), Anzeige " + Screen.currentResolution + ", Eingabe-Optionen: Skript " + (string.IsNullOrEmpty(Options.ScriptPath) ? "-" : Options.ScriptPath));
            if (string.IsNullOrEmpty(scriptPath)) scriptPath = Options.ScriptPath;
            if (Options.AutoContinue) autoContinue = true;
            _camera = Camera.main;
            if (_camera == null) _camera = FindFirstObjectByType<Camera>();
            if (PadInput.Instance == null) new GameObject("GameInput").AddComponent<PadInput>();
            _override = new InputOverride();

            var root = SaveSlotService.ResolveRoot(Options.SaveRoot, Application.persistentDataPath);
            Saves = new SaveSlotService(root, ResolveSaveSource(Options.SaveSource), SaveSlotService.DropInSources(Application.persistentDataPath));

            var tb = new GameObject("Textbox");
            tb.transform.SetParent(transform, false);
            Textbox = tb.AddComponent<TextboxView>();
            Textbox.Configure(_camera, 1, false, MessageSpeed.Normal);
            Textbox.InputSource = new MergedUiInput(_realUi, _manual);
            Textbox.EnsureBuilt();
            // Awake hat die Textbox schon ohne Kamera gebaut (Overlay); an die Spielkamera binden, damit Letterbox und Bildaufnahmen stimmen.
            if (_camera != null && Textbox.Canvas != null)
            {
                Textbox.Canvas.renderMode = RenderMode.ScreenSpaceCamera;
                Textbox.Canvas.worldCamera = _camera;
                Textbox.Canvas.planeDistance = 1f;
            }

            var bv = new GameObject("Battle");
            bv.transform.SetParent(transform, false);
            Battle = bv.AddComponent<BattleView>();
            Battle.Build(_camera);

            var wm = new GameObject("Windows");
            wm.transform.SetParent(transform, false);
            Windows = wm.AddComponent<UiWindowManager>();
            Windows.Configure(_camera, null);
            Windows.SaveHandler = SaveForMenu;

            BuildTitle();

            if (!string.IsNullOrEmpty(scriptPath) && !File.Exists(scriptPath))
            {
                // Relativer Pfad (iPad: Datei per devicectl nach Documents kopiert): relativ zum Ablageordner der App auflösen.
                var alt = Path.Combine(Application.persistentDataPath, scriptPath);
                if (File.Exists(alt)) scriptPath = alt;
            }
            if (!string.IsNullOrEmpty(scriptPath))
            {
                try
                {
                    Runner = new InputScriptRunner(InputScript.Parse(File.ReadAllText(scriptPath)));
                    PadInput.Instance.Override = _override;
                    Log("Eingabeskript " + Path.GetFileName(scriptPath) + " (" + Runner.Current + ")");
                }
                catch (Exception e) { Log("Eingabeskript nicht lesbar: " + e.Message); }
            }
            Log("Start; Daten " + GameDataPaths.Root + "; Slot " + (Saves.HasSlot ? "vorhanden" : "keiner") + "; Quelle " + (Saves.CanContinue && !Saves.HasSlot ? "gültig" : "-") + "; Weiter " + (Saves.CanContinue ? "möglich" : "nicht möglich"));
            foreach (var line in Saves.Diagnose()) Log("Spielstand: " + line);
            if (!Saves.CanContinue) { StatusNote = "Kein gültiger Spielstand: " + Saves.Problem; RefreshTitle(); }
        }

        static string ResolveSaveSource(string explicitPath)
        {
            if (!string.IsNullOrEmpty(explicitPath)) return explicitPath;
            var guess = Path.GetFullPath(Path.Combine(GameDataPaths.Root, "..", "Ryujinx", "bis", "user", "save", "0000000000000006", "0"));
            return Directory.Exists(guess) ? guess : "";
        }

        public static void Log(string s) => Debug.Log("[Game] " + s);

        // ---- Titel ----

        void BuildTitle()
        {
            _titleCanvas = UiCanvasFactory.Create("TitleCanvas", _camera, 800, transform);
            _titleRoot = _titleCanvas.gameObject;
            UiKit.Panel(_titleCanvas.transform, "Back", Vector2.zero, Vector2.one, Vector2.zero, Vector2.zero, new Color(0.08f, 0.1f, 0.18f, 1f));
            UiKit.Label(_titleCanvas.transform, "Title", new Vector2(0f, 0.62f), new Vector2(1f, 0.9f), Vector2.zero, Vector2.zero, 96f, Color.white, TextAlignmentOptions.Center).text = "Xnu";
            UiKit.Label(_titleCanvas.transform, "Sub", new Vector2(0f, 0.52f), new Vector2(1f, 0.62f), Vector2.zero, Vector2.zero, 30f, new Color(0.7f, 0.75f, 0.85f), TextAlignmentOptions.Center).text = "Vertikaler Durchstich – Prototyp";
            _titleText = UiKit.Label(_titleCanvas.transform, "Menu", new Vector2(0.35f, 0.15f), new Vector2(0.65f, 0.5f), Vector2.zero, Vector2.zero, 44f, Color.white, TextAlignmentOptions.TopLeft);
            _titleText.lineSpacing = 10f;
            RefreshTitle();
        }

        string[] TitleRows() => new[] { Saves.CanContinue ? "Weiter" : "Weiter (kein Spielstand)", "Neues Spiel (noch nicht verfügbar)" };

        void RefreshTitle()
        {
            var rows = TitleRows();
            var sb = new System.Text.StringBuilder();
            for (var i = 0; i < rows.Length; i++) sb.Append(i == _titleCursor ? "> " : "   ").Append(rows[i]).Append('\n');
            sb.Append("\n<size=24><color=#99a>").Append(StatusNote).Append("</color></size>");
            _titleText.richText = true;
            _titleText.text = sb.ToString();
        }

        void TickTitle(UiInputState ui)
        {
            if (ui.MoveY != 0) { _titleCursor = (_titleCursor + (ui.MoveY > 0 ? 1 : 1)) % 2; RefreshTitle(); }
            if (autoContinue && Saves.CanContinue) { autoContinue = false; CurrentPhase = Phase.Loading; StatusNote = "Lade …"; RefreshTitle(); return; }
            if (!ui.ConfirmPressed) return;
            Saves.Refresh();
            if (_titleCursor == 0 && Saves.CanContinue) { CurrentPhase = Phase.Loading; StatusNote = "Lade Stammdaten und Spielstand …"; RefreshTitle(); }
            else { StatusNote = _titleCursor == 0 ? "Kein gültiger Spielstand: " + Saves.Problem : "Nicht verfügbar."; if (_titleCursor == 0) foreach (var line in Saves.Diagnose()) Log("Spielstand: " + line); RefreshTitle(); }
        }

        // ---- Laden ----

        void LoadGame()
        {
            try
            {
                var sw = System.Diagnostics.Stopwatch.StartNew();
                Bundle = GameDataLoader.Load(FieldDataSet.DefaultDirectory);
                Log(Bundle.ToString());
                var save = Saves.Load();
                Log(Saves.Note);
                Session = new GameSession(save, Bundle.Data, (ulong)DateTime.UtcNow.Ticks);
                _uiData = new GameUiData(Session);
                Windows.Configure(_camera, _uiData);
                var pos = SavedPosition.Read(save);
                Session.ZoneId = pos.Zone;
                Log("Spielstand: Zone " + pos.Zone + (pos.Valid ? ", Zelle (" + pos.GridX + ", " + pos.GridY + "), Richtung " + pos.Direction : ", keine gültige Position") +
                    ", Team " + Session.PartyCount + ", Geld " + Session.Money + ", Abzeichen " + Session.BadgeCount);

                var go = new GameObject("Field");
                go.SetActive(false);
                Field = go.AddComponent<FieldController>();
                Field.zoneId = pos.Zone;
                Field.cameraOverride = _camera;
                Field.streaming = true;
                Field.usePlayerModel = true;
                Field.showNpcs = true;
                Field.ExternalTick = true;
                if (pos.Valid) Field.SetStartCell(pos.GridX, pos.GridY, SavedPosition.ToFacing(pos.Direction));
                Adapter = new FieldHostAdapter(Field, Session);
                Loop = new GameLoop(Session, Bundle.Book, Adapter);
                Adapter.LoopBusy = () => Loop.State != GameState.Field || Battle.Active || Textbox.IsOpen || Textbox.IsChoosing || Windows.IsOpen;
                go.SetActive(true);
                _titleRoot.SetActive(false);
                CurrentPhase = Phase.Playing;
                Log("Feld gestartet nach " + sw.Elapsed.TotalSeconds.ToString("F1") + " s");
            }
            catch (Exception e)
            {
                ErrorText = e.GetType().Name + ": " + e.Message;
                CurrentPhase = Phase.Error;
                StatusNote = "Fehler: " + ErrorText;
                _titleRoot.SetActive(true);
                RefreshTitle();
                Debug.LogError("[Game] " + e);
            }
        }

        // ---- Schleife ----

        void Update()
        {
            LatchRealInput();
            PerfUpdate(Time.unscaledDeltaTime);
            if (CurrentPhase == Phase.Loading) { LoadGame(); return; }
            var dt = Mathf.Min(Time.unscaledDeltaTime, 0.25f);
            _accumulator += dt;
            while (_accumulator >= LogicStep)
            {
                _accumulator -= LogicStep;
                Tick(LogicStep);
            }
            if (_quit) { _quit = false; Log("Ende (Skriptbefehl quit)"); Application.Quit(); }
        }

        void LatchRealInput()
        {
            var s = _realUi.Poll();
            _latchConfirm |= s.ConfirmPressed;
            _latchCancel |= s.CancelPressed;
            _latchHeld |= s.ConfirmHeld;
            if (s.MoveY != 0) _latchMove = s.MoveY;
            if (s.MoveX != 0) _latchMoveX = s.MoveX;
            var gi = PadInput.Instance;
            if (gi != null && gi.WasPressedThisFrame(GameButton.Plus)) _latchMenu = true;
        }

        // Ein Logikschritt (30 Hz). Öffentlich für Tests und die Editor-Steuerung.
        public void Tick(float dt)
        {
            Ticks++;
            ScriptFrame sf = ScriptFrame.None;
            var scripted = Runner != null && !Runner.Finished;
            if (scripted) sf = Runner.Next(this);

            // Eingabe des Ticks: Skript oder Zwischenspeicher der echten Geräte.
            var ui = scripted
                ? new UiInputState(sf.A, sf.B, sf.A, sf.B, sf.Down ? 1 : sf.Up ? -1 : 0, sf.Right ? 1 : sf.Left ? -1 : 0, sf.Plus)
                : new UiInputState(_latchConfirm, _latchCancel, _latchHeld, false, _latchMove, _latchMoveX, _latchMenu);
            var menuKey = scripted ? sf.Plus : _latchMenu;
            _latchConfirm = _latchCancel = _latchMenu = _latchHeld = false;
            _latchMove = _latchMoveX = 0;
            if (scripted) FeedScriptToDevices(sf);
            _override.Enabled = scripted;

            switch (CurrentPhase)
            {
                case Phase.Title: TickTitle(ui); break;
                case Phase.Playing: TickPlaying(dt, ui, sf, menuKey); break;
            }
            _override.ClearPressed();
        }

        void FeedScriptToDevices(ScriptFrame sf)
        {
            var move = Vector2.zero;
            if (sf.Up) move.y += 1f;
            if (sf.Down) move.y -= 1f;
            if (sf.Left) move.x -= 1f;
            if (sf.Right) move.x += 1f;
            _override.Move = move;
            _override.Hold(GameButton.A, sf.A);
            if (sf.A) _override.Press(GameButton.A);
            _override.Hold(GameButton.B, sf.B);
            if (sf.B) _override.Press(GameButton.B);
            // Die Textbox liest je Bild; der Druck bleibt bis zum nächsten Bild gespeichert.
            if (sf.A) _manual.PressConfirm();
            if (sf.B) _manual.PressCancel();
            if (sf.Down) _manual.MoveDown();
            if (sf.Up) _manual.MoveUp();
            if (sf.Left) _manual.MoveLeft();
            if (sf.Right) _manual.MoveRight();
        }

        void TickPlaying(float dt, UiInputState ui, ScriptFrame sf, bool menuKey)
        {
            if (Loop == null) return;
            var name = Loop.State.ToString();
            StateTicks.TryGetValue(name, out var n);
            StateTicks[name] = n + 1;
            if (name != _lastLoopState) { Log("Zustand " + _lastLoopState + " -> " + name + " (Tick " + Ticks + ")"); _lastLoopState = name; }

            var windowActive = Windows.IsOpen;
            Adapter.Tick();
            BridgeText();
            BridgeMenu(ui);
            if (windowActive && Windows.IsOpen) Windows.Tick(ui);

            var gi = GameFrame.None;
            if (!Textbox.IsOpen && !Textbox.IsChoosing && !windowActive && !Windows.IsOpen)
            {
                gi.Confirm = ui.ConfirmPressed;
                gi.Cancel = ui.CancelPressed || _menuCancel;
                gi.Menu = menuKey && !Battle.Active;
                gi.Up = ui.MoveY < 0;
                gi.Down = ui.MoveY > 0;
            }
            else if (_menuCancel) gi.Cancel = true;
            _menuCancel = false;
            if (sf.Starter >= 0) gi.StarterChoice = sf.Starter;

            // Kampfansicht: Befehl des Spielers in die Schleife geben; solange sie Schritte abspielt, bleibt die Schleife stehen.
            var hold = false;
            if (Battle.Active)
            {
                var r = Battle.Tick(dt, ui);
                if (sf.Fight >= 0 && Loop.State == GameState.Battle && Battle.CurrentMode == BattleView.Mode.Command) r.Command = BattleCommand.Fight(sf.Fight);
                if (r.Command.HasValue) gi.Battle = r.Command;
                if (r.Replacement >= 0) gi.Replacement = r.Replacement;
                hold = Loop.State != GameState.Battle && Battle.Busy;
            }

            if (!hold)
            {
                var sig = _pendingStep ?? Adapter.TakePending();
                _pendingStep = null;
                Loop.Tick(dt, gi, sig);
                if (Loop.State == GameState.Battle && !Battle.Active && Loop.Battle?.Engine != null)
                {
                    BeginBattleView();
                    Log("Kampf beginnt: " + Loop.Battle.Request.Kind + (Loop.Battle.Request.Kind == BattleRequestKind.Wild ? " Art " + Loop.Battle.Request.MonsNo + " Stufe " + Loop.Battle.Request.Level : " Trainer " + Loop.Battle.Request.TrainerId));
                }
            }

            if (Loop.State == GameState.Field && !Battle.Active && !Textbox.IsOpen && Field != null && Field.Loaded)
            {
                if (!_startChecked) EnsureWalkableStart();
                var ev = Field.LogicTickExternal(dt);
                if ((ev & MoveEvents.Arrived) != 0) CheckEncounter();
            }
        }

        bool _startChecked;

        // Der gespeicherte Ort (TownMapLocation) kann eine gesperrte Zelle sein (Kartenmarke, nicht Standort): dann nächste begehbare Zelle nehmen.
        void EnsureWalkableStart()
        {
            _startChecked = true;
            var m = Field.Mover;
            if (Field.Collision.CanEnter(m.GridX, m.GridY, m.Height, false, false).CanEnter) { Log("Startzelle begehbar"); return; }
            for (var r = 1; r <= 8; r++)
                for (var dx = -r; dx <= r; dx++)
                    for (var dy = -r; dy <= r; dy++)
                    {
                        if (Math.Max(Math.Abs(dx), Math.Abs(dy)) != r) continue;
                        var gx = m.GridX + dx;
                        var gy = m.GridY + dy;
                        var cell = Field.Collision.CellAt(gx, gy);
                        if (cell.Code == AttributeCodes.Door || !Field.Collision.CanEnter(gx, gy, m.Height, false, false).CanEnter) continue;
                        Log("Startzelle (" + m.GridX + ", " + m.GridY + ") gesperrt; nächste begehbare Zelle (" + gx + ", " + gy + ")");
                        Teleport(gx, gy, MoveDir.Down);
                        return;
                    }
            Log("Startzelle gesperrt, keine begehbare Zelle im Umkreis 8");
        }

        void CheckEncounter()
        {
            var m = Field.Mover;
            var cell = Field.Collision.CellAt(m.GridX, m.GridY);
            if (!AttributeCodes.IsGrass(cell.Code) && !AttributeCodes.IsLongGrass(cell.Code)) return;
            var zone = Field.Data.Router.ZoneAtCell(Field.ZoneIdNow, m.GridX, m.GridY);
            _pendingStep = FieldSignal.Step(zone, EncounterKind.Grass);
        }

        // Dialog und Auswahl des Ereignis-Hosts in der Textbox darstellen; deren Ende meldet an das Datenmodell zurück.
        void BridgeText()
        {
            var host = Loop.Host;
            var d = host.Dialog;
            if (!d.IsOpen) _dialogToken = -1;
            else if (!d.IsFinished && _dialogToken != d.ShownPages && !Textbox.IsOpen)
            {
                var token = d.ShownPages;
                _dialogToken = token;
                var msg = host.ComposeLabel(d.Msbt, d.Label) ?? PlainMessage.Parse("[" + d.Msbt + " / " + d.Label + "]");
                Textbox.Show(msg, () =>
                {
                    if (host.Dialog.IsOpen && host.Dialog.ShownPages == token) host.Dialog.ForceFinish();
                });
            }

            var c = host.Choice;
            if (!c.IsOpen) _choiceShown = false;
            else if (!_choiceShown && c.Result < 0 && !Textbox.IsOpen && !Textbox.IsChoosing && !Windows.IsOpen)
            {
                _choiceShown = true;
                var labels = new string[c.Labels.Count];
                for (var i = 0; i < labels.Length; i++) labels[i] = c.Labels[i] == "yes" ? "Ja" : c.Labels[i] == "no" ? "Nein" : c.Labels[i];
                var cancel = c.CancelIndex;
                // Auswahlfenster: Original-Kontextmenü, sonst die eigene Auswahl der Textbox.
                if (!Windows.IsAvailable || !Windows.OpenChoice(labels, cancel, idx => host.Choice.Force(idx)))
                    Textbox.Choose(labels, cancel, idx => host.Choice.Force(idx));
            }
        }

        // Menü-Taste: Hauptmenü aus dem Original-Prefab (Party, Beutel, Bericht); ohne Original-Fenster das kleine eigene Menü.
        void BridgeMenu(UiInputState ui)
        {
            if (Loop.State != GameState.Menu) { _menuAsked = false; return; }
            if (_menuAsked || Textbox.IsOpen || Textbox.IsChoosing || Windows.IsOpen) return;
            _menuAsked = true;
            if (Windows.IsAvailable && Windows.OpenMainMenu(() => _menuCancel = true)) return;
            Textbox.Ask("Menü", new[] { "Speichern", "Zurück" }, 1, a =>
            {
                if (a == 0) SaveNow();
                _menuCancel = true;
            });
        }

        string SaveForMenu() => SaveNow();

        // ---- Speichern ----

        public string SaveNow()
        {
            if (Session == null || Field == null || !Field.Loaded) return "nicht möglich";
            var m = Field.Mover;
            SavedPosition.Write(Session.Save, Field.ZoneIdNow, m.GridX, m.GridY, m.Facing);
            try
            {
                var r = Saves.Write(Session.Save);
                var s = "gespeichert: " + r.Bytes + " Byte, Backup " + (string.IsNullOrEmpty(r.BackupPath) ? "-" : Path.GetFileName(Path.GetDirectoryName(r.BackupPath)));
                Log("Speichern " + s);
                return s;
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException || e is Xnu.Save.SaveFormatException)
            {
                Debug.LogError("[Game] Speichern fehlgeschlagen: " + e.GetType().Name + ": " + e.Message);
                return "Speichern fehlgeschlagen: " + e.GetType().Name;
            }
        }

        // ---- IScriptWorld ----

        public string StateName
        {
            get
            {
                if (CurrentPhase != Phase.Playing) return CurrentPhase.ToString();
                if (Field == null || !Field.Loaded) return "Loading";
                if (Field.InTransition) return "Transition";
                if (Battle.Active)
                    return Battle.CurrentMode == BattleView.Mode.Command ? "BattleCommand" : Battle.CurrentMode == BattleView.Mode.Moves ? "BattleMoves" : "BattleBeats";
                if (Windows != null && Windows.IsOpen) return "Ui" + Windows.Screen;
                if (Textbox.IsChoosing) return "Choice";
                if (Textbox.IsOpen) return "Textbox";
                return Loop.State.ToString();
            }
        }

        // Ein Fehler in einem Skriptbefehl (z. B. Speichern ohne Schreibrecht) darf den Befehl nicht endlos wiederholen:
        // sonst legte jeder Tick ein neues Backup an (auf dem iPad 11.190 Stück in 80 s). Fehler werden gezählt und gemeldet, der Befehl gilt als erledigt.
        public int ScriptCommandErrors { get; private set; }

        public bool Execute(string command, string[] args)
        {
            try { return ExecuteCore(command, args); }
            catch (Exception e)
            {
                ScriptCommandErrors++;
                Debug.LogError("[Game] Skriptbefehl " + command + " fehlgeschlagen: " + e.GetType().Name + ": " + e.Message);
                return true;
            }
        }

        bool ExecuteCore(string command, string[] args)
        {
            switch (command)
            {
                case "log": Log("Skript: " + string.Join(" ", args)); return true;
                case "quit": _quit = true; return true;
                case "save": Log("Skript: " + SaveNow()); return true;
                case "shot":
                    if (!Field?.Loaded ?? true) { if (CurrentPhase == Phase.Playing) return false; }
                    Shot(args.Length > 0 ? args[0] : "shot");
                    return true;
                case "goto":
                    if (Field == null || !Field.Loaded || Field.InTransition) return false;
                    Teleport(int.Parse(args[0]), int.Parse(args[1]), args.Length > 2 ? ParseDir(args[2]) : Field.Mover.Facing);
                    return true;
                case "nearnpc":
                    if (Field == null || !Field.Loaded || Field.InTransition) return false;
                    Log("Skript: nearnpc " + (NearNpc(args.Length > 0 ? args[0] : "") ? "ok" : "kein Ansprechpartner"));
                    return true;
                case "encounter":
                    if (Loop == null || Loop.State != GameState.Field) return false;
                    ForceEncounter();
                    return true;
                case "state":
                    Log("Zustand " + StateName + ", Textbox offen " + (Textbox != null && Textbox.IsOpen) + (Textbox != null && Textbox.Flow != null ? " (" + Textbox.Flow.State + ")" : "") +
                        ", Dialog " + (Loop != null && Loop.Host.Dialog.IsOpen) + " " + (Loop != null ? Loop.Host.Dialog.Label : ""));
                    return true;
                case "report":
                    Log(Summary());
                    return true;
                case "mem":
                    Log("Speicher: " + MemoryLine() + ", Fehlermeldungen " + ErrorLogs + ", lowMemory " + LowMemoryEvents);
                    foreach (var e in _firstErrors) Log("Fehlermeldung (erste): " + e);
                    return true;
            }
            Log("Skript: unbekannter Befehl " + command);
            return true;
        }

        static MoveDir ParseDir(string s)
        {
            switch (s.ToLowerInvariant())
            {
                case "up": return MoveDir.Up;
                case "right": return MoveDir.Right;
                case "left": return MoveDir.Left;
                default: return MoveDir.Down;
            }
        }

        void Teleport(int gx, int gy, MoveDir facing)
        {
            Field.Mover.Teleport(gx, gy, facing);
            Field.ForceStream();
            Field.RefreshNpcsNow();
        }

        // Stellt den Spieler neben den nächsten ansprechbaren NPC der Zone und dreht ihn hin.
        public bool NearNpc(string idContains = "")
        {
            var zone = Field.Zone.ZoneId;
            PlacementRecord best = null;
            var bestD = int.MaxValue;
            var m = Field.Mover;
            foreach (var p in Field.Data.Placements.InZone(zone))
            {
                if (!p.IsVisibleNpc || !p.HasTalk || !PlacementDirectory.IsActive(p, Adapter)) continue;
                if (!string.IsNullOrEmpty(idContains) && p.Id.IndexOf(idContains, StringComparison.OrdinalIgnoreCase) < 0) continue;
                var d = Math.Abs(p.GridX - m.GridX) + Math.Abs(p.GridY - m.GridY);
                if (d < bestD && d > 0) { bestD = d; best = p; }
            }
            if (best == null) return false;
            foreach (var dir in new[] { MoveDir.Down, MoveDir.Up, MoveDir.Left, MoveDir.Right })
            {
                var d = dir.GridDelta();
                var gx = best.GridX + d.Dx;
                var gy = best.GridY + d.Dy;
                if (!Field.Collision.CanEnter(gx, gy, m.Height, false, false).CanEnter) continue;
                var look = OppositeOf(dir);
                Teleport(gx, gy, look);
                Log("NPC " + best.Id + " (" + best.GridX + ", " + best.GridY + "), Spieler an (" + gx + ", " + gy + ")");
                return true;
            }
            return false;
        }

        static MoveDir OppositeOf(MoveDir d)
        {
            switch (d)
            {
                case MoveDir.Up: return MoveDir.Down;
                case MoveDir.Down: return MoveDir.Up;
                case MoveDir.Left: return MoveDir.Right;
                default: return MoveDir.Left;
            }
        }

        void ForceEncounter()
        {
            var zone = Field.Data.Router.ZoneAtCell(Field.ZoneIdNow, Field.Mover.GridX, Field.Mover.GridY);
            var req = EncounterService.Roll(Session.Data, zone, EncounterKind.Grass, Session.Rng, true) ?? BattleRequest.Wild(396, 3);
            WildEncounters++;
            Log("Begegnung erzwungen: Art " + req.MonsNo + " Stufe " + req.Level + " (Zone " + zone + ")");
            _pendingStep = null;
            if (Loop.BeginBattle(req))
                BeginBattleView();
        }

        void BeginBattleView()
        {
            if (!Battle.SkinActive && Windows.IsAvailable && _uiData != null) Battle.UseOriginalSkin(_uiData, _camera);
            Battle.Begin(Loop.Battle, new GameBattleTexts(Session.Data, Session.Language));
        }

        // Bild der Hauptkamera (mit Kamera-Canvas) als PNG; Ziel: -xnuShotDir, sonst persistentDataPath/Shots.
        public string Shot(string name)
        {
            var dir = !string.IsNullOrEmpty(Options.ShotDir) ? Options.ShotDir : Path.Combine(Application.persistentDataPath, "Shots");
            var path = Path.Combine(dir, name + ".png");
            Directory.CreateDirectory(dir);
            var cam = _camera;
            var rt = new RenderTexture(1280, 720, 24, RenderTextureFormat.ARGB32);
            var oldRt = cam.targetTexture;
            var oldRect = cam.rect;
            cam.rect = new Rect(0, 0, 1, 1);
            cam.targetTexture = rt;
            cam.Render();
            cam.targetTexture = oldRt;
            cam.rect = oldRect;
            var prev = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D(1280, 720, TextureFormat.RGBA32, false);
            tex.ReadPixels(new Rect(0, 0, 1280, 720), 0, 0);
            tex.Apply();
            RenderTexture.active = prev;
            var px = tex.GetPixels32();
            long r = 0, g = 0, b = 0;
            for (var i = 0; i < px.Length; i++) { r += px[i].r; g += px[i].g; b += px[i].b; px[i].a = 255; }
            tex.SetPixels32(px);
            tex.Apply();
            File.WriteAllBytes(path, tex.EncodeToPNG());
            Destroy(rt);
            Destroy(tex);
            ShotsTaken++;
            var s = "Bild " + name + " Mittel " + (r / px.Length) + "," + (g / px.Length) + "," + (b / px.Length) + " -> " + path;
            Log(s);
            return s;
        }

        // ---- Messung (iPad, docs/ipad-durchstich-1.md) ----

        public int ErrorLogs { get; private set; }
        public int WarningLogs { get; private set; }
        public int LowMemoryEvents { get; private set; }
        readonly List<string> _firstErrors = new List<string>();
        readonly long[] _vm = new long[7];
        int _perfFrames;
        float _perfTime, _perfWorst, _perfTotal;
        float _loadStartedAt = -1f;
        bool _fieldLoadLogged;

        void OnLogMessage(string condition, string stackTrace, LogType type)
        {
            if (type == LogType.Warning) { WarningLogs++; return; }
            if (type == LogType.Log) return;
            ErrorLogs++;
            if (_firstErrors.Count < 8 && !condition.StartsWith("[Game] ")) _firstErrors.Add(condition.Length > 160 ? condition.Substring(0, 160) : condition);
        }

        void OnLowMemory() { LowMemoryEvents++; Log("Systemwarnung: wenig Speicher (lowMemory) bei " + MemoryLine()); }

        string MemoryLine()
        {
            NativeProbe.VmInfo(_vm);
            return "footprintMiB=" + Mib(_vm[0]) + " peakMiB=" + Mib(_vm[1]) + " internalMiB=" + Mib(_vm[2]) + " compressedMiB=" + Mib(_vm[3]) +
                   " availMiB=" + Mib(NativeProbe.AvailableMemory()) + " thermal=" + NativeProbe.ThermalState() + " lowPower=" + NativeProbe.LowPowerMode() +
                   " unityMiB=" + Mib(UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong()) + " monoMiB=" + Mib(UnityEngine.Profiling.Profiler.GetMonoUsedSizeLong());
        }

        static string Mib(long bytes) => bytes < 0 ? "-1" : (bytes / (1024.0 * 1024.0)).ToString("F1", System.Globalization.CultureInfo.InvariantCulture);

        // Alle 5 s Echtzeit eine Zeile (nur mit -xnuPerfLog); die Zeit bis zum geladenen Feld immer, einmalig.
        void PerfUpdate(float dt)
        {
            if (_loadStartedAt < 0f && CurrentPhase == Phase.Loading) _loadStartedAt = Time.realtimeSinceStartup;
            if (!_fieldLoadLogged && _loadStartedAt >= 0f && Field != null && Field.Loaded)
            {
                _fieldLoadLogged = true;
                Log("Zone geladen nach " + (Time.realtimeSinceStartup - _loadStartedAt).ToString("F1", System.Globalization.CultureInfo.InvariantCulture) + " s seit „Weiter“; " + MemoryLine());
            }
            if (Options == null || !Options.PerfLog) return;
            _perfFrames++;
            _perfTime += dt;
            _perfTotal += dt;
            if (dt > _perfWorst) _perfWorst = dt;
            if (_perfTime < 5f) return;
            Log("XNUPERF|t=" + _perfTotal.ToString("F0", System.Globalization.CultureInfo.InvariantCulture) + "|state=" + StateName + "|fps=" + (_perfFrames / _perfTime).ToString("F1", System.Globalization.CultureInfo.InvariantCulture) +
                "|worstMs=" + (_perfWorst * 1000f).ToString("F0", System.Globalization.CultureInfo.InvariantCulture) + "|ticks=" + Ticks + "|" + MemoryLine().Replace(' ', '|') + "|errors=" + ErrorLogs + "|warnings=" + WarningLogs + "|lowMemory=" + LowMemoryEvents);
            _perfFrames = 0; _perfTime = 0f; _perfWorst = 0f;
        }

        public string Summary()
        {
            if (Loop == null) return "Phase " + CurrentPhase;
            var pos = Field != null && Field.Mover != null ? ", Spieler (" + Field.Mover.GridX + ", " + Field.Mover.GridY + ") Zone " + Field.ZoneIdNow : "";
            return "Ticks " + Ticks + ", Schleife " + Loop.State + pos + ", Ereignisse " + Loop.EventsStarted + "/" + Loop.EventsFinished + ", Kämpfe " + Loop.BattlesStarted + "/" + Loop.BattlesFinished +
                   ", Zonenwechsel " + Adapter.ZoneChanges + ", Ansprechen " + Adapter.TalkRequests + ", Berühren " + Adapter.ContactRequests + ", Lücken-Aufrufe " + Loop.Host.GapCommandCalls +
                   ", Textfenster " + Loop.Host.Dialog.ShownPages + ", Kampfschritte " + Battle.BeatsShown + ", Kampfbefehle " + Battle.CommandsIssued + ", Speichern " + SavesWritten +
                   ", Skript-Timeouts " + (Runner?.Timeouts ?? 0) + ", Fehlermeldungen " + ErrorLogs + ", Warnungen " + WarningLogs;
        }

        void OnDestroy()
        {
            Application.logMessageReceived -= OnLogMessage;
            Application.lowMemory -= OnLowMemory;
            if (PadInput.Instance != null && PadInput.Instance.Override == _override) PadInput.Instance.Override = null;
            Adapter?.Detach();
        }
    }
}
