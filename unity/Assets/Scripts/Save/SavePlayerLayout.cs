namespace Xnu.Save
{
    // Native Offsets innerhalb von PLAYER_DATA (Datei-Offset 0x79B74, 1972 Byte) und SaveItem.
    // Herkunft: Marshal-Routine PLAYER_DATA (Ghidra 0x2e9050) und SaveItem (0x2af6d0), disassembliert; die Abbildung
    // verwaltet → nativ ist dort Feld für Feld sichtbar (bool = 4 Byte). Siehe docs/save-kompatibilitaet.md.
    public static class SavePlayerLayout
    {
        public const int PlayerDataOffset = 0x79B74;
        public const int PlayerDataSize = 1972;

        // MYSTATUS (nativ, relativ zu PLAYER_DATA)
        public const int NameOffset = 0x40;
        public const int NameChars = 13;
        public const int MaxNameLength = 12;
        public const int TrainerIdOffset = 0x5C;
        public const int MoneyOffset = 0x60;
        public const int SexOffset = 0x64;
        public const int RegionCodeOffset = 0x68;
        public const int BadgeOffset = 0x69;
        public const int RomCodeOffset = 0x6B;

        // PLAYTIME: ushort Stunden, Byte Minuten, Byte Sekunden
        public const int PlayHoursOffset = 0x90;
        public const int PlayMinutesOffset = 0x92;
        public const int PlaySecondsOffset = 0x93;

        // MoneyWork.MAX_MOENY (dump.cs); MoneyWork.Set klemmt auf 0..999999 (Disassembly 0x207d350).
        public const int MaxMoney = 999999;

        // rivalName: festes UTF-16-Feld auf Top-Level-Ebene (Feldtabelle: 0x55F4, 64 Byte).
        public const int RivalNameOffset = 0x55F4;
        public const int RivalNameChars = 32;

        // saveItem[3000] zu je 16 Byte: Count (u32) @0, VanishNew (bool, 4 Byte) @4, FavoriteFlag @8, ShowWazaNameFlag @9,
        // Dummy1 @10, Dummy2 @11, SortNumber (u16) @12, 2 Byte Padding.
        public const int ItemSlotCount = 3000;
        public const int ItemStride = 16;
        public const int ItemCountOffset = 0;
        public const int ItemVanishNewOffset = 4;
        public const int ItemFavoriteOffset = 8;
        public const int ItemShowWazaNameOffset = 9;
        public const int ItemSortNumberOffset = 12;
        public const int ItemMaxCount = 999;
    }
}
