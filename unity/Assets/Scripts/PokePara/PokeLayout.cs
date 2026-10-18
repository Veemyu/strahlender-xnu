namespace Xnu.PokePara
{
    // Reihenfolge der vier Datenblöcke im logischen Sinn (CoreDataBlockId des Originals).
    public enum CoreBlock
    {
        A = 0,
        B = 1,
        C = 2,
        D = 3,
    }

    // Konstanten des Pokémon-Slots (Pml.PokePara, docs/pokepara-spezifikation.md Abschnitt 2).
    // Ein Slot ist 344 Byte groß: CoreData (328 Byte = 8 Byte Kopf + 4 Blöcke je 80 Byte) und CalcData (16 Byte).
    public static class PokeLayout
    {
        public const int SlotSize = 344;
        public const int CoreSize = 328;
        public const int HeaderSize = 8;
        public const int BlockSize = 80;
        public const int BlockCount = 4;
        // Kodierter Bereich: die vier Blöcke (Offset 8, Länge 320); der Kopf bleibt im Klartext.
        public const int EncodedOffset = 8;
        public const int EncodedLength = 320;
        public const int CalcOffset = 328;
        public const int CalcSize = 16;

        public const int PersonalRndOffset = 0;
        public const int HeaderFlagsOffset = 4;
        public const int ChecksumOffset = 6;

        public const int NameChars = 13;
        public const int NameBytes = 26;
        public const int MaxNameLength = 12;

        // Party im Spielstand: 6 Slots, danach Anzahl und Markierungsindex (SavePokeParty, 2066 Byte).
        public const int PartyCapacity = 6;
        public const int PartyMemberCountOffset = PartyCapacity * SlotSize;
        public const int PartyMarkingIndexOffset = PartyMemberCountOffset + 1;
        public const int PartySize = PartyMarkingIndexOffset + 1;

        // PC-Boxen: 40 Ablagen mit je 30 Slots (SaveBoxTrayData, 10320 Byte).
        public const int TrayCount = 40;
        public const int TraySlots = 30;
        public const int TrayStride = TraySlots * SlotSize;

        // SaveBoxData (1610 Byte): trayMax liegt 45 Byte vor dem Ende der Struktur (Fundlage am echten Save, siehe Spezifikation).
        public const int BoxDataSize = 1610;
        public const int BoxDataTrayMaxFromEnd = 45;

        // Offsets innerhalb der Blöcke.
        public static class A
        {
            public const int SpeciesNo = 0x00;       // ushort monsno
            public const int HeldItem = 0x02;        // ushort itemno
            public const int TrainerId = 0x04;       // uint id
            public const int Exp = 0x08;             // uint
            public const int Ability = 0x0C;         // ushort tokuseino
            public const int FlagsA = 0x0E;          // ushort: Bit0..2 Fähigkeit 1/2/3, 3 Favorit, 4 Spezial-G, 5 Debug
            public const int BoxMark = 0x10;         // ushort
            public const int ColorRnd = 0x14;        // uint
            public const int Nature = 0x18;          // byte seikaku
            public const int NatureAdjust = 0x19;    // byte seikakuHosei (für Statuswerte maßgebliches Wesen)
            public const int FlagsB = 0x1A;          // byte: Bit0 Ereignis, 1 offizieller Kampf, 2..3 Geschlecht
            public const int FormNo = 0x1C;          // ushort
            public const int EvHp = 0x1E;
            public const int EvAtk = 0x1F;
            public const int EvDef = 0x20;
            public const int EvSpeed = 0x21;
            public const int EvSpAtk = 0x22;
            public const int EvSpDef = 0x23;
            public const int Style = 0x24;           // Wettbewerbswerte: Style, Beautiful, Cute, Clever, Strong, Fur
            public const int Pokerus = 0x2A;
            public const int RibbonA = 0x2C;         // uint, Bänder 0..31
            public const int RibbonB = 0x30;         // uint, Bänder 32..63
            public const int LumpingRibbonA = 0x34;
            public const int LumpingRibbonB = 0x35;
            public const int RibbonC = 0x38;         // uint, Bänder 64..95
            public const int RibbonD = 0x3C;         // uint, Bänder 96..127
            public const int CampFriendship = 0x40;  // byte (Wort _bitsC)
            public const int CampReserved = 0x44;    // uint
            public const int TalentHeight = 0x48;    // byte
            public const int TalentWeight = 0x49;    // byte
            public const int FlagsD = 0x4A;          // byte: Bit0 dpr_illegal_flag
        }

        public static class B
        {
            public const int Nickname = 0x00;        // 13 UTF-16-Zeichen
            public const int Moves = 0x1A;           // 4 × ushort
            public const int Pp = 0x22;              // 4 × byte
            public const int PpUps = 0x26;           // 4 × byte
            public const int EggMoves = 0x2A;        // 4 × ushort
            public const int Hp = 0x32;              // ushort aktuelle KP
            public const int IvBits = 0x34;          // uint: 6 × 5 Bit IV, Bit 30 Ei, Bit 31 Spitzname
            public const int EffortG = 0x38;         // byte
            public const int Sick = 0x3C;            // uint Zustandsbits
            public const int Palma = 0x40;           // uint
        }

        public static class C
        {
            public const int PastParentsName = 0x00;
            public const int PastParentsSex = 0x1A;
            public const int PastParentsLang = 0x1B;
            public const int OwnedByOthers = 0x1C;
            public const int OthersFriendshipTrainerId = 0x1E; // ushort
            public const int OthersFriendship = 0x20;
            public const int OthersMemoriesLevel = 0x21;
            public const int OthersMemoriesCode = 0x22;
            public const int OthersMemoriesFeel = 0x23;
            public const int OthersMemoriesData = 0x24;        // ushort
            public const int PokeJob = 0x26;                   // 14 Byte Bitfeld
            public const int Enjoy = 0x34;
            public const int NadeNade = 0x35;
            public const int CassetteVersion = 0x36;
            public const int BattleRomMark = 0x37;
            public const int LangId = 0x3A;
            public const int MultiWork = 0x3C;                 // uint
            public const int EquipRibbon = 0x40;
        }

        public static class D
        {
            public const int TrainerName = 0x00;               // 13 UTF-16-Zeichen
            public const int Friendship = 0x1A;                // Freundschaft zum Erstbesitzer
            public const int MemoriesLevel = 0x1B;
            public const int MemoriesCode = 0x1C;
            public const int MemoriesData = 0x1E;              // ushort
            public const int MemoriesFeel = 0x20;
            public const int EggYear = 0x21;
            public const int EggMonth = 0x22;
            public const int EggDay = 0x23;
            public const int MetYear = 0x24;                   // "firstContact" im Original, Accessor: Birth*
            public const int MetMonth = 0x25;
            public const int MetDay = 0x26;
            public const int EggPlace = 0x28;                  // ushort "getPlace"
            public const int MetPlace = 0x2A;                  // ushort "birthPlace"
            public const int Ball = 0x2C;
            public const int LevelAndSex = 0x2D;               // Bit0..6 Fangstufe, Bit7 Geschlecht des Trainers
            public const int TrainingFlags = 0x2E;             // Bit i: Wert i gilt als 31 (siehe Statuswerte)
            public const int MoveRecord = 0x2F;                // 14 Byte Bitfeld
            public const int BankUniqueId = 0x3D;              // 8 Byte (unausgerichtet)
        }

        // CalcData-Offsets (16 Byte).
        public static class Calc
        {
            public const int Level = 0x0;
            public const int MaxHp = 0x2;
            public const int Atk = 0x4;
            public const int Def = 0x6;
            public const int Speed = 0x8;
            public const int SpAtk = 0xA;
            public const int SpDef = 0xC;
            public const int GState = 0xE;
        }
    }
}
