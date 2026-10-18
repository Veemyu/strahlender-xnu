using System;
using System.Collections.Generic;
using System.IO;

namespace Xnu.Save
{
    public readonly struct RyujinxSaveIndexEntry
    {
        public ulong ProgramId { get; }
        // Hex, 32 Zeichen (nur bei Typ „Account“ ≠ 0).
        public string UserId { get; }
        // SaveDataType: 0 System, 1 Account, 2 Bcat/Device, 3 Temporary … (nur 1 und 2 sind lokal beobachtet).
        public byte SaveType { get; }
        public ulong SaveId { get; }

        public RyujinxSaveIndexEntry(ulong programId, string userId, byte saveType, ulong saveId)
        {
            ProgramId = programId;
            UserId = userId;
            SaveType = saveType;
            SaveId = saveId;
        }

        public string ProgramIdHex => ProgramId.ToString("X16");
    }

    // Save-Index von Ryujinx: bis/system/save/8000000000000000/0/imkvdb.arc.
    // Aufbau (am lokalen Index gemessen): "IMKV", u32, u32 Anzahl; je Eintrag 0x8C Byte: "IMEN", u32 Key-Größe (0x40), u32 Wert-Größe (0x40),
    // Key = SaveDataAttribute (ProgramId u64 @0, UserId 16 Byte @8, Typ u8 @0x20), Wert beginnt mit der Save-ID (u64 LE).
    public static class RyujinxSaveIndex
    {
        public const string IndexRelativePath = "bis/system/save/8000000000000000/0/imkvdb.arc";
        public const string UserSaveRelativePath = "bis/user/save";

        public static IReadOnlyList<RyujinxSaveIndexEntry> Parse(byte[] data)
        {
            if (data == null) throw new ArgumentNullException(nameof(data));
            var list = new List<RyujinxSaveIndexEntry>();
            if (data.Length < 12 || data[0] != 'I' || data[1] != 'M' || data[2] != 'K' || data[3] != 'V')
                throw new SaveFormatException("imkvdb.arc: Kopf \"IMKV\" fehlt");
            var count = BitConverter.ToUInt32(data, 8);
            var pos = 12L;
            for (uint i = 0; i < count; i++)
            {
                if (pos + 12 > data.Length) break;
                var p = (int)pos;
                if (data[p] != 'I' || data[p + 1] != 'M' || data[p + 2] != 'E' || data[p + 3] != 'N')
                    throw new SaveFormatException("imkvdb.arc: Eintrag " + i + " ohne \"IMEN\"");
                var keySize = BitConverter.ToUInt32(data, p + 4);
                var valSize = BitConverter.ToUInt32(data, p + 8);
                if (keySize < 0x24 || valSize < 8 || pos + 12 + keySize + valSize > data.Length)
                    throw new SaveFormatException("imkvdb.arc: Eintrag " + i + " mit unplausibler Größe");
                var key = p + 12;
                var val = key + (int)keySize;
                var user = new System.Text.StringBuilder(32);
                for (var k = 0; k < 16; k++) user.Append(data[key + 8 + k].ToString("X2"));
                list.Add(new RyujinxSaveIndexEntry(BitConverter.ToUInt64(data, key), user.ToString(), data[key + 0x20], BitConverter.ToUInt64(data, val)));
                pos += 12 + keySize + valSize;
            }
            return list;
        }

        public static IReadOnlyList<RyujinxSaveIndexEntry> Load(string ryujinxRoot)
        {
            var path = Path.Combine(ryujinxRoot, IndexRelativePath.Replace('/', Path.DirectorySeparatorChar));
            return Parse(SaveFileIO.ReadAll(path));
        }

        // Ordner „…/bis/user/save/<SaveId>“ der Account-Saves (Typ 1) des Titels, die auf der Platte existieren.
        public static IReadOnlyList<string> FindSaveDirectories(string ryujinxRoot, string titleId)
        {
            var program = Convert.ToUInt64(titleId, 16);
            var dirs = new List<string>();
            foreach (var e in Load(ryujinxRoot))
            {
                if (e.ProgramId != program || e.SaveType != 1) continue;
                var d = Path.Combine(ryujinxRoot, UserSaveRelativePath.Replace('/', Path.DirectorySeparatorChar), e.SaveId.ToString("x16"));
                if (Directory.Exists(d)) dirs.Add(d);
            }
            return dirs;
        }
    }
}
