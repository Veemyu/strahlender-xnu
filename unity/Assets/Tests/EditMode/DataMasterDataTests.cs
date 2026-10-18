using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using Xnu.Data;

namespace Xnu.Tests
{
    // Ausschließlich synthetische Beispieldaten; spiegelt scripts/tests/test_masterdata.py.
    public class DataMasterDataTests
    {
        static string Table(string cls, string sheet, string rows) =>
            "{\"class\":\"" + cls + "\",\"namespace\":\"XLSXContent\",\"assembly\":\"Assembly-CSharp.dll\"," +
            "\"bundle\":\"synthetic\",\"instances\":[{\"name\":\"" + cls + "\",\"data\":{\"" + sheet + "\":[" + rows + "]}}]}";

        const string SpeciesRow =
            "{\"valid_flag\":1,\"id\":7,\"monsno\":7,\"form_index\":0,\"form_max\":1,\"color\":2,\"gra_no\":7," +
            "\"basic_hp\":50,\"basic_atk\":51,\"basic_def\":52,\"basic_agi\":53,\"basic_spatk\":54,\"basic_spdef\":55," +
            "\"type1\":3,\"type2\":4,\"get_rate\":120,\"rank\":1,\"exp_value\":64,\"item1\":0,\"item2\":1,\"item3\":2," +
            "\"sex\":127,\"egg_birth\":20,\"initial_friendship\":70,\"egg_group1\":1,\"egg_group2\":2,\"grow\":3," +
            "\"tokusei1\":9,\"tokusei2\":10,\"tokusei3\":11,\"give_exp\":60,\"height\":5,\"weight\":90,\"chihou_zukan_no\":12," +
            "\"machine1\":4294967295,\"machine2\":1,\"machine3\":2,\"machine4\":3,\"hiden_machine\":4," +
            "\"egg_monsno\":7,\"egg_formno\":0,\"egg_formno_kawarazunoishi\":0,\"egg_form_inherit_kawarazunoishi\":0}";

        const string MoveRow =
            "{\"wazaNo\":1,\"isValid\":1,\"type\":2,\"category\":1,\"damageType\":1,\"power\":40,\"hitPer\":100,\"basePP\":35," +
            "\"priority\":-1,\"hitCountMax\":1,\"hitCountMin\":1,\"sickID\":0,\"sickPer\":0,\"sickCont\":0,\"sickTurnMin\":0," +
            "\"sickTurnMax\":0,\"criticalRank\":0,\"shrinkPer\":10,\"aiSeqNo\":5,\"damageRecoverRatio\":-25,\"hpRecoverRatio\":0," +
            "\"target\":0,\"rankEffType1\":1,\"rankEffType2\":2,\"rankEffType3\":3,\"rankEffValue1\":-1,\"rankEffValue2\":0," +
            "\"rankEffValue3\":2,\"rankEffPer1\":100,\"rankEffPer2\":0,\"rankEffPer3\":30,\"flags\":3000000000,\"contestWazaNo\":8}";

        const string ItemRow =
            "{\"no\":4,\"type\":1,\"iconid\":10,\"price\":200,\"bp_price\":0,\"eqp\":5,\"atc\":6,\"nage_atc\":30,\"sizen_atc\":80," +
            "\"sizen_type\":9,\"tuibamu_eff\":1,\"sort\":2,\"group\":3,\"group_id\":4,\"fld_pocket\":1,\"field_func\":2,\"battle_func\":3," +
            "\"wk_cmn\":1,\"wk_prm_hp_exp\":-5,\"flags0\":7}";

        [Test]
        public void MiniJsonParsesAllValueKinds()
        {
            var root = (Dictionary<string, object>)MiniJson.Parse(
                "{\"a\":[1,-2,3.5,1e2],\"b\":\"x\\ty\\u00e4\",\"c\":true,\"d\":null,\"e\":{},\"f\":NaN,\"g\":4294967295}");
            var a = (List<object>)root["a"];
            Assert.AreEqual(1L, a[0]);
            Assert.AreEqual(-2L, a[1]);
            Assert.AreEqual(3.5, (double)a[2], 1e-9);
            Assert.AreEqual(100.0, (double)a[3], 1e-9);
            Assert.AreEqual("x\tyä", root["b"]);
            Assert.AreEqual(true, root["c"]);
            Assert.IsNull(root["d"]);
            Assert.IsTrue(double.IsNaN((double)root["f"]));
            Assert.AreEqual(4294967295L, root["g"]);
        }

        [Test]
        public void MiniJsonRejectsGarbage()
        {
            Assert.Throws<FormatException>(() => MiniJson.Parse("{\"a\":1"));
            Assert.Throws<FormatException>(() => MiniJson.Parse("[1,2] x"));
            Assert.Throws<FormatException>(() => MiniJson.Parse("{\"a\" 1}"));
        }

        [Test]
        public void ParseSpecies()
        {
            var list = MasterDataReader.ParseSpecies(Table("PersonalTable", "Personal", SpeciesRow));
            Assert.AreEqual(1, list.Count);
            var s = list[0];
            Assert.IsTrue(s.IsValid);
            Assert.AreEqual(7, s.DexNo);
            Assert.AreEqual(53, s.BaseSpeed);
            Assert.AreEqual(55, s.BaseSpDefense);
            Assert.AreEqual(4, s.Type2);
            Assert.AreEqual(11, s.Ability3);
            Assert.AreEqual(4294967295u, s.MachineMask1);
            Assert.IsFalse(s.EggFormInheritHeldStone);
        }

        [Test]
        public void ParseMoves()
        {
            var list = MasterDataReader.ParseMoves(Table("WazaTable", "Waza", MoveRow));
            var m = list[0];
            Assert.AreEqual(-1, m.Priority);
            Assert.AreEqual(-25, m.DamageRecoverRatio);
            Assert.AreEqual(new[] { 1, 2, 3 }, m.StatStageTypes);
            Assert.AreEqual(new[] { -1, 0, 2 }, m.StatStageValues);
            Assert.AreEqual(new[] { 100, 0, 30 }, m.StatStageChances);
            Assert.AreEqual(3000000000u, m.Flags);
        }

        [Test]
        public void ParseItemsKeepsEffects()
        {
            var item = MasterDataReader.ParseItems(Table("ItemTable", "Item", ItemRow))[0];
            Assert.AreEqual(4, item.ItemNo);
            Assert.AreEqual(200, item.Price);
            Assert.AreEqual(7u, item.Flags);
            Assert.AreEqual(1, item.Effects["tuibamu_eff"]);
            Assert.AreEqual(-5, item.Effects["wk_prm_hp_exp"]);
            Assert.IsFalse(item.Effects.ContainsKey("price"));
        }

        [Test]
        public void ParseMachinesAndEvolutions()
        {
            var machines = MasterDataReader.ParseMachines(Table("ItemTable", "WazaMachine", "{\"itemNo\":328,\"machineNo\":1,\"wazaNo\":29}"));
            Assert.AreEqual(29, machines[0].MoveNo);
            var evo = MasterDataReader.ParseEvolutions(Table("EvolveTable", "Evolve", "{\"id\":1,\"ar\":[4,16,2,0,0,0]}"));
            Assert.AreEqual(1, evo[0].Id);
            Assert.AreEqual(6, evo[0].Values.Length);
            Assert.AreEqual(16, evo[0].Values[1]);
        }

        [Test]
        public void ParseMessages()
        {
            const string json =
                "{\"class\":\"MsbtData\",\"namespace\":\"Dpr.Message\",\"assembly\":\"Assembly-CSharp.dll\",\"bundle\":\"synthetic\",\"instances\":[" +
                "{\"name\":\"file_a\",\"data\":{\"hash\":5,\"langID\":2,\"isResident\":0,\"isKanji\":0,\"labelDataArray\":[" +
                "{\"labelIndex\":1,\"arrayIndex\":0,\"labelName\":\"label_001\",\"styleInfo\":{},\"attributeValueArray\":[],\"tagDataArray\":[]," +
                "\"wordDataArray\":[{\"patternID\":0,\"eventID\":-1,\"tagIndex\":-1,\"tagValue\":0.0,\"str\":\"Beispieltext\",\"strWidth\":12.5}]}]}}," +
                "{\"name\":\"file_b\",\"data\":{\"hash\":6,\"langID\":2,\"isResident\":1,\"isKanji\":0,\"labelDataArray\":[]}}]}";
            var files = MasterDataReader.ParseMessages(json);
            Assert.AreEqual(2, files.Count);
            Assert.AreEqual("file_a", files[0].Name);
            Assert.AreEqual("label_001", files[0].Labels[0].Name);
            Assert.AreEqual("Beispieltext", files[0].Labels[0].Words[0].Text);
            Assert.AreEqual(12.5f, files[0].Labels[0].Words[0].Width, 1e-6);
            Assert.IsTrue(files[1].IsResident);
            Assert.AreEqual(0, files[1].Labels.Count);
        }

        [Test]
        public void WrongClassOrInstanceCountThrows()
        {
            Assert.Throws<FormatException>(() => MasterDataReader.ParseSpecies(Table("WazaTable", "Personal", SpeciesRow)));
            const string two = "{\"class\":\"WazaTable\",\"instances\":[{\"name\":\"a\",\"data\":{\"Waza\":[]}},{\"name\":\"b\",\"data\":{\"Waza\":[]}}]}";
            Assert.Throws<FormatException>(() => MasterDataReader.ParseMoves(two));
            Assert.Throws<FormatException>(() => MasterDataReader.ParseMoves(Table("WazaTable", "Waza", "{\"wazaNo\":1}")));
        }

        [Test]
        public void ReaderLoadsFromDirectory()
        {
            var dir = Path.Combine(Path.GetTempPath(), "xnu-masterdata-" + Guid.NewGuid().ToString("N"));
            try
            {
                Directory.CreateDirectory(Path.Combine(dir, "pml_personal"));
                File.WriteAllText(Path.Combine(dir, MasterDataReader.WazaPath), Table("WazaTable", "Waza", MoveRow));
                var reader = new MasterDataReader(dir);
                Assert.AreEqual(1, reader.LoadMoves().Count);
                Assert.Throws<FileNotFoundException>(() => reader.LoadSpecies());
            }
            finally
            {
                if (Directory.Exists(dir)) Directory.Delete(dir, true);
            }
        }
    }
}
