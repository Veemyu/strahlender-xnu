using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using NUnit.Framework;
using Xnu.Data;

namespace Xnu.Tests
{
    // Ausschließlich synthetische Beispieldaten (keine Spielinhalte); Teil 2 der Stammdaten.
    public class DataMasterData2Tests
    {
        static string Doc(string cls, string instances) =>
            "{\"class\":\"" + cls + "\",\"namespace\":\"XLSXContent\",\"assembly\":\"Assembly-CSharp.dll\"," +
            "\"bundle\":\"synthetic\",\"instances\":[" + instances + "]}";

        static string Inst(string name, string data) => "{\"name\":\"" + name + "\",\"data\":{" + data + "}}";

        static string Single(string cls, string sheets) => Doc(cls, Inst(cls, sheets));

        static string Sheet(string name, params string[] rows) => "\"" + name + "\":[" + string.Join(",", rows) + "]";

        // Ein Teamplatz mit ausgefüllten Werten (Index i = 1..6) oder leer (monsNo 0).
        static string PokeSlot(int i, int monsNo)
        {
            var p = "P" + i;
            var lv = monsNo == 0 ? 0 : 7;
            return "\"" + p + "MonsNo\":" + monsNo + ",\"" + p + "FormNo\":0,\"" + p + "IsRare\":0,\"" + p + "Level\":" + lv + "," +
                "\"" + p + "Sex\":3,\"" + p + "Seikaku\":4,\"" + p + "Tokusei\":5,\"" + p + "Waza1\":10,\"" + p + "Waza2\":20,\"" + p + "Waza3\":0,\"" + p + "Waza4\":0," +
                "\"" + p + "Item\":0,\"" + p + "Ball\":4,\"" + p + "Seal\":-1,\"" + p + "TalentHp\":1,\"" + p + "TalentAtk\":2,\"" + p + "TalentDef\":3," +
                "\"" + p + "TalentSpAtk\":4,\"" + p + "TalentSpDef\":5,\"" + p + "TalentAgi\":6,\"" + p + "EffortHp\":0,\"" + p + "EffortAtk\":0," +
                "\"" + p + "EffortDef\":0,\"" + p + "EffortSpAtk\":0,\"" + p + "EffortSpDef\":0,\"" + p + "EffortAgi\":9";
        }

        static string PokeRow(int id, params int[] monsNos)
        {
            var sb = new StringBuilder("{\"ID\":" + id);
            for (var i = 1; i <= 6; i++) sb.Append(',').Append(PokeSlot(i, i <= monsNos.Length ? monsNos[i - 1] : 0));
            return sb.Append('}').ToString();
        }

        const string TypeRow =
            "{\"TrainerID\":3,\"LabelTrType\":\"type_label\",\"Sex\":1,\"Group\":2,\"BallId\":4,\"FieldEncount\":[\"01\",\"02\"],\"BtlEffId\":[-1,5],\"EyeBgm\":\"EV_X\"," +
            "\"ModelID\":\"model_a\",\"Hand\":2,\"HoldBallHand\":0,\"HelpHand\":2,\"HelpHoldBallHand\":0,\"ThrowTime\":0.5,\"CaptureThrowTime\":0.25,\"LoseLoopTime\":2.0," +
            "\"TrainerEffect\":\"\",\"Age\":1}";

        static string TrainerRow(int typeId, uint ai) =>
            "{\"TypeID\":" + typeId + ",\"ColorID\":1,\"FightType\":0,\"ArenaID\":-1,\"EffectID\":-1,\"Gold\":19,\"UseItem1\":17,\"UseItem2\":0,\"UseItem3\":0,\"UseItem4\":0," +
            "\"HpRecoverFlag\":1,\"GiftItem\":0,\"NameLabel\":\"name_label\",\"MsgFieldPokeOne\":\"\",\"MsgFieldBefore\":\"before\",\"MsgFieldRevenge\":\"revenge\"," +
            "\"MsgFieldAfter\":\"after\",\"MsgBattle\":[\"\",\"lose\"],\"SeqBattle\":[],\"AIBit\":" + ai + "}";

        [Test]
        public void ParseTrainersJoinsPartyByIdAndSkipsEmptySlots()
        {
            var json = Single("TrainerTable",
                Sheet("TrainerType", TypeRow) + "," +
                Sheet("TrainerData", TrainerRow(3, 9), TrainerRow(3, 4294967295)) + "," +
                Sheet("TrainerPoke", PokeRow(0), PokeRow(1, 129, 396)) + "," +
                Sheet("TrainerRematch", "{\"BaseTrainerID\":1,\"Rematch_01\":10,\"Rematch_02\":11,\"Rematch_03\":0,\"Rematch_04\":0,\"Rematch_05\":0}"));
            var t = MasterData2Reader.ParseTrainers(json);

            Assert.AreEqual(1, t.Types.Count);
            Assert.AreEqual(new[] { "01", "02" }, t.Types[0].FieldEncountKeys);
            Assert.AreEqual(new[] { -1, 5 }, t.Types[0].BattleEffectIds);
            Assert.AreEqual(0.25f, t.Types[0].CaptureThrowTime, 1e-6);

            Assert.AreEqual(2, t.Trainers.Count);
            Assert.AreEqual(0, t.Trainers[0].Id);
            Assert.AreEqual(1, t.Trainers[1].Id);
            Assert.AreEqual(9u, t.Trainers[0].AiBits);
            Assert.AreEqual(4294967295u, t.Trainers[1].AiBits);
            Assert.IsTrue(t.Trainers[0].HpRecoverFlag);
            Assert.AreEqual(new[] { 17, 0, 0, 0 }, t.Trainers[0].UseItems);
            Assert.AreEqual(new[] { "", "lose" }, t.Trainers[0].BattleMessages);
            Assert.AreEqual(0, t.Trainers[0].BattleSequences.Length);

            Assert.AreEqual(0, t.Trainers[0].Party.Members.Count);
            var party = t.Trainers[1].Party;
            Assert.AreEqual(2, party.Members.Count);
            Assert.AreEqual(new[] { 129, 396 }, new[] { party.Members[0].MonsNo, party.Members[1].MonsNo });
            Assert.AreEqual(new[] { 1, 2 }, new[] { party.Members[0].Slot, party.Members[1].Slot });
            Assert.AreEqual(7, party.Members[0].Level);
            Assert.AreEqual(new[] { 10, 20, 0, 0 }, party.Members[0].Moves);
            Assert.AreEqual(new[] { 1, 2, 3, 4, 5, 6 }, party.Members[0].Talents);
            Assert.AreEqual(9, party.Members[0].Efforts[5]);
            Assert.AreEqual(-1, party.Members[0].SealTemplateId);

            Assert.AreEqual(new[] { 10, 11, 0, 0, 0 }, t.Rematches[0].RematchTrainerIds);
        }

        [Test]
        public void TrainerWithoutPartyRowHasNullParty()
        {
            var json = Single("TrainerTable",
                Sheet("TrainerType") + "," + Sheet("TrainerData", TrainerRow(1, 0)) + "," + Sheet("TrainerPoke") + "," + Sheet("TrainerRematch"));
            Assert.IsNull(MasterData2Reader.ParseTrainers(json).Trainers[0].Party);
        }

        static string Slots(int count, int firstMons, int lv) =>
            "[" + string.Join(",", Generate(count, i => "{\"maxlv\":" + (lv + 1) + ",\"minlv\":" + lv + ",\"monsNo\":" + (firstMons + i) + "}")) + "]";

        static IEnumerable<string> Generate(int count, Func<int, string> f)
        {
            for (var i = 0; i < count; i++) yield return f(i);
        }

        static string EncounterRow(int zone)
        {
            return "{\"zoneID\":" + zone + ",\"encRate_gr\":30,\"ground_mons\":" + Slots(12, 100, 5) + ",\"tairyo\":" + Slots(2, 200, 6) + "," +
                "\"day\":" + Slots(2, 210, 7) + ",\"night\":" + Slots(2, 220, 8) + ",\"swayGrass\":" + Slots(4, 230, 9) + ",\"FormProb\":[0,1],\"Nazo\":[2,3],\"AnnoonTable\":[4,5]," +
                "\"gbaRuby\":" + Slots(2, 1, 1) + ",\"gbaSapp\":" + Slots(2, 2, 1) + ",\"gbaEme\":" + Slots(2, 3, 1) + ",\"gbaFire\":" + Slots(2, 4, 1) + ",\"gbaLeaf\":" + Slots(2, 5, 1) + "," +
                "\"encRate_wat\":20,\"water_mons\":" + Slots(5, 300, 10) + ",\"encRate_turi_boro\":15,\"boro_mons\":" + Slots(5, 310, 2) + "," +
                "\"encRate_turi_ii\":10,\"ii_mons\":" + Slots(5, 320, 3) + ",\"encRate_sugoi\":5,\"sugoi_mons\":" + Slots(5, 330, 4) + "}";
        }

        static string EncounterData(int zone, int marker) =>
            Sheet("table", EncounterRow(zone)) + "," +
            Sheet("urayama", "{\"monsNo\":" + marker + "}") + "," +
            Sheet("mistu", "{\"Rate\":40,\"Normal\":1,\"Rare\":2,\"SuperRare\":3}") + "," +
            Sheet("honeytree", "{\"Normal\":70,\"Rare\":20}") + "," +
            Sheet("safari", "{\"MonsNo\":" + marker + "}") + "," +
            Sheet("mvpoke", "{\"zoneID\":354,\"nextCount\":2,\"nextZoneID\":[355,403,-1,-1,-1]}") + "," +
            Sheet("legendpoke", "{\"monsNo\":144,\"formNo\":-1,\"isFixedEncSeq\":1,\"encSeq\":\"seq\",\"isFixedBGM\":1,\"bgmEvent\":\"EV\",\"isFixedBtlBg\":0,\"btlBg\":-1," +
                "\"isFixedSetupEffect\":0,\"setupEffect\":0,\"waza1\":-1,\"waza2\":-1,\"waza3\":-1,\"waza4\":-1}") + "," +
            Sheet("zui", "{\"zoneID\":0,\"form\":[0,1,true]}");

        [Test]
        public void ParseFieldEncountersSelectsEditionInstance()
        {
            var json = Doc("FieldEncountTable", Inst("FieldEncountTable_p", EncounterData(24, 11)) + "," + Inst("FieldEncountTable_d", EncounterData(54, 22)));
            var d = MasterData2Reader.ParseFieldEncounters(json, MasterData2Reader.DiamondEncounterInstance);
            Assert.AreEqual("FieldEncountTable_d", d.InstanceName);
            Assert.AreEqual(54, d.Zones[0].ZoneId);
            Assert.AreEqual(new[] { 22 }, d.UnderRoadMonsters.ToArray());
            Assert.AreEqual(new[] { 22 }, d.SafariMonsters.ToArray());
            var p = MasterData2Reader.ParseFieldEncounters(json, "FieldEncountTable_p");
            Assert.AreEqual(24, p.Zones[0].ZoneId);
            Assert.Throws<FormatException>(() => MasterData2Reader.ParseFieldEncounters(json, "FieldEncountTable_x"));
        }

        [Test]
        public void ParseFieldEncountersReadsSlotsAndRates()
        {
            var json = Doc("FieldEncountTable", Inst("FieldEncountTable_d", EncounterData(54, 22)));
            var t = MasterData2Reader.ParseFieldEncounters(json, "FieldEncountTable_d");
            var z = t.Zones[0];
            Assert.AreEqual(30, z.GrassRate);
            Assert.AreEqual(12, z.Grass.Length);
            Assert.AreEqual(new EncounterSlot { MonsNo = 103, MinLevel = 5, MaxLevel = 6 }, z.Grass[3]);
            Assert.AreEqual(2, z.Outbreak.Length);
            Assert.AreEqual(2, z.Day.Length);
            Assert.AreEqual(2, z.Night.Length);
            Assert.AreEqual(4, z.SwayGrass.Length);
            Assert.AreEqual(5, z.Water.Length);
            Assert.AreEqual(new[] { 20, 15, 10, 5 }, new[] { z.WaterRate, z.OldRodRate, z.GoodRodRate, z.SuperRodRate });
            Assert.AreEqual(310, z.OldRod[0].MonsNo);
            Assert.AreEqual(320, z.GoodRod[0].MonsNo);
            Assert.AreEqual(330, z.SuperRod[0].MonsNo);
            Assert.AreEqual(new[] { 0, 1 }, z.FormProbabilities);
            Assert.AreEqual(1, z.GbaRuby[0].MonsNo);
            Assert.AreEqual(5, z.GbaLeafGreen[0].MonsNo);

            Assert.AreEqual(40, t.Honey[0].Rate);
            Assert.AreEqual(3, t.Honey[0].SuperRare);
            Assert.AreEqual(70, t.HoneyTrees[0].Normal);
            Assert.AreEqual(new[] { 355, 403, -1, -1, -1 }, t.Roaming[0].NextZoneIds);
            Assert.AreEqual(144, t.FixedEncounters[0].MonsNo);
            Assert.IsTrue(t.FixedEncounters[0].IsFixedEncounterSequence);
            Assert.IsFalse(t.FixedEncounters[0].IsFixedBattleBackground);
            Assert.AreEqual(new[] { -1, -1, -1, -1 }, t.FixedEncounters[0].Moves);
            Assert.AreEqual(new[] { false, true, true }, t.ZuiForms[0].Forms);
        }

        [Test]
        public void ParseHoneyTreesAndCalendar()
        {
            var honey = MasterData2Reader.ParseHoneyTrees(Single("HoneyTree",
                Sheet("HoneyTreeIndex", "{\"ZoneID\":359,\"HoneyStartFlag\":493,\"HoneyPosXZ\":{\"x\":7.0,\"y\":17.5}}") + "," +
                Sheet("HoneyTreeShake", "{\"Big\":19,\"Normal\":60,\"None\":20,\"Super\":1}")));
            Assert.AreEqual(359, honey.Spots[0].ZoneId);
            Assert.AreEqual(17.5f, honey.Spots[0].Position.Y, 1e-6);
            Assert.AreEqual(100, honey.Shakes[0].Big + honey.Shakes[0].Normal + honey.Shakes[0].None + honey.Shakes[0].Super);

            var cal = MasterData2Reader.ParseCalendar(Single("CalenderEncTable",
                Sheet("data", "{\"month\":1,\"day\":2,\"add_rate\":10,\"add_hatching\":0}") + "," +
                Sheet("weather", "{\"r212b\":2,\"r213\":0,\"r216\":6,\"l3\":5,\"c9\":4}")));
            Assert.AreEqual(2, cal.Days[0].Day);
            Assert.AreEqual(10, cal.Days[0].AddRate);
            Assert.AreEqual(new[] { 2, 0, 6, 5, 4 }, new[] { cal.Weather[0].Route212b, cal.Weather[0].Route213, cal.Weather[0].Route216, cal.Weather[0].Lake3, cal.Weather[0].City9 });
        }

        const string Pptr0 = "{\"m_FileID\":0,\"m_PathID\":0}";

        static string PptrTo(string cls, string name) =>
            "{\"m_FileID\":0,\"m_PathID\":123,\"target_class\":\"" + cls + "\",\"target_name\":\"" + name + "\"}";

        static string ZoneRow(int zone, string attribute) =>
            "{\"Caption\":\"debug\",\"MSLabel\":\"area_label\",\"PokePlaceName\":\"place\",\"FlyingPlaceName\":\"fly\",\"MapType\":3,\"IsField\":0,\"LandmarkType\":-1," +
            "\"MiniMapOffset\":{\"x\":1.5,\"y\":2.5},\"Bicycle\":1,\"Escape\":0,\"Fly\":1,\"BattleSearcher\":0,\"TureAruki\":1,\"KuruKuru\":0,\"Fall\":0," +
            "\"BattleBg\":[14,7],\"ZoneID\":" + zone + ",\"AreaID\":8,\"ZoneGrid\":" + Pptr0 + ",\"Attribute\":" + attribute + ",\"AttributeEx\":" + Pptr0 + "," +
            "\"SubAttribute\":" + Pptr0 + ",\"SubAttributeEx\":" + Pptr0 + ",\"BGM\":[\"day\",\"night\"],\"EnvironmentalSound\":\"env\",\"Weather\":2," +
            "\"RenderSettings\":" + PptrTo("EnvironmentSettings", "render_a") + ",\"ReflectionCamera\":0,\"FixedTime\":1,\"AssetBundleName\":\"prefab_map/map_a\"," +
            "\"RoomPanCamera\":1,\"Locators\":[{\"x\":2.0,\"y\":10.0,\"z\":3.0,\"w\":0.5}],\"Reload\":0}";

        const string CameraRow =
            "{\"ariaID\":8,\"pitch\":42.5,\"fov\":18.0,\"targetRange\":30.0,\"panDistance\":25.0,\"panPitch\":35.0,\"panFov\":20.0,\"panpos_useflag\":0," +
            "\"panMinposY\":1.0,\"panMaxposY\":2.0,\"panMinposZ\":3.0,\"panMaxposZ\":4.0,\"defocusStart\":0.0,\"defocusEnd\":10.5,\"distance\":30.0}";

        [Test]
        public void ParseMapInfoResolvesNamesAndFlags()
        {
            var json = Single("MapInfo",
                Sheet("ZoneData", ZoneRow(5, PptrTo("AttributeMatrix", "matrix_a")), ZoneRow(6, Pptr0)) + "," + Sheet("Camera", CameraRow));
            var t = MasterData2Reader.ParseMapInfo(json);
            Assert.AreEqual(2, t.Zones.Count);
            var z = t.Zones[0];
            Assert.AreEqual(5, z.ZoneId);
            Assert.AreEqual("matrix_a", z.AttributeName);
            Assert.AreEqual("", z.AttributeExName);
            Assert.AreEqual("", z.ZoneGridName);
            Assert.AreEqual("render_a", z.RenderSettingsName);
            Assert.AreEqual("", t.Zones[1].AttributeName);
            Assert.IsTrue(z.CanUseBicycle);
            Assert.IsFalse(z.CanEscape);
            Assert.IsTrue(z.CanFly);
            Assert.IsTrue(z.WalkWithPartner);
            Assert.IsFalse(z.IsField);
            Assert.IsTrue(z.FixedTime);
            Assert.AreEqual(new[] { 14, 7 }, z.BattleBackgrounds);
            Assert.AreEqual(new[] { "day", "night" }, z.Bgm);
            Assert.AreEqual("prefab_map/map_a", z.AssetBundleName);
            Assert.AreEqual(2.5f, z.MiniMapOffset.Y, 1e-6);
            Assert.AreEqual(1, z.Locators.Length);
            Assert.AreEqual(0.5f, z.Locators[0].W, 1e-6);
            Assert.AreEqual(8, t.Cameras[0].AreaId);
            Assert.AreEqual(42.5f, t.Cameras[0].Pitch, 1e-6);
            Assert.IsFalse(t.Cameras[0].PanPosUseFlag);
        }

        [Test]
        public void ParseZoneGridsAttributesAndMatrices()
        {
            var grids = MasterData2Reader.ParseZoneGrids(Doc("ZoneTable",
                Inst("World", "\"ZoneIDs\":[-1,10,11,12,-1,13],\"Width\":3") + "," + Inst("Small", "\"ZoneIDs\":[1],\"Width\":1")));
            Assert.AreEqual(2, grids.Count);
            Assert.AreEqual("World", grids[0].Name);
            Assert.AreEqual(2, grids[0].Height);
            Assert.AreEqual(11, grids[0].ZoneAt(2, 0));
            Assert.AreEqual(13, grids[0].ZoneAt(2, 1));
            Assert.AreEqual(12, grids[0].ZoneAt(0, 1));
            Assert.AreEqual(-1, grids[0].ZoneAt(0, 0));

            var blocks = MasterData2Reader.ParseAttributeBlocks(Doc("AttributeBlock",
                Inst("block_a", "\"Attributes\":[0,128,128,0],\"Width\":2")));
            Assert.AreEqual("block_a", blocks[0].Name);
            Assert.AreEqual(2, blocks[0].Height);
            Assert.AreEqual(128, blocks[0].At(0, 1));

            var matrices = MasterData2Reader.ParseAttributeMatrices(Doc("AttributeMatrix",
                Inst("matrix_a", "\"AttributeBlocks\":[" + PptrTo("AttributeBlock", "block_a") + "," + Pptr0 + "],\"Width\":2")));
            Assert.AreEqual(new[] { "block_a", "" }, matrices[0].BlockNames);
            Assert.AreEqual(2, matrices[0].Width);

            var codes = MasterData2Reader.ParseMapAttributeCodes(Single("MapAttributeTable",
                Sheet("Data", "{\"Code\":7,\"Attribute\":3,\"Entry\":1,\"Water\":0,\"Encount\":1,\"FieldEncount\":\"grass\"}")));
            Assert.AreEqual(7, codes[0].Code);
            Assert.IsTrue(codes[0].Entry);
            Assert.IsFalse(codes[0].Water);
            Assert.IsTrue(codes[0].Encounter);
            Assert.AreEqual("grass", codes[0].FieldEncounterKey);
        }

        [Test]
        public void ParseMapWarpsKeepsInstancePerMap()
        {
            const string row =
                "{\"Position\":{\"x\":9.75,\"y\":0.0,\"z\":15.0},\"GruopID\":1,\"Size\":{\"x\":1.5,\"y\":1.0},\"WarpZone\":42,\"WarpIndex\":7,\"InputDir\":2," +
                "\"FlagIndex\":4000,\"ScriptLabel\":4,\"ExitLabel\":21,\"ConnectionName\":\"\"}";
            var sets = MasterData2Reader.ParseMapWarps(Doc("MapWarp",
                Inst("MapWarp_A", Sheet("Data", row, row)) + "," + Inst("MapWarp_B", Sheet("Data"))));
            Assert.AreEqual(2, sets.Count);
            Assert.AreEqual("MapWarp_A", sets[0].Name);
            Assert.AreEqual(2, sets[0].Warps.Count);
            Assert.AreEqual(0, sets[1].Warps.Count);
            var w = sets[0].Warps[0];
            Assert.AreEqual(9.75f, w.Position.X, 1e-6);
            Assert.AreEqual(1.5f, w.Size.X, 1e-6);
            Assert.AreEqual(42, w.WarpZone);
            Assert.AreEqual(2, w.InputDirection);
            Assert.AreEqual(4000, w.FlagIndex);
        }

        [Test]
        public void ParseShops()
        {
            var shops = MasterData2Reader.ParseShops(Single("ShopTable",
                Sheet("FS", "{\"ItemNo\":4,\"BadgeNum\":2,\"ZoneID\":-1}") + "," +
                Sheet("FixedShop", "{\"ItemNo\":94,\"ShopID\":3}") + "," +
                Sheet("BPShop", "{\"ItemNo\":1606,\"NPCID\":8}")));
            Assert.AreEqual(2, shops.FriendlyShop[0].BadgeNum);
            Assert.AreEqual(-1, shops.FriendlyShop[0].ZoneId);
            Assert.AreEqual(3, shops.FixedShop[0].ShopId);
            Assert.AreEqual(8, shops.BpShop[0].ShopId);
            Assert.AreEqual(1606, shops.BpShop[0].ItemNo);
        }

        [Test]
        public void ParseEvolutionLearnsetEggMovesAndGrowth()
        {
            var evo = MasterData2Reader.ParseEvolutionLists(Single("EvolveTable",
                Sheet("Evolve", "{\"id\":0,\"ar\":[]}", "{\"id\":1,\"ar\":[4,0,2,0,16,8,85,470,1,0]}")));
            Assert.AreEqual(0, evo[0].Steps.Count);
            Assert.AreEqual(2, evo[1].Steps.Count);
            Assert.AreEqual(new[] { 4, 0, 2, 0, 16 },
                new[] { evo[1].Steps[0].Method, evo[1].Steps[0].Parameter, evo[1].Steps[0].TargetSpecies, evo[1].Steps[0].TargetForm, evo[1].Steps[0].Level });
            Assert.AreEqual(85, evo[1].Steps[1].Parameter);
            Assert.AreEqual(1, evo[1].Steps[1].TargetForm);

            var learn = MasterData2Reader.ParseLearnsets(Single("WazaOboeTable", Sheet("WazaOboe", "{\"id\":1,\"ar\":[1,33,3,45]}")));
            Assert.AreEqual(2, learn[0].Moves.Count);
            Assert.AreEqual(3, learn[0].Moves[1].Level);
            Assert.AreEqual(45, learn[0].Moves[1].MoveNo);

            var egg = MasterData2Reader.ParseEggMoves(Single("TamagoWazaTable", Sheet("Data", "{\"no\":1,\"formNo\":0,\"wazaNo\":[130,80]}")));
            Assert.AreEqual(1, egg[0].No);
            Assert.AreEqual(new[] { 130, 80 }, egg[0].MoveNos);

            var grow = MasterData2Reader.ParseGrowthCurves(Single("GrowTable", Sheet("Data", "{\"exps\":[0,0,8,27]}")));
            Assert.AreEqual(27, grow[0].ExpByLevel[3]);
        }

        [Test]
        public void MalformedListLengthsThrow()
        {
            Assert.Throws<FormatException>(() => MasterData2Reader.ParseEvolutionLists(Single("EvolveTable", Sheet("Evolve", "{\"id\":1,\"ar\":[1,2,3]}"))));
            Assert.Throws<FormatException>(() => MasterData2Reader.ParseLearnsets(Single("WazaOboeTable", Sheet("WazaOboe", "{\"id\":1,\"ar\":[1,2,3]}"))));
        }

        [Test]
        public void ParseEventScriptsKeepsStructureAndRawArguments()
        {
            var json = Doc("EvData", Inst("map_a",
                "\"Scripts\":[{\"Label\":\"ev_start\",\"Commands\":[" +
                "{\"Arg\":[{\"argType\":0,\"data\":4},{\"argType\":1,\"data\":1065353216},{\"argType\":2,\"data\":246},{\"argType\":5,\"data\":0}]}," +
                "{\"Arg\":[]}," +
                "{\"Arg\":[{\"argType\":9,\"data\":-1}]}]}]," +
                "\"StrList\":[\"label_a\",\"label_b\"]") + "," + Inst("map_b", "\"Scripts\":[],\"StrList\":[]"));
            var files = MasterData2Reader.ParseEventScripts(json);
            Assert.AreEqual(2, files.Count);
            Assert.AreEqual(0, files[1].Scripts.Count);
            var f = files[0];
            Assert.AreEqual("map_a", f.Name);
            Assert.AreEqual(new[] { "label_a", "label_b" }, f.Strings.ToArray());
            var script = f.Scripts[0];
            Assert.AreEqual("ev_start", script.Label);
            Assert.AreEqual(3, script.Commands.Count);
            var args = script.Commands[0].Args;
            Assert.AreEqual(4, args.Count);
            Assert.AreEqual((int)EventArgType.Command, args[0].Type);
            Assert.AreEqual(4, args[0].Data);
            Assert.AreEqual((int)EventArgType.Float, args[1].Type);
            Assert.AreEqual(1.0f, args[1].AsFloat(), 1e-9);
            Assert.AreEqual((int)EventArgType.Work, args[2].Type);
            Assert.AreEqual((int)EventArgType.String, args[3].Type);
            Assert.AreEqual(0, script.Commands[1].Args.Count);
            Assert.AreEqual(9, script.Commands[2].Args[0].Type);   // unbekannte Typen bleiben erhalten
            Assert.AreEqual(-1, script.Commands[2].Args[0].Data);
        }

        [Test]
        public void WrongClassOrMissingInstanceThrows()
        {
            Assert.Throws<FormatException>(() => MasterData2Reader.ParseShops(Single("HoneyTree", Sheet("FS"))));
            Assert.Throws<FormatException>(() => MasterData2Reader.ParseHoneyTrees(Doc("HoneyTree", "")));
            Assert.Throws<FormatException>(() => MasterData2Reader.ParseTrainers(Single("TrainerTable", Sheet("TrainerType"))));
        }

        [Test]
        public void ReaderLoadsFromDirectoryAndReportsMissingFiles()
        {
            var dir = Path.Combine(Path.GetTempPath(), "xnu-masterdata2-" + Guid.NewGuid().ToString("N"));
            try
            {
                Directory.CreateDirectory(Path.Combine(dir, "dpr_masterdatas"));
                File.WriteAllText(Path.Combine(dir, MasterData2Reader.ShopPath),
                    Single("ShopTable", Sheet("FS") + "," + Sheet("FixedShop", "{\"ItemNo\":1,\"ShopID\":0}") + "," + Sheet("BPShop")));
                var reader = new MasterData2Reader(dir);
                Assert.AreEqual(1, reader.LoadShops().FixedShop.Count);
                Assert.Throws<FileNotFoundException>(() => reader.LoadTrainers());
                Assert.Throws<ArgumentNullException>(() => new MasterData2Reader(null));
            }
            finally
            {
                if (Directory.Exists(dir)) Directory.Delete(dir, true);
            }
        }
    }
}
