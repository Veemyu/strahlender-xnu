using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using NUnit.Framework;
using Xnu.Save;
using static Xnu.Tests.SaveTestSupport;

namespace Xnu.Tests
{
    // Ordnerkonventionen, Erkennen/Validieren, Backup und atomares Schreiben. Synthetische Verzeichnisbäume unter einem
    // Wegwerfordner; der Test am lokalen Save (Real*) liest nur und wird ohne Datei übersprungen.
    public class SaveStorageTests
    {
        string _tmp;

        [SetUp]
        public void SetUp() => _tmp = NewTempDir();

        [TearDown]
        public void TearDown() => Cleanup(_tmp);

        string Dir(params string[] parts)
        {
            var d = Path.Combine(new[] { _tmp }.Concat(parts).ToArray());
            Directory.CreateDirectory(d);
            return d;
        }

        static string Put(string dir, string name, byte[] data)
        {
            var p = Path.Combine(dir, name);
            File.WriteAllBytes(p, data);
            return p;
        }

        // ---- Erkennen ----

        [Test]
        public void RyujinxLayoutIsDetected()
        {
            var d = Dir("Ryujinx", "bis", "user", "save", "0000000000000006", "0");
            Put(d, "SaveData.bin", NewSave(1));
            Put(d, "Backup.bin", NewSave(2));
            var ins = SaveInspector.Inspect(d);
            Assert.AreEqual(SaveHostKind.Ryujinx, ins.Kind);
            Assert.AreEqual(6UL, ins.SaveId);
            Assert.IsTrue(ins.Main.IsValid);
            Assert.IsTrue(ins.Backup.IsValid);
            Assert.IsTrue(ins.HasUsableSave);

            // Save-ID-Ordner führt zum Unterordner „0“.
            var viaId = SaveInspector.Inspect(Path.GetDirectoryName(d));
            Assert.AreEqual(SaveHostKind.Ryujinx, viaId.Kind);
            Assert.AreEqual(Path.GetFullPath(d), viaId.Path);
        }

        [Test]
        public void YuzuCheckpointAndJksvLayoutsAreDetected()
        {
            var user = new string('A', 32);
            var y = Dir("yuzu", "nand", "user", "save", "0000000000000000", user, BrilliantDiamond.ToLowerInvariant());
            Put(y, "SaveData.bin", NewSave());
            var yi = SaveInspector.Inspect(y);
            Assert.AreEqual(SaveHostKind.Yuzu, yi.Kind);
            Assert.AreEqual(BrilliantDiamond, yi.TitleId);
            Assert.AreEqual("Pokémon Brilliant Diamond", yi.TitleName);
            Assert.AreEqual(user, yi.UserId);

            var c = Dir("sd", "switch", "Checkpoint", "saves", "0x" + BrilliantDiamond + " Pokemon Brilliant Diamond", "20230707-Nutzer");
            Put(c, "SaveData.bin", NewSave());
            var ci = SaveInspector.Inspect(c);
            Assert.AreEqual(SaveHostKind.Checkpoint, ci.Kind);
            Assert.AreEqual(BrilliantDiamond, ci.TitleId);

            var j = Dir("sd2", "JKSV", "Pokemon Brilliant Diamond", "Backup 1");
            Put(j, "SaveData.bin", NewSave());
            Put(j, "Backup.bin", NewSave());
            Assert.AreEqual(SaveHostKind.Jksv, SaveInspector.Inspect(j).Kind);
        }

        [Test]
        public void OtherTitleIsNotedAndPlainFolderIsGeneric()
        {
            var y = Dir("nand", "user", "save", "0000000000000000", new string('B', 32), "0100000000010000");
            Put(y, "SaveData.bin", NewSave());
            var yi = SaveInspector.Inspect(y);
            Assert.AreEqual(SaveHostKind.Yuzu, yi.Kind);
            Assert.IsNull(yi.TitleName);
            Assert.IsTrue(yi.Notes.Any(n => n.Contains("nicht Brilliant")));

            var g = Dir("irgendwo");
            Put(g, "SaveData.bin", NewSave());
            Assert.AreEqual(SaveHostKind.Folder, SaveInspector.Inspect(g).Kind);
        }

        [Test]
        public void InvalidAndMissingFilesAreReportedNotThrown()
        {
            var d = Dir("kaputt");
            var good = NewSave();
            var badHash = (byte[])good.Clone();
            badHash[SaveLayout.HashOffset + 3] ^= 0xFF;
            Put(d, "SaveData.bin", badHash);
            Put(d, "Backup.bin", good.Take(1000).ToArray());
            Put(d, "rp0001.dat", new byte[10]);
            var ins = SaveInspector.Inspect(d);
            Assert.IsFalse(ins.Main.IsValid);
            Assert.IsFalse(ins.Backup.IsValid);
            Assert.IsFalse(ins.HasUsableSave);
            Assert.IsTrue(ins.Notes.Any(n => n.Contains("rp0001.dat")));
            Assert.Throws<SaveFormatException>(() => SaveInspector.ReadBest(ins));

            var empty = SaveInspector.Inspect(Dir("leer"));
            Assert.AreEqual(SaveHostKind.Unknown, empty.Kind);
            Assert.IsFalse(empty.HasUsableSave);
            Assert.AreEqual(SaveHostKind.Unknown, SaveInspector.Inspect(Path.Combine(_tmp, "gibt-es-nicht")).Kind);
        }

        [Test]
        public void ReadBestFallsBackToBackupAndHonoursPreference()
        {
            var d = Dir("fallback");
            var main = NewSave(1);
            var backup = NewSave(2);
            var broken = (byte[])main.Clone();
            broken[100] ^= 1;
            Put(d, "SaveData.bin", broken);
            Put(d, "Backup.bin", backup);
            CollectionAssert.AreEqual(backup, SaveInspector.ReadBest(SaveInspector.Inspect(d)));

            Put(d, "SaveData.bin", main);
            var ins = SaveInspector.Inspect(d);
            CollectionAssert.AreEqual(main, SaveInspector.ReadBest(ins));
            CollectionAssert.AreEqual(backup, SaveInspector.ReadBest(ins, preferBackup: true));
        }

        [Test]
        public void LooseFileAndZipAreRecognised()
        {
            var data = NewSave(3);
            var f = Put(_tmp, "meinexport.sav", data);
            var li = SaveInspector.Inspect(f);
            Assert.AreEqual(SaveHostKind.LooseFile, li.Kind);
            Assert.IsTrue(li.Main.IsValid);
            CollectionAssert.AreEqual(data, SaveInspector.ReadBest(li));

            var zipPath = Path.Combine(_tmp, "backup.zip");
            using (var z = ZipFile.Open(zipPath, ZipArchiveMode.Create))
            {
                var e = z.CreateEntry("Pokemon/SaveData.bin");
                using (var s = e.Open()) s.Write(data, 0, data.Length);
                var e2 = z.CreateEntry("Pokemon/Backup.bin");
                using (var s = e2.Open()) s.Write(data, 0, 100);
            }
            var zi = SaveInspector.Inspect(zipPath);
            Assert.AreEqual(SaveHostKind.ZipArchive, zi.Kind);
            Assert.IsTrue(zi.Main.IsValid);
            Assert.IsFalse(zi.Backup.IsValid);
            CollectionAssert.AreEqual(data, SaveInspector.ReadBest(zi));

            var junk = Path.Combine(_tmp, "kaputt.zip");
            File.WriteAllBytes(junk, new byte[50]);
            Assert.IsFalse(SaveInspector.Inspect(junk).HasUsableSave);
        }

        [Test]
        public void OversizedFilesAreRefusedWithoutReadingEverything()
        {
            var f = Path.Combine(_tmp, "riesig.bin");
            using (var fs = File.Create(f)) fs.SetLength(SaveFileIO.MaxFileSize + 10);
            var ins = SaveInspector.Inspect(f);
            Assert.IsFalse(ins.HasUsableSave);
            Assert.IsNull(ins.Main.Validation);
        }

        [Test]
        public void FindIsBoundedAndFindsNestedSaves()
        {
            Put(Dir("a", "b", "0"), "SaveData.bin", NewSave());
            Put(Dir("c"), "Backup.bin", NewSave());
            Dir("a", "x", "y", "z", "w", "v", "u", "t");
            Assert.AreEqual(2, SaveInspector.Find(_tmp).Count);
            Assert.AreEqual(1, SaveInspector.Find(_tmp, maxResults: 1).Count);
            Assert.AreEqual(1, SaveInspector.Find(_tmp, maxDepth: 1).Count);
            Assert.AreEqual(0, SaveInspector.Find(Path.Combine(_tmp, "nope")).Count);
        }

        // ---- Ryujinx-Index ----

        [Test]
        public void RyujinxIndexIsParsedAndMapsTitleToSaveDirectories()
        {
            var root = Dir("Ryujinx");
            var idx = Dir("Ryujinx", "bis", "system", "save", "8000000000000000", "0");
            File.WriteAllBytes(Path.Combine(idx, "imkvdb.arc"), BuildIndex(
                (0x0100000011D90000UL, 1, 7), (0x0100000011D90000UL, 1, 6), (0x0100000011D90000UL, 2, 12), (0x01007EF00011E000UL, 1, 13)));
            Dir("Ryujinx", "bis", "user", "save", "0000000000000006", "0");
            Dir("Ryujinx", "bis", "user", "save", "0000000000000007", "0");
            var entries = RyujinxSaveIndex.Load(root);
            Assert.AreEqual(4, entries.Count);
            Assert.AreEqual("0100000011D90000", entries[0].ProgramIdHex);
            var dirs = RyujinxSaveIndex.FindSaveDirectories(root, BrilliantDiamond);
            Assert.AreEqual(2, dirs.Count);
            Assert.IsTrue(dirs.Any(d => d.EndsWith("0000000000000006")));
            Assert.AreEqual(0, RyujinxSaveIndex.FindSaveDirectories(root, "0100000000010000").Count);
        }

        [Test]
        public void MalformedIndexIsRejected()
        {
            Assert.Throws<SaveFormatException>(() => RyujinxSaveIndex.Parse(new byte[4]));
            var good = BuildIndex((1UL, 1, 1));
            var bad = (byte[])good.Clone();
            bad[12] = (byte)'X';
            Assert.Throws<SaveFormatException>(() => RyujinxSaveIndex.Parse(bad));
            var big = (byte[])good.Clone();
            big[16] = 0xFF;
            big[17] = 0xFF;
            Assert.Throws<SaveFormatException>(() => RyujinxSaveIndex.Parse(big));
            Assert.AreEqual(0, RyujinxSaveIndex.Parse(BuildIndex()).Count);
        }

        // ---- Schreiben ----

        [Test]
        public void WriteAtomicCreatesNewFileWithoutLeftovers()
        {
            var data = NewSave();
            var path = Path.Combine(_tmp, "SaveData.bin");
            var r = SaveFileIO.WriteAtomic(path, data);
            Assert.IsNull(r.BackupPath);
            Assert.AreEqual(data.Length, r.Bytes);
            CollectionAssert.AreEqual(data, File.ReadAllBytes(path));
            Assert.AreEqual(1, Directory.GetFileSystemEntries(_tmp).Length);
        }

        [Test]
        public void OverwriteRequiresBackupDirectoryAndKeepsOldContent()
        {
            var oldData = NewSave(1);
            var newData = NewSave(2);
            var path = Path.Combine(_tmp, "SaveData.bin");
            File.WriteAllBytes(path, oldData);

            Assert.Throws<InvalidOperationException>(() => SaveFileIO.WriteAtomic(path, newData));
            CollectionAssert.AreEqual(oldData, File.ReadAllBytes(path));

            var backups = Path.Combine(_tmp, "bk");
            var now = new DateTime(2026, 1, 2, 3, 4, 5, DateTimeKind.Utc);
            var r = SaveFileIO.WriteAtomic(path, newData, new SaveWriteOptions { BackupDirectory = backups, Clock = () => now });
            CollectionAssert.AreEqual(newData, File.ReadAllBytes(path));
            CollectionAssert.AreEqual(oldData, File.ReadAllBytes(r.BackupPath));
            StringAssert.Contains("20260102T030405000Z", r.BackupPath);

            // gleicher Zeitstempel → eigener Ordner, kein Überschreiben des Backups
            var r2 = SaveFileIO.WriteAtomic(path, oldData, new SaveWriteOptions { BackupDirectory = backups, Clock = () => now });
            Assert.AreNotEqual(r.BackupPath, r2.BackupPath);
            CollectionAssert.AreEqual(newData, File.ReadAllBytes(r2.BackupPath));
            CollectionAssert.AreEqual(oldData, File.ReadAllBytes(r.BackupPath));
            Assert.IsFalse(Directory.GetFiles(_tmp).Any(f => f.EndsWith(".tmp")));
        }

        [Test]
        public void InvalidDataIsRefusedAndTargetStaysUntouched()
        {
            var good = NewSave();
            var path = Path.Combine(_tmp, "SaveData.bin");
            File.WriteAllBytes(path, good);
            var bad = (byte[])NewSave(9).Clone();
            bad[5000] ^= 1;
            var o = new SaveWriteOptions { BackupDirectory = Path.Combine(_tmp, "bk") };
            Assert.Throws<SaveFormatException>(() => SaveFileIO.WriteAtomic(path, bad, o));
            Assert.Throws<SaveFormatException>(() => SaveFileIO.WriteAtomic(path, new byte[10], o));
            CollectionAssert.AreEqual(good, File.ReadAllBytes(path));
            Assert.IsFalse(Directory.Exists(Path.Combine(_tmp, "bk")));

            o.AllowInvalid = true;
            SaveFileIO.WriteAtomic(path, bad, o);
            CollectionAssert.AreEqual(bad, File.ReadAllBytes(path));
        }

        [Test]
        public void MissingTargetDirectoryIsNotCreatedUnlessRequested()
        {
            var path = Path.Combine(_tmp, "nope", "SaveData.bin");
            Assert.Throws<DirectoryNotFoundException>(() => SaveFileIO.WriteAtomic(path, NewSave()));
            Assert.IsFalse(Directory.Exists(Path.Combine(_tmp, "nope")));
            SaveFileIO.WriteAtomic(path, NewSave(), new SaveWriteOptions { CreateDirectory = true });
            Assert.IsTrue(File.Exists(path));
        }

        [Test]
        public void FailedWriteLeavesNoTempFile()
        {
            // Ein Verzeichnis als Ziel lässt den Austausch scheitern; die Temp-Datei muss verschwinden.
            var target = Path.Combine(_tmp, "SaveData.bin");
            Directory.CreateDirectory(target);
            Assert.Catch<Exception>(() => SaveFileIO.WriteAtomic(target, NewSave()));
            Assert.AreEqual(0, Directory.GetFiles(_tmp).Length);
        }

        // ---- Export ----

        [Test]
        public void RyujinxExportWritesBothCopiesWithBackups()
        {
            var id = Dir("Ryujinx", "bis", "user", "save", "0000000000000006");
            var oldData = NewSave(1);
            Put(Dir("Ryujinx", "bis", "user", "save", "0000000000000006", "0"), "SaveData.bin", oldData);
            Put(Dir("Ryujinx", "bis", "user", "save", "0000000000000006", "0"), "Backup.bin", NewSave(5));
            Put(Dir("Ryujinx", "bis", "user", "save", "0000000000000006", "1"), "SaveData.bin", oldData);
            var newData = NewSave(2);
            var bk = Path.Combine(_tmp, "bk");

            var results = SaveExporter.ExportToRyujinx(newData, Path.Combine(id, "0"), new SaveExportOptions { BackupDirectory = bk });
            Assert.AreEqual(2, results.Count);
            CollectionAssert.AreEqual(newData, File.ReadAllBytes(Path.Combine(id, "0", "SaveData.bin")));
            CollectionAssert.AreEqual(newData, File.ReadAllBytes(Path.Combine(id, "1", "SaveData.bin")));
            CollectionAssert.AreEqual(NewSave(5), File.ReadAllBytes(Path.Combine(id, "0", "Backup.bin")));
            Assert.IsTrue(results.All(r => r.BackupPath != null && File.ReadAllBytes(r.BackupPath).SequenceEqual(oldData)));
            Assert.IsFalse(Directory.GetFiles(Path.Combine(id, "0")).Any(f => f.EndsWith(".tmp")));

            Assert.Throws<DirectoryNotFoundException>(() =>
                SaveExporter.ExportToRyujinx(newData, Path.Combine(_tmp, "ohne-null"), new SaveExportOptions { BackupDirectory = bk }));
        }

        [Test]
        public void SwitchBackupFoldersFollowConventionsAndAreSanitized()
        {
            var j = SaveExporter.SwitchBackupFolder(SaveHostKind.Jksv, "SD", BrilliantDiamond, "Pokémon: BD?", "a/b");
            Assert.AreEqual(Path.Combine("SD", "JKSV", "Pokémon_ BD_", "a_b"), j);
            var c = SaveExporter.SwitchBackupFolder(SaveHostKind.Checkpoint, "SD", BrilliantDiamond, "Pokemon BD", "2026");
            Assert.AreEqual(Path.Combine("SD", "switch", "Checkpoint", "saves", "0x" + BrilliantDiamond + " Pokemon BD", "2026"), c);
            Assert.AreEqual("_", SaveExporter.SanitizeName(".."));
            Assert.AreEqual("_", SaveExporter.SanitizeName(null));
            Assert.Throws<ArgumentException>(() => SaveExporter.SwitchBackupFolder(SaveHostKind.Ryujinx, "SD", null, "x", "y"));
            Assert.Throws<ArgumentException>(() => SaveExporter.SwitchBackupFolder(SaveHostKind.Checkpoint, "SD", "123", "x", "y"));
        }

        // ---- App-Ablage ----

        [Test]
        public void StoreImportsFromRyujinxLayoutAndExportsToJksvFolder()
        {
            var src = Dir("Ryujinx", "bis", "user", "save", "0000000000000006", "0");
            var data = NewSave(7);
            Put(src, "SaveData.bin", data);
            var store = new SaveStore(Path.Combine(_tmp, "app"));
            store.Import(src, "spieler1");
            CollectionAssert.AreEqual(new[] { "spieler1" }, store.ListSlots().ToArray());
            Assert.AreEqual(SaveHostKind.AppStore, store.Inspect("spieler1").Kind);
            CollectionAssert.AreEqual(data, store.Load("spieler1").ToBytes());

            var edited = store.Load("spieler1");
            edited.Money = 4242;
            var r = store.Write("spieler1", edited, alsoBackupFile: true);
            Assert.IsNotNull(r.BackupPath);
            StringAssert.StartsWith(store.BackupsRoot, r.BackupPath);
            CollectionAssert.AreEqual(data, File.ReadAllBytes(r.BackupPath));
            Assert.AreEqual(4242, store.Load("spieler1").Money);
            Assert.IsTrue(store.Inspect("spieler1").Backup.IsValid);

            var jk = SaveExporter.SwitchBackupFolder(SaveHostKind.Jksv, Path.Combine(_tmp, "sd"), BrilliantDiamond, "Pokemon BD", "Xnu");
            store.Export("spieler1", jk, SaveHostKind.Jksv, null);
            Assert.AreEqual(4242, SaveData.FromBytes(File.ReadAllBytes(Path.Combine(jk, "SaveData.bin"))).Money);
            Assert.AreEqual(SaveHostKind.Jksv, SaveInspector.Inspect(jk).Kind);
        }

        [Test]
        public void StoreRejectsUnsafeSlotNamesAndInvalidSources()
        {
            var store = new SaveStore(Path.Combine(_tmp, "app"));
            foreach (var bad in new[] { "", "..", "../x", "a/b", "a\\b", ".x", "a..b", new string('a', 65), null })
                Assert.IsFalse(SaveStore.IsValidSlotName(bad), "Name: " + bad);
            Assert.Throws<ArgumentException>(() => store.SlotDirectory("../x"));
            Assert.Throws<ArgumentException>(() => store.Write("a/b", NewSave()));
            var d = Dir("kaputt");
            var bad2 = NewSave();
            bad2[77] ^= 1;
            Put(d, "SaveData.bin", bad2);
            Assert.Throws<SaveFormatException>(() => store.Import(d, "x"));
            Assert.AreEqual(0, store.ListSlots().Count);
        }

        // ---- lokaler echter Save (nur lesend) ----

        [Test]
        public void RealSaveFolderIsDetectedAsRyujinxAndValid()
        {
            RequireRealSave(out var path);
            var dir = Path.GetDirectoryName(path);
            var before = File.GetLastWriteTimeUtc(path);
            var ins = SaveInspector.Inspect(Path.GetDirectoryName(dir));
            Assert.AreEqual(SaveHostKind.Ryujinx, ins.Kind);
            Assert.AreEqual(6UL, ins.SaveId);
            Assert.IsTrue(ins.Main.IsValid);
            Assert.AreEqual(0xEF0A4, ins.Main.Size);
            Assert.AreEqual(0x34, ins.Main.Validation.Version);

            var root = dir;
            for (var i = 0; i < 5; i++) root = Path.GetDirectoryName(root);
            var dirs = RyujinxSaveIndex.FindSaveDirectories(root, BrilliantDiamond);
            Assert.IsTrue(dirs.Any(d => d.EndsWith("0000000000000006")));
            Assert.AreEqual(before, File.GetLastWriteTimeUtc(path), "Original unverändert");
        }
    }
}
