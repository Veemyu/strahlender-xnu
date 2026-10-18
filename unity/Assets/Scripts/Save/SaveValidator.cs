using System;
using System.Security.Cryptography;

namespace Xnu.Save
{
    // Reiner Prüfer für SaveData.bin/Backup.bin (Version, Größe, MD5). Mutiert Eingaben nie.
    public static class SaveValidator
    {
        public static SaveHeader ReadHeader(byte[] data)
        {
            if (data == null) throw new ArgumentNullException(nameof(data));
            if (data.Length < 4)
                throw new SaveFormatException("Datei kürzer als 4 Byte, keine Version lesbar");
            var version = data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24);
            return new SaveHeader(version, data.Length);
        }

        // Erwartete Dateigröße/Hashlänge, null für Versionen ohne Tabelleneintrag.
        public static int? ExpectedSize(int version) => SaveLayout.ExpectedSize(version);

        static int HashLength(byte[] data, int version)
        {
            var n = SaveLayout.ExpectedSize(version);
            if (n == null)
                throw new SaveFormatException(string.Format(
                    "Version 0x{0:X} hat keine Hashlänge (bekannt: 0x{1:X}–0x{2:X})",
                    (uint)version, SaveLayout.LaunchVersion, SaveLayout.CurrentVersion));
            if (data.Length < n.Value)
                throw new SaveFormatException(string.Format(
                    "Datei abgeschnitten: {0} Byte, erwartet {1} (0x{1:X})", data.Length, n.Value));
            return n.Value;
        }

        // MD5 über die ersten N Byte (N laut Version) mit auf 0 gesetztem Hashfeld.
        public static byte[] ComputeHash(byte[] data)
        {
            return ComputeHash(data, ReadHeader(data).Version);
        }

        public static byte[] ComputeHash(byte[] data, int version)
        {
            if (data == null) throw new ArgumentNullException(nameof(data));
            var n = HashLength(data, version);
            var buf = new byte[n];
            Buffer.BlockCopy(data, 0, buf, 0, n);
            Array.Clear(buf, SaveLayout.HashOffset, SaveLayout.HashLength);
            using (var md5 = MD5.Create())
                return md5.ComputeHash(buf);
        }

        public static byte[] StoredHash(byte[] data)
        {
            if (data == null) throw new ArgumentNullException(nameof(data));
            if (data.Length < SaveLayout.HashEnd)
                throw new SaveFormatException(string.Format(
                    "Datei zu kurz für das Hashfeld (< 0x{0:X} Byte)", SaveLayout.HashEnd));
            var h = new byte[SaveLayout.HashLength];
            Buffer.BlockCopy(data, SaveLayout.HashOffset, h, 0, SaveLayout.HashLength);
            return h;
        }

        // true/false; null, wenn das Spiel die Version nicht prüft (< 0x25).
        // Wirft SaveFormatException bei unbekannter Version oder abgeschnittener Datei.
        public static bool? VerifyHash(byte[] data)
        {
            var version = ReadHeader(data).Version;
            if (version < SaveLayout.LaunchVersion) return null;
            var computed = ComputeHash(data, version);
            var stored = StoredHash(data);
            return BytesEqual(computed, stored);
        }

        // Sammelt alle Befunde, wirft nicht.
        public static SaveValidationResult Validate(byte[] data)
        {
            var r = new SaveValidationResult();
            SaveHeader header;
            try
            {
                header = ReadHeader(data);
            }
            catch (SaveFormatException e)
            {
                r.Size = data.Length;
                r.AddProblem(e.Message);
                return r;
            }

            r.HasHeader = true;
            r.Version = header.Version;
            r.Size = header.Size;
            r.ExpectedSize = ExpectedSize(header.Version);

            if (header.Version < SaveLayout.LaunchVersion)
            {
                r.AddProblem(string.Format("Version < 0x{0:X}: Spiel prüft keinen Hash", SaveLayout.LaunchVersion));
                return r;
            }
            if (r.ExpectedSize == null)
            {
                r.AddProblem(string.Format("unbekannte Version 0x{0:X} (> 0x{1:X})",
                    (uint)header.Version, SaveLayout.CurrentVersion));
                return r;
            }

            r.SizeOk = header.Size == r.ExpectedSize.Value;
            if (r.SizeOk == false)
                r.AddProblem(string.Format("Größe {0} weicht von erwarteten {1} ab", header.Size, r.ExpectedSize.Value));
            try
            {
                r.HashValid = VerifyHash(data);
                if (r.HashValid == false) r.AddProblem("MD5 stimmt nicht");
            }
            catch (SaveFormatException e)
            {
                r.AddProblem(e.Message);
            }
            return r;
        }

        static bool BytesEqual(byte[] a, byte[] b)
        {
            if (a.Length != b.Length) return false;
            var diff = 0;
            for (var i = 0; i < a.Length; i++) diff |= a[i] ^ b[i];
            return diff == 0;
        }
    }
}
