using System;
using System.Collections.Generic;
using NUnit.Framework;
using Xnu.PokePara;
using static Xnu.Tests.BattleFixtures;
using static Xnu.Tests.PokeParaTestUtil;

namespace Xnu.Tests
{
    // Entschlüsselung und Felder gegen die echten Accessor-Getter/-Setter (Orakel). Die Slots sind synthetisch und wurden vom
    // Spiel selbst (UpdateChecksumAndEncode) kodiert.
    public class PokeParaAccessorTests
    {
        static Dictionary<string, object> _acc;
        static Dictionary<string, object> Acc => _acc ??= Load("PokeParaAccessor.json");

        static Dictionary<string, object> _set;
        static Dictionary<string, object> Set => _set ??= Load("PokeParaSetters.json");

        // Getter-Name im Spiel -> Zugriff in C#. Index-Getter bekommen ihren Index, die übrigen ignorieren ihn.
        static readonly Dictionary<string, Func<PokemonParam, int, long>> Getters = new Dictionary<string, Func<PokemonParam, int, long>>
        {
            ["GetPersonalRnd"] = (p, i) => p.Core.PersonalRnd,
            ["GetColorRnd"] = (p, i) => p.Core.ColorRnd,
            ["GetCheckSum"] = (p, i) => p.Core.StoredChecksum,
            ["IsFuseiTamago"] = (p, i) => p.Core.IsBadEgg ? 1 : 0,
            ["GetSick"] = (p, i) => p.Core.Sick,
            ["GetMonsNo"] = (p, i) => p.Core.SpeciesNo,
            ["GetItemNo"] = (p, i) => p.Core.HeldItem,
            ["GetID"] = (p, i) => p.Core.TrainerId,
            ["GetExp"] = (p, i) => p.Core.Exp,
            ["GetFriendship"] = (p, i) => p.Core.Friendship,
            ["GetTokuseiNo"] = (p, i) => p.Core.Ability,
            ["GetBoxMark"] = (p, i) => p.Core.BoxMark,
            ["GetLangId"] = (p, i) => p.Core.LangId,
            ["GetEffortHp"] = (p, i) => p.Core.GetEv(StatId.Hp),
            ["GetEffortAtk"] = (p, i) => p.Core.GetEv(StatId.Atk),
            ["GetEffortDef"] = (p, i) => p.Core.GetEv(StatId.Def),
            ["GetEffortSpAtk"] = (p, i) => p.Core.GetEv(StatId.SpAtk),
            ["GetEffortSpDef"] = (p, i) => p.Core.GetEv(StatId.SpDef),
            ["GetEffortAgi"] = (p, i) => p.Core.GetEv(StatId.Speed),
            ["GetStyle"] = (p, i) => p.Core.GetContestStat(0),
            ["GetBeautiful"] = (p, i) => p.Core.GetContestStat(1),
            ["GetCute"] = (p, i) => p.Core.GetContestStat(2),
            ["GetClever"] = (p, i) => p.Core.GetContestStat(3),
            ["GetStrong"] = (p, i) => p.Core.GetContestStat(4),
            ["GetFur"] = (p, i) => p.Core.GetContestStat(5),
            ["GetEquipRibbonNo"] = (p, i) => p.Core.EquipRibbon,
            ["GetTalentHp"] = (p, i) => p.Core.GetNativeIv(StatId.Hp),
            ["GetTalentAtk"] = (p, i) => p.Core.GetNativeIv(StatId.Atk),
            ["GetTalentDef"] = (p, i) => p.Core.GetNativeIv(StatId.Def),
            ["GetTalentSpAtk"] = (p, i) => p.Core.GetNativeIv(StatId.SpAtk),
            ["GetTalentSpDef"] = (p, i) => p.Core.GetNativeIv(StatId.SpDef),
            ["GetTalentAgi"] = (p, i) => p.Core.GetNativeIv(StatId.Speed),
            ["GetEffortG"] = (p, i) => p.Core.EffortG,
            ["IsEventPokemon"] = (p, i) => p.Core.IsEventPokemon ? 1 : 0,
            ["GetOfficialBattleEnableFlag"] = (p, i) => p.Core.OfficialBattleEnabled ? 1 : 0,
            ["GetSex"] = (p, i) => p.Core.Sex,
            ["GetFormNo"] = (p, i) => p.Core.FormNo,
            ["GetSeikaku"] = (p, i) => p.Core.Nature,
            ["GetSeikakuHosei"] = (p, i) => p.Core.NatureAdjust,
            ["IsTokusei1"] = (p, i) => p.Core.Ability1Flag ? 1 : 0,
            ["IsTokusei2"] = (p, i) => p.Core.Ability2Flag ? 1 : 0,
            ["IsTokusei3"] = (p, i) => p.Core.Ability3Flag ? 1 : 0,
            ["IsFavorite"] = (p, i) => p.Core.IsFavorite ? 1 : 0,
            ["IsSpecialGEnable"] = (p, i) => p.Core.SpecialGFlag ? 1 : 0,
            ["IsTamago"] = (p, i) => p.Core.IsEgg ? 1 : 0,
            ["HaveNickName"] = (p, i) => p.Core.HasNickname ? 1 : 0,
            ["GetCassetteVersion"] = (p, i) => p.Core.CassetteVersion,
            ["GetTamagoGetYear"] = (p, i) => p.Core.EggYear,
            ["GetTamagoGetMonth"] = (p, i) => p.Core.EggMonth,
            ["GetTamagoGetDay"] = (p, i) => p.Core.EggDay,
            ["GetBirthYear"] = (p, i) => p.Core.MetYear,
            ["GetBirthMonth"] = (p, i) => p.Core.MetMonth,
            ["GetBirthDay"] = (p, i) => p.Core.MetDay,
            ["GetGetPlace"] = (p, i) => p.Core.EggPlace,
            ["GetBirthPlace"] = (p, i) => p.Core.MetPlace,
            ["GetPokerus"] = (p, i) => p.Core.Pokerus,
            ["GetGetBall"] = (p, i) => p.Core.Ball,
            ["GetGetLevel"] = (p, i) => p.Core.MetLevel,
            ["GetOyasex"] = (p, i) => p.Core.TrainerSex,
            ["GetLevel"] = (p, i) => p.Level,
            ["GetHp"] = (p, i) => p.Core.CurrentHp,
            ["GetMaxHp"] = (p, i) => p.MaxHp,
            ["GetAtk"] = (p, i) => p.Atk,
            ["GetDef"] = (p, i) => p.Def,
            ["GetSpAtk"] = (p, i) => p.SpAtk,
            ["GetSpDef"] = (p, i) => p.SpDef,
            ["GetAgi"] = (p, i) => p.Speed,
            ["GetGState"] = (p, i) => p.GState,
            ["GetEnjoy"] = (p, i) => p.Core.Enjoy,
            ["GetNadenadeValue"] = (p, i) => p.Core.NadeNadeValue,
            ["GetOthersFriendshipTrainerID"] = (p, i) => p.Core.OthersFriendshipTrainerId,
            ["GetOwnedOthersFlag"] = (p, i) => p.Core.OwnedByOthers ? 1 : 0,
            ["GetOriginalFriendship"] = (p, i) => p.Core.OriginalFriendship,
            ["GetOthersFriendship"] = (p, i) => p.Core.OthersFriendship,
            ["GetMemoriesLevel"] = (p, i) => p.Core.MemoriesLevel,
            ["GetMemoriesCode"] = (p, i) => p.Core.MemoriesCode,
            ["GetMemoriesData"] = (p, i) => p.Core.MemoriesData,
            ["GetMemoriesFeel"] = (p, i) => p.Core.MemoriesFeel,
            ["GetOthersMemoriesLevel"] = (p, i) => p.Core.OthersMemoriesLevel,
            ["GetOthersMemoriesCode"] = (p, i) => p.Core.OthersMemoriesCode,
            ["GetOthersMemoriesData"] = (p, i) => p.Core.OthersMemoriesData,
            ["GetOthersMemoriesFeel"] = (p, i) => p.Core.OthersMemoriesFeel,
            ["GetPastParentsSex"] = (p, i) => p.Core.PastParentsSex,
            ["GetPastParentsLangID"] = (p, i) => p.Core.PastParentsLang,
            ["GetMultiPurposeWork"] = (p, i) => p.Core.MultiWork,
            ["GetTrainingFlag"] = (p, i) => p.Core.TrainingFlags,
            // Das Spiel liefert hier das ganze 32-Bit-Wort _bitsC, genutzt wird nur das niedrigste Byte.
            ["GetCampFriendship"] = (p, i) => p.Core.CampFriendship,
            ["GetPalma"] = (p, i) => p.Core.Palma,
            ["GetTalentHeight"] = (p, i) => p.Core.TalentHeight,
            ["GetTalentWeight"] = (p, i) => p.Core.TalentWeight,
            ["GetBattleRomMark"] = (p, i) => p.Core.BattleRomMark,
            ["GetDprIllegalFlag"] = (p, i) => p.Core.DprIllegalFlag ? 1 : 0,
            ["GetBankUniqueID"] = (p, i) => unchecked((long)p.Core.BankUniqueId),
            ["HaveRibbon"] = (p, i) => p.Core.HasRibbon(i) ? 1 : 0,
            ["GetLumpingRibbon"] = (p, i) => p.Core.GetLumpingRibbon(i),
            ["GetWazaNo"] = (p, i) => p.Core.GetMove(i),
            ["GetPP"] = (p, i) => p.Core.GetPp(i),
            ["GetWazaPPUpCount"] = (p, i) => p.Core.GetPpUps(i),
            ["GetTamagoWazaNo"] = (p, i) => p.Core.GetEggMove(i),
            ["GetWazaRecordFlag"] = (p, i) => p.Core.GetMoveRecordFlag(i) ? 1 : 0,
            ["GetPokeJobFlag"] = (p, i) => p.Core.GetPokeJobFlag(i) ? 1 : 0,
        };

        // Rückgaben, deren obere Bits im Spiel nicht definiert sind (bool/Flag): nur "ungleich 0" vergleichen.
        static bool IsBoolGetter(string name) => name.StartsWith("Is") || name.StartsWith("Have") || name.EndsWith("Flag") || name == "GetOwnedOthersFlag";

        static long Num(object v) => v is string s ? unchecked((long)ulong.Parse(s)) : Convert.ToInt64(v);

        [Test]
        public void SlotsDecodeWithValidChecksumAndRoundTripExactly()
        {
            var slots = (List<object>)Acc["slots"];
            Assert.AreEqual(32, slots.Count);
            foreach (Dictionary<string, object> s in slots)
            {
                var slot = Hex(s["slot"]);
                var p = PokemonParam.FromSlot(slot);
                Assert.IsTrue(p.ChecksumValid);
                Assert.AreEqual(U32(s, "rnd"), p.Core.PersonalRnd);
                CollectionAssert.AreEqual(Hex(s["plainCore"]), p.Core.ToPlain(), "Klartext-Kern");
                CollectionAssert.AreEqual(Hex(s["plainCalc"]), p.CalcBytes(), "Klartext-CalcData");
                CollectionAssert.AreEqual(slot, p.ToSlot(), "Slot nach Neukodierung");
                CollectionAssert.AreEqual(slot, p.ToSlot(false), "Slot ohne Prüfsummenberechnung");
            }
        }

        [Test]
        public void AllGettersMatchTheGameAccessors()
        {
            var tested = new HashSet<string>();
            foreach (Dictionary<string, object> s in (List<object>)Acc["slots"])
            {
                var p = PokemonParam.FromSlot(Hex(s["slot"]));
                var get = (Dictionary<string, object>)s["get"];
                foreach (var kv in get)
                {
                    Assert.IsTrue(Getters.ContainsKey(kv.Key), "Getter fehlt im Test: " + kv.Key);
                    var fn = Getters[kv.Key];
                    if (kv.Value is List<object> list)
                    {
                        for (int i = 0; i < list.Count; i++) Compare(kv.Key, i, Num(list[i]), fn(p, i));
                    }
                    else
                    {
                        Compare(kv.Key, 0, Num(kv.Value), fn(p, 0));
                    }
                    tested.Add(kv.Key);
                }
            }
            Assert.GreaterOrEqual(tested.Count, 100);
        }

        static void Compare(string name, int index, long expected, long actual)
        {
            if (IsBoolGetter(name))
            {
                Assert.AreEqual(expected != 0, actual != 0, $"{name}[{index}]");
                return;
            }
            if (name == "GetCampFriendship") expected &= 0xFF;
            Assert.AreEqual(expected, actual, $"{name}[{index}]");
        }

        [Test]
        public void IvPackingMatchesGetterBitPositions()
        {
            foreach (Dictionary<string, object> s in (List<object>)Acc["slots"])
            {
                var p = PokemonParam.FromSlot(Hex(s["slot"]));
                var get = (Dictionary<string, object>)s["get"];
                Assert.AreEqual(Num(get["GetTalentHp"]), p.Core.IvBits & 0x1F);
                Assert.AreEqual(Num(get["GetTalentAtk"]), p.Core.IvBits >> 5 & 0x1F);
                Assert.AreEqual(Num(get["GetTalentDef"]), p.Core.IvBits >> 10 & 0x1F);
                Assert.AreEqual(Num(get["GetTalentAgi"]), p.Core.IvBits >> 15 & 0x1F);
                Assert.AreEqual(Num(get["GetTalentSpAtk"]), p.Core.IvBits >> 20 & 0x1F);
                Assert.AreEqual(Num(get["GetTalentSpDef"]), p.Core.IvBits >> 25 & 0x1F);
            }
        }

        // ---- Setter -------------------------------------------------------------------------------------------------

        static readonly Dictionary<string, Action<PokemonParam, long[]>> Setters = new Dictionary<string, Action<PokemonParam, long[]>>
        {
            ["SetPersonalRnd"] = (p, a) => p.Core.PersonalRnd = (uint)a[0],
            ["SetColorRnd"] = (p, a) => p.Core.ColorRnd = (uint)a[0],
            ["SetSick"] = (p, a) => p.Core.Sick = (uint)a[0],
            ["SetMonsNo"] = (p, a) => p.Core.SpeciesNo = (ushort)a[0],
            ["SetItemNo"] = (p, a) => p.Core.HeldItem = (ushort)a[0],
            ["SetID"] = (p, a) => p.Core.TrainerId = (uint)a[0],
            ["SetExp"] = (p, a) => p.Core.Exp = (uint)a[0],
            ["SetFriendship"] = (p, a) => p.Core.Friendship = (byte)a[0],
            ["SetTokuseiNo"] = (p, a) => p.Core.Ability = (ushort)a[0],
            ["SetBoxMark"] = (p, a) => p.Core.BoxMark = (ushort)a[0],
            ["SetLangId"] = (p, a) => p.Core.LangId = (byte)a[0],
            ["SetEffortHp"] = (p, a) => p.Core.SetEv(StatId.Hp, (byte)a[0]),
            ["SetEffortAtk"] = (p, a) => p.Core.SetEv(StatId.Atk, (byte)a[0]),
            ["SetEffortDef"] = (p, a) => p.Core.SetEv(StatId.Def, (byte)a[0]),
            ["SetEffortSpAtk"] = (p, a) => p.Core.SetEv(StatId.SpAtk, (byte)a[0]),
            ["SetEffortSpDef"] = (p, a) => p.Core.SetEv(StatId.SpDef, (byte)a[0]),
            ["SetEffortAgi"] = (p, a) => p.Core.SetEv(StatId.Speed, (byte)a[0]),
            ["SetStyle"] = (p, a) => p.Core.SetContestStat(0, (byte)a[0]),
            ["SetBeautiful"] = (p, a) => p.Core.SetContestStat(1, (byte)a[0]),
            ["SetCute"] = (p, a) => p.Core.SetContestStat(2, (byte)a[0]),
            ["SetClever"] = (p, a) => p.Core.SetContestStat(3, (byte)a[0]),
            ["SetStrong"] = (p, a) => p.Core.SetContestStat(4, (byte)a[0]),
            ["SetFur"] = (p, a) => p.Core.SetContestStat(5, (byte)a[0]),
            ["SetRibbon"] = (p, a) => p.Core.SetRibbon((int)a[0], true),
            ["RemoveRibbon"] = (p, a) => p.Core.SetRibbon((int)a[0], false),
            ["RemoveAllRibbon"] = (p, a) => p.Core.RemoveAllRibbons(),
            ["SetLumpingRibbon"] = (p, a) => p.Core.SetLumpingRibbon((int)a[0], (byte)a[1]),
            ["SetEquipRibbonNo"] = (p, a) => p.Core.EquipRibbon = (byte)a[0],
            ["SetWazaNo"] = (p, a) => p.Core.SetMove((int)a[0], (ushort)a[1]),
            ["SetPP"] = (p, a) => p.Core.SetPp((int)a[0], (byte)a[1]),
            ["SetWazaPPUpCount"] = (p, a) => p.Core.SetPpUps((int)a[0], (byte)a[1]),
            ["SetTamagoWazaNo"] = (p, a) => p.Core.SetEggMove((int)a[0], (ushort)a[1]),
            ["SetTalentHp"] = (p, a) => p.Core.SetNativeIv(StatId.Hp, (uint)a[0]),
            ["SetTalentAtk"] = (p, a) => p.Core.SetNativeIv(StatId.Atk, (uint)a[0]),
            ["SetTalentDef"] = (p, a) => p.Core.SetNativeIv(StatId.Def, (uint)a[0]),
            ["SetTalentSpAtk"] = (p, a) => p.Core.SetNativeIv(StatId.SpAtk, (uint)a[0]),
            ["SetTalentSpDef"] = (p, a) => p.Core.SetNativeIv(StatId.SpDef, (uint)a[0]),
            ["SetTalentAgi"] = (p, a) => p.Core.SetNativeIv(StatId.Speed, (uint)a[0]),
            ["SetEffortG"] = (p, a) => p.Core.EffortG = (byte)a[0],
            ["SetEventPokemonFlag"] = (p, a) => p.Core.IsEventPokemon = (a[0] & 1) != 0,
            ["SetOfficialBattleEnableFlag"] = (p, a) => p.Core.OfficialBattleEnabled = (a[0] & 1) != 0,
            ["SetSex"] = (p, a) => p.Core.Sex = (byte)a[0],
            ["SetFormNo"] = (p, a) => p.Core.FormNo = (ushort)a[0],
            ["SetSeikaku"] = (p, a) => p.Core.Nature = (byte)a[0],
            ["SetSeikakuHosei"] = (p, a) => p.Core.NatureAdjust = (byte)a[0],
            ["SetTamagoFlag"] = (p, a) => p.Core.IsEgg = (a[0] & 1) != 0,
            ["SetTokusei1Flag"] = (p, a) => p.Core.Ability1Flag = (a[0] & 1) != 0,
            ["SetTokusei2Flag"] = (p, a) => p.Core.Ability2Flag = (a[0] & 1) != 0,
            ["SetTokusei3Flag"] = (p, a) => p.Core.Ability3Flag = (a[0] & 1) != 0,
            ["SetFavoriteFlag"] = (p, a) => p.Core.IsFavorite = (a[0] & 1) != 0,
            ["SetSpecialGFlag"] = (p, a) => p.Core.SpecialGFlag = (a[0] & 1) != 0,
            ["SetNickNameFlag"] = (p, a) => p.Core.HasNickname = (a[0] & 1) != 0,
            ["SetCassetteVersion"] = (p, a) => p.Core.CassetteVersion = (byte)a[0],
            ["SetTamagoGetYear"] = (p, a) => p.Core.EggYear = (byte)a[0],
            ["SetTamagoGetMonth"] = (p, a) => p.Core.EggMonth = (byte)a[0],
            ["SetTamagoGetDay"] = (p, a) => p.Core.EggDay = (byte)a[0],
            ["SetBirthYear"] = (p, a) => p.Core.MetYear = (byte)a[0],
            ["SetBirthMonth"] = (p, a) => p.Core.MetMonth = (byte)a[0],
            ["SetBirthDay"] = (p, a) => p.Core.MetDay = (byte)a[0],
            ["SetGetPlace"] = (p, a) => p.Core.EggPlace = (ushort)a[0],
            ["SetBirthPlace"] = (p, a) => p.Core.MetPlace = (ushort)a[0],
            ["SetPokerus"] = (p, a) => p.Core.Pokerus = (byte)a[0],
            ["SetGetBall"] = (p, a) => p.Core.Ball = (byte)a[0],
            ["SetGetLevel"] = (p, a) => p.Core.MetLevel = (byte)a[0],
            ["SetOyasex"] = (p, a) => p.Core.TrainerSex = (byte)a[0],
            ["SetLevel"] = (p, a) => p.Level = (byte)a[0],
            ["SetMaxHp"] = (p, a) => p.MaxHp = (ushort)a[0],
            ["SetHp"] = (p, a) => p.Core.CurrentHp = (ushort)a[0],
            ["SetAtk"] = (p, a) => p.Atk = (ushort)a[0],
            ["SetDef"] = (p, a) => p.Def = (ushort)a[0],
            ["SetSpAtk"] = (p, a) => p.SpAtk = (ushort)a[0],
            ["SetSpDef"] = (p, a) => p.SpDef = (ushort)a[0],
            ["SetAgi"] = (p, a) => p.Speed = (ushort)a[0],
            ["SetGState"] = (p, a) => p.GState = (byte)a[0],
            ["SetEnjoy"] = (p, a) => p.Core.Enjoy = (byte)a[0],
            ["SetNadenadeValue"] = (p, a) => p.Core.NadeNadeValue = (byte)a[0],
            ["SetOthersFriendshipTrainerID"] = (p, a) => p.Core.OthersFriendshipTrainerId = (ushort)a[0],
            ["SetOwnedOthersFlag"] = (p, a) => p.Core.OwnedByOthers = (a[0] & 1) != 0,
            ["SetOriginalFriendship"] = (p, a) => p.Core.OriginalFriendship = (byte)a[0],
            ["SetOthersFriendship"] = (p, a) => p.Core.OthersFriendship = (byte)a[0],
            ["SetMemoriesLevel"] = (p, a) => p.Core.MemoriesLevel = (byte)a[0],
            ["SetMemoriesCode"] = (p, a) => p.Core.MemoriesCode = (byte)a[0],
            ["SetMemoriesData"] = (p, a) => p.Core.MemoriesData = (ushort)a[0],
            ["SetMemoriesFeel"] = (p, a) => p.Core.MemoriesFeel = (byte)a[0],
            ["SetOthersMemoriesLevel"] = (p, a) => p.Core.OthersMemoriesLevel = (byte)a[0],
            ["SetOthersMemoriesCode"] = (p, a) => p.Core.OthersMemoriesCode = (byte)a[0],
            ["SetOthersMemoriesData"] = (p, a) => p.Core.OthersMemoriesData = (ushort)a[0],
            ["SetOthersMemoriesFeel"] = (p, a) => p.Core.OthersMemoriesFeel = (byte)a[0],
            ["SetPastParentsSex"] = (p, a) => p.Core.PastParentsSex = (byte)a[0],
            ["SetPastParentsLangID"] = (p, a) => p.Core.PastParentsLang = (byte)a[0],
            ["SetMultiPurposeWork"] = (p, a) => p.Core.MultiWork = (uint)a[0],
            ["SetTrainingFlag"] = (p, a) => p.Core.TrainingFlags = (byte)a[0],
            ["SetWazaRecordFlag"] = (p, a) => p.Core.SetMoveRecordFlag((int)a[0], (a[1] & 1) != 0),
            ["SetPokeJobFlag"] = (p, a) => p.Core.SetPokeJobFlag((int)a[0], (a[1] & 1) != 0),
            ["SetBankUniqueID"] = (p, a) => p.Core.BankUniqueId = unchecked((ulong)a[0]),
            ["ClearBankUniqueID"] = (p, a) => p.Core.ClearBankUniqueId(),
            ["ClearWazaRecordFlag"] = (p, a) => p.Core.ClearMoveRecordFlags(),
            ["ClearPokeJobFlag"] = (p, a) => p.Core.ClearPokeJobFlags(),
            ["SetCampFriendship"] = (p, a) => p.Core.CampFriendship = (byte)a[0],
            ["SetPalma"] = (p, a) => p.Core.Palma = (uint)a[0],
            ["SetTalentHeight"] = (p, a) => p.Core.TalentHeight = (byte)a[0],
            ["SetTalentWeight"] = (p, a) => p.Core.TalentWeight = (byte)a[0],
            ["SetBattleRomMark"] = (p, a) => p.Core.BattleRomMark = (byte)a[0],
            ["SetDprIllegalFlag"] = (p, a) => p.Core.DprIllegalFlag = (a[0] & 1) != 0,
        };

        [Test]
        public void SettersProduceTheSameEncodedSlotAsTheGame()
        {
            var bases = (List<object>)Set["bases"];
            var cases = Cases(Set, "cases");
            Assert.GreaterOrEqual(cases.Count, 300);
            var covered = new HashSet<string>();
            foreach (var c in cases)
            {
                string name = (string)c["setter"];
                Assert.IsTrue(Setters.ContainsKey(name), "Setter fehlt im Test: " + name);
                var p = PokemonParam.FromSlot(Hex(bases[I(c, "base")]));
                var args = new List<long>();
                foreach (var a in (List<object>)c["args"]) args.Add(Num(a));
                Setters[name](p, args.ToArray());
                var expected = Hex(c["after"]);
                var actual = p.ToSlot();
                if (!expected.AsSpan().SequenceEqual(actual))
                    Assert.Fail($"{name}({string.Join(",", args)}) weicht ab\n erwartet {ToHex(expected)}\n erhalten {ToHex(actual)}");
                covered.Add(name);
            }
            Assert.AreEqual(Setters.Count, covered.Count, "nicht alle Setter vom Orakel abgedeckt");
        }

        [Test]
        public void StringSettersMatchTheGame()
        {
            var bases = (List<object>)Set["bases"];
            var cases = Cases(Set, "stringCases");
            Assert.GreaterOrEqual(cases.Count, 18);
            foreach (var c in cases)
            {
                string name = (string)c["setter"];
                var chars = new char[((List<object>)c["chars"]).Count];
                for (int i = 0; i < chars.Length; i++) chars[i] = (char)Num(((List<object>)c["chars"])[i]);
                string text = new string(chars);
                var p = PokemonParam.FromSlot(Hex(bases[I(c, "base")]));
                switch (name)
                {
                    case "SetNickName": p.Core.Nickname = text; break;
                    case "SetOyaName": p.Core.TrainerName = text; break;
                    case "SetPastParentsName": p.Core.PastParentsName = text; break;
                    default: Assert.Fail("unbekannter Setter " + name); break;
                }
                CollectionAssert.AreEqual(Hex(c["after"]), p.ToSlot(), $"{name} mit {chars.Length} Zeichen");
                string back = name == "SetNickName" ? p.Core.Nickname : name == "SetOyaName" ? p.Core.TrainerName : p.Core.PastParentsName;
                Assert.AreEqual(text.Length > 12 ? text.Substring(0, 12) : text, back);
            }
        }
    }
}
