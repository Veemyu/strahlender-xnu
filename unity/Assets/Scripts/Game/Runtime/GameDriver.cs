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
        int _latchMove;
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
            if (string.IsNullOrEmpty(scriptPath)) scriptPath = Options.ScriptPath;
            if (Options.AutoContinue) autoContinue = true;
            _camera = Camera.main;
            if (_camera == null) _camera = FindFirstObjectByType<Camera>();
            if (PadInput.Instance == null) new GameObject("GameInput").AddComponent<PadInput>();
            _override = new InputOverride();

            var root = !string.IsNullOrEmpty(Options.SaveRoot) ? Options.SaveRoot : Path.Combine(Application.persistentDataPath, "Saves");
            Saves = new SaveSlotService(root, ResolveSaveSource(Options.SaveSource));

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
            Log("Start; Daten " + GameDataPaths.Root + "; Slot " + (Saves.HasSlot ? "vorhanden" : "keiner") + "; Quelle " + (string.IsNullOrEmpty(Saves.ImportSource) ? "-" : "vorhanden"));
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
            if (_titleCursor == 0 && Saves.CanContinue) { CurrentPhase = Phase.Loading; StatusNote = "Lade Stammdaten und Spielstand …"; RefreshTitle(); }
            else { StatusNote = "Nicht verfügbar."; RefreshTitle(); }
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
                Adapter.LoopBusy = () => Loop.State != GameState.Field || Battle.Active || Textbox.IsOpen || Textbox.IsChoosing;
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
                ? new UiInputState(sf.A, sf.B, sf.A, sf.B, sf.Down ? 1 : sf.Up ? -1 : 0)
                : new UiInputState(_latchConfirm, _latchCancel, _latchHeld, false, _latchMove);
            var menuKey = scripted ? sf.Plus : _latchMenu;
            _latchConfirm = _latchCancel = _latchMenu = _latchHeld = false;
            _latchMove = 0;
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
        }

        void TickPlaying(float dt, UiInputState ui, ScriptFrame sf, bool menuKey)
        {
            if (Loop == null) return;
            var name = Loop.State.ToString();
            StateTicks.TryGetValue(name, out var n);
            StateTicks[name] = n + 1;
            if (name != _lastLoopState) { Log("Zustand " + _lastLoopState + " -> " + name + " (Tick " + Ticks + ")"); _lastLoopState = name; }

            Adapter.Tick();
            BridgeText();
            BridgeMenu(ui);

            var gi = GameFrame.None;
            if (!Textbox.IsOpen && !Textbox.IsChoosing)
            {
                gi.Confirm = ui.ConfirmPressed;
                gi.Cancel = ui.CancelPressed || _menuCancel;
                gi.Menu = menuKey && !Battle.Active;
                gi.Up = ui.MoveY < 0;
                gi.Down = ui.MoveY > 0;
            }
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
                    Battle.Begin(Loop.Battle, new GameBattleTexts(Session.Data, Session.Language));
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
            else if (!_choiceShown && c.Result < 0 && !Textbox.IsOpen && !Textbox.IsChoosing)
            {
                _choiceShown = true;
                var labels = new string[c.Labels.Count];
                for (var i = 0; i < labels.Length; i++) labels[i] = c.Labels[i] == "yes" ? "Ja" : c.Labels[i] == "no" ? "Nein" : c.Labels[i];
                Textbox.Choose(labels, c.CancelIndex, idx => host.Choice.Force(idx));
            }
        }

        // Menü-Taste: kleines Menü mit „Speichern“ (die übrigen Menüinhalte sind Lücke).
        void BridgeMenu(UiInputState ui)
        {
            if (Loop.State != GameState.Menu) { _menuAsked = false; return; }
            if (_menuAsked || Textbox.IsOpen || Textbox.IsChoosing) return;
            _menuAsked = true;
            Textbox.Ask("Menü", new[] { "Speichern", "Zurück" }, 1, a =>
            {
                if (a == 0) SaveNow();
                _menuCancel = true;
            });
        }

        // ---- Speichern ----

        public string SaveNow()
        {
            if (Session == null || Field == null || !Field.Loaded) return "nicht möglich";
            var m = Field.Mover;
            SavedPosition.Write(Session.Save, Field.ZoneIdNow, m.GridX, m.GridY, m.Facing);
            var r = Saves.Write(Session.Save);
            var s = "gespeichert: " + r.Bytes + " Byte, Backup " + (string.IsNullOrEmpty(r.BackupPath) ? "-" : Path.GetFileName(Path.GetDirectoryName(r.BackupPath)));
            Log("Speichern " + s);
            return s;
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
                if (Textbox.IsChoosing) return "Choice";
                if (Textbox.IsOpen) return "Textbox";
                return Loop.State.ToString();
            }
        }

        public bool Execute(string command, string[] args)
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

        public string Summary()
        {
            if (Loop == null) return "Phase " + CurrentPhase;
            var pos = Field != null && Field.Mover != null ? ", Spieler (" + Field.Mover.GridX + ", " + Field.Mover.GridY + ") Zone " + Field.ZoneIdNow : "";
            return "Ticks " + Ticks + ", Schleife " + Loop.State + pos + ", Ereignisse " + Loop.EventsStarted + "/" + Loop.EventsFinished + ", Kämpfe " + Loop.BattlesStarted + "/" + Loop.BattlesFinished +
                   ", Zonenwechsel " + Adapter.ZoneChanges + ", Ansprechen " + Adapter.TalkRequests + ", Berühren " + Adapter.ContactRequests + ", Lücken-Aufrufe " + Loop.Host.GapCommandCalls +
                   ", Textfenster " + Loop.Host.Dialog.ShownPages + ", Kampfschritte " + Battle.BeatsShown + ", Kampfbefehle " + Battle.CommandsIssued + ", Speichern " + SavesWritten +
                   ", Skript-Timeouts " + (Runner?.Timeouts ?? 0);
        }

        void OnDestroy()
        {
            if (PadInput.Instance != null && PadInput.Instance.Override == _override) PadInput.Instance.Override = null;
            Adapter?.Detach();
        }
    }
}
