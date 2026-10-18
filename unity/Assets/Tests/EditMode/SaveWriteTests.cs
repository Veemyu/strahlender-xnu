using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using NUnit.Framework;
using Xnu.PokePara;
using Xnu.Save;
using static Xnu.Tests.SaveTestSupport;

namespace Xnu.Tests
{
    // Bearbeiten und Schreiben (SaveData, Erweiterungen in Xnu.PokePara). Synthetische Fixtures; die Tests am lokalen
    // Save (Real*) werden ohne Datei übersprungen und lesen/schreiben nie in den Originalordner.
    public class SaveWriteTests
    {
        string _tmp;

        [TearDown]
        public void TearDown() => Cleanup(_tmp);

        static (int, int) Player(int rel, int len) => (SavePlayerLayout.PlayerDataOffset + rel, SavePlayerLayout.PlayerDataOffset + rel + len);

        [Test]
        public void RoundTripWithoutChangeIsByteIdentical()
        {
            var orig = NewSave();
            var save = SaveData.FromBytes(orig);
            CollectionAssert.AreEqual(orig, save.ToBytes());
            Assert.IsTrue(save.IsHashValid);
        }

        [Test]
        public void FromBytesCopiesInputAndToBytesDoesNotMutate()
        {
            var orig = NewSave();
            var copy = (byte[])orig.Clone();
            var save = SaveData.FromBytes(orig);
            save.Money = 123;
            CollectionAssert.AreEqual(copy, orig);
            var bytes = save.ToBytes();
            Assert.IsFalse(save.IsHashValid);
            Assert.IsTrue(SaveValidator.Validate(bytes).IsValid);
            save.Seal();
            Assert.IsTrue(save.IsHashValid);
        }

        [Test]
        public void FromBytesRejectsWrongVersionSizeHash()
        {
            var good = NewSave();
            var old = (byte[])good.Clone();
            old[0] = 0x33;
            Assert.Throws<SaveFormatException>(() => SaveData.FromBytes(old));
            Assert.Throws<SaveFormatException>(() => SaveData.FromBytes(good.Take(good.Length - 1).ToArray()));
            var bad = (byte[])good.Clone();
            bad[SaveLayout.HashOffset] ^= 1;
            Assert.Throws<SaveFormatException>(() => SaveData.FromBytes(bad));
            Assert.IsNotNull(SaveData.FromBytes(bad, verifyHash: false));
            Assert.IsFalse(SaveData.TryFromBytes(new byte[2], out _));
        }

        [Test]
        public void MoneyChangesOnlyItsFourBytesAndTheHash()
        {
            var orig = NewSave();
            var save = SaveData.FromBytes(orig);
            save.Money = 999999;
            var after = save.ToBytes();
            var n = Diff(orig, after, new[] { Player(SavePlayerLayout.MoneyOffset, 4), HashRange }, out var outside);
            Assert.IsFalse(outside);
            Assert.LessOrEqual(n, 4 + 16);
            Assert.AreEqual(999999, SaveData.FromBytes(after).Money);
            Assert.Throws<ArgumentOutOfRangeException>(() => save.Money = 1000000);
            Assert.Throws<ArgumentOutOfRangeException>(() => save.Money = -1);
        }

        [Test]
        public void PlayerBasicsRoundTrip()
        {
            var orig = NewSave(2);
            var save = SaveData.FromBytes(orig);
            save.PlayerName = "Lüthien";
            save.TrainerId = 0xDEADBEEF;
            save.SexRaw = 1;
            save.PlayHours = 321;
            save.PlayMinutes = 59;
            save.PlaySeconds = 7;
            save.RivalName = "Rivale";
            var after = save.ToBytes();
            var allowed = new[]
            {
                Player(SavePlayerLayout.NameOffset, SavePlayerLayout.NameChars * 2),
                Player(SavePlayerLayout.TrainerIdOffset, 4), Player(SavePlayerLayout.SexOffset, 4),
                Player(SavePlayerLayout.PlayHoursOffset, 4),
                (SavePlayerLayout.RivalNameOffset, SavePlayerLayout.RivalNameOffset + SavePlayerLayout.RivalNameChars * 2),
                HashRange,
            };
            Diff(orig, after, allowed, out var outside);
            Assert.IsFalse(outside);
            var back = SaveData.FromBytes(after);
            Assert.AreEqual("Lüthien", back.PlayerName);
            Assert.AreEqual(0xDEADBEEF, back.TrainerId);
            Assert.AreEqual(1, back.SexRaw);
            Assert.AreEqual(321, back.PlayHours);
            Assert.AreEqual(59, back.PlayMinutes);
            Assert.AreEqual(7, back.PlaySeconds);
            Assert.AreEqual("Rivale", back.RivalName);
        }

        [Test]
        public void NameIsTerminatedAndRestZeroed()
        {
            var save = SaveData.FromBytes(NewSave(3));
            save.PlayerName = "Abcdefghijkl";
            Assert.AreEqual(12, save.PlayerName.Length);
            save.PlayerName = "Ab";
            var o = SavePlayerLayout.PlayerDataOffset + SavePlayerLayout.NameOffset;
            for (var i = 4; i < SavePlayerLayout.NameChars * 2; i++) Assert.AreEqual(0, save.Buffer[o + i], "Byte " + i);
            Assert.AreEqual("Ab", save.PlayerName);
            Assert.Throws<ArgumentException>(() => save.PlayerName = "Abcdefghijklm");
            Assert.Throws<ArgumentException>(() => save.PlayerName = "a\0b");
            Assert.Throws<ArgumentNullException>(() => save.PlayerName = null);
        }

        [Test]
        public void ValueRangesAreChecked()
        {
            var save = SaveData.FromBytes(NewSave());
            Assert.Throws<ArgumentOutOfRangeException>(() => save.PlayMinutes = 60);
            Assert.Throws<ArgumentOutOfRangeException>(() => save.PlaySeconds = -1);
            Assert.Throws<ArgumentOutOfRangeException>(() => save.PlayHours = 70000);
            Assert.Throws<ArgumentOutOfRangeException>(() => save.SexRaw = 2);
        }

        [Test]
        public void ItemCountChangesOnlyTheCountField()
        {
            var orig = NewSave(4);
            var save = SaveData.FromBytes(orig);
            var before = save.GetItem(17);
            save.SetItemCount(17, 99);
            Assert.AreEqual(99, save.GetItemCount(17));
            var after = save.GetItem(17);
            Assert.AreEqual(before.VanishNew, after.VanishNew);
            Assert.AreEqual(before.Favorite, after.Favorite);
            Assert.AreEqual(before.SortNumber, after.SortNumber);
            SaveLayout.TryGetField("saveItem", out var f);
            var o = f.Offset + 17 * SavePlayerLayout.ItemStride;
            Diff(orig, save.ToBytes(), new[] { (o, o + 4), HashRange }, out var outside);
            Assert.IsFalse(outside);
            Assert.Throws<ArgumentOutOfRangeException>(() => save.SetItemCount(17, 1000));
            Assert.Throws<ArgumentOutOfRangeException>(() => save.SetItemCount(3000, 1));
            Assert.Throws<ArgumentOutOfRangeException>(() => save.GetItemCount(-1));
        }

        [Test]
        public void PartyAndBoxEditsAreIsolatedAndReadBack()
        {
            var orig = NewSave(5);
            var save = SaveData.FromBytes(orig);
            Assert.AreEqual(1, save.PartyCount());
            save.SetParty(new[] { Sample(483), Sample(484, 0x00004000) });
            save.SetBox(3, 7, Sample(487, 0x0001A000));
            Assert.AreEqual(2, save.PartyCount());

            var after = save.ToBytes();
            SaveLayout.TryGetField("playerParty", out var party);
            SaveLayout.TryGetField("boxTray", out var tray);
            var boxOff = tray.Offset + 3 * PokeLayout.TrayStride + 7 * PokeLayout.SlotSize;
            Diff(orig, after, new[] { (party.Offset, party.End), (boxOff, boxOff + PokeLayout.SlotSize), HashRange }, out var outside);
            Assert.IsFalse(outside);

            var back = SaveData.FromBytes(after);
            Assert.AreEqual(483, back.GetPartyMember(0).Core.SpeciesNo);
            Assert.AreEqual(484, back.GetPartyMember(1).Core.SpeciesNo);
            Assert.IsTrue(back.GetPartyMember(2).IsEmpty);
            Assert.AreEqual(487, back.GetBox(3, 7).Core.SpeciesNo);
            Assert.AreEqual("Testwesen", back.GetBox(3, 7).Core.Nickname);
            var report = back.VerifySlots();
            Assert.AreEqual(report.TotalSlots, report.ValidChecksums);
            Assert.AreEqual(3, report.NonEmptySlots);

            back.ClearBox(3, 7);
            Assert.IsTrue(back.GetBox(3, 7).IsEmpty);
            Assert.Throws<ArgumentOutOfRangeException>(() => back.SetParty(new PokemonParam[0]));
            Assert.Throws<ArgumentOutOfRangeException>(() => back.SetBox(40, 0, Sample()));
            Assert.Throws<ArgumentOutOfRangeException>(() => back.SetBox(0, 30, Sample()));
        }

        [Test]
        public void EditedSaveSurvivesAtomicWriteAndReload()
        {
            _tmp = NewTempDir();
            var save = SaveData.FromBytes(NewSave(6));
            save.Money = 5000;
            save.SetItemCount(4, 42);
            var path = Path.Combine(_tmp, "SaveData.bin");
            SaveFileIO.WriteAtomic(path, save.ToBytes());
            var loaded = SaveData.FromBytes(File.ReadAllBytes(path));
            Assert.AreEqual(5000, loaded.Money);
            Assert.AreEqual(42, loaded.GetItemCount(4));
        }

        // ---- lokaler echter Save (nur lesend; Schreiben in ein Wegwerfverzeichnis) ----

        [TestCase("SaveData.bin")]
        [TestCase("Backup.bin")]
        public void RealSaveRoundTripIsByteIdentical(string file)
        {
            var orig = RequireRealSave(out _, file);
            var save = SaveData.FromBytes(orig);
            var bytes = save.ToBytes();
            Assert.AreEqual(orig.Length, bytes.Length);
            Assert.IsTrue(orig.AsSpan().SequenceEqual(bytes), "Bytes");
            using (var sha = SHA256.Create())
                CollectionAssert.AreEqual(sha.ComputeHash(orig), sha.ComputeHash(bytes), "SHA-256");
            Assert.IsTrue(save.IsHashValid);
        }

        [Test]
        public void RealSaveSlotRewriteThroughSaveDataIsIdentical()
        {
            var orig = RequireRealSave(out _);
            var save = SaveData.FromBytes(orig);
            for (var i = 0; i < PokeLayout.PartyCapacity; i++) save.SetPartyMember(i, save.GetPartyMember(i));
            for (var t = 0; t < PokeLayout.TrayCount; t++)
                for (var p = 0; p < PokeLayout.TraySlots; p++)
                    save.SetBox(t, p, save.GetBox(t, p));
            Assert.IsTrue(orig.AsSpan().SequenceEqual(save.ToBytes()));
            var r = save.VerifySlots();
            Assert.AreEqual(1206, r.TotalSlots);
            Assert.AreEqual(r.TotalSlots, r.ValidChecksums);
            Assert.AreEqual(r.TotalSlots, r.IdenticalAfterRoundTrip);
        }

        [Test]
        public void RealSaveEditsTouchOnlyTheirBytesAndCanBeRestored()
        {
            var orig = RequireRealSave(out _);
            _tmp = NewTempDir();
            var save = SaveData.FromBytes(orig);
            var money = save.Money;
            var trainerId = save.TrainerId;
            var hours = save.PlayHours;
            var itemNo = Enumerable.Range(0, 3000).First(i => save.GetItemCount(i) > 0 && save.GetItemCount(i) < 900);
            var itemCount = save.GetItemCount(itemNo);
            var first = save.GetPartyMember(0);
            var heldItem = first.Core.HeldItem;

            Assert.That(money, Is.InRange(0, SavePlayerLayout.MaxMoney));
            Assert.That(save.PlayMinutes, Is.InRange(0, 59));
            Assert.That(save.PlayerName.Length, Is.InRange(1, SavePlayerLayout.MaxNameLength));
            Assert.AreEqual(6, save.PartyCount());

            save.Money = money == 12345 ? 12346 : 12345;
            save.SetItemCount(itemNo, itemCount + 1);
            save.PlayHours = hours + 1;
            first.Core.HeldItem = (ushort)(heldItem == 1 ? 2 : 1);
            save.SetPartyMember(0, first);
            var changed = save.ToBytes();

            SaveLayout.TryGetField("saveItem", out var items);
            SaveLayout.TryGetField("playerParty", out var party);
            var io = items.Offset + itemNo * SavePlayerLayout.ItemStride;
            var n = Diff(orig, changed, new[]
            {
                Player(SavePlayerLayout.MoneyOffset, 4), Player(SavePlayerLayout.PlayHoursOffset, 2), (io, io + 4),
                (party.Offset, party.Offset + PokeLayout.SlotSize), HashRange,
            }, out var outside);
            Assert.IsFalse(outside);
            Assert.Greater(n, 0);

            var path = Path.Combine(_tmp, "SaveData.bin");
            SaveFileIO.WriteAtomic(path, changed);
            var loaded = SaveData.FromBytes(File.ReadAllBytes(path));
            Assert.AreNotEqual(money, loaded.Money);
            Assert.AreEqual(itemCount + 1, loaded.GetItemCount(itemNo));
            Assert.AreEqual(hours + 1, loaded.PlayHours);
            Assert.AreEqual(trainerId, loaded.TrainerId);
            Assert.IsTrue(loaded.GetPartyMember(0).ChecksumValid);

            loaded.Money = money;
            loaded.SetItemCount(itemNo, itemCount);
            loaded.PlayHours = hours;
            var restored = loaded.GetPartyMember(0);
            restored.Core.HeldItem = heldItem;
            loaded.SetPartyMember(0, restored);
            Assert.IsTrue(orig.AsSpan().SequenceEqual(loaded.ToBytes()), "nach Rückstellen identisch zum Original");
        }

        [Test]
        public void RealSaveNameEditStaysInsideTheNameField()
        {
            var orig = RequireRealSave(out _);
            var save = SaveData.FromBytes(orig);
            save.PlayerName = "Xnu";
            var n = Diff(orig, save.ToBytes(), new[] { Player(SavePlayerLayout.NameOffset, SavePlayerLayout.NameChars * 2), HashRange }, out var outside);
            Assert.IsFalse(outside);
            Assert.Greater(n, 0);
            Assert.AreEqual("Xnu", SaveData.FromBytes(save.ToBytes()).PlayerName);
        }
    }
}
