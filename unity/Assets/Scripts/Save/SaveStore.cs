using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;

namespace Xnu.Save
{
    // Eigene Save-Ablage der App.
    //   <root>/Saves/<Slot>/SaveData.bin (+ Backup.bin)
    //   <root>/Backups/<Slot>/<Zeitstempel>/<Datei>     (vor jedem Überschreiben)
    // root: macOS Application Support bzw. iPadOS Documents – im Unity-Player Application.persistentDataPath
    // (Xnu.Save kennt UnityEngine nicht, der Aufrufer übergibt den Pfad).
    public sealed class SaveStore
    {
        static readonly Regex SlotPattern = new Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", RegexOptions.CultureInvariant);

        public string Root { get; }
        public string SlotsRoot => Path.Combine(Root, "Saves");
        public string BackupsRoot => Path.Combine(Root, "Backups");

        public SaveStore(string root)
        {
            if (string.IsNullOrEmpty(root)) throw new ArgumentException("root fehlt", nameof(root));
            Root = Path.GetFullPath(root);
        }

        // Slot-Namen: Buchstaben/Ziffern/._-, 1..64 Zeichen, kein „..“ (kein Pfadausbruch).
        public static bool IsValidSlotName(string slot) => slot != null && SlotPattern.IsMatch(slot) && !slot.Contains("..");

        public string SlotDirectory(string slot)
        {
            if (!IsValidSlotName(slot)) throw new ArgumentException("ungültiger Slot-Name", nameof(slot));
            return Path.Combine(SlotsRoot, slot);
        }

        public IReadOnlyList<string> ListSlots()
        {
            var list = new List<string>();
            if (!Directory.Exists(SlotsRoot)) return list;
            foreach (var d in Directory.GetDirectories(SlotsRoot))
            {
                var n = Path.GetFileName(d);
                if (IsValidSlotName(n)) list.Add(n);
            }
            list.Sort(StringComparer.Ordinal);
            return list;
        }

        public SaveInspection Inspect(string slot) => SaveInspector.Inspect(SlotDirectory(slot), Root);

        // Gültigen Save des Slots laden (SaveData.bin, sonst Backup.bin).
        public SaveData Load(string slot, bool preferBackup = false) =>
            SaveData.FromBytes(SaveInspector.ReadBest(Inspect(slot), preferBackup));

        // Schreibt SaveData.bin des Slots atomar; ein vorhandener Stand wandert vorher ins Backup-Verzeichnis des Slots.
        public SaveWriteResult Write(string slot, byte[] data, bool alsoBackupFile = false)
        {
            var dir = SlotDirectory(slot);
            var results = SaveExporter.ExportToDirectory(data, dir, new SaveExportOptions
            {
                BackupDirectory = Path.Combine(BackupsRoot, slot),
                WriteBackupFile = alsoBackupFile,
                CreateDirectory = true,
            });
            return results[0];
        }

        public SaveWriteResult Write(string slot, SaveData save, bool alsoBackupFile = false) => Write(slot, save.ToBytes(), alsoBackupFile);

        // Importiert den besten gültigen Stand einer erkannten Quelle (Ordner/Datei/Zip) in einen Slot.
        public SaveWriteResult Import(SaveInspection source, string slot, bool preferBackup = false) =>
            Write(slot, SaveInspector.ReadBest(source, preferBackup));

        public SaveWriteResult Import(string sourcePath, string slot, bool preferBackup = false) =>
            Import(SaveInspector.Inspect(sourcePath, Root), slot, preferBackup);

        // Exportiert den Slot in einen Ordner (Konvention siehe SaveExporter); geprüft wird vor dem Schreiben.
        public IReadOnlyList<SaveWriteResult> Export(string slot, string targetDirectory, SaveHostKind targetKind, string externalBackupDirectory, bool writeBackupFile = false)
        {
            var data = SaveInspector.ReadBest(Inspect(slot));
            var o = new SaveExportOptions { BackupDirectory = externalBackupDirectory ?? Path.Combine(BackupsRoot, slot + "-export"), WriteBackupFile = writeBackupFile,
                // Neue Backup-Ordner von JKSV/Checkpoint anlegen; Emulator-Ordner müssen existieren.
                CreateDirectory = targetKind == SaveHostKind.Jksv || targetKind == SaveHostKind.Checkpoint };
            return targetKind == SaveHostKind.Ryujinx
                ? SaveExporter.ExportToRyujinx(data, targetDirectory, o)
                : SaveExporter.ExportToDirectory(data, targetDirectory, o);
        }
    }
}
