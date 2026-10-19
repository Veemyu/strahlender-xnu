using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using Xnu.Battle.Flow;
using Xnu.EvScript;
using Xnu.Field;
using Xnu.Game;
using Xnu.Game.Unity;
using Xnu.Save;
using Xnu.UI;
using static Xnu.Tests.EvB;
using static Xnu.Tests.GameFixture;
using GameFrame = Xnu.Game.GameInput;

namespace Xnu.Tests
{
    // Tests des vertikalen Durchstichs (docs/vertikaler-durchstich-1.md): Eingabeskript, Optionen, Kampf-Protokoll-Player, Kampfansicht,
    // Feld-Adapter, Spielstand-Slot und Treiber (Start im EditMode, ohne Spielmodus und ohne Fokus). Nur erfundene Daten.
    public class GameUnityTests
    {
        sealed class Texts : IBattleTexts
        {
            public string Species(int monsNo) => "Art" + monsNo;
            public string Move(int moveNo) => "Atk" + moveNo;
            public string Item(int itemNo) => "Item" + itemNo;
            public string Label(string msbt, string label, params string[] words) => label == "BTL_STRID_STD_Encount_Wild1" ? "Wild: " + words[0] : null;
        }

        sealed class World2 : IScriptWorld
        {
            public string State = "Title";
            public readonly List<string> Commands = new List<string>();
            public string StateName => State;
            public bool Execute(string command, string[] args) { Commands.Add(command + " " + string.Join(" ", args)); return true; }
        }

        static FileBuilder Empty()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.End));
            return b;
        }

        static World BattleWorld(int partyLevel = 30)
        {
            var w = NewWorld(Empty(), partyLevel);
            Assert.IsTrue(w.Loop.BeginBattle(BattleRequest.Wild(BattleFlowTestData.Mon4, 5)));
            return w;
        }

        // ---- Eingabeskript ----

        [Test]
        public void ScriptParsesCommentsAndArguments()
        {
            var s = InputScript.Parse("# Kopf\nwait 5   # Pause\n\n  TAP A\nhold Up 3\nshot bild_1\n");
            Assert.AreEqual(4, s.Steps.Count);
            Assert.AreEqual("wait", s.Steps[0].Command);
            Assert.AreEqual(5, s.Steps[0].Number(0));
            Assert.AreEqual("tap", s.Steps[1].Command);
            Assert.AreEqual("shot", s.Steps[3].Command);
            Assert.AreEqual("bild_1", s.Steps[3].Args[0]);
            Assert.AreEqual(3, s.Steps[2].Number(1), "hold-Dauer");
        }

        [Test]
        public void RunnerWaitsTapsAndHolds()
        {
            var r = new InputScriptRunner(InputScript.Parse("wait 2\ntap A\nhold Up 2\ntap B"));
            var w = new World2();
            Assert.IsFalse(r.Next(w).Any);
            Assert.IsFalse(r.Next(w).Any);
            Assert.IsTrue(r.Next(w).A, "nach zwei Warte-Ticks folgt der Tastendruck im selben Tick");
        }

        [Test]
        public void RunnerProducesExactTapSequence()
        {
            var r = new InputScriptRunner(InputScript.Parse("tap A\nhold Up 2\ntap B"));
            var w = new World2();
            var f1 = r.Next(w);
            Assert.IsTrue(f1.A);
            var f2 = r.Next(w);
            Assert.IsTrue(f2.Up && !f2.A);
            var f3 = r.Next(w);
            Assert.IsTrue(f3.Up);
            var f4 = r.Next(w);
            Assert.IsTrue(f4.B);
            r.Next(w);
            Assert.IsTrue(r.Finished);
        }

        [Test]
        public void RunnerWaitstateEndsOnStateOrTimeout()
        {
            var r = new InputScriptRunner(InputScript.Parse("waitstate Field 3\ntap A"));
            var w = new World2();
            Assert.IsFalse(r.Next(w).A);
            w.State = "Field";
            Assert.IsTrue(r.Next(w).A, "Zustand erreicht: gleich weiter");
            Assert.AreEqual(0, r.Timeouts);

            var r2 = new InputScriptRunner(InputScript.Parse("waitstate Battle 2\ntap B"));
            var w2 = new World2();
            for (var i = 0; i < 6 && !r2.Finished; i++) r2.Next(w2);
            Assert.AreEqual(1, r2.Timeouts);
            Assert.IsTrue(r2.Finished);
        }

        [Test]
        public void RunnerMashPressesAEverySixthTick()
        {
            var r = new InputScriptRunner(InputScript.Parse("mash 12"));
            var w = new World2();
            var presses = 0;
            for (var i = 0; i < 12; i++) if (r.Next(w).A) presses++;
            Assert.AreEqual(2, presses);
        }

        [Test]
        public void RunnerPassesUnknownCommandsToTheWorldAndFightStarterToFrame()
        {
            var r = new InputScriptRunner(InputScript.Parse("goto 3 4 Up\nfight 2\nstarter 1"));
            var w = new World2();
            var f = r.Next(w);
            Assert.AreEqual(2, f.Fight);
            Assert.AreEqual("goto 3 4 Up", w.Commands[0]);
            Assert.AreEqual(1, r.Next(w).Starter);
        }

        // ---- Optionen ----

        [Test]
        public void OptionsPreferCommandLineOverEnvironment()
        {
            var env = new Dictionary<string, string> { ["XNU_SCRIPTED_INPUT"] = "env.txt", ["XNU_SAVE_ROOT"] = "envroot", ["XNU_AUTO_CONTINUE"] = "1" };
            var o = GameOptions.Parse(new[] { "x", "-xnuInputScript", "cli.txt", "-xnuShotDir", "shots" }, k => env.TryGetValue(k, out var v) ? v : null);
            Assert.AreEqual("cli.txt", o.ScriptPath);
            Assert.AreEqual("envroot", o.SaveRoot);
            Assert.AreEqual("shots", o.ShotDir);
            Assert.IsTrue(o.AutoContinue);
            Assert.AreEqual("", GameOptions.Parse(null, null).ScriptPath);
        }

        [Test]
        public void OptionsParseTargetFpsAndPerfLog()
        {
            var env = new Dictionary<string, string> { ["XNU_TARGET_FPS"] = "60", ["XNU_PERF_LOG"] = "1" };
            var o = GameOptions.Parse(null, k => env.TryGetValue(k, out var v) ? v : null);
            Assert.AreEqual(60, o.TargetFps);
            Assert.IsTrue(o.PerfLog);
            var cli = GameOptions.Parse(new[] { "-xnuTargetFps", "120", "-xnuPerfLog" }, k => null);
            Assert.AreEqual(120, cli.TargetFps);
            Assert.IsTrue(cli.PerfLog);
            Assert.AreEqual(0, GameOptions.Parse(new[] { "-xnuTargetFps", "abc" }, k => null).TargetFps, "ungültig: Standard bleibt");
            Assert.AreEqual(0, GameOptions.Parse(new[] { "-xnuTargetFps", "9999" }, k => null).TargetFps);
            Assert.IsFalse(GameOptions.Parse(null, null).PerfLog);
        }

        // ---- Datenmodelle ----

        [Test]
        public void DialogForceFinishAndChoiceForce()
        {
            var d = new DialogModel();
            d.Open("a", "b", null);
            Assert.IsFalse(d.IsFinished);
            d.ForceFinish();
            Assert.IsTrue(d.IsFinished);
            var c = new ChoiceModel();
            c.Open(new[] { "yes", "no" }, 0, 1);
            c.Force(1);
            Assert.AreEqual(1, c.Result);
            c.Close();
            c.Force(0);
            Assert.AreEqual(-1, c.Result, "geschlossen: keine Wirkung");
        }

        // ---- Kampf-Protokoll-Player ----

        [Test]
        public void LogPlayerTurnsLogIntoBeatsAndTracksHp()
        {
            var w = BattleWorld();
            var e = w.Loop.Battle.Engine;
            var p = new BattleLogPlayer(e, new Texts());
            p.Pump();
            var first = p.Dequeue();
            Assert.AreEqual(LogKind.BattleStart, first.Kind);
            Assert.IsTrue(first.FromLabel);
            StringAssert.StartsWith("Wild: Art", first.Text);
            var send = p.Dequeue();
            Assert.AreEqual(LogKind.SendOut, send.Kind);
            p.Apply(send);
            Assert.AreEqual(send.Poke, p.ShownActive[send.Side]);
            while (p.HasBeats) p.Apply(p.Dequeue());

            e.Submit(BattleCommand.Fight(0));
            Assert.Greater(p.Pump(), 0);
            var kinds = new List<LogKind>();
            while (p.HasBeats)
            {
                var b = p.Dequeue();
                kinds.Add(b.Kind);
                p.Apply(b);
                Assert.IsNotEmpty(b.Text + "x");
            }
            Assert.Contains(LogKind.MoveUsed, kinds);
            Assert.Contains(LogKind.Damage, kinds);
            var enemyId = e.Active(BattleEngine.EnemySide).PokeId;
            Assert.AreEqual(e.Active(BattleEngine.EnemySide).Poke.Hp, p.ShownHp[enemyId], "gezeigte KP = Engine-KP nach allen Schritten");
            Assert.Greater(p.LabelBeats, 0);
        }

        [Test]
        public void LogPlayerPlaysBattleToTheEnd()
        {
            var w = BattleWorld(60);
            var e = w.Loop.Battle.Engine;
            var p = new BattleLogPlayer(e, new Texts());
            var guard = 0;
            while (e.Phase != BattlePhase.Finished && guard++ < 50)
            {
                if (e.Phase == BattlePhase.AwaitCommands) e.Submit(BattleCommand.Fight(0));
                else if (e.Phase == BattlePhase.AwaitReplacement) e.SubmitReplacement(0);
            }
            p.Pump();
            var last = LogKind.BattleStart;
            while (p.HasBeats) last = p.Dequeue().Kind;
            Assert.AreEqual(BattlePhase.Finished, e.Phase);
            Assert.IsTrue(p.KindCounts.ContainsKey(LogKind.BattleEnd));
            Assert.IsTrue(last == LogKind.BattleEnd || last == LogKind.PrizeMoney || last == LogKind.MoneyLost || last == LogKind.ExpGained || last == LogKind.EvGained
                          || last == LogKind.LevelUp || last == LogKind.Faint);
        }

        // ---- Kampfansicht ----

        static UiInputState Press() => new UiInputState(true, false, true, false);

        [Test]
        public void BattleViewShowsBeatsThenMenuAndIssuesFightCommand()
        {
            var w = BattleWorld();
            var go = new GameObject("bv");
            try
            {
                var v = go.AddComponent<BattleView>();
                v.Build(null);
                v.Begin(w.Loop.Battle, new Texts());
                Assert.IsTrue(v.Active);
                Assert.IsTrue(v.Busy);
                var guard = 0;
                while (v.CurrentMode != BattleView.Mode.Command && guard++ < 400) v.Tick(1f / 30f, UiInputState.None);
                Assert.AreEqual(BattleView.Mode.Command, v.CurrentMode);
                StringAssert.Contains("Kampf", v.MenuText);
                StringAssert.Contains("Flucht", v.MenuText);
                Assert.Greater(v.BeatsShown, 0);
                v.Tick(1f / 30f, Press());                      // Kampf
                Assert.AreEqual(BattleView.Mode.Moves, v.CurrentMode);
                v.Tick(1f / 30f, UiInputState.None);            // Menü neu zeichnen
                StringAssert.Contains("Atk", v.MenuText);
                var r = v.Tick(1f / 30f, Press());              // erste Attacke
                Assert.IsTrue(r.Command.HasValue);
                Assert.AreEqual(CommandKind.Fight, r.Command.Value.Kind);
                Assert.AreEqual(0, r.Command.Value.MoveSlot);
                Assert.AreEqual(1, v.CommandsIssued);
            }
            finally { Object.DestroyImmediate(go); }
        }

        [Test]
        public void BattleViewBagNoticeAndRunCommand()
        {
            var w = BattleWorld();
            var go = new GameObject("bv");
            try
            {
                var v = go.AddComponent<BattleView>();
                v.Build(null);
                v.Begin(w.Loop.Battle, new Texts());
                var guard = 0;
                while (v.CurrentMode != BattleView.Mode.Command && guard++ < 400) v.Tick(1f / 30f, UiInputState.None);
                v.Tick(1f / 30f, new UiInputState(false, false, false, false, 1));   // Cursor auf Beutel
                v.Tick(1f / 30f, Press());
                Assert.AreEqual(BattleView.Mode.Notice, v.CurrentMode);
                v.Tick(1f / 30f, Press());
                Assert.AreEqual(BattleView.Mode.Command, v.CurrentMode);
                v.Tick(1f / 30f, new UiInputState(false, false, false, false, -1));  // von Beutel nach Kampf
                v.Tick(1f / 30f, new UiInputState(false, false, false, false, -1));  // Umlauf nach Flucht
                Assert.AreEqual(3, v.Cursor);
                var r = v.Tick(1f / 30f, Press());
                Assert.IsTrue(r.Command.HasValue);
                Assert.AreEqual(CommandKind.Run, r.Command.Value.Kind);
            }
            finally { Object.DestroyImmediate(go); }
        }

        [Test]
        public void BattleViewEndsAfterLastBeatWhenBattleIsFinished()
        {
            var w = BattleWorld(80);
            var go = new GameObject("bv");
            try
            {
                var v = go.AddComponent<BattleView>();
                v.Build(null);
                v.Begin(w.Loop.Battle, new Texts());
                var e = w.Loop.Battle.Engine;
                var ticks = 0;
                while (v.Active && ticks++ < 4000)
                {
                    var r = v.Tick(1f / 30f, UiInputState.None);
                    if (!r.Command.HasValue && v.CurrentMode == BattleView.Mode.Command) r = v.Tick(1f / 30f, Press());
                    if (!r.Command.HasValue && v.CurrentMode == BattleView.Mode.Moves) r = v.Tick(1f / 30f, Press());
                    if (r.Command.HasValue || r.Replacement >= 0)
                        w.Loop.Tick(1f / 30f, new GameFrame { Battle = r.Command, Replacement = r.Replacement, StarterChoice = -1 });
                }
                Assert.IsFalse(v.Active, "Ansicht endet nach dem letzten Schritt");
                Assert.AreEqual(BattlePhase.Finished, e.Phase);
                Assert.IsTrue(w.Loop.Battle.IsFinished);
                Assert.AreEqual(GameState.Field, w.Loop.State);
            }
            finally { Object.DestroyImmediate(go); }
        }

        // ---- Feld-Adapter ----

        [Test]
        public void AdapterTurnsInteractionsIntoSignalsAndReadsFlags()
        {
            var w = NewWorld(Empty());
            var go = new GameObject("fc");
            try
            {
                var field = go.AddComponent<FieldController>();
                var a = new FieldHostAdapter(field, w.Session);
                var place = new PlacementRecord { Id = "npc1", TalkLabel = "ev_talk", ContactLabel = "ev_touch" };
                Assert.IsFalse(a.Busy);
                Assert.IsTrue(a.Handle(new InteractionRequest(InteractionKind.Talk, 1, place, 3, 4, MoveDir.Up)));
                Assert.IsTrue(a.Busy, "bis die Schleife das Signal übernommen hat");
                Assert.IsFalse(a.Handle(new InteractionRequest(InteractionKind.Contact, 1, place, 3, 4, MoveDir.Up)));
                var s = a.TakePending();
                Assert.AreEqual(FieldSignalKind.Talk, s.Value.Kind);
                Assert.AreEqual("ev_talk", s.Value.Label);
                Assert.IsFalse(a.Busy);
                Assert.IsTrue(a.Handle(new InteractionRequest(InteractionKind.Contact, 1, place, 3, 4, MoveDir.Up)));
                Assert.AreEqual(FieldSignalKind.Contact, a.TakePending().Value.Kind);

                Assert.IsFalse(a.IsSet(150));
                w.Session.Vars.SetFlag(150, true);
                Assert.IsTrue(a.IsSet(150));
                Assert.IsFalse(a.IsSet(-1));
                Assert.IsFalse(a.IsSet(99999));
                var visible = new PlacementRecord { WorkFlag = 150 };
                Assert.IsTrue(PlacementDirectory.IsActive(visible, a));
                Assert.AreSame(a, field.Flags);
            }
            finally { Object.DestroyImmediate(go); }
        }

        [Test]
        public void AdapterQueuesZoneChangeUntilFieldIsLoadedAndCountsVisualCommands()
        {
            var w = NewWorld(Empty());
            var go = new GameObject("fc");
            try
            {
                var field = go.AddComponent<FieldController>();
                var a = new FieldHostAdapter(field, w.Session);
                a.LoopBusy = () => true;
                Assert.IsTrue(a.Busy);
                a.ChangeZone(425, 0, true);
                Assert.IsFalse(a.ChangeZoneIsDone());
                Assert.IsFalse(a.GetPlayerGrid(out _, out _, out _));
                a.SetObjectVisible("npc", false);
                Assert.AreEqual(1, a.VisibilityCalls);
                Assert.IsTrue(a.Hidden.Contains("npc"));
                a.SetEventMode(true);
                Assert.IsTrue(a.EventMode);
                Assert.IsTrue(a.AnimationsDone("x"));
            }
            finally { Object.DestroyImmediate(go); }
        }

        // ---- Spielstand ----

        [Test]
        public void SavedPositionRoundTripsAndRejectsEmpty()
        {
            var save = NewSave();
            Assert.IsFalse(SavedPosition.Read(save).Valid, "leerer Save: keine Position");
            SavedPosition.Write(save, 167, 842, 597, MoveDir.Left);
            var p = SavedPosition.Read(save);
            Assert.IsTrue(p.Valid);
            Assert.AreEqual(167, p.Zone);
            Assert.AreEqual(842, p.GridX);
            Assert.AreEqual(597, p.GridY);
            Assert.AreEqual(MoveDir.Left, SavedPosition.ToFacing(p.Direction));
            Assert.AreEqual(MoveDir.Down, SavedPosition.ToFacing(0));
        }

        [Test]
        public void SaveSlotImportsReadOnlyWritesWithBackupAndReloads()
        {
            var dir = SaveTestSupport.NewTempDir();
            try
            {
                var source = Path.Combine(dir, "quelle");
                Directory.CreateDirectory(source);
                var original = NewSave(30, 777).ToBytes();
                File.WriteAllBytes(Path.Combine(source, "SaveData.bin"), original);
                var svc = new SaveSlotService(Path.Combine(dir, "ablage"), source);
                Assert.IsFalse(svc.HasSlot);
                Assert.IsTrue(svc.CanContinue);
                var save = svc.Load();
                Assert.AreEqual(777, save.Money);
                Assert.IsTrue(svc.HasSlot);
                StringAssert.Contains("importiert", svc.Note);

                save.Money = 888;
                SavedPosition.Write(save, 425, 3, 4, MoveDir.Up);
                var r1 = svc.Write(save);
                save.Money = 999;
                var r2 = svc.Write(save);
                Assert.AreEqual(2, svc.Writes);
                Assert.IsNotNull(r2.BackupPath, "zweites Schreiben sichert den ersten Stand");
                var again = new SaveSlotService(Path.Combine(dir, "ablage"), null).Load();
                Assert.AreEqual(999, again.Money);
                Assert.AreEqual(425, SavedPosition.Read(again).Zone);
                CollectionAssert.AreEqual(original, File.ReadAllBytes(Path.Combine(source, "SaveData.bin")), "Quelle bleibt unverändert");
            }
            finally { SaveTestSupport.Cleanup(dir); }
        }

        [Test]
        public void SaveSlotWithoutSourceCannotContinue()
        {
            var dir = SaveTestSupport.NewTempDir();
            try
            {
                var svc = new SaveSlotService(Path.Combine(dir, "ablage"), "");
                Assert.IsFalse(svc.CanContinue);
                Assert.Throws<FileNotFoundException>(() => svc.Load());
                StringAssert.Contains("Slot-Ordner fehlt", svc.Problem);
            }
            finally { SaveTestSupport.Cleanup(dir); }
        }

        [Test]
        public void ResolveRootUsesDocumentsAndKeepsLegacyAndExplicit()
        {
            var dir = SaveTestSupport.NewTempDir();
            try
            {
                Assert.AreEqual("/x", SaveSlotService.ResolveRoot("/x", dir));
                Assert.AreEqual(dir, SaveSlotService.ResolveRoot("", dir), "neu: Documents selbst, Slot unter Saves/main");
                Directory.CreateDirectory(Path.Combine(dir, "Saves", "Saves", "main"));
                Assert.AreEqual(Path.Combine(dir, "Saves"), SaveSlotService.ResolveRoot(null, dir), "ältere Läufe: Saves/Saves/main bleibt maßgebend");
                Assert.Throws<System.ArgumentException>(() => SaveSlotService.ResolveRoot("", ""));
            }
            finally { SaveTestSupport.Cleanup(dir); }
        }

        // Der Weg aus devicectl/Dateien-App: Datei liegt nach „copy to Documents/Saves/main/SaveData.bin“ genau dort, wo der Dienst sucht.
        [Test]
        public void SlotFoundAtDocumentsSavesMainAfterExternalCopy()
        {
            var dir = SaveTestSupport.NewTempDir();
            try
            {
                var docs = Path.Combine(dir, "Documents");
                Directory.CreateDirectory(Path.Combine(docs, "Saves", "main"));
                var bytes = NewSave(30, 4242).ToBytes();
                File.WriteAllBytes(Path.Combine(docs, "Saves", "main", "SaveData.bin"), bytes);
                var svc = new SaveSlotService(SaveSlotService.ResolveRoot("", docs), "", SaveSlotService.DropInSources(docs));
                Assert.IsTrue(svc.HasSlot);
                Assert.IsTrue(svc.CanContinue);
                Assert.AreEqual(Path.Combine(docs, "Saves", "main"), svc.SlotPath);
                Assert.AreEqual(4242, svc.Load().Money);
                StringAssert.Contains("eigenen Slot", svc.Note);
                Assert.IsTrue(string.Join("\n", svc.Diagnose()).Contains(bytes.Length + " Byte"));
            }
            finally { SaveTestSupport.Cleanup(dir); }
        }

        [Test]
        public void TruncatedOrEmptySlotIsNotASlotAndSaysWhy()
        {
            var dir = SaveTestSupport.NewTempDir();
            try
            {
                var docs = Path.Combine(dir, "Documents");
                var slot = Path.Combine(docs, "Saves", "main");
                Directory.CreateDirectory(slot);
                var svc = new SaveSlotService(docs, "");
                Assert.IsFalse(svc.HasSlot, "leerer Ordner");
                StringAssert.Contains("weder SaveData.bin noch Backup.bin", svc.Problem);

                var bytes = NewSave(30, 5).ToBytes();
                var half = new byte[bytes.Length / 2];
                System.Array.Copy(bytes, half, half.Length);
                File.WriteAllBytes(Path.Combine(slot, "SaveData.bin"), half);
                svc.Refresh();
                Assert.IsFalse(svc.HasSlot, "halb übertragen");
                Assert.IsFalse(svc.CanContinue);
                StringAssert.Contains("SaveData.bin " + half.Length + " Byte", svc.Problem);
                Assert.Throws<FileNotFoundException>(() => svc.Load());
            }
            finally { SaveTestSupport.Cleanup(dir); }
        }

        [Test]
        public void LooseDropInFileIsImportedAndBrokenSlotIsReplacedWithBackup()
        {
            var dir = SaveTestSupport.NewTempDir();
            try
            {
                var docs = Path.Combine(dir, "Documents");
                var slot = Path.Combine(docs, "Saves", "main");
                Directory.CreateDirectory(slot);
                File.WriteAllBytes(Path.Combine(slot, "SaveData.bin"), new byte[] { 1, 2, 3 });
                var good = NewSave(30, 321).ToBytes();
                File.WriteAllBytes(Path.Combine(docs, "SaveData.bin"), good);

                var svc = new SaveSlotService(docs, "", SaveSlotService.DropInSources(docs));
                Assert.IsFalse(svc.HasSlot);
                Assert.IsTrue(svc.CanContinue, "lose Datei in Documents ist gültige Quelle");
                Assert.AreEqual(321, svc.Load().Money);
                Assert.IsTrue(svc.HasSlot);
                CollectionAssert.AreEqual(good, File.ReadAllBytes(Path.Combine(slot, "SaveData.bin")));
                CollectionAssert.AreEqual(good, File.ReadAllBytes(Path.Combine(docs, "SaveData.bin")), "Quelle bleibt");
                Assert.IsTrue(Directory.Exists(Path.Combine(docs, "Backups", "main")), "kaputter Vorgänger wurde gesichert");
            }
            finally { SaveTestSupport.Cleanup(dir); }
        }

        [Test]
        public void NewDropInReplacesSlotOnceAndKeepsProgressOtherwise()
        {
            var dir = SaveTestSupport.NewTempDir();
            try
            {
                var docs = Path.Combine(dir, "Documents");
                Directory.CreateDirectory(docs);
                var drop = Path.Combine(docs, "SaveData.bin");
                File.WriteAllBytes(drop, NewSave(30, 100).ToBytes());
                var svc = new SaveSlotService(docs, "", SaveSlotService.DropInSources(docs));
                Assert.AreEqual(drop, svc.PendingDropIn);
                var save = svc.Load();
                Assert.AreEqual(100, save.Money);
                StringAssert.Contains("abgelegter Datei", svc.Note);

                save.Money = 555;
                svc.Write(save);
                var again = new SaveSlotService(docs, "", SaveSlotService.DropInSources(docs));
                Assert.AreEqual("", again.PendingDropIn, "gleiche Datei wurde schon importiert");
                Assert.AreEqual(555, again.Load().Money, "Fortschritt bleibt");
                StringAssert.Contains("eigenen Slot", again.Note);

                File.WriteAllBytes(drop, NewSave(30, 200).ToBytes());
                var third = new SaveSlotService(docs, "", SaveSlotService.DropInSources(docs));
                Assert.AreEqual(drop, third.PendingDropIn, "neue Datei ersetzt den Slot");
                Assert.AreEqual(200, third.Load().Money);
                StringAssert.Contains("vorheriger Slot gesichert", third.Note);
                Assert.IsTrue(Directory.GetFiles(Path.Combine(docs, "Backups", "main"), "SaveData.bin", SearchOption.AllDirectories).Length >= 1);
            }
            finally { SaveTestSupport.Cleanup(dir); }
        }

        [Test]
        public void InvalidSourceIsReportedNotUsed()
        {
            var dir = SaveTestSupport.NewTempDir();
            try
            {
                var src = Path.Combine(dir, "SaveData.bin");
                File.WriteAllBytes(src, new byte[100]);
                var svc = new SaveSlotService(Path.Combine(dir, "ablage"), src);
                Assert.IsFalse(svc.CanContinue);
                StringAssert.Contains("Quelle ungültig", svc.Problem);
                Assert.Throws<FileNotFoundException>(() => svc.Load());
            }
            finally { SaveTestSupport.Cleanup(dir); }
        }

        // ---- Info.plist (iPad: Dateien-App/Finder) ----

        const string PlistSample = "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\">\n  <dict>\n    <key>CFBundleName</key>\n    <string>x</string>\n    <key>UIApplicationSceneManifest</key>\n    <dict>\n      <key>A</key>\n      <false />\n    </dict>\n    <key>UIFileSharingEnabled</key>\n    <false />\n  </dict>\n</plist>\n";

        [Test]
        public void InfoPlistPatchAddsReplacesAndIsIdempotent()
        {
            var once = Xnu.Core.InfoPlistPatch.EnableDocumentSharing(PlistSample);
            Assert.IsTrue(Xnu.Core.InfoPlistPatch.HasBool(once, "UIFileSharingEnabled", true), "vorhandenes false wird true");
            Assert.IsTrue(Xnu.Core.InfoPlistPatch.HasBool(once, "LSSupportsOpeningDocumentsInPlace", true), "fehlender Schlüssel wird ergänzt");
            Assert.IsTrue(Xnu.Core.InfoPlistPatch.HasBool(once, "A", false), "verschachtelte Werte bleiben");
            Assert.AreEqual(1, System.Text.RegularExpressions.Regex.Matches(once, "<key>UIFileSharingEnabled</key>").Count);
            Assert.AreEqual(once, Xnu.Core.InfoPlistPatch.EnableDocumentSharing(once));
            Assert.IsTrue(once.TrimEnd().EndsWith("</dict>\n</plist>"));
            Assert.Throws<System.FormatException>(() => Xnu.Core.InfoPlistPatch.SetBool("<plist><array/></plist>", "K", true));
        }

        // ---- Treiber ----

        [Test]
        public void DriverStartsAtTitleAndScriptDrivesTicksWithoutDevices()
        {
            var dir = SaveTestSupport.NewTempDir();
            var go = new GameObject("drv");
            try
            {
                var scriptPath = Path.Combine(dir, "s.txt");
                File.WriteAllText(scriptPath, "wait 3\nlog hallo\ntap A\nwaitstate Field 5\nreport\n");
                var d = go.AddComponent<GameDriver>();
                d.Configure(new GameOptions { SaveRoot = Path.Combine(dir, "ablage"), SaveSource = Path.Combine(dir, "keine-quelle"), ScriptPath = scriptPath }, scriptPath);
                typeof(GameDriver).GetMethod("Start", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic).Invoke(d, null);
                Assert.AreEqual(GameDriver.Phase.Title, d.CurrentPhase);
                Assert.AreEqual("Title", d.StateName);
                Assert.IsNotNull(d.Runner);
                UnityEngine.TestTools.LogAssert.Expect(LogType.Log, "[Game] Skript: hallo");
                for (var i = 0; i < 30; i++) d.Tick(1f / 30f);
                Assert.AreEqual(GameDriver.Phase.Title, d.CurrentPhase, "ohne Spielstand bleibt der Titel stehen");
                Assert.IsTrue(d.Runner.Finished);
                Assert.AreEqual(1, d.Runner.Timeouts);
                Assert.AreEqual(30, d.Ticks);
                Assert.IsTrue(d.Battle.IsBuilt);
                Assert.IsNotNull(d.Textbox);
            }
            finally
            {
                Object.DestroyImmediate(go);
                SaveTestSupport.Cleanup(dir);
            }
        }
    }
}
