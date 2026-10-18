using System;
using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Battle;
using Xnu.Data;
using Xnu.PokePara;
using Xnu.Save;
using static Xnu.Tests.PokeParaTestUtil;

namespace Xnu.Tests
{
    // Synthetische Slots und Spielstände (im Test erzeugt; keine echten Saves): Lesen, Schreiben, Prüfsummen, Namen, Bitfelder,
    // berechnete Werte.
    public class PokeParaSlotTests
    {
        static PokemonParam Sample(uint rnd = 0x00006000)
        {
            var p = new PokemonParam();
            p.Core.PersonalRnd = rnd;
            p.Core.SpeciesNo = 483;
            p.Core.HeldItem = 234;
            p.Core.TrainerId = 0xA1B2C3D4;
            p.Core.Exp = 125000;
            p.Core.Ability = 46;
            p.Core.ColorRnd = 0x01020304;
            p.Core.Nature = 3;
            p.Core.NatureAdjust = 3;
            p.Core.Sex = 2;
            p.Core.FormNo = 1;
            p.Core.SetEv(StatId.Hp, 4);
            p.Core.SetEv(StatId.Atk, 252);
            p.Core.SetEv(StatId.Speed, 252);
            p.Core.Nickname = "Testwesen";
            p.Core.HasNickname = true;
            p.Core.SetMove(0, 57);
            p.Core.SetMove(3, 89);
            p.Core.SetPp(0, 15);
            p.Core.SetPpUps(0, 3);
            p.Core.CurrentHp = 100;
            p.Core.TrainerName = "Spieler";
            p.Core.OriginalFriendship = 70;
            p.Core.Ball = 4;
            p.Core.MetLevel = 5;
            p.Core.TrainerSex = 1;
            p.Core.BankUniqueId = 0x0102030405060708UL;
            p.Level = 50;
            p.MaxHp = 207;
            p.Atk = 150;
            return p;
        }

        static byte[] NewSave()
        {
            var save = new byte[SaveLayout.TotalSize];
            save[0] = SaveLayout.CurrentVersion;
            var empty = PokemonParam.CreateEmpty();
            for (int i = 0; i < PokeLayout.PartyCapacity; i++) PokeSaveSlots.WriteParty(save, i, empty);
            for (int t = 0; t < PokeLayout.TrayCount; t++)
                for (int s = 0; s < PokeLayout.TraySlots; s++) PokeSaveSlots.WriteBox(save, t, s, empty);
            return SaveWriter.FixHash(save);
        }

        [Test]
        public void SlotSizesFollowTheSaveLayout()
        {
            Assert.AreEqual(344, PokeLayout.SlotSize);
            Assert.AreEqual(PokeLayout.CoreSize + PokeLayout.CalcSize, PokeLayout.SlotSize);
            Assert.AreEqual(PokeLayout.HeaderSize + PokeLayout.BlockCount * PokeLayout.BlockSize, PokeLayout.CoreSize);
            Assert.AreEqual(PokeLayout.BlockCount * PokeLayout.BlockSize, PokeLayout.EncodedLength);
            Assert.IsTrue(SaveLayout.TryGetField("playerParty", out var party));
            Assert.AreEqual(2066, PokeLayout.PartySize);
            Assert.AreEqual(2066, party.Size);
            Assert.IsTrue(SaveLayout.TryGetField("boxTray", out var tray));
            Assert.AreEqual(PokeLayout.TrayCount * PokeLayout.TrayStride, tray.Size);
            Assert.IsTrue(SaveLayout.TryGetField("boxData", out var box));
            Assert.AreEqual(PokeLayout.BoxDataSize, box.Size);
        }

        [Test]
        public void EmptySlotHasSeedZeroAndNoCalcData()
        {
            var slot = PokemonParam.CreateEmpty().ToSlot();
            Assert.AreEqual(PokeLayout.SlotSize, slot.Length);
            for (int i = 0; i < 8; i++) Assert.AreEqual(0, slot[i], "Kopf Byte " + i);
            for (int i = PokeLayout.CalcOffset; i < PokeLayout.SlotSize; i++) Assert.AreEqual(0, slot[i], "CalcData Byte " + i);
            // Der kodierte Bereich ist nicht 0: auch Nullen werden mit dem Strom des Seeds 0 verknüpft.
            int any = 0;
            for (int i = PokeLayout.EncodedOffset; i < PokeLayout.CoreSize; i++) any |= slot[i];
            Assert.AreNotEqual(0, any);
            var back = PokemonParam.FromSlot(slot);
            Assert.IsTrue(back.IsEmpty);
            Assert.IsTrue(back.ChecksumValid);
            Assert.IsFalse(back.HasCalcData);
        }

        [Test]
        public void FieldsSurviveEncodeDecodeForAllShuffleRows()
        {
            for (uint row = 0; row < 32; row++)
            {
                var p = Sample((row << 13) | 0x1357u);
                var slot = p.ToSlot();
                var q = PokemonParam.FromSlot(slot);
                Assert.IsTrue(q.ChecksumValid, "Zeile " + row);
                Assert.AreEqual(483, q.Core.SpeciesNo);
                Assert.AreEqual(234, q.Core.HeldItem);
                Assert.AreEqual(0xA1B2C3D4u, q.Core.TrainerId);
                Assert.AreEqual(125000u, q.Core.Exp);
                Assert.AreEqual("Testwesen", q.Core.Nickname);
                Assert.AreEqual("Spieler", q.Core.TrainerName);
                Assert.AreEqual(89, q.Core.GetMove(3));
                Assert.AreEqual(3, q.Core.GetPpUps(0));
                Assert.AreEqual(100, q.Core.CurrentHp);
                Assert.AreEqual(5, q.Core.MetLevel);
                Assert.AreEqual(1, q.Core.TrainerSex);
                Assert.AreEqual(0x0102030405060708UL, q.Core.BankUniqueId);
                Assert.AreEqual(50, q.Level);
                Assert.AreEqual(207, q.MaxHp);
                CollectionAssert.AreEqual(slot, q.ToSlot());
            }
        }

        [Test]
        public void EncodedBytesDoNotContainTheNickname()
        {
            var slot = Sample().ToSlot();
            var s = ToHex(slot);
            // "T" "e" als UTF-16 (54 00 65 00) darf im kodierten Slot nicht im Klartext stehen
            Assert.IsFalse(s.Contains("54006500"));
        }

        [Test]
        public void CorruptedBlockIsDetectedAndStoredChecksumIsKept()
        {
            var slot = Sample().ToSlot();
            slot[100] ^= 0x10;
            var p = PokemonParam.FromSlot(slot);
            Assert.IsFalse(p.ChecksumValid);
            Assert.IsFalse(p.Core.IsBadEgg);
            CollectionAssert.AreEqual(slot, p.ToSlot(false), "ohne Neuberechnung bleibt die gespeicherte Prüfsumme");
            Assert.AreNotEqual(ToHex(slot), ToHex(p.ToSlot(true)));
            var bad = PokemonParam.FromSlot(slot, 0, true);
            Assert.IsTrue(bad.Core.IsBadEgg, "Spiel setzt bei falscher Prüfsumme das Bad-Egg-Bit");
        }

        [Test]
        public void ChecksumCoversAllFourBlocks()
        {
            var slot = Sample().ToSlot();
            for (int pos = PokeLayout.EncodedOffset; pos < PokeLayout.CoreSize; pos += 37)
            {
                var copy = (byte[])slot.Clone();
                copy[pos] ^= 1;
                Assert.IsFalse(PokemonParam.FromSlot(copy).ChecksumValid, "Byte " + pos);
            }
            // CalcData ist nicht in der Prüfsumme
            var c2 = (byte[])slot.Clone();
            c2[PokeLayout.CalcOffset + 2] ^= 1;
            Assert.IsTrue(PokemonParam.FromSlot(c2).ChecksumValid);
        }

        [Test]
        public void ReseedPreservingBlocksKeepsAllFields()
        {
            var a = Sample(0x0000);
            var b = Sample(0x0000);
            b.Core.ReseedPreservingBlocks(0x5A5Au << 13 | 0x0321);
            Assert.AreEqual(a.Core.SpeciesNo, b.Core.SpeciesNo);
            Assert.AreEqual(a.Core.Nickname, b.Core.Nickname);
            Assert.AreEqual(a.Core.TrainerName, b.Core.TrainerName);
            Assert.AreEqual(a.Core.BankUniqueId, b.Core.BankUniqueId);
            Assert.AreEqual(a.Core.GetEv(StatId.Atk), b.Core.GetEv(StatId.Atk));
            Assert.AreNotEqual(ToHex(a.ToSlot()), ToHex(b.ToSlot()));
            var c = PokemonParam.FromSlot(b.ToSlot());
            Assert.AreEqual("Testwesen", c.Core.Nickname);
            Assert.IsTrue(c.ChecksumValid);
        }

        [Test]
        public void RawSeedChangeDoesNotMoveBlocksLikeTheGame()
        {
            var p = Sample(0);
            p.Core.PersonalRnd = 6u << 13;  // andere Zeile der Mischtabelle
            Assert.AreNotEqual(483, p.Core.SpeciesNo);
        }

        [Test]
        public void NamesAreLimitedToTwelveCharactersAndZeroPadded()
        {
            var c = new CoreParam();
            c.Nickname = "ABCDEFGHIJKLMNOP";
            Assert.AreEqual("ABCDEFGHIJKL", c.Nickname);
            c.Nickname = "Kurz";
            Assert.AreEqual("Kurz", c.Nickname);
            var plain = c.ToPlain();
            int o = PokeEncoder.BlockOffset(c.PersonalRnd, CoreBlock.B) + PokeLayout.B.Nickname;
            for (int i = 8; i < PokeLayout.NameBytes; i++) Assert.AreEqual(0, plain[o + i]);
            c.Nickname = null;
            Assert.AreEqual("", c.Nickname);
            c.Nickname = "Ab\0cd";
            Assert.AreEqual("Ab", c.Nickname);
        }

        [Test]
        public void IvFieldsAreIndependentFiveBitValues()
        {
            var c = new CoreParam();
            var stats = (StatId[])Enum.GetValues(typeof(StatId));
            uint value = 1;
            foreach (var s in stats) c.SetNativeIv(s, value++ * 5);
            value = 1;
            foreach (var s in stats) Assert.AreEqual(value++ * 5, c.GetNativeIv(s), s.ToString());
            c.SetNativeIv(StatId.Atk, 0xFF);
            Assert.AreEqual(31u, c.GetNativeIv(StatId.Atk));
            Assert.AreEqual(5u, c.GetNativeIv(StatId.Hp));
            Assert.AreEqual(15u, c.GetNativeIv(StatId.Def));
            c.IsEgg = true;
            c.HasNickname = true;
            Assert.AreEqual(0xC0000000u, c.IvBits & 0xC0000000u);
            Assert.AreEqual(31u, c.GetNativeIv(StatId.Atk));
            c.IsEgg = false;
            Assert.IsTrue(c.HasNickname);
            Assert.AreEqual(0u, c.IvBits >> 30 & 1);
            Assert.AreEqual(0, CoreParam.IvShift(StatId.Hp));
            Assert.AreEqual(15, CoreParam.IvShift(StatId.Speed));
        }

        [Test]
        public void TrainingFlagMakesTheEffectiveIvThirtyOne()
        {
            var c = new CoreParam();
            c.SetNativeIv(StatId.SpAtk, 3);
            Assert.AreEqual(3u, c.GetEffectiveIv(StatId.SpAtk));
            c.TrainingFlags = 1 << (int)StatId.SpAtk;
            Assert.AreEqual(31u, c.GetEffectiveIv(StatId.SpAtk));
            Assert.AreEqual(3u, c.GetNativeIv(StatId.SpAtk));
            Assert.AreEqual(0u, c.GetEffectiveIv(StatId.Hp));
        }

        [Test]
        public void RibbonsAndBitFieldsAddressEveryBit()
        {
            var c = new CoreParam();
            for (int i = 0; i < 128; i++)
            {
                c.SetRibbon(i, true);
                for (int j = 0; j < 128; j++) Assert.AreEqual(j <= i, c.HasRibbon(j), $"nach Band {i}: {j}");
            }
            c.RemoveAllRibbons();
            for (int i = 0; i < 128; i++) Assert.IsFalse(c.HasRibbon(i));
            for (int i = 0; i < 0x70; i++)
            {
                c.SetMoveRecordFlag(i, true);
                c.SetPokeJobFlag(i, i % 3 == 0);
            }
            for (int i = 0; i < 0x70; i++)
            {
                Assert.IsTrue(c.GetMoveRecordFlag(i));
                Assert.AreEqual(i % 3 == 0, c.GetPokeJobFlag(i));
            }
            c.ClearMoveRecordFlags();
            Assert.IsFalse(c.GetMoveRecordFlag(0x6F));
            Assert.Throws<ArgumentOutOfRangeException>(() => c.SetRibbon(128, true));
            Assert.Throws<ArgumentOutOfRangeException>(() => c.GetMoveRecordFlag(0x70));
            Assert.Throws<ArgumentOutOfRangeException>(() => c.GetMove(4));
            Assert.Throws<ArgumentOutOfRangeException>(() => c.SetPp(-1, 0));
        }

        [Test]
        public void FriendshipFollowsTheOwner()
        {
            var c = new CoreParam();
            c.OriginalFriendship = 70;
            c.OthersFriendship = 120;
            Assert.AreEqual(70, c.Friendship);
            c.OwnedByOthers = true;
            Assert.AreEqual(120, c.Friendship);
            c.Friendship = 200;
            Assert.AreEqual(200, c.OthersFriendship);
            Assert.AreEqual(70, c.OriginalFriendship);
        }

        [Test]
        public void SexMetLevelAndTrainerSexShareBitsCorrectly()
        {
            var c = new CoreParam();
            c.Sex = 7;
            Assert.AreEqual(3, c.Sex);
            c.IsEventPokemon = true;
            c.OfficialBattleEnabled = true;
            Assert.AreEqual(3, c.Sex);
            c.Sex = 0;
            Assert.IsTrue(c.IsEventPokemon && c.OfficialBattleEnabled);
            c.MetLevel = 0xFF;
            c.TrainerSex = 1;
            Assert.AreEqual(0x7F, c.MetLevel);
            c.TrainerSex = 0;
            Assert.AreEqual(0x7F, c.MetLevel);
            c.MetLevel = 3;
            c.TrainerSex = 1;
            Assert.AreEqual(3, c.MetLevel);
        }

        // ---- Berechnete Werte ---------------------------------------------------------------------------------------

        static SpeciesRecord Species(int hp, int atk, int def, int spa, int spd, int spe) => new SpeciesRecord
        {
            BaseHp = hp,
            BaseAttack = atk,
            BaseDefense = def,
            BaseSpAttack = spa,
            BaseSpDefense = spd,
            BaseSpeed = spe,
        };

        static List<uint> ExpTable(int curve)
        {
            var t = new List<uint> { 0 };
            for (int l = 1; l <= 100; l++) t.Add((uint)GrowthRate.ExpForLevel(curve, l));
            return t;
        }

        [Test]
        public void StatsFollowTheClassicFormulaWithNatureAdjust()
        {
            var p = new PokemonParam();
            p.Core.SpeciesNo = 100;
            foreach (StatId s in Enum.GetValues(typeof(StatId))) { p.Core.SetNativeIv(s, 31); p.Core.SetEv(s, 252); }
            var sp = Species(100, 100, 100, 100, 100, 100);
            var neutral = p.CalcStats(sp, 50);
            Assert.AreEqual(207, neutral.Hp);
            Assert.AreEqual(152, neutral.Attack);
            Assert.AreEqual(152, neutral.Speed);
            p.Core.NatureAdjust = 1; // +Angriff, -Verteidigung
            var lonely = p.CalcStats(sp, 50);
            Assert.AreEqual(167, lonely.Attack);
            Assert.AreEqual(136, lonely.Defense);
            Assert.AreEqual(152, lonely.SpAttack);
            // Das Grundwesen ändert die Werte nicht, nur NatureAdjust zählt.
            p.Core.NatureAdjust = 0;
            p.Core.Nature = 1;
            Assert.AreEqual(152, p.CalcStats(sp, 50).Attack);
        }

        [Test]
        public void StatsUseTrainingFlagsAndFixedHpSpecies()
        {
            var p = new PokemonParam();
            p.Core.SpeciesNo = 292;
            var sp = Species(1, 90, 45, 30, 30, 40);
            Assert.AreEqual(1, p.CalcStats(sp, 50).Hp);
            p.Core.SpeciesNo = 25;
            p.Core.SetNativeIv(StatId.Atk, 0);
            int plain = p.CalcStats(Species(35, 55, 40, 50, 50, 90), 50).Attack;
            p.Core.TrainingFlags = 1 << (int)StatId.Atk;
            int trained = p.CalcStats(Species(35, 55, 40, 50, 50, 90), 50).Attack;
            Assert.AreEqual(plain + 15, trained);  // IV 31 statt 0 bei Level 50: (31 * 50) / 100 = 15
        }

        [Test]
        public void RecalculateCalcDataMovesCurrentHpWithMaxHp()
        {
            var exps = ExpTable(0);
            var sp = Species(100, 100, 100, 100, 100, 100);
            var p = new PokemonParam();
            p.Core.SpeciesNo = 100;
            foreach (StatId s in Enum.GetValues(typeof(StatId))) { p.Core.SetNativeIv(s, 31); p.Core.SetEv(s, 252); }
            p.Core.Exp = exps[50];
            p.MaxHp = 100;
            p.Core.CurrentHp = 80;
            p.RecalculateCalcData(sp, exps);
            Assert.AreEqual(50, p.Level);
            Assert.AreEqual(207, p.MaxHp);
            Assert.AreEqual(187, p.Core.CurrentHp);  // 80 - 100 + 207
            Assert.AreEqual(152, p.Atk);
            Assert.AreEqual(152, p.Speed);
            // Max-KP sinken: aktuelle KP werden begrenzt
            p.Core.Exp = exps[20];
            p.RecalculateCalcData(sp, exps);
            Assert.AreEqual(20, p.Level);
            Assert.LessOrEqual(p.Core.CurrentHp, p.MaxHp);
            // Kampfunfähig bleibt kampfunfähig, wenn gewünscht
            p.Core.CurrentHp = 0;
            p.Core.Exp = exps[60];
            p.RecalculateCalcData(sp, exps, keepFainted: true);
            Assert.AreEqual(0, p.Core.CurrentHp);
            Assert.AreEqual(60, p.Level);
        }

        [Test]
        public void LevelFromExpUsesTheGrowthTable()
        {
            var exps = ExpTable(4);
            var p = new PokemonParam();
            p.Core.Exp = 0;
            Assert.AreEqual(1, p.LevelFromExp(exps));
            p.Core.Exp = exps[37];
            Assert.AreEqual(37, p.LevelFromExp(exps));
            p.Core.Exp = exps[37] - 1;
            Assert.AreEqual(36, p.LevelFromExp(exps));
            p.Core.Exp = uint.MaxValue;
            Assert.AreEqual(100, p.LevelFromExp(exps));
            Assert.AreEqual(exps[100], PokemonParam.ExpForLevel(exps, 150));
        }

        [Test]
        public void MaxPpGrowsByTwentyPercentPerPpUp()
        {
            Assert.AreEqual(5, PokemonParam.MaxPp(5, 0));
            Assert.AreEqual(16, PokemonParam.MaxPp(10, 3));
            Assert.AreEqual(21, PokemonParam.MaxPp(15, 2));
            Assert.AreEqual(64, PokemonParam.MaxPp(40, 3));
            Assert.AreEqual(64, PokemonParam.MaxPp(40, 9));
            Assert.AreEqual(24, PokemonParam.MaxPp(20, 1));
        }

        [Test]
        public void RareColorUsesTrainerIdAndColorRnd()
        {
            Assert.IsTrue(PokemonParam.IsRareColor(0, 0));
            Assert.IsFalse(PokemonParam.IsRareColor(0x10, 0));
            Assert.IsTrue(PokemonParam.IsRareColor(0x12345678, 0x12345678 ^ 0x0005));
            var p = new PokemonParam();
            Assert.IsTrue(p.IsRare);
            p.Core.ColorRnd = 0xFFF0;
            Assert.IsFalse(p.IsRare);
        }

        // ---- Spielstand ---------------------------------------------------------------------------------------------

        [Test]
        public void SaveSlotsReadAndWriteParty()
        {
            var save = NewSave();
            var a = Sample(0x2000);
            var b = Sample(0x4000);
            b.Core.SpeciesNo = 25;
            PokeSaveSlots.WriteParty(save, 0, a);
            PokeSaveSlots.WriteParty(save, 5, b);
            PokeSaveSlots.SetPartyCount(save, 2);
            Assert.AreEqual(2, PokeSaveSlots.PartyCount(save));
            Assert.AreEqual(483, PokeSaveSlots.ReadParty(save, 0).Core.SpeciesNo);
            Assert.AreEqual(25, PokeSaveSlots.ReadParty(save, 5).Core.SpeciesNo);
            Assert.IsTrue(PokeSaveSlots.ReadParty(save, 3).IsEmpty);
            Assert.Throws<ArgumentOutOfRangeException>(() => PokeSaveSlots.ReadParty(save, 6));
            Assert.AreEqual(0, PokeSaveSlots.PartyMarkingIndex(save));
        }

        [Test]
        public void SaveSlotsReadAndWriteBoxesAtTheEdges()
        {
            var save = NewSave();
            var p = Sample();
            PokeSaveSlots.WriteBox(save, 0, 0, p);
            PokeSaveSlots.WriteBox(save, 39, 29, p);
            SaveLayout.TryGetField("boxTray", out var tray);
            var raw = p.ToSlot();
            for (int i = 0; i < raw.Length; i++)
            {
                Assert.AreEqual(raw[i], save[tray.Offset + i]);
                Assert.AreEqual(raw[i], save[tray.Offset + 39 * PokeLayout.TrayStride + 29 * PokeLayout.SlotSize + i]);
            }
            Assert.AreEqual(483, PokeSaveSlots.ReadBox(save, 39, 29).Core.SpeciesNo);
            Assert.IsTrue(PokeSaveSlots.ReadBox(save, 1, 0).IsEmpty);
            Assert.Throws<ArgumentOutOfRangeException>(() => PokeSaveSlots.ReadBox(save, 40, 0));
            Assert.Throws<ArgumentOutOfRangeException>(() => PokeSaveSlots.WriteBox(save, 0, 30, p));
        }

        [Test]
        public void VerifyCountsSlotsAndRoundTripsExactly()
        {
            var save = NewSave();
            PokeSaveSlots.WriteParty(save, 0, Sample(0x2000));
            PokeSaveSlots.WriteBox(save, 3, 7, Sample(0x6000));
            PokeSaveSlots.WriteBox(save, 12, 29, Sample(0x1000));
            var before = (byte[])save.Clone();
            var report = PokeSaveSlots.Verify(save);
            Assert.AreEqual(6, report.PartySlots);
            Assert.AreEqual(1200, report.BoxSlots);
            Assert.AreEqual(1206, report.TotalSlots);
            Assert.AreEqual(3, report.NonEmptySlots);
            Assert.AreEqual(1206, report.ValidChecksums);
            Assert.AreEqual(1206, report.IdenticalAfterRoundTrip);
            CollectionAssert.AreEqual(before, save, "Verify verändert den Spielstand nicht");
            CollectionAssert.AreEqual(save, PokeSaveSlots.RewriteAll(save));
        }

        [Test]
        public void VerifyFlagsACorruptedSlot()
        {
            var save = NewSave();
            PokeSaveSlots.WriteBox(save, 2, 2, Sample());
            SaveLayout.TryGetField("boxTray", out var tray);
            save[tray.Offset + 2 * PokeLayout.TrayStride + 2 * PokeLayout.SlotSize + 50] ^= 0x01;
            var report = PokeSaveSlots.Verify(save);
            Assert.AreEqual(1205, report.ValidChecksums);
            Assert.AreEqual(1206, report.IdenticalAfterRoundTrip, "ohne Neuberechnung bleibt auch der defekte Slot unverändert");
            var rewritten = PokeSaveSlots.RewriteAll(save);
            CollectionAssert.AreNotEqual(save, rewritten, "RewriteAll berechnet die Prüfsumme neu");
        }

        [Test]
        public void ModifiedSaveNeedsAFreshFileHash()
        {
            var save = NewSave();
            Assert.IsTrue(SaveValidator.Validate(save).IsValid);
            PokeSaveSlots.WriteParty(save, 1, Sample());
            Assert.IsFalse(SaveValidator.Validate(save).IsValid);
            Assert.IsTrue(SaveValidator.Validate(SaveWriter.FixHash(save)).IsValid);
        }

        [Test]
        public void TrayMaxIsReadFromBoxData()
        {
            var save = NewSave();
            SaveLayout.TryGetField("boxData", out var box);
            save[box.Offset + PokeLayout.BoxDataSize - PokeLayout.BoxDataTrayMaxFromEnd] = 18;
            Assert.AreEqual(18, PokeSaveSlots.TrayMax(save));
        }

        [Test]
        public void ShortSaveIsRejected()
        {
            Assert.Throws<SaveFormatException>(() => PokeSaveSlots.Verify(new byte[1000]));
            Assert.Throws<ArgumentNullException>(() => PokeSaveSlots.Verify(null));
        }

        [Test]
        public void RandomizedCoreRoundTripsForManySeeds()
        {
            var rng = new Lcg(12345);
            for (int i = 0; i < 200; i++)
            {
                var plain = rng.Bytes(PokeLayout.CoreSize);
                var core = CoreParam.FromPlain(plain);
                var enc = new byte[PokeLayout.CoreSize];
                core.EncodeTo(enc, 0);
                var back = CoreParam.FromEncoded(enc, 0);
                Assert.IsTrue(back.ChecksumValid);
                var expected = (byte[])plain.Clone();
                expected[PokeLayout.ChecksumOffset] = (byte)core.ComputeChecksum();
                expected[PokeLayout.ChecksumOffset + 1] = (byte)(core.ComputeChecksum() >> 8);
                CollectionAssert.AreEqual(expected, back.ToPlain());
            }
        }
    }
}
