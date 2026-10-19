using System;

namespace Xnu.Battle.Flow
{
    // BTL_SICKCONT: Dauer eines Zustands in 64 Bit (Spezifikation 4, Abschnitt 5.1).
    // Bits 0-2 Art (0 keine, 1 dauerhaft, 2 Runden, 3 Pokemon, 4 Pokemon+Runden), 3-7 Verursacher, 8-13 Rundenzahl/Zaehlmaximum/Pokemon-ID,
    // ab 14 (bei Art 4: Pokemon-ID 14-19, Parameter ab 20) Parameter (16 Bit); Bit 30 Flag.
    public static class SickCont
    {
        public const byte TypeNone = 0;
        public const byte TypePermanent = 1;
        public const byte TypeTurn = 2;
        public const byte TypePoke = 3;
        public const byte TypePokeTurn = 4;
        public const byte NoPoke = 0x1F;

        public static byte GetType(ulong c) => (byte)(c & 7);

        static ulong SetType(ulong c, uint type) => c & ~7UL | type & 7;

        static ulong SetCause(ulong c, uint cause) => c & 0xFFFFFFFFFFFFFF00UL | c & 7 | (cause & 0x1F) << 3;

        static ulong SetCount(ulong c, uint count) => c & 0xFFFFFFFFFFFFC000UL | c & 0xFF | (count & 0x3F) << 8;

        static ulong SetParam(ulong c, uint param) => c & 0xFFFFFFFFC0000000UL | c & 0x3FFF | (param & 0xFFFF) << 14;

        public static ulong MakeNull() => SetCause(SetType(0, TypeNone), NoPoke);

        public static ulong MakeNone(uint cause) => SetCause(0, cause);

        public static bool IsNull(ulong c) => GetType(c) == TypeNone;

        public static ulong MakeTurn(uint cause, uint turns) => SetParam(SetCount(SetCause(SetType(0, TypeTurn), cause), turns), 0);

        public static ulong MakeTurnParam(uint cause, uint turns, uint param) => SetParam(SetCount(SetCause(SetType(0, TypeTurn), cause), turns), param);

        public static ulong MakePoke(uint cause, uint pokeId) => SetCount(SetCause(SetType(0, TypePoke), cause), pokeId);

        public static ulong MakePermanent(uint cause) => SetCause(SetType(0, TypePermanent), cause);

        public static ulong MakePermanentInc(uint cause, uint countMax) => SetCount(MakePermanent(cause), countMax);

        public static ulong MakePermanentParam(uint cause, uint param) => SetParam(MakePermanent(cause), param);

        public static ulong MakePermanentIncParam(uint cause, uint countMax, uint param) => SetParam(MakePermanentInc(cause, countMax), param);

        public static ulong MakePokeTurn(uint cause, uint pokeId, uint turns)
        {
            ulong c = SetCount(SetCause(SetType(0, TypePokeTurn), cause), turns);
            return c & 0xFFFFFFFFFFF00000UL | c & 0x3FFF | (pokeId & 0x3F) << 14;
        }

        // Schwerer Giftzustand: Dauerzustand mit Zaehlmaximum 15.
        public static ulong MakeMoudokuCont(uint cause) => MakePermanentInc(cause, 0xF);

        public static ulong MakePokeTurnParam(uint cause, uint pokeId, uint turns, uint param)
            => MakePokeTurn(cause, pokeId, turns) & 0xFFFFFUL | (ulong)(param & 0xFFFF) << 20;

        public static byte GetCause(ulong c) => (byte)(c >> 3 & 0x1F);

        // Rundenzahl (Art 2) bzw. Pokemon-Rundenzahl (Art 4); sonst 0.
        public static byte GetTurnMax(ulong c)
        {
            byte t = GetType(c);
            return t == TypeTurn || t == TypePokeTurn ? (byte)(c >> 8 & 0x3F) : (byte)0;
        }

        public static byte GetPermanentCountMax(ulong c) => (byte)(c >> 8 & 0x3F);

        public static bool IsMoudokuCont(ulong c) => GetType(c) == TypePermanent && GetPermanentCountMax(c) == 0xF;

        public static byte GetPokeId(ulong c)
        {
            byte t = GetType(c);
            if (t == TypePoke) return (byte)(c >> 8 & 0x3F);
            if (t == TypePokeTurn) return (byte)(c >> 14 & 0x3F);
            return NoPoke;
        }

        public static ushort GetParam(ulong c)
        {
            switch (GetType(c))
            {
                case TypePermanent:
                case TypePoke:
                case TypeTurn:
                    return (ushort)(c >> 14);
                case TypePokeTurn:
                    return (ushort)(c >> 20);
                default:
                    return 0;
            }
        }
    }
}
