using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;

namespace Xnu.Save
{
    // Woher ein Save stammt bzw. in welcher Ordnerkonvention er liegt (siehe docs/save-kompatibilitaet.md).
    public enum SaveHostKind
    {
        Unknown = 0,
        // Beliebige einzelne Datei (z. B. umbenannter Export).
        LooseFile,
        // Zip mit SaveData.bin (z. B. Backup-Archiv).
        ZipArchive,
        // .../bis/user/save/<SaveId 16 Hex>/<0|1>/
        Ryujinx,
        // .../nand/user/save/0000000000000000/<UserId 32 Hex>/<TitleId 16 Hex>/
        Yuzu,
        // <SD>/JKSV/<Spielname>/<Backup>/
        Jksv,
        // <SD>/switch/Checkpoint/saves/0x<TitleId> <Name>/<Backup>/
        Checkpoint,
        // Eigene Ablage (SaveStore)
        AppStore,
        // Ordner mit SaveData.bin/Backup.bin ohne erkennbare Konvention.
        Folder,
    }

    public sealed class SaveFileInfo
    {
        public string Name { get; internal set; }
        // Dateipfad bzw. Zip-Eintragsname.
        public string Location { get; internal set; }
        public long Size { get; internal set; }
        // null, wenn die Datei nicht lesbar/zu groß war.
        public SaveValidationResult Validation { get; internal set; }
        public bool IsValid => Validation != null && Validation.IsValid;
    }

    public sealed class SaveInspection
    {
        readonly List<SaveFileInfo> _files = new List<SaveFileInfo>();
        readonly List<string> _notes = new List<string>();

        public string Path { get; internal set; }
        public SaveHostKind Kind { get; internal set; }
        public IReadOnlyList<SaveFileInfo> Files => _files;
        public SaveFileInfo Main { get; internal set; }
        public SaveFileInfo Backup { get; internal set; }
        // Aus dem Pfad gelesen, sofern die Konvention sie enthält (sonst null).
        public string TitleId { get; internal set; }
        public string TitleName { get; internal set; }
        public string UserId { get; internal set; }
        public ulong? SaveId { get; internal set; }
        public IReadOnlyList<string> Notes => _notes;

        public bool HasUsableSave => (Main != null && Main.IsValid) || (Backup != null && Backup.IsValid);

        internal void AddFile(SaveFileInfo f) => _files.Add(f);
        internal void AddNote(string n) => _notes.Add(n);
    }

    // Erkennen und Validieren von Save-Ablagen. Liest nur; verändert nichts.
    public static class SaveInspector
    {
        public const string BrilliantDiamondTitleId = "0100000011D90000";
        // Nicht lokal geprüft; öffentlich bekannte Titel-ID.
        public const string ShiningPearlTitleId = "010018E011D92000";

        public static string TitleName(string titleId)
        {
            if (string.Equals(titleId, BrilliantDiamondTitleId, StringComparison.OrdinalIgnoreCase)) return "Pokémon Brilliant Diamond";
            if (string.Equals(titleId, ShiningPearlTitleId, StringComparison.OrdinalIgnoreCase)) return "Pokémon Shining Pearl";
            return null;
        }

        // path: Ordner (auch der Ryujinx-Save-ID-Ordner, dann wird „0“ genommen), Datei oder .zip.
        public static SaveInspection Inspect(string path, string appRoot = null)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            var full = System.IO.Path.GetFullPath(path);
            var ins = new SaveInspection { Path = full };

            if (File.Exists(full))
            {
                if (full.EndsWith(".zip", StringComparison.OrdinalIgnoreCase)) InspectZip(full, ins);
                else InspectLooseFile(full, ins);
                return ins;
            }
            if (!Directory.Exists(full))
            {
                ins.AddNote("Pfad existiert nicht");
                return ins;
            }

            var dir = full;
            if (FindFile(dir, SaveFileIO.MainFileName) == null && FindFile(dir, SaveFileIO.BackupFileName) == null)
            {
                var zero = System.IO.Path.Combine(dir, "0");
                if (Directory.Exists(zero) && (FindFile(zero, SaveFileIO.MainFileName) != null || FindFile(zero, SaveFileIO.BackupFileName) != null))
                {
                    dir = zero;
                    ins.Path = zero;
                    ins.AddNote("Save-ID-Ordner: „0“ verwendet");
                }
            }

            ClassifyPath(dir, appRoot, ins);
            AddDirFile(dir, SaveFileIO.MainFileName, ins, true);
            AddDirFile(dir, SaveFileIO.BackupFileName, ins, false);
            foreach (var f in Directory.GetFiles(dir))
            {
                var n = System.IO.Path.GetFileName(f);
                if (n.EndsWith(".dat", StringComparison.OrdinalIgnoreCase) && n.StartsWith("rp", StringComparison.OrdinalIgnoreCase))
                    ins.AddNote("Zusatzdatei " + n + " wird ignoriert");
            }
            if (ins.Main == null && ins.Backup == null) ins.AddNote("weder SaveData.bin noch Backup.bin gefunden");
            if (ins.Kind == SaveHostKind.Unknown) ins.Kind = ins.Main != null || ins.Backup != null ? SaveHostKind.Folder : SaveHostKind.Unknown;
            AddTitleNote(ins);
            return ins;
        }

        // Sucht unterhalb root (begrenzte Tiefe/Anzahl) nach Ordnern mit SaveData.bin/Backup.bin.
        public static IReadOnlyList<SaveInspection> Find(string root, int maxDepth = 6, int maxResults = 64, int maxDirectories = 5000, string appRoot = null)
        {
            var found = new List<SaveInspection>();
            if (!Directory.Exists(root)) return found;
            var queue = new Queue<KeyValuePair<string, int>>();
            queue.Enqueue(new KeyValuePair<string, int>(root, 0));
            var visited = 0;
            while (queue.Count > 0 && found.Count < maxResults && visited < maxDirectories)
            {
                var cur = queue.Dequeue();
                visited++;
                try
                {
                    if (FindFile(cur.Key, SaveFileIO.MainFileName) != null || FindFile(cur.Key, SaveFileIO.BackupFileName) != null)
                    {
                        found.Add(Inspect(cur.Key, appRoot));
                        continue;
                    }
                    if (cur.Value >= maxDepth) continue;
                    foreach (var sub in Directory.GetDirectories(cur.Key))
                        queue.Enqueue(new KeyValuePair<string, int>(sub, cur.Value + 1));
                }
                catch (UnauthorizedAccessException) { }
                catch (IOException) { }
            }
            return found;
        }

        // Liest die gewählte Datei der Inspektion (Ordner, einzelne Datei oder Zip-Eintrag), mit Größenlimit.
        public static byte[] Read(SaveInspection ins, SaveFileInfo file)
        {
            if (ins == null) throw new ArgumentNullException(nameof(ins));
            if (file == null) throw new ArgumentNullException(nameof(file));
            if (ins.Kind == SaveHostKind.ZipArchive)
            {
                using (var zip = ZipFile.OpenRead(ins.Path))
                {
                    var e = zip.GetEntry(file.Location);
                    if (e == null) throw new FileNotFoundException("Zip-Eintrag fehlt", file.Location);
                    using (var s = e.Open()) return SaveFileIO.ReadLimited(s);
                }
            }
            return SaveFileIO.ReadAll(file.Location);
        }

        // Bevorzugt SaveData.bin, sonst Backup.bin; nur gültige Dateien. Wirft SaveFormatException, wenn keine gültig ist.
        public static byte[] ReadBest(SaveInspection ins, bool preferBackup = false)
        {
            var order = preferBackup ? new[] { ins.Backup, ins.Main } : new[] { ins.Main, ins.Backup };
            foreach (var f in order)
                if (f != null && f.IsValid) return Read(ins, f);
            throw new SaveFormatException("Kein gültiger Save gefunden" + (ins.Notes.Count > 0 ? ": " + string.Join("; ", ins.Notes) : ""));
        }

        // ---- Pfadkonventionen ----

        static void ClassifyPath(string dir, string appRoot, SaveInspection ins)
        {
            var comps = dir.Split(new[] { '/', '\\' }, StringSplitOptions.RemoveEmptyEntries);

            if (appRoot != null)
            {
                var root = System.IO.Path.GetFullPath(appRoot).TrimEnd(System.IO.Path.DirectorySeparatorChar, System.IO.Path.AltDirectorySeparatorChar);
                if (dir.StartsWith(root + System.IO.Path.DirectorySeparatorChar, StringComparison.Ordinal))
                {
                    ins.Kind = SaveHostKind.AppStore;
                    return;
                }
            }

            for (var i = 0; i + 3 < comps.Length; i++)
            {
                if (!Eq(comps[i], "bis") || !Eq(comps[i + 1], "user") || !Eq(comps[i + 2], "save")) continue;
                if (IsHex(comps[i + 3], 16) && comps.Length == i + 5 && (comps[i + 4] == "0" || comps[i + 4] == "1"))
                {
                    ins.Kind = SaveHostKind.Ryujinx;
                    ins.SaveId = Convert.ToUInt64(comps[i + 3], 16);
                    return;
                }
            }
            for (var i = 0; i + 5 < comps.Length; i++)
            {
                if (!Eq(comps[i], "nand") || !Eq(comps[i + 1], "user") || !Eq(comps[i + 2], "save")) continue;
                if (IsHex(comps[i + 3], 16) && IsHex(comps[i + 4], 32) && IsHex(comps[i + 5], 16))
                {
                    ins.Kind = SaveHostKind.Yuzu;
                    ins.UserId = comps[i + 4].ToUpperInvariant();
                    ins.TitleId = comps[i + 5].ToUpperInvariant();
                    return;
                }
            }
            for (var i = 0; i + 2 < comps.Length; i++)
            {
                if (Eq(comps[i], "Checkpoint") && Eq(comps[i + 1], "saves"))
                {
                    ins.Kind = SaveHostKind.Checkpoint;
                    var t = comps[i + 2];
                    if (t.Length >= 18 && (t.StartsWith("0x") || t.StartsWith("0X")) && IsHex(t.Substring(2, 16), 16))
                        ins.TitleId = t.Substring(2, 16).ToUpperInvariant();
                    return;
                }
            }
            foreach (var c in comps)
                if (Eq(c, "JKSV"))
                {
                    ins.Kind = SaveHostKind.Jksv;
                    return;
                }
        }

        static void AddTitleNote(SaveInspection ins)
        {
            if (ins.TitleId == null) return;
            ins.TitleName = TitleName(ins.TitleId);
            if (ins.TitleName == null) ins.AddNote("Titel-ID " + ins.TitleId + " ist nicht Brilliant Diamond/Shining Pearl");
        }

        static bool Eq(string a, string b) => string.Equals(a, b, StringComparison.OrdinalIgnoreCase);

        static bool IsHex(string s, int length)
        {
            if (s.Length != length) return false;
            foreach (var c in s)
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'))) return false;
            return true;
        }

        // ---- Dateien ----

        static string FindFile(string dir, string name)
        {
            try
            {
                foreach (var f in Directory.GetFiles(dir))
                    if (Eq(System.IO.Path.GetFileName(f), name)) return f;
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            return null;
        }

        static void AddDirFile(string dir, string name, SaveInspection ins, bool isMain)
        {
            var path = FindFile(dir, name);
            if (path == null) return;
            var info = Examine(name, path, () => SaveFileIO.ReadAll(path), new FileInfo(path).Length);
            ins.AddFile(info);
            if (isMain) ins.Main = info;
            else ins.Backup = info;
        }

        static SaveFileInfo Examine(string name, string location, Func<byte[]> read, long size)
        {
            var info = new SaveFileInfo { Name = name, Location = location, Size = size };
            try
            {
                info.Validation = SaveValidator.Validate(read());
            }
            catch (SaveFormatException)
            {
                // zu groß: Validation bleibt null
            }
            return info;
        }

        static void InspectLooseFile(string path, SaveInspection ins)
        {
            ins.Kind = SaveHostKind.LooseFile;
            var name = System.IO.Path.GetFileName(path);
            var info = Examine(name, path, () => SaveFileIO.ReadAll(path), new FileInfo(path).Length);
            ins.AddFile(info);
            if (Eq(name, SaveFileIO.BackupFileName)) ins.Backup = info;
            else ins.Main = info;
            if (info.Validation == null) ins.AddNote("Datei zu groß für einen Save");
        }

        static void InspectZip(string path, SaveInspection ins)
        {
            ins.Kind = SaveHostKind.ZipArchive;
            try
            {
                using (var zip = ZipFile.OpenRead(path))
                {
                    ZipArchiveEntry main = null, backup = null;
                    foreach (var e in zip.Entries)
                    {
                        if (Eq(e.Name, SaveFileIO.MainFileName) && (main == null || e.FullName.Length < main.FullName.Length)) main = e;
                        if (Eq(e.Name, SaveFileIO.BackupFileName) && (backup == null || e.FullName.Length < backup.FullName.Length)) backup = e;
                    }
                    ins.Main = ExamineEntry(main, ins);
                    ins.Backup = ExamineEntry(backup, ins);
                    if (ins.Main == null && ins.Backup == null) ins.AddNote("Zip enthält weder SaveData.bin noch Backup.bin");
                }
            }
            catch (InvalidDataException)
            {
                ins.AddNote("Zip nicht lesbar");
            }
        }

        static SaveFileInfo ExamineEntry(ZipArchiveEntry e, SaveInspection ins)
        {
            if (e == null) return null;
            var info = Examine(e.Name, e.FullName, () =>
            {
                using (var s = e.Open()) return SaveFileIO.ReadLimited(s);
            }, e.Length);
            ins.AddFile(info);
            return info;
        }
    }
}
