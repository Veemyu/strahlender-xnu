using System;
using System.Collections.Generic;

namespace Xnu.Save
{
    // Ein Top-Level-Feld der SaveData.bin (Marshal-Abbild, Version 0x34).
    // Size ist der Abstand zum nächsten Feld und enthält ggf. Padding.
    public readonly struct SaveField
    {
        public string Name { get; }
        public int Offset { get; }
        public int Size { get; }
        public string Type { get; }

        public SaveField(string name, int offset, int size, string type)
        {
            Name = name;
            Offset = offset;
            Size = size;
            Type = type;
        }

        public int End => Offset + Size;
    }

    // Konstanten und Feldtabelle gemäß docs/save-spec-entwurf.md (Abschnitte 3 und 4).
    public static class SaveLayout
    {
        public const int VersionOffset = 0;
        public const int HashOffset = 0xE9818;
        public const int HashLength = 16;
        public const int HashEnd = HashOffset + HashLength;

        public const int CurrentVersion = 0x34;
        // Ab dieser Version prüft das Spiel den Hash.
        public const int LaunchVersion = 0x25;

        // Hash-/Dateilänge je Version 0x25 … 0x34.
        static readonly int[] BinarySizes =
        {
            0xE9828, 0xE9BE8, 0xED158, 0xED188, 0xED188, 0xED680, 0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20, 0xEDC20, 0xEED8C, 0xEED8C, 0xEF0A4,
        };

        static readonly SaveField[] FieldTable =
        {
            new SaveField("version", 0x0, 4, "int"),
            new SaveField("intValues", 0x4, 2000, "int[500]"),
            new SaveField("boolValues", 0x7D4, 16000, "bool[4000] (4 B/Elem)"),
            new SaveField("systemFlags", 0x4654, 4000, "bool[1000]"),
            new SaveField("rivalName", 0x55F4, 64, "string (32 UTF-16)"),
            new SaveField("zoneID", 0x5634, 4, "ZoneID"),
            new SaveField("timeScale", 0x5638, 4, "float"),
            new SaveField("saveItem", 0x563C, 48000, "SaveItem[3000] à 16"),
            new SaveField("saveUgItem", 0x111BC, 11988, "SaveUgItem[999] à 12"),
            new SaveField("saveItemShortcut", 0x14090, 8, "ushort[4]"),
            new SaveField("playerParty", 0x14098, 2066, "SavePokeParty"),
            new SaveField("boxData", 0x148AA, 1610, "SaveBoxData"),
            new SaveField("boxTray", 0x14EF4, 412800, "SaveBoxTrayData[40] à 10320 (30 × 344)"),
            new SaveField("playerData", 0x79B74, 1972, "PLAYER_DATA"),
            new SaveField("zukanData", 0x7A328, 12472, "ZUKAN_WORK"),
            new SaveField("tr_battleData", 0x7D3E0, 5656, "TR_BATTLE_DATA[707] à 8"),
            new SaveField("topMenuData", 0x7E9F8, 68, "TOPMENU_WORK"),
            new SaveField("fieldObj_Save", 0x7EA3C, 68000, "_FIELDOBJ_SAVE"),
            new SaveField("record", 0x8F3DC, 1440, "RECORD_ARRAY"),
            new SaveField("enc_sv_data", 0x8F97C, 392, "ENC_SV_DATA"),
            new SaveField("player_save_data", 0x8FB04, 128, "PLAYER_SAVE_DATA"),
            new SaveField("ballDecoData", 0x8FB84, 17032, "SaveBallDecoData"),
            new SaveField("saveSeal", 0x93E0C, 2400, "SaveSealData[200] à 12"),
            new SaveField("randomGroup", 0x9476C, 1584, "_RANDOM_GROUP"),
            new SaveField("fieldGimmickSaveData", 0x94D9C, 12, "FieldGimmickSaveData"),
            new SaveField("kinomiGrowSaveData", 0x94DA8, 2056, "KinomiGrowSaveData"),
            new SaveField("poffinSaveData", 0x955B0, 1604, "PoffinSaveData"),
            new SaveField("btlTowerSave", 0x95BF4, 440, "BTLTOWER_SAVEWORK"),
            new SaveField("systemData", 0x95DAC, 308, "SYSTEMDATA"),
            new SaveField("poketchData", 0x95EE0, 416, "POKETCH_DATA"),
            new SaveField("azukariyaData", 0x96080, 704, "AzukariyaData"),
            new SaveField("dendoudata", 0x96340, 14768, "_DENDOU_SAVEDATA"),
            new SaveField("badgeSaveData", 0x99CF0, 8, "BadgeSaveData"),
            new SaveField("boukenNote", 0x99CF8, 24, "BoukenNote"),
            new SaveField("tvDataOld", 0x99D10, 2956, "byte[]"),
            new SaveField("ugSaveData", 0x9A89C, 10144, "UgSaveData"),
            new SaveField("gmsdata", 0x9D03C, 201508, "GMS_DATA"),
            new SaveField("networkdata", 0xCE360, 1712, "PLAYER_NETWORK_DATA"),
            new SaveField("unionSaveData", 0xCEA10, 12, "UnionSaveData"),
            new SaveField("contstPhotoLangData", 0xCEA1C, 24, "CON_PHOTO_LANG_DATA"),
            new SaveField("zukanPersonalRndData", 0xCEA34, 100, "ZUKAN_PERSONAL_RND_DATA"),
            new SaveField("contestPhotoExtData", 0xCEA98, 160, "CON_PHOTO_EXT_DATA[]"),
            new SaveField("gmsPointExtData", 0xCEB38, 104000, "GMS_POINT_HISTORY_EXT_DATA[]"),
            new SaveField("ugCountRecord", 0xE8178, 32, "UgCountRecord"),
            new SaveField("reBuffNameData", 0xE8198, 5760, "ReBuffnameData"),
            new SaveField("saveDataHash", 0xE9818, 16, "byte[16] (MD5)"),
            new SaveField("recodeAddData", 0xE9828, 960, "RECORD_ADD_DATA"),
            new SaveField("mysteryGiftSaveData", 0xE9BE8, 13680, "MysteryGiftSaveData"),
            new SaveField("poketoreCountArray", 0xED158, 48, "POKETCH_POKETORE_COUNT_ARRAY"),
            new SaveField("playReportData", 0xED188, 248, "PLAYREPORT_DATA"),
            new SaveField("mtData", 0xED280, 1024, "MT_DATA"),
            new SaveField("dendouSaveAdd", 0xED680, 1440, "DENDOU_SAVE_ADD"),
            new SaveField("tvData", 0xEDC20, 4460, "TV_DATA"),
            new SaveField("ballDecoExtraData", 0xEED8C, 792, "SaveBallDecoExtraData"),
        };

        public static IReadOnlyList<SaveField> Fields => FieldTable;

        public static int TotalSize => BinarySizes[BinarySizes.Length - 1];

        // Erwartete Dateigröße/Hashlänge, null für Versionen ohne Tabelleneintrag.
        public static int? ExpectedSize(int version)
        {
            if (version < LaunchVersion || version > CurrentVersion) return null;
            return BinarySizes[version - LaunchVersion];
        }

        public static bool TryGetField(string name, out SaveField field)
        {
            foreach (var f in FieldTable)
            {
                if (f.Name == name)
                {
                    field = f;
                    return true;
                }
            }
            field = default;
            return false;
        }
    }
}
