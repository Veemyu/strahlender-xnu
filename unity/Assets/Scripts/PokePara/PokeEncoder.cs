using System;

namespace Xnu.PokePara
{
    // Pml.PokePara.Encoder: Prüfsumme und LCG-Strom (docs/pokepara-spezifikation.md Abschnitt 3).
    public static class PokeEncoder
    {
        public const uint LcgFactor = 0x41C64E6D;
        public const uint LcgIncrement = 0x6073;

        // Encoder.CalcChecksum @0x2152460: Summe der 16-Bit-Wörter (little endian) in 32 Bit; ein ungerades Restbyte zählt nicht.
        public static uint CalcChecksum(byte[] data, int offset, int count)
        {
            Check(data, offset, count);
            uint sum = 0;
            for (int i = 0; i + 1 < count; i += 2)
                sum = unchecked(sum + (uint)(data[offset + i] | (data[offset + i + 1] << 8)));
            return sum;
        }

        // Im Slot gespeichert werden nur die unteren 16 Bit.
        public static ushort Checksum16(byte[] data, int offset, int count) => unchecked((ushort)CalcChecksum(data, offset, count));

        // Encoder.CalcNextRandCode @0x2152500: Zustand fortschalten, Rückgabe sind die oberen 16 Bit des neuen Zustands.
        public static ushort NextRandCode(ref uint state)
        {
            state = unchecked(state * LcgFactor + LcgIncrement);
            return (ushort)(state >> 16);
        }

        // Encoder.Encode @0x21524d0 und Encoder.Decode @0x2152520 sind identisch: jedes 16-Bit-Wort wird mit dem nächsten
        // LCG-Code (Startzustand = Seed) per XOR verknüpft. Ein ungerades Restbyte bleibt unverändert.
        public static void Crypt(byte[] data, int offset, int count, uint seed)
        {
            Check(data, offset, count);
            uint state = seed;
            for (int i = 0; i + 1 < count; i += 2)
            {
                ushort key = NextRandCode(ref state);
                data[offset + i] ^= (byte)key;
                data[offset + i + 1] ^= (byte)(key >> 8);
            }
        }

        public static void Encode(byte[] data, int offset, int count, uint seed) => Crypt(data, offset, count, seed);

        public static void Decode(byte[] data, int offset, int count, uint seed) => Crypt(data, offset, count, seed);

        // Standard-Permutationen der Blockreihenfolge in lexikografischer Reihenfolge. Das Spiel hat eine Tabelle mit 32 Zeilen
        // (Accessor..cctor @0x25ac480); Zeile i entspricht Permutation i % 24.
        static readonly byte[][] Shuffle =
        {
            new byte[] { 0, 1, 2, 3 }, new byte[] { 0, 1, 3, 2 }, new byte[] { 0, 2, 1, 3 }, new byte[] { 0, 3, 1, 2 },
            new byte[] { 0, 2, 3, 1 }, new byte[] { 0, 3, 2, 1 }, new byte[] { 1, 0, 2, 3 }, new byte[] { 1, 0, 3, 2 },
            new byte[] { 2, 0, 1, 3 }, new byte[] { 3, 0, 1, 2 }, new byte[] { 2, 0, 3, 1 }, new byte[] { 3, 0, 2, 1 },
            new byte[] { 1, 2, 0, 3 }, new byte[] { 1, 3, 0, 2 }, new byte[] { 2, 1, 0, 3 }, new byte[] { 3, 1, 0, 2 },
            new byte[] { 2, 3, 0, 1 }, new byte[] { 3, 2, 0, 1 }, new byte[] { 1, 2, 3, 0 }, new byte[] { 1, 3, 2, 0 },
            new byte[] { 2, 1, 3, 0 }, new byte[] { 3, 1, 2, 0 }, new byte[] { 2, 3, 1, 0 }, new byte[] { 3, 2, 1, 0 },
            new byte[] { 0, 1, 2, 3 }, new byte[] { 0, 1, 3, 2 }, new byte[] { 0, 2, 1, 3 }, new byte[] { 0, 3, 1, 2 },
            new byte[] { 0, 2, 3, 1 }, new byte[] { 0, 3, 2, 1 }, new byte[] { 1, 0, 2, 3 }, new byte[] { 1, 0, 3, 2 },
        };

        public const int ShuffleRows = 32;

        // Accessor.GetCoreDataBlockPos @0x25a3e00: Zeile (personalRnd >> 13) & 0x1f, Spalte = logischer Block; Ergebnis = physische Position 0..3.
        public static int BlockPosition(uint personalRnd, CoreBlock block)
        {
            int id = (int)block;
            if (id < 0 || id >= PokeLayout.BlockCount) throw new ArgumentOutOfRangeException(nameof(block));
            return Shuffle[(int)((personalRnd >> 13) & 0x1F)][id];
        }

        // Byteoffset des Blocks im 328-Byte-Kern.
        public static int BlockOffset(uint personalRnd, CoreBlock block) => PokeLayout.HeaderSize + BlockPosition(personalRnd, block) * PokeLayout.BlockSize;

        public static int ShuffleEntry(int row, int column) => Shuffle[row][column];

        static void Check(byte[] data, int offset, int count)
        {
            if (data == null) throw new ArgumentNullException(nameof(data));
            if (offset < 0 || count < 0 || offset + count > data.Length) throw new ArgumentOutOfRangeException(nameof(count));
        }
    }
}
