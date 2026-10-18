using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace Xnu.Save
{
    public sealed class SaveExportOptions
    {
        // Pflicht, wenn Zieldateien existieren (siehe SaveWriteOptions.BackupDirectory).
        public string BackupDirectory { get; set; }
        // Zusätzlich Backup.bin mit demselben Inhalt schreiben.
        public bool WriteBackupFile { get; set; }
        public bool CreateDirectory { get; set; }
        public Func<DateTime> Clock { get; set; }
    }

    // Schreibt Saves in die Ordnerkonventionen der Emulatoren/Switch-Werkzeuge. Jede Datei wird atomar geschrieben
    // und vorher geprüft/gesichert (SaveFileIO.WriteAtomic).
    public static class SaveExporter
    {
        // Generischer Ordner (yuzu-Titelordner, ein JKSV-/Checkpoint-Backup-Ordner, Ablageordner).
        public static IReadOnlyList<SaveWriteResult> ExportToDirectory(byte[] data, string dir, SaveExportOptions options)
        {
            if (dir == null) throw new ArgumentNullException(nameof(dir));
            options = options ?? new SaveExportOptions();
            var results = new List<SaveWriteResult>();
            results.Add(SaveFileIO.WriteAtomic(Path.Combine(dir, SaveFileIO.MainFileName), data, Opts(options, options.BackupDirectory)));
            if (options.WriteBackupFile)
                results.Add(SaveFileIO.WriteAtomic(Path.Combine(dir, SaveFileIO.BackupFileName), data, Opts(options, options.BackupDirectory)));
            return results;
        }

        // Ryujinx: erwartet „…/bis/user/save/<SaveId>“ oder dessen Unterordner „0“/„1“. Geschrieben wird nach „0“ und – falls vorhanden –
        // auch in die Zweitkopie „1“ (lokal beobachtet: beide Ordner enthalten dieselbe SaveData.bin). Ryujinx muss beendet sein.
        public static IReadOnlyList<SaveWriteResult> ExportToRyujinx(byte[] data, string saveDir, SaveExportOptions options)
        {
            if (saveDir == null) throw new ArgumentNullException(nameof(saveDir));
            options = options ?? new SaveExportOptions();
            var full = Path.GetFullPath(saveDir).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var leaf = Path.GetFileName(full);
            var idDir = (leaf == "0" || leaf == "1") ? Path.GetDirectoryName(full) : full;
            var targets = new List<string>();
            var zero = Path.Combine(idDir, "0");
            if (!Directory.Exists(zero)) throw new DirectoryNotFoundException("Ryujinx-Savefolder „0“ fehlt: " + idDir);
            targets.Add(zero);
            var one = Path.Combine(idDir, "1");
            if (Directory.Exists(one)) targets.Add(one);

            var results = new List<SaveWriteResult>();
            foreach (var t in targets)
            {
                var sub = string.IsNullOrEmpty(options.BackupDirectory) ? null : Path.Combine(options.BackupDirectory, Path.GetFileName(t));
                var o = new SaveExportOptions { BackupDirectory = sub, WriteBackupFile = options.WriteBackupFile, Clock = options.Clock };
                results.AddRange(ExportToDirectory(data, t, o));
            }
            return results;
        }

        // Ordnerpfad für ein neues Backup in der Konvention von JKSV bzw. Checkpoint (nur Pfadbildung, schreibt nichts).
        // JKSV: <sd>/JKSV/<Spielname>/<Backup>; Checkpoint: <sd>/switch/Checkpoint/saves/0x<TitleId> <Spielname>/<Backup>.
        public static string SwitchBackupFolder(SaveHostKind kind, string sdRoot, string titleId, string gameName, string backupName)
        {
            var game = SanitizeName(gameName);
            var backup = SanitizeName(backupName);
            switch (kind)
            {
                case SaveHostKind.Jksv:
                    return Path.Combine(sdRoot, "JKSV", game, backup);
                case SaveHostKind.Checkpoint:
                    if (titleId == null || titleId.Length != 16) throw new ArgumentException("Titel-ID (16 Hex) nötig", nameof(titleId));
                    return Path.Combine(sdRoot, "switch", "Checkpoint", "saves", "0x" + titleId.ToUpperInvariant() + " " + game, backup);
                default:
                    throw new ArgumentException("nur Jksv oder Checkpoint", nameof(kind));
            }
        }

        // Ordnername ohne Pfadtrenner/Sonderzeichen (FAT/exFAT-tauglich), nie leer, nie „.“/„..“.
        public static string SanitizeName(string name)
        {
            var sb = new StringBuilder();
            foreach (var c in name ?? string.Empty)
            {
                if (c < 0x20 || "\\/:*?\"<>|".IndexOf(c) >= 0) sb.Append('_');
                else sb.Append(c);
            }
            var s = sb.ToString().Trim().TrimEnd('.', ' ');
            return s.Length == 0 ? "_" : s;
        }

        static SaveWriteOptions Opts(SaveExportOptions o, string backupDir) => new SaveWriteOptions
        {
            BackupDirectory = backupDir,
            CreateDirectory = o.CreateDirectory,
            Clock = o.Clock,
        };
    }
}
