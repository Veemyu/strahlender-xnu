using System;
using System.Globalization;
using System.IO;

namespace Xnu.Save
{
    public sealed class SaveWriteOptions
    {
        // Pflicht, wenn das Ziel schon existiert: Das alte Ziel wird nach <BackupDirectory>/<Zeitstempel>/<Dateiname> kopiert.
        public string BackupDirectory { get; set; }
        // Fehlende Zielordner anlegen (App-Ablage: ja; fremde Ordner wie Ryujinx: nein).
        public bool CreateDirectory { get; set; }
        // Daten ohne gültige Größe/Hash schreiben (Standard: ablehnen).
        public bool AllowInvalid { get; set; }
        // Nach dem Schreiben zurücklesen und byteweise vergleichen.
        public bool VerifyAfterWrite { get; set; } = true;
        // Für Tests; Standard UtcNow.
        public Func<DateTime> Clock { get; set; }
    }

    public sealed class SaveWriteResult
    {
        public string TargetPath { get; internal set; }
        // null, wenn es kein altes Ziel gab.
        public string BackupPath { get; internal set; }
        public int Bytes { get; internal set; }
    }

    // Lesen mit Größenlimit, Backup vor dem Überschreiben und atomares Schreiben (Temp-Datei im selben Ordner + Austausch).
    public static class SaveFileIO
    {
        public const string MainFileName = "SaveData.bin";
        public const string BackupFileName = "Backup.bin";
        // Obergrenze für gelesene Dateien/Zip-Einträge; ein Save ist 0xEF0A4 Byte groß.
        public const int MaxFileSize = 0x100000;

        public static byte[] ReadAll(string path)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                return ReadLimited(fs);
        }

        // Liest bis zum Ende, wirft SaveFormatException bei mehr als MaxFileSize Byte.
        public static byte[] ReadLimited(Stream s)
        {
            using (var ms = new MemoryStream())
            {
                var buf = new byte[81920];
                int n;
                while ((n = s.Read(buf, 0, buf.Length)) > 0)
                {
                    if (ms.Length + n > MaxFileSize)
                        throw new SaveFormatException("Datei größer als " + MaxFileSize + " Byte");
                    ms.Write(buf, 0, n);
                }
                return ms.ToArray();
            }
        }

        // Kopiert path nach backupDirectory/<Zeitstempel>/<Dateiname> (atomar) und liefert den Zielpfad.
        public static string BackupFile(string path, string backupDirectory, Func<DateTime> clock = null)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("Datei fehlt", path);
            if (string.IsNullOrEmpty(backupDirectory)) throw new ArgumentException("backupDirectory fehlt", nameof(backupDirectory));
            var stamp = (clock != null ? clock() : DateTime.UtcNow).ToString("yyyyMMdd'T'HHmmssfff'Z'", CultureInfo.InvariantCulture);
            var dir = Path.Combine(backupDirectory, stamp);
            for (var i = 1; Directory.Exists(dir); i++)
                dir = Path.Combine(backupDirectory, stamp + "-" + i.ToString(CultureInfo.InvariantCulture));
            Directory.CreateDirectory(dir);
            var dest = Path.Combine(dir, Path.GetFileName(path));
            var bytes = ReadAll(path);
            WriteRaw(dest, bytes);
            if (!SameBytes(ReadAll(dest), bytes)) throw new IOException("Backup stimmt nicht mit dem Original überein");
            return dest;
        }

        // Schreibt data nach path. Reihenfolge: prüfen → Backup des alten Ziels → Temp-Datei schreiben und auf die Platte
        // bringen → Austausch (File.Replace bzw. Move) → Rücklesen. Bei Fehlern bleibt das alte Ziel erhalten (bzw. wird aus dem Backup
        // zurückgespielt) und die Temp-Datei wird entfernt.
        public static SaveWriteResult WriteAtomic(string path, byte[] data, SaveWriteOptions options = null)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            if (data == null) throw new ArgumentNullException(nameof(data));
            options = options ?? new SaveWriteOptions();

            if (!options.AllowInvalid)
            {
                var v = SaveValidator.Validate(data);
                if (!v.IsValid)
                    throw new SaveFormatException("Daten sind kein gültiger Save: " + string.Join("; ", v.Problems));
            }

            var dir = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!Directory.Exists(dir))
            {
                if (!options.CreateDirectory) throw new DirectoryNotFoundException("Zielordner fehlt: " + dir);
                Directory.CreateDirectory(dir);
            }

            var result = new SaveWriteResult { TargetPath = path, Bytes = data.Length };
            var exists = File.Exists(path);
            if (exists)
            {
                if (string.IsNullOrEmpty(options.BackupDirectory))
                    throw new InvalidOperationException("Ziel existiert; BackupDirectory ist Pflicht (kein Überschreiben ohne Backup)");
                result.BackupPath = BackupFile(path, options.BackupDirectory, options.Clock);
            }

            var tmp = Path.Combine(dir, "." + Path.GetFileName(path) + "." + Guid.NewGuid().ToString("N").Substring(0, 8) + ".tmp");
            try
            {
                WriteRaw(tmp, data);
                if (exists) Replace(tmp, path);
                else File.Move(tmp, path);

                if (options.VerifyAfterWrite && !SameBytes(ReadAll(path), data))
                {
                    if (result.BackupPath != null) File.Copy(result.BackupPath, path, true);
                    throw new IOException("Rücklesen stimmt nicht mit den geschriebenen Daten überein");
                }
            }
            finally
            {
                if (File.Exists(tmp)) File.Delete(tmp);
            }
            return result;
        }

        static void Replace(string tmp, string path)
        {
            try
            {
                File.Replace(tmp, path, null);
            }
            catch (PlatformNotSupportedException)
            {
                // Rückfall (nicht atomar); das alte Ziel ist durch das Backup gesichert.
                File.Delete(path);
                File.Move(tmp, path);
            }
        }

        // Neue Datei (CreateNew), Daten schreiben und bis auf den Datenträger flushen.
        static void WriteRaw(string path, byte[] data)
        {
            using (var fs = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                fs.Write(data, 0, data.Length);
                fs.Flush(true);
            }
        }

        internal static bool SameBytes(byte[] a, byte[] b)
        {
            if (a.Length != b.Length) return false;
            for (var i = 0; i < a.Length; i++)
                if (a[i] != b[i]) return false;
            return true;
        }
    }
}
