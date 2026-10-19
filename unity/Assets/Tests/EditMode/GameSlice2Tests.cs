using System;
using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Data;
using Xnu.EvScript;
using Xnu.Game;
using Xnu.PokePara;
using Xnu.Text;
using static Xnu.Tests.EvB;
using static Xnu.Tests.GameFixture;

namespace Xnu.Tests
{
    // Szenario-Tests der Host-Befehle von Scheibe 2 (erfundene Daten, keine Spielinhalte).
    public class GameSlice2Tests
    {
        const int GetPokeCount = 522, GetPokeCount2 = 523, GetPokeCount3 = 524, PokecenPutBall = 979, PokecenClearBall = 980, PcRecoverAnm = 663, ChkPokeWaza = 221,
            WazaCount = 571, WazaDel = 572, GetNatsuki = 557, AddNatsuki = 558, ChkRibbon = 654, SetRibbon = 655, GetPoketch = 417, GetPoketchFlag = 418,
            SysFlagBadgeSet = 449, SysFlagGameClearGet = 459, ChkWeek = 658, GetNowHour = 702, GetRandomHit = 734, BicycleCheck = 293, BicycleReq = 294, Naminori = 292,
            NaminoriEnd = 884, SetTeleportId = 1186, EyeTrainerIdGet = 276, TrainerIdGet = 334, TrainerTalkTypeGet = 338, NameInPoke = 278, WazaName = 313,
            PartyMonsnoCheck = 696, CountMonsboxSpace = 683, AddTamago = 219, LdvalVersion = 840, SxyMvChange = 505, ObjAdd = 146, ObjDel = 147, Record = 612, DendouNumGet = 236,
            CbItemAdd = 216, CbItemGet = 215, AusuItemCheck = 747, DebugPrint = 782, BtwrSubGetRank = 1031;

        static World NewW(Action<FileBuilder> script, int partyLevel = 30)
        {
            var b = new FileBuilder();
            script(b);
            return NewWorld(b, partyLevel);
        }

        static void RunToEnd(World w, string label = "t")
        {
            Assert.IsTrue(w.Loop.StartEvent(label));
            for (var i = 0; i < 400 && w.Loop.State == GameState.Event; i++) w.Loop.Tick(1f / 30f, w.Player.Next(w.Loop));
            Assert.AreEqual(GameState.Field, w.Loop.State, "Ereignis endet");
            Assert.AreEqual(EvStatus.Ended, w.Loop.LastEventStatus);
        }

        static PokemonParam Mon(int level = 20) => BattleFlowTestData.Mon(GameFixture.Battle, BattleFlowTestData.Mon1, level, BattleFlowTestData.Tackle);

        static void SetParty(World w, params PokemonParam[] members) => w.Session.Save.SetParty(new List<PokemonParam>(members));

        // ---- Team: Zählungen (Korrektur: 523 zählt Nicht-Eier, nicht die Teamgröße) ----

        [Test]
        public void PokeCountVariantsDistinguishEggsAndFainted()
        {
            var w = NewW(b => b.Script("t", C(GetPokeCount, W(10)), C(GetPokeCount2, W(11)), C(GetPokeCount3, W(12)), C(EvCmdId.End)));
            var egg = Mon();
            egg.Core.IsEgg = true;
            var fainted = Mon();
            fainted.Core.CurrentHp = 0;
            SetParty(w, Mon(), egg, fainted, Mon());
            RunToEnd(w);
            Assert.AreEqual(4, w.Session.Vars.GetWork(10), "522: Teamgröße");
            Assert.AreEqual(3, w.Session.Vars.GetWork(11), "523: ohne Eier");
            Assert.AreEqual(2, w.Session.Vars.GetWork(12), "524: ohne Eier, KP ≠ 0");
        }

        [Test]
        public void PokecenterAnimationPlacesOneBallPerNonEggMember()
        {
            var w = NewW(b => b.Script("t", C(GetPokeCount2, W(10)), C(PokecenPutBall, F(0)), C(PokecenPutBall, F(1)), C(PcRecoverAnm, W(10)), C(PcRecoverAnm, W(10)), C(EvCmdId.End)));
            var egg = Mon();
            egg.Core.IsEgg = true;
            var second = Mon();
            second.Core.Ball = 5;
            var first = Mon();
            first.Core.Ball = 3;
            SetParty(w, first, egg, second);
            RunToEnd(w);
            Assert.AreEqual(2, w.Session.Vars.GetWork(10));
            CollectionAssert.AreEqual(new[] { 3, 5 }, w.Session.World.PokecenterBalls);
            Assert.AreEqual(2, w.Session.World.HealEffectCalls);
        }

        [Test]
        public void ClearBallEmptiesTheTray()
        {
            var w = NewW(b => b.Script("t", C(PokecenPutBall, F(0)), C(PokecenClearBall), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(0, w.Session.World.PokecenterBalls.Count);
        }

        [Test]
        public void MoveQueriesAndDeletionWorkOnPartyAndBox()
        {
            var w = NewW(b => b.Script("t", C(ChkPokeWaza, W(10), F(BattleFlowTestData.Tackle), F(0), F(-1)), C(WazaCount, W(11), F(0), F(-1)),
                C(WazaDel, F(0), F(0), F(-1)), C(WazaCount, W(12), F(0), F(-1)), C(ChkPokeWaza, W(13), F(BattleFlowTestData.Tackle), F(0), F(-1)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(1, w.Session.Vars.GetWork(10));
            Assert.AreEqual(1, w.Session.Vars.GetWork(11));
            Assert.AreEqual(0, w.Session.Vars.GetWork(12));
            Assert.AreEqual(0, w.Session.Vars.GetWork(13));
        }

        [Test]
        public void FriendshipRibbonAndSpeciesChecks()
        {
            var w = NewW(b => b.Script("t", C(GetNatsuki, W(10), F(0)), C(AddNatsuki, F(0), F(300)), C(GetNatsuki, W(11), F(0)), C(AddNatsuki, F(0), F(-1000)), C(GetNatsuki, W(12), F(0)),
                C(SetRibbon, F(0), F(7)), C(ChkRibbon, W(13), F(0), F(7)), C(ChkRibbon, W(14), F(0), F(8)),
                C(PartyMonsnoCheck, F(BattleFlowTestData.Mon1), W(15)), C(PartyMonsnoCheck, F(BattleFlowTestData.Mon2), W(16)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(255, w.Session.Vars.GetWork(11), "Obergrenze 255");
            Assert.AreEqual(0, w.Session.Vars.GetWork(12), "Untergrenze 0");
            Assert.AreEqual(1, w.Session.Vars.GetWork(13));
            Assert.AreEqual(0, w.Session.Vars.GetWork(14));
            Assert.AreEqual(1, w.Session.Vars.GetWork(15));
            Assert.AreEqual(0, w.Session.Vars.GetWork(16));
        }

        [Test]
        public void EggCreationAddsAnEggWithBallFour()
        {
            var w = NewW(b => b.Script("t", C(AddTamago, F(BattleFlowTestData.Mon2), F(0)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(2, w.Session.PartyCount);
            var egg = w.Session.GetPartyMember(1);
            Assert.IsTrue(egg.Core.IsEgg);
            Assert.AreEqual(4, egg.Core.Ball);
        }

        [Test]
        public void BoxFullFlagIsOneWithoutSpace()
        {
            var w = NewW(b => b.Script("t", C(CountMonsboxSpace, W(10)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(w.Session.BoxSpaceCount() < 1 ? 1 : 0, w.Session.Vars.GetWork(10));
        }

        // ---- Flags, Systemflags, Zeit ----

        [Test]
        public void PoketchAndSystemFlagCommands()
        {
            var w = NewW(b => b.Script("t", C(GetPoketchFlag, W(10)), C(GetPoketch), C(GetPoketchFlag, W(11)), C(SysFlagBadgeSet, SF(0x7C)), C(SysFlagGameClearGet, W(12)),
                C(Record, F(1)), C(Record, F(1)), C(DendouNumGet, W(13)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(0, w.Session.Vars.GetWork(10));
            Assert.AreEqual(1, w.Session.Vars.GetWork(11));
            Assert.IsTrue(w.Session.Vars.GetFlag(WorldState.PoketchFlag));
            Assert.AreEqual(1, w.Session.BadgeCount);
            Assert.AreEqual(0, w.Session.Vars.GetWork(12));
            Assert.AreEqual(2, w.Session.Vars.GetWork(13));
        }

        [Test]
        public void ClockWorkGivesWeekdayAndHour()
        {
            var w = NewW(b => b.Script("t", C(ChkWeek, W(10)), C(GetNowHour, W(11)), C(EvCmdId.End)));
            w.Session.World.Clock = () => new DateTime(2026, 10, 21, 13, 45, 0);   // Mittwoch
            RunToEnd(w);
            Assert.AreEqual(3, w.Session.Vars.GetWork(10));
            Assert.AreEqual(13, w.Session.Vars.GetWork(11));
            Assert.AreEqual(1, GameSession.PeriodForHour(13));
            Assert.AreEqual(3, GameSession.PeriodForHour(2));
        }

        [Test]
        public void RandomHitIsNeverAtZeroAndAlwaysAtHundred()
        {
            var w = NewW(b => b.Script("t", C(GetRandomHit, F(0), W(10)), C(GetRandomHit, F(100), W(11)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(0, w.Session.Vars.GetWork(10));
            Assert.AreEqual(1, w.Session.Vars.GetWork(11));
        }

        [Test]
        public void CmpWkComparesWorkOfWork()
        {
            var w = NewW(b => b.Script("t", C(EvCmdId.LdVal, W(20), F(30)), C(EvCmdId.LdVal, W(21), F(31)), C(EvCmdId.LdVal, W(30), F(5)), C(EvCmdId.LdVal, W(31), F(9)),
                C(EvCmdId.CmpWk, W(20), W(21)), C(EvCmdId.IfJump, b.S("LT"), b.S("less")), C(EvCmdId.LdVal, W(40), F(1)), C(EvCmdId.End))
                .Script("less", C(EvCmdId.LdVal, W(40), F(2)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(2, w.Session.Vars.GetWork(40), "Work[Work[20]] = 5 < Work[Work[21]] = 9");
        }

        [Test]
        public void CaseCancelJumpsWhenWorkAEqualsWorkF8()
        {
            var w = NewW(b => b.Script("t", C(EvCmdId.LdVal, W(0xF2), F(4)), C(EvCmdId.LdVal, W(0xF8), F(4)), C(EvCmdId.CaseCancel, b.S("cancel")), C(EvCmdId.LdVal, W(40), F(1)), C(EvCmdId.End))
                .Script("cancel", C(EvCmdId.LdVal, W(40), F(2)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(2, w.Session.Vars.GetWork(40));
        }

        [Test]
        public void VersionLoadPicksArgumentByCassette()
        {
            var w = NewW(b => b.Script("t", C(LdvalVersion, F(11), F(22)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(11, w.Session.Vars.GetWork(0xEE));
            w.Session.World.CassetteVersion = 11;
            RunToEnd(w);
            Assert.AreEqual(22, w.Session.Vars.GetWork(0xEE));
        }

        // ---- Fortbewegung, Objekte, Warp ----

        [Test]
        public void BicycleAndSwimStateAreTracked()
        {
            var w = NewW(b => b.Script("t", C(BicycleCheck, W(10)), C(BicycleReq, F(1)), C(BicycleCheck, W(11)), C(Naminori), C(BicycleCheck, W(12)), C(NaminoriEnd), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(0, w.Session.Vars.GetWork(10));
            Assert.AreEqual(1, w.Session.Vars.GetWork(11));
            Assert.AreEqual(0, w.Session.Vars.GetWork(12), "Surfen löst das Rad");
            Assert.IsFalse(w.Session.World.Swimming);
            Assert.AreEqual(1, w.Field.VisualIds[BicycleReq]);
        }

        [Test]
        public void ObjectVisibilityAndMoveCodeAreRemembered()
        {
            var w = NewW(b => b.Script("t", C(ObjAdd, b.S("NPC_A")), C(ObjAdd, b.S("NPC_B")), C(ObjDel, b.S("NPC_B")), C(SxyMvChange, b.S("NPC_A"), F(9)), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.IsTrue(w.Session.World.ObjectVisible["NPC_A"]);
            Assert.IsFalse(w.Session.World.ObjectVisible["NPC_B"]);
            Assert.AreEqual(9, w.Session.World.ObjectMoveCode["NPC_A"]);
        }

        [Test]
        public void TeleportIdSetsZoneForTeleport()
        {
            var w = NewW(b => b.Script("t", C(SetTeleportId, F(425), F(3)), C(935), C(EvCmdId.End)));
            RunToEnd(w);
            Assert.AreEqual(425, w.Session.ZoneId);
            Assert.AreEqual(425, w.Field.Zone);
        }

        // ---- Trainer ----

        [Test]
        public void EyeTrainerQueries()
        {
            var w = NewW(b => b.Script("t", C(TrainerIdGet, W(10)), C(EyeTrainerIdGet, F(1), W(11)), C(EvCmdId.End)));
            w.Session.World.EyeTrainerIds.AddRange(new[] { 5, 6 });
            RunToEnd(w);
            Assert.AreEqual(5, w.Session.Vars.GetWork(10));
            Assert.AreEqual(6, w.Session.Vars.GetWork(11));
        }

        [Test]
        public void TrainerTalkTypeDependsOnFightType()
        {
            var tr = Trainer(5, BattleFlowTestData.Mon2, 10);
            var b = new FileBuilder();
            b.Script("t", C(TrainerTalkTypeGet, W(10), W(11), W(12)), C(EvCmdId.End));
            var w = NewWorld(b, trainers: new[] { tr });
            w.Session.World.EyeTrainerIds.Add(5);
            RunToEnd(w);
            Assert.AreEqual(0, w.Session.Vars.GetWork(10));
            Assert.AreEqual(2, w.Session.Vars.GetWork(11));
            Assert.AreEqual(0, w.Session.Vars.GetWork(12));
        }

        // ---- Namen, Eingabe ----

        [Test]
        public void MoveNameWordComesFromTheMessageFile()
        {
            var w = NewW(b => b.Script("t", C(WazaName, F(1), F(33)), C(EvCmdId.YesNoWin, W(10)), C(EvCmdId.End)));
            var file = new MsbtFile { Name = "german_ss_wazaname", LanguageId = 5 };
            file.Labels.Add(new MsbtLabel { LabelIndex = 0, ArrayIndex = 0, Name = "WAZANAME_033", Words = new[] { new MsbtWord { Pattern = WordPattern.Str, Text = "Testattacke", Event = MessageEvent.End } } });
            w.Session.Data.Messages.Add(file);
            w.Loop.StartEvent("t");
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual("Testattacke", w.Session.Words.Get(1).Text);
        }

        [Test]
        public void NicknameInputUsesTextOfTheInput()
        {
            var w = NewW(b => b.Script("t", C(NameInPoke, F(0), F(-1), W(10)), C(EvCmdId.End)));
            Assert.IsTrue(w.Loop.StartEvent("t"));
            w.Loop.Tick(1f / 30f, GameInput.None);
            Assert.AreEqual(GameState.Event, w.Loop.State, "wartet auf die Eingabe");
            var input = GameInput.None;
            input.Text = "Blitz";
            w.Loop.Tick(1f / 30f, input);
            Assert.AreEqual(GameState.Field, w.Loop.State);
            Assert.AreEqual("Blitz", w.Session.GetPartyMember(0).Core.Nickname);
            Assert.IsTrue(w.Session.GetPartyMember(0).Core.HasNickname);
            Assert.AreEqual(1, w.Session.Vars.GetWork(10));
        }

        // ---- Zustand, Läden und Katalog ----

        [Test]
        public void BallSealsAndItemRangeChecks()
        {
            var w = NewW(b => b.Script("t", C(CbItemAdd, F(5), F(3)), C(CbItemGet, W(20), W(10)), C(AusuItemCheck, F(0x12A), W(11)), C(AusuItemCheck, F(0x13A), W(12)), C(EvCmdId.End)));
            w.Session.Vars.SetWork(20, 5);
            RunToEnd(w);
            Assert.AreEqual(3, w.Session.Vars.GetWork(10));
            Assert.AreEqual(1, w.Session.Vars.GetWork(11));
            Assert.AreEqual(0, w.Session.Vars.GetWork(12));
        }

        [Test]
        public void FixedShopBuyAndSellSettleMoneyAndBag()
        {
            var item = GameFixture.Battle.GetItem(17);
            var oldPrice = item.Price;
            item.Price = 300;
            try
            {
                var w = NewW(b => b.Script("t", C(921, F(3)), C(913), C(EvCmdId.End)));
                ((GameData)w.Session.Data).Shops = new ShopTables
                {
                    FixedShop = { new ShopEntryRecord { ItemNo = 17, ShopId = 3 }, new ShopEntryRecord { ItemNo = 18, ShopId = 4 } },
                };
                w.Session.AddMoney(-w.Session.Money + 1000);
                Assert.IsTrue(w.Loop.StartEvent("t"));
                w.Loop.Tick(1f / 30f, GameInput.None);
                var shop = w.Session.Shop;
                Assert.IsNotNull(shop);
                Assert.AreEqual(1, shop.Items.Count, "nur Waren der Laden-Nr. 3");
                Assert.AreEqual(300, shop.Items[0].Price);
                w.Session.OpenShop(ShopKind.Fixed, 3);
                Assert.AreEqual(ShopResult.Ok, w.Session.Buy(17, 3));
                Assert.AreEqual(100, w.Session.Money);
                Assert.AreEqual(3, w.Session.GetItemCount(17));
                Assert.AreEqual(ShopResult.NoMoney, w.Session.Buy(17, 1));
                Assert.AreEqual(ShopResult.NotOffered, w.Session.Buy(18, 1));
                w.Session.OpenShop(ShopKind.Sell);
                Assert.AreEqual(ShopResult.Ok, w.Session.Sell(17, 2));
                Assert.AreEqual(100 + 2 * 150, w.Session.Money);
                Assert.AreEqual(1, w.Session.GetItemCount(17));
                Assert.AreEqual(ShopResult.NotOwned, w.Session.Sell(17, 5));
                w.Session.CloseShop();
                Assert.AreEqual(ShopResult.Invalid, w.Session.Sell(17, 1));
            }
            finally
            {
                item.Price = oldPrice;
            }
        }

        [Test]
        public void DelegatedCommandsEmitEventsAndDebugIsSilent()
        {
            var w = NewW(b => b.Script("t", C(BtwrSubGetRank), C(DebugPrint), C(EvCmdId.End)));
            w.Loop.Host.Record = true;
            RunToEnd(w);
            Assert.AreEqual(1, w.Loop.Host.EventCount);
            Assert.AreEqual("BTWR_SUB_GET_RANK", w.Loop.Host.Events[0].Name);
            Assert.AreEqual(0, w.Loop.Host.GapCommandCalls);
        }

        [Test]
        public void WaitCommandsRecordTheirDurationInFrames()
        {
            var w = NewW(b => b.Script("t", C(942, F(7)), C(943), C(EvCmdId.End)));
            w.Field.WaitPolls = 3;
            w.Loop.Host.Record = true;
            RunToEnd(w);
            Assert.AreEqual(7, w.Session.World.CameraIndex);
            Assert.IsFalse(w.Session.World.CameraBusy);
            var e = w.Loop.Host.Events.Find(x => x.Name == "EVENT_CAMERA_END_WAIT");
            Assert.IsNotNull(e);
            Assert.AreEqual(3, e.DurationFrames);
            Assert.AreEqual(7, w.Loop.Host.Events.Find(x => x.Name == "EVENT_CAMERA_INDEX").Args[0]);
        }

        [Test]
        public void LosingWithoutWarpIdReturnsToTheLastHealedPokecenterAndResetsPartner()
        {
            var b = new FileBuilder();
            b.Script("heal", C(480), C(EvCmdId.End));
            b.Script("fight", C(EvCmdId.TrainerBtlSet, b.S("RIVAL_01")), C(EvCmdId.FlagSet, FL(201)), C(EvCmdId.End));
            var w = NewWorld(b, partyLevel: 2, trainers: new[] { Trainer(5, BattleFlowTestData.Mon3, 60) });
            w.Session.ZoneId = 425;
            RunToEnd(w, "heal");
            Assert.AreEqual(425, w.Session.World.LastHealZone);
            w.Session.Vars.SetSysFlag(2, true);
            w.Session.ZoneId = 600;
            w.Loop.StartEvent("fight");
            w.Player.Run(w.Loop, l => l.Wipeouts > 0, 3000);
            Assert.AreEqual(425, w.Session.ZoneId);
            Assert.AreEqual(425, w.Field.Zone);
            Assert.IsFalse(w.Session.Vars.GetSysFlag(2), "Partner-Systemflag nach der Niederlage aus");
        }

        [Test]
        public void CatalogCoversNearlyAllHostCommands()
        {
            var hostIds = 0;
            for (var id = 1; id <= EvCmdId.MaxDispatchId; id++)
                if (EvCommandTable.Classify(id) == EvCmdKind.Host && HostCommands.Table.ContainsKey(id)) hostIds++;
            Assert.GreaterOrEqual(hostIds, 590);
            foreach (var id in HostCommands.Table.Keys)
                Assert.AreEqual(EvCmdKind.Host, EvCommandTable.Classify(id), "Kennung " + id);
            Assert.Greater(HostCommands.Count(HostEvidence.P), 100);
        }
    }
}
