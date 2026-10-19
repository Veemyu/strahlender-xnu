using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Battle.Flow;
using Xnu.Data;
using Xnu.EvScript;
using Xnu.Game;
using Xnu.PokePara;
using static Xnu.Tests.EvB;
using static Xnu.Tests.GameFixture;

namespace Xnu.Tests
{
    // Szenario-Tests des Spielkerns (Xnu.Game) mit erfundenen Daten: Skript -> Host -> Spielstand/Kampf/Feld, ohne Unity und ohne Spieldaten.
    public class GameFlowTests
    {
        const int PlayerName = 306, GetMySex = 479, PcKaifuku = 480, AddPokemon = 218, FirstBtlSet = 403, WildBtlSet = 401, FirstPokeSelect = 259,
            FirstPokeNoGet = 326, SetWarpId = 478, EventStart = 155, EventEnd = 157, ObjAdd = 146, ObjDel = 147, SePlay = 109, BlackOut = 283, FadeWait = 784,
            TemotiPokeChk = 563, GetPokeCount = 522, PlayerPosGet = 158, ItemName = 310, NumberName = 314, BadgeCount = 450, BadgeGet = 448, GetNowZone = 290;

        static void Press(World w, int times = 1)
        {
            for (var i = 0; i < times; i++) w.Loop.Tick(1f / 30f, GameInput.Press());
        }

        // ---- Text, Namen, Auswahl ----

        [Test]
        public void TalkShowsComposedPagesAndAdvancesWithConfirm()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.TalkMsg, b.S("dp_scenario3%two_pages"), F(1)), C(EvCmdId.TalkClose), C(EvCmdId.End));
            var w = NewWorld(b);
            Assert.IsTrue(w.Loop.StartEvent("t"));
            Assert.AreEqual(GameState.Event, w.Loop.State);
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.IsTrue(w.Loop.Host.Dialog.IsOpen);
            Assert.AreEqual(2, w.Loop.Host.Dialog.PageCount);
            Assert.AreEqual("Seite eins", w.Loop.Host.Dialog.CurrentPage);
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(0, w.Loop.Host.Dialog.PageIndex, "ohne Taste bleibt die Seite stehen");
            Press(w);
            Assert.AreEqual("Seite zwei", w.Loop.Host.Dialog.CurrentPage);
            Assert.AreEqual(GameState.Event, w.Loop.State);
            Press(w);
            Assert.AreEqual(GameState.Field, w.Loop.State);
            Assert.IsFalse(w.Loop.Host.Dialog.IsOpen);
            Assert.AreEqual(1, w.Loop.EventsFinished);
        }

        [Test]
        public void NameWordsReachTheMessage()
        {
            var b = new FileBuilder();
            b.Script("t", C(PlayerName, F(0)), C(EvCmdId.TalkMsg, b.S("dp_scenario3%hello_name"), F(1)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual("Hallo Tester!", w.Loop.Host.Dialog.CurrentPage);
        }

        [Test]
        public void ItemNameAndNumberWordsUseMessageBankAndWork()
        {
            var b = new FileBuilder();
            b.Script("t", C(ItemName, F(1), F(17), F(1)), C(NumberName, F(2), F(1234)), C(EvCmdId.YesNoWin, W(10)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual("Trank", w.Session.Words.Get(1).Text);
            Assert.AreEqual(1234, w.Session.Words.Get(2).Number);
        }

        [Test]
        public void YesNoWindowStoresChosenIndexInWork()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.YesNoWin, W(10), F(1)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.IsTrue(w.Loop.Host.Choice.IsOpen);
            w.Loop.Tick(1f / 30f, new GameInput { Down = true, Replacement = -1, StarterChoice = -1 });
            Assert.AreEqual(1, w.Loop.Host.Choice.Cursor);
            Press(w);
            Assert.AreEqual(1, w.Session.Vars.GetWork(10));
            Assert.AreEqual(GameState.Field, w.Loop.State);
        }

        [Test]
        public void CustomWindowMapsCursorToReturnValue()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.AddCustumWinLabel, b.S("dp_scenario3%opt_a"), F(7)), C(EvCmdId.AddCustumWinLabel, b.S("dp_scenario3%opt_b"), F(9)),
                C(EvCmdId.OpenCustumWin, W(11)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            CollectionAssert.AreEqual(new[] { "A", "B" }, w.Loop.Host.Choice.Labels);
            w.Loop.Tick(1f / 30f, new GameInput { Down = true, Replacement = -1, StarterChoice = -1 });
            Press(w);
            Assert.AreEqual(9, w.Session.Vars.GetWork(11));
        }

        // ---- Spielstand: Work, Flags, Beutel, Geld, Team ----

        [Test]
        public void ScriptChangesSaveBytesForWorkFlagsItemsAndMoney()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.LdVal, W(20), F(5)), C(EvCmdId.FlagSet, FL(100)), C(EvCmdId.SetSysFlag, SF(0x7C)), C(EvCmdId.SetSysFlag, SF(0x7D)),
                C(EvCmdId.AddItem, F(17), F(3), W(21)), C(EvCmdId.SubItem, F(17), F(1), W(22)), C(EvCmdId.AddGold, F(500)), C(EvCmdId.SubGold, F(100)),
                C(BadgeCount, W(23)), C(BadgeGet, SF(0x7C), W(24)), C(GetNowZone, W(25)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Session.ZoneId = 425;
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(GameState.Field, w.Loop.State);
            var v = w.Session.Vars;
            Assert.AreEqual(5, v.GetWork(20));
            Assert.IsTrue(v.GetFlag(100));
            Assert.AreEqual(2, w.Session.GetItemCount(17));
            Assert.AreEqual(1400, w.Session.Money);
            Assert.AreEqual(2, v.GetWork(23));
            Assert.AreEqual(1, v.GetWork(24));
            Assert.AreEqual(425, v.GetWork(25));
            Assert.AreEqual(2, w.Session.BadgeCount);
            // Alles liegt im Save-Puffer und überlebt Speichern und Neuladen.
            var reload = SaveDataRoundTrip(w.Session);
            Assert.AreEqual(5, reload.GetWork(20));
            Assert.IsTrue(reload.GetFlag(100));
        }

        static EvSaveVariables SaveDataRoundTrip(GameSession s) => new EvSaveVariables(Xnu.Save.SaveData.FromBytes(s.Save.ToBytes()));

        [Test]
        public void ItemCountIsCappedAt999AndMoneyIsClamped()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.AddItem, F(17), F(998), W(1)), C(EvCmdId.AddItemChk, F(17), F(5), W(2)), C(EvCmdId.AddGold, F(2000000)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(998, w.Session.GetItemCount(17));
            Assert.AreEqual(0, w.Session.Vars.GetWork(2));
            Assert.AreEqual(999999, w.Session.Money);
        }

        [Test]
        public void AddPokemonAppendsToPartyAndReportsResult()
        {
            var b = new FileBuilder();
            b.Script("t", C(AddPokemon, F(BattleFlowTestData.Mon2), F(5), F(0), W(30)), C(TemotiPokeChk, W(31), F(BattleFlowTestData.Mon2)),
                C(TemotiPokeChk, W(32), F(BattleFlowTestData.Mon4)), C(GetPokeCount, W(33)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            var v = w.Session.Vars;
            Assert.AreEqual(1, v.GetWork(30));
            Assert.AreEqual(1, v.GetWork(31));
            Assert.AreEqual(0, v.GetWork(32));
            Assert.AreEqual(2, v.GetWork(33));
            Assert.AreEqual(BattleFlowTestData.Mon2, w.Session.GetPartyMember(1).Core.SpeciesNo);
            Assert.AreEqual(5, w.Session.GetPartyMember(1).Level);
        }

        [Test]
        public void FullPartyRefusesNewMember()
        {
            var w = NewWorld(new FileBuilder());
            for (var i = 0; i < 5; i++) Assert.IsTrue(w.Session.AddPartyMember(w.Session.CreateOwnPokemon(BattleFlowTestData.Mon2, 5, 0)));
            Assert.AreEqual(6, w.Session.PartyCount);
            Assert.IsFalse(w.Session.AddPartyMember(w.Session.CreateOwnPokemon(BattleFlowTestData.Mon2, 5, 0)));
        }

        [Test]
        public void PokeCenterHealsHpAndPp()
        {
            var b = new FileBuilder();
            b.Script("t", C(PcKaifuku), C(EvCmdId.End));
            var w = NewWorld(b);
            var p = w.Session.GetPartyMember(0);
            var maxHp = p.MaxHp;
            p.Core.CurrentHp = 1;
            p.Core.SetPp(0, 1);
            w.Session.Save.SetPartyMember(0, p);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            var healed = w.Session.GetPartyMember(0);
            Assert.AreEqual(maxHp, healed.Core.CurrentHp);
            Assert.AreEqual(35, healed.Core.GetPp(0));
        }

        [Test]
        public void GetMySexFlipsTheStoredByte()
        {
            var b = new FileBuilder();
            b.Script("t", C(GetMySex, W(40)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(1, w.Session.Vars.GetWork(40));
        }

        // ---- Kämpfe ----

        [Test]
        public void TrainerBattleRunsInsideEventAndPaysPrizeMoney()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.TrainerBtlSet, b.S("RIVAL_01")), C(EvCmdId.FlagSet, FL(200)), C(EvCmdId.End));
            var w = NewWorld(b, trainers: new[] { Trainer(5, BattleFlowTestData.Mon2, 2, gold: 30) });
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(GameState.Battle, w.Loop.State);
            Assert.IsFalse(w.Session.Vars.GetFlag(200), "Skript pausiert, bis der Kampf zu Ende ist");
            Run(w);
            Assert.AreEqual(BattleResult.Win, w.Loop.LastOutcome.Result);
            Assert.AreEqual(30 * 2 * 4, w.Loop.LastOutcome.PrizeMoney);
            Assert.AreEqual(1000 + 240, w.Session.Money);
            Assert.IsTrue(w.Session.Vars.GetFlag(200), "Skript läuft nach dem Kampf weiter");
            Assert.AreEqual(GameState.Field, w.Loop.State);
            Assert.AreEqual(1, w.Loop.BattlesFinished);
        }

        [Test]
        public void BattleWritesExperienceAndHpBackIntoTheSave()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.TrainerBtlSet, b.S("RIVAL_01")), C(EvCmdId.End));
            var w = NewWorld(b, partyLevel: 5, trainers: new[] { Trainer(5, BattleFlowTestData.Mon2, 5) });
            var before = w.Session.GetPartyMember(0).Core.Exp;
            w.Loop.StartEvent("t");
            Run(w);
            Assert.AreEqual(BattleResult.Win, w.Loop.LastOutcome.Result);
            Assert.Greater(w.Session.GetPartyMember(0).Core.Exp, before);
        }

        [Test]
        public void LosingReturnsToWipeoutZoneHealsAndTakesMoney()
        {
            var b = new FileBuilder();
            b.Script("t", C(SetWarpId, F(425)), C(EvCmdId.TrainerBtlSet, b.S("RIVAL_01")), C(EvCmdId.FlagSet, FL(201)), C(EvCmdId.End));
            var w = NewWorld(b, partyLevel: 2, trainers: new[] { Trainer(5, BattleFlowTestData.Mon3, 60) });
            w.Session.ZoneId = 600;
            w.Loop.StartEvent("t");
            w.Player.Run(w.Loop, l => l.Wipeouts > 0, 3000);
            Assert.AreEqual(1, w.Loop.Wipeouts);
            Assert.AreEqual(GameState.Field, w.Loop.State);
            Assert.IsFalse(w.Loop.Interpreter.IsRunning, "Ereignis abgebrochen");
            Assert.IsFalse(w.Session.Vars.GetFlag(201), "Skript läuft nach einer Niederlage nicht weiter");
            Assert.AreEqual(425, w.Session.ZoneId);
            Assert.AreEqual(425, w.Field.Zone);
            Assert.AreEqual(1000 - 2 * 2 * 4, w.Session.Money, "höchste Stufe 2 x Tabelle[0] x 4");
            var p = w.Session.GetPartyMember(0);
            Assert.AreEqual(p.MaxHp, p.Core.CurrentHp, "Team geheilt");
        }

        [Test]
        public void MissingTrainerSkipsBattleInsteadOfHanging()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.TrainerBtlSet, b.S("UNKNOWN")), C(EvCmdId.FlagSet, FL(202)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Player.Run(w.Loop, l => l.EventsFinished > 0, 50);
            Assert.AreEqual(1, w.Loop.BattlesSkipped);
            Assert.IsTrue(w.Session.Vars.GetFlag(202));
        }

        [Test]
        public void FirstBattleWaitsForStarterChoiceThenFightsWildMon()
        {
            var b = new FileBuilder();
            b.Script("t", C(FirstPokeSelect), C(FirstPokeNoGet, W(50)), C(AddPokemon, W(50), F(5), F(0), W(51)), C(FirstBtlSet, F(BattleFlowTestData.Mon3), F(2)), C(EvCmdId.FlagSet, FL(203)),
                C(EvCmdId.End));
            var w = NewWorld(b, partyLevel: 30);
            w.Session.StarterSpecies = new[] { Starter0, Starter1, Starter2 };
            w.Loop.StartEvent("t");
            for (var i = 0; i < 5; i++) w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(GameState.Event, w.Loop.State, "ohne Wahl wartet die Demo");
            Assert.AreEqual(0, w.Session.DefaultPokeNo);
            w.Loop.Tick(1f / 30f, GameInput.Starter(1));
            Assert.AreEqual(Starter1, w.Session.DefaultPokeNo);
            Assert.AreEqual(Starter1, w.Session.Vars.GetWork(50));
            Assert.AreEqual(GameState.Battle, w.Loop.State);
            Assert.IsTrue(w.Loop.Battle.Request.Tutorial);
            Assert.AreEqual(2, w.Session.PartyCount);
            Run(w);
            Assert.AreEqual(BattleResult.Win, w.Loop.LastOutcome.Result);
            Assert.AreEqual(0, w.Loop.LastOutcome.PrizeMoney, "Wildkampf zahlt nichts");
            Assert.IsTrue(w.Session.Vars.GetFlag(203));
        }

        [Test]
        public void WildBattleCommandUsesGivenSpeciesAndLevel()
        {
            var b = new FileBuilder();
            b.Script("t", C(WildBtlSet, F(BattleFlowTestData.Mon4), F(7)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(GameState.Battle, w.Loop.State);
            var enemy = w.Loop.Battle.Engine.Active(BattleEngine.EnemySide);
            Assert.AreEqual(BattleFlowTestData.Mon4, enemy.Poke.MonsNo);
            Assert.AreEqual(7, enemy.Level);
        }

        // ---- Feld, Warps, Begegnungen, Menü ----

        [Test]
        public void MapChangeResolvesZoneNameAndWaitsForField()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.MapChange, b.S("T01R0201"), F(3)), C(EvCmdId.FlagSet, FL(204)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Field.WaitPolls = 2;
            w.Session.ZoneId = 600;
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(425, w.Field.Zone);
            Assert.AreEqual(425, w.Session.ZoneId);
            Assert.AreEqual(600, w.Session.BeforeZoneId);
            Assert.IsFalse(w.Session.Vars.GetFlag(204));
            for (var i = 0; i < 5; i++) w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.IsTrue(w.Session.Vars.GetFlag(204));
        }

        [Test]
        public void EventFrameObjectsFadeAndSoundGoThroughHost()
        {
            var b = new FileBuilder();
            b.Script("t", C(EventStart), C(SePlay, b.S("S_X")), C(ObjAdd, b.S("OBJ_A")), C(ObjDel, b.S("OBJ_B")), C(BlackOut), C(FadeWait), C(PlayerPosGet, W(60), W(61)), C(EventEnd), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Field.GridX = 12;
            w.Field.GridZ = 34;
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(GameState.Field, w.Loop.State);
            Assert.AreEqual(12, w.Session.Vars.GetWork(60));
            Assert.AreEqual(34, w.Session.Vars.GetWork(61));
            Assert.IsTrue(w.Field.Visible.Contains("OBJ_A"));
            Assert.IsFalse(w.Field.Visible.Contains("OBJ_B"));
            Assert.IsFalse(w.Field.EventMode);
            Assert.AreEqual(0, w.Loop.Host.GapCommandCalls);
            CollectionAssert.Contains(w.Field.Log, "fade black out");
        }

        [Test]
        public void UnknownHostCommandsAreCountedAsGapsAndDoNotBlock()
        {
            var b = new FileBuilder();
            b.Script("t", C(1234), C(EvCmdId.FlagSet, FL(205)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(1, w.Loop.Host.GapCommandCalls);
            Assert.AreEqual(1, w.Loop.Host.Gaps[1234]);
            Assert.IsTrue(w.Session.Vars.GetFlag(205));
        }

        [Test]
        public void FieldSignalsStartEventsAndWarps()
        {
            var b = new FileBuilder();
            b.Script("talk_01", C(EvCmdId.FlagSet, FL(206)), C(EvCmdId.End));
            var w = NewWorld(b);
            w.Loop.Tick(1f / 30f, GameInput.None, FieldSignal.Talk("talk_01"));
            Assert.AreEqual(GameState.Event, w.Loop.State);
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(GameState.Field, w.Loop.State);
            Assert.IsTrue(w.Session.Vars.GetFlag(206));
            w.Loop.Tick(1f / 30f, GameInput.None, FieldSignal.Warp(77, 2));
            Assert.AreEqual(77, w.Session.ZoneId);
            Assert.AreEqual(77, w.Field.Zone);
            w.Loop.Tick(1f / 30f, GameInput.None, FieldSignal.Talk("gibt_es_nicht"));
            Assert.AreEqual(1, w.Loop.MissingLabels);
            Assert.AreEqual(GameState.Field, w.Loop.State);
        }

        [Test]
        public void GrassStepStartsWildBattleFromEncounterTable()
        {
            var zone = new ZoneEncounterRecord
            {
                ZoneId = 354, GrassRate = 100,
                Grass = Enumerable.Range(0, 12).Select(i => new EncounterSlot { MonsNo = BattleFlowTestData.Mon4, MinLevel = 3, MaxLevel = 5 }).ToArray(),
            };
            var w = NewWorld(new FileBuilder(), zones: new[] { zone });
            w.Loop.Tick(1f / 30f, GameInput.None, FieldSignal.Step(354, EncounterKind.Grass));
            Assert.AreEqual(GameState.Battle, w.Loop.State);
            var enemy = w.Loop.Battle.Engine.Active(BattleEngine.EnemySide);
            Assert.AreEqual(BattleFlowTestData.Mon4, enemy.Poke.MonsNo);
            Assert.That(enemy.Level, Is.InRange(3, 5));
            Run(w, 2000);
            w.Player.Run(w.Loop, l => l.State == GameState.Field, 2000);
            Assert.AreEqual(GameState.Field, w.Loop.State);
            Assert.AreEqual(1, w.Loop.BattlesFinished);
        }

        [Test]
        public void StepWithoutTableOrZeroRateStartsNothing()
        {
            var zone = new ZoneEncounterRecord { ZoneId = 1, GrassRate = 0, Grass = new[] { new EncounterSlot { MonsNo = 1, MinLevel = 2, MaxLevel = 2 } } };
            var w = NewWorld(new FileBuilder(), zones: new[] { zone });
            for (var i = 0; i < 50; i++) w.Loop.Tick(1f / 30f, GameInput.None, FieldSignal.Step(1, EncounterKind.Grass));
            for (var i = 0; i < 50; i++) w.Loop.Tick(1f / 30f, GameInput.None, FieldSignal.Step(999, EncounterKind.Grass));
            Assert.AreEqual(GameState.Field, w.Loop.State);
            Assert.AreEqual(0, w.Loop.BattlesStarted);
        }

        [Test]
        public void EncounterSlotWeightsAreDeterministicAndCoverAllSlots()
        {
            Assert.AreEqual(100, EncounterService.GrassWeights.Sum());
            var rng = new Xnu.Battle.BattleRandom(5);
            var hits = new int[12];
            for (var i = 0; i < 20000; i++) hits[EncounterService.PickSlot(EncounterService.GrassWeights, 12, rng)]++;
            Assert.IsTrue(hits.All(h => h > 0));
            Assert.Greater(hits[0], hits[6]);
            Assert.Greater(hits[6], hits[11]);
        }

        [Test]
        public void MenuOpensAndClosesOnlyFromField()
        {
            var w = NewWorld(new FileBuilder());
            w.Loop.Tick(1f / 30f, new GameInput { Menu = true, Replacement = -1, StarterChoice = -1 });
            Assert.AreEqual(GameState.Menu, w.Loop.State);
            w.Loop.Tick(1f / 30f, new GameInput { Cancel = true, Replacement = -1, StarterChoice = -1 });
            Assert.AreEqual(GameState.Field, w.Loop.State);
        }

        [Test]
        public void EventCannotStartWhileInBattle()
        {
            var b = new FileBuilder();
            b.Script("t", C(EvCmdId.TrainerBtlSet, b.S("RIVAL_01")), C(EvCmdId.End));
            b.Script("other", C(EvCmdId.End));
            var w = NewWorld(b, trainers: new[] { Trainer(5, BattleFlowTestData.Mon2, 2) });
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(GameState.Battle, w.Loop.State);
            Assert.IsFalse(w.Loop.StartEvent("other"));
        }

        // ---- Katalog ----

        [Test]
        public void EveryCatalogEntryIsAHostCommandOfTheInterpreter()
        {
            foreach (var id in HostCommands.Table.Keys)
                Assert.AreEqual(EvCmdKind.Host, EvCommandTable.Classify(id), "Kennung " + id + " ist kein Host-Befehl");
        }

        [Test]
        public void CatalogCountsAreConsistent()
        {
            var all = HostCommands.Count();
            Assert.AreEqual(all, HostCommands.Count(HostEvidence.P) + HostCommands.Count(HostEvidence.A) + HostCommands.Count(HostEvidence.N));
            Assert.Greater(HostCommands.Count(HostEvidence.P), 25);
            Assert.Greater(HostCommands.Count(kind: HostKind.Sound), 10);
        }
    }
}
