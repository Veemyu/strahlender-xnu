using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.Field
{
    // Eigenschaften der Attributcodes (MapAttributeTable): Zeile = Code; Entry = betretbar, Water = Wasser,
    // Encounter = Wildbegegnung (Gras), Attribute = Unterart (bei manchen Codes weicht sie vom Code ab).
    public sealed class AttributeCodeTable
    {
        public readonly struct Entry
        {
            public readonly int Attribute;
            public readonly bool CanEnter;
            public readonly bool Water;
            public readonly bool Encounter;

            public Entry(int attribute, bool canEnter, bool water, bool encounter)
            {
                Attribute = attribute; CanEnter = canEnter; Water = water; Encounter = encounter;
            }
        }

        readonly Dictionary<int, Entry> _byCode = new Dictionary<int, Entry>();

        public int Count => _byCode.Count;

        public AttributeCodeTable(IEnumerable<MapAttributeCodeRecord> records)
        {
            foreach (var r in records)
                _byCode[r.Code] = new Entry(r.Attribute, r.Entry, r.Water, r.Encounter);
        }

        public bool TryGet(int code, out Entry entry) => _byCode.TryGetValue(code, out entry);
    }

    // Namen der Attributcodes (MapAttribute-Enum und AttributeID.MATR_Is*-Funktionen aus dem Original).
    public static class AttributeCodes
    {
        public const int Ground = 0;
        public const int Ice = 0x20;
        public const int Sand = 0x21;
        public const int StairsRight = 0x5E;
        public const int StairsLeft = 0x5F;
        public const int Door = 0x69;
        public const int Counter = 0x80;
        public const int TakeOffLeft = 0xD7;
        public const int TakeOffRight = 0xD8;

        public static bool IsWaterHeightLevel(int c) => c >= 0x56 && c <= 0x58;

        // AttributeID.MATR_IsGrass: 2, 4..7, 9, 10 und 0xA9 (Langgras 3 hat eine eigene Prüfung).
        public static bool IsGrass(int c) => c == 2 || (c >= 4 && c <= 7) || c == 9 || c == 10 || c == 0xA9;

        // 113..125 (BRIDGE_GROUND .. BRIDGEH_SAND)
        public static bool IsBridge(int c) => c >= 0x71 && c <= 0x7D;
        public static bool IsBridgeVertical(int c) => c >= 0x76 && c <= 0x79;
        public static bool IsBridgeHorizontal(int c) => c >= 0x7A && c <= 0x7D;
        public static bool IsLongGrass(int c) => c == 3;
        public static bool IsShallowSnow(int c) => c == 0xA1;
        public static bool IsSnowDeep(int c) => c == 0xA2;
        public static bool IsSnowDeepMost(int c) => c == 0xA3;

        // Fahrrad darf nicht auf diese Unterarten (AttributeID.IsBicycleNoEntory auf Entry.Attribute).
        public static bool IsBicycleNoEntry(int attribute) =>
            attribute == 3 || (attribute >= 0xA1 && attribute <= 0xA6) || attribute == 0xA7 || attribute == 0xA8;
    }
}
