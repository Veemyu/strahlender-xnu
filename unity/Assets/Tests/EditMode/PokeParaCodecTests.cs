using System;
using System.Collections.Generic;
using NUnit.Framework;
using Xnu.PokePara;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Hilfen für die PokePara-Tests: Hex-Fixtures (synthetische Zufallsdaten) und deterministische Slots.
    static class PokeParaTestUtil
    {
        public static byte[] Hex(object value) => Hex((string)value);

        public static byte[] Hex(string s)
        {
            var b = new byte[s.Length / 2];
            for (int i = 0; i < b.Length; i++) b[i] = Convert.ToByte(s.Substring(2 * i, 2), 16);
            return b;
        }

        public static string ToHex(byte[] b) => BitConverter.ToString(b).Replace("-", "").ToLowerInvariant();

        // Einfacher deterministischer Zufall (LCG), unabhängig vom Code unter Test.
        public sealed class Lcg
        {
            ulong _s;

            public Lcg(ulong seed)
            {
                _s = seed;
            }

            public uint Next()
            {
                _s = unchecked(_s * 6364136223846793005UL + 1442695040888963407UL);
                return (uint)(_s >> 33);
            }

            public byte[] Bytes(int n)
            {
                var b = new byte[n];
                for (int i = 0; i < n; i++) b[i] = (byte)(Next() >> 7);
                return b;
            }
        }
    }

    // Verschlüsselung, Prüfsumme und Blockmischung gegen die echten Spielfunktionen (Orakel, Unicorn).
    public class PokeParaCodecTests
    {
        static Dictionary<string, object> _root;
        static Dictionary<string, object> Root => _root ??= Load("PokeParaCodec.json");

        [Test]
        public void ChecksumMatchesGameFunction()
        {
            var cases = Cases(Root, "checksum");
            Assert.Greater(cases.Count, 10);
            foreach (var c in cases)
            {
                var data = PokeParaTestUtil.Hex(c["data"]);
                Assert.AreEqual(U32(c, "sum"), PokeEncoder.CalcChecksum(data, 0, data.Length), "Länge " + data.Length);
            }
        }

        [Test]
        public void ChecksumIgnoresOddTrailingByte()
        {
            Assert.AreEqual(0x0201u, PokeEncoder.CalcChecksum(new byte[] { 1, 2, 3 }, 0, 3));
            Assert.AreEqual(0u, PokeEncoder.CalcChecksum(new byte[0], 0, 0));
            Assert.AreEqual((ushort)0x0001, PokeEncoder.Checksum16(new byte[] { 0xFF, 0xFF, 0x02, 0x00 }, 0, 4));
        }

        [Test]
        public void EncodeAndDecodeMatchGameFunctions()
        {
            var cases = Cases(Root, "crypt");
            Assert.Greater(cases.Count, 20);
            foreach (var c in cases)
            {
                uint seed = U32(c, "seed");
                var plain = PokeParaTestUtil.Hex(c["plain"]);
                var expected = PokeParaTestUtil.Hex(c["encoded"]);
                var buf = (byte[])plain.Clone();
                PokeEncoder.Encode(buf, 0, buf.Length, seed);
                CollectionAssert.AreEqual(expected, buf, "Encode, Seed " + seed);
                PokeEncoder.Decode(buf, 0, buf.Length, seed);
                CollectionAssert.AreEqual(plain, buf, "Decode, Seed " + seed);
                CollectionAssert.AreEqual(PokeParaTestUtil.Hex(c["decodedAgain"]), plain);
            }
        }

        [Test]
        public void EncodeWithOffsetTouchesOnlyTheRange()
        {
            var buf = new byte[10];
            PokeEncoder.Encode(buf, 2, 6, 0x1234);
            Assert.AreEqual(0, buf[0] | buf[1] | buf[8] | buf[9]);
            Assert.AreNotEqual(0, buf[2] | buf[3] | buf[4] | buf[5] | buf[6] | buf[7]);
        }

        [Test]
        public void NextRandCodeMatchesGameFunction()
        {
            foreach (var c in Cases(Root, "nextRand"))
            {
                uint state = U32(c, "seed");
                ushort code = PokeEncoder.NextRandCode(ref state);
                Assert.AreEqual(U32(c, "state"), state);
                Assert.AreEqual(I(c, "code"), code);
            }
        }

        [Test]
        public void BlockPositionMatchesGameFunctionForAllShuffleRows()
        {
            var cases = Cases(Root, "blockPos");
            Assert.GreaterOrEqual(cases.Count, 32);
            foreach (var c in cases)
            {
                uint rnd = U32(c, "rnd");
                var pos = LongList(c["pos"]);
                for (int b = 0; b < 4; b++)
                    Assert.AreEqual(pos[b], PokeEncoder.BlockPosition(rnd, (CoreBlock)b), $"rnd {rnd}, Block {b}");
            }
        }

        [Test]
        public void ShuffleTableMatchesBinaryAndIsAPermutationPerRow()
        {
            var table = Matrix(Root["shuffleTable"]);
            Assert.AreEqual(PokeEncoder.ShuffleRows, table.Count);
            for (int r = 0; r < table.Count; r++)
            {
                var seen = new HashSet<long>();
                for (int c = 0; c < 4; c++)
                {
                    Assert.AreEqual(table[r][c], PokeEncoder.ShuffleEntry(r, c), $"Zeile {r}, Spalte {c}");
                    seen.Add(table[r][c]);
                }
                Assert.AreEqual(4, seen.Count, "Zeile " + r);
            }
        }

        [Test]
        public void BlockOffsetsAreInsideTheEncodedRange()
        {
            for (uint shift = 0; shift < 32; shift++)
            {
                var offsets = new HashSet<int>();
                for (int b = 0; b < 4; b++)
                {
                    int o = PokeEncoder.BlockOffset(shift << 13, (CoreBlock)b);
                    Assert.GreaterOrEqual(o, PokeLayout.HeaderSize);
                    Assert.LessOrEqual(o + PokeLayout.BlockSize, PokeLayout.CoreSize);
                    offsets.Add(o);
                }
                Assert.AreEqual(4, offsets.Count);
            }
        }

        [Test]
        public void RareColorMatchesGameFunction()
        {
            int rare = 0;
            foreach (var c in Cases(Root, "rare"))
            {
                bool expected = B(c, "rare");
                if (expected) rare++;
                Assert.AreEqual(expected, PokemonParam.IsRareColor(U32(c, "id"), U32(c, "colorRnd")));
            }
            Assert.Greater(rare, 0);
        }
    }
}
