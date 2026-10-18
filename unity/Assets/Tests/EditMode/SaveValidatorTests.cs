using System;
using System.Linq;
using System.Security.Cryptography;
using NUnit.Framework;
using Xnu.Save;

namespace Xnu.Tests
{
    // Ausschließlich synthetische Bytes; spiegelt scripts/tests/test_bdsp_save.py.
    public class SaveValidatorTests
    {
        static byte[] MakeSave(int version = 0x34, int? size = null, bool validHash = true)
        {
            var n = size ?? SaveLayout.ExpectedSize(version).Value;
            var buf = new byte[n];
            for (var i = 0; i < n; i++) buf[i] = (byte)((i * 31 + 7) & 0xFF);
            BitConverter.GetBytes(version).CopyTo(buf, 0);
            if (n >= SaveLayout.HashEnd)
            {
                Array.Clear(buf, SaveLayout.HashOffset, SaveLayout.HashLength);
                byte[] h;
                if (validHash)
                {
                    using (var md5 = MD5.Create()) h = md5.ComputeHash(buf);
                }
                else
                {
                    h = Enumerable.Repeat((byte)0xAA, 16).ToArray();
                }
                Buffer.BlockCopy(h, 0, buf, SaveLayout.HashOffset, 16);
            }
            return buf;
        }

        // Tabellen

        [Test]
        public void ExpectedSizeTable()
        {
            Assert.AreEqual(0xEF0A4, SaveLayout.ExpectedSize(0x34));
            Assert.AreEqual(0xE9828, SaveLayout.ExpectedSize(0x25));
            Assert.AreEqual(0xEDC20, SaveLayout.ExpectedSize(0x2B));
            Assert.AreEqual(0xEDC20, SaveLayout.ExpectedSize(0x31));
            Assert.AreEqual(0xEED8C, SaveLayout.ExpectedSize(0x32));
            Assert.IsNull(SaveLayout.ExpectedSize(0x24));
            Assert.IsNull(SaveLayout.ExpectedSize(0x35));
        }

        [Test]
        public void FieldsAreContiguousAndSumToTotal()
        {
            var pos = 0;
            foreach (var f in SaveLayout.Fields)
            {
                Assert.AreEqual(pos, f.Offset, f.Name);
                pos += f.Size;
            }
            Assert.AreEqual(0xEF0A4, pos);
            Assert.AreEqual(0xEF0A4, SaveLayout.TotalSize);
        }

        [Test]
        public void HashAndGmsFieldsInTable()
        {
            Assert.IsTrue(SaveLayout.TryGetField("saveDataHash", out var hash));
            Assert.AreEqual(0xE9818, hash.Offset);
            Assert.AreEqual(16, hash.Size);
            Assert.IsTrue(SaveLayout.TryGetField("gmsdata", out var gms));
            Assert.AreEqual(0x9D03C, gms.Offset);
            Assert.IsFalse(SaveLayout.TryGetField("gibtEsNicht", out _));
        }

        [Test]
        public void VersionSizesMatchFieldStarts()
        {
            var starts = SaveLayout.Fields.Select(f => f.Offset).ToHashSet();
            for (var v = SaveLayout.LaunchVersion; v < SaveLayout.CurrentVersion; v++)
                Assert.IsTrue(starts.Contains(SaveLayout.ExpectedSize(v).Value), "Version 0x" + v.ToString("X"));
        }

        // Kopf und Hash

        [Test]
        public void ReadHeader()
        {
            var h = SaveValidator.ReadHeader(MakeSave());
            Assert.AreEqual(0x34, h.Version);
            Assert.AreEqual(0xEF0A4, h.Size);
        }

        [Test]
        public void ReadHeaderNegativeVersionIsSigned()
        {
            var h = SaveValidator.ReadHeader(new byte[] { 0xFF, 0xFF, 0xFF, 0xFF });
            Assert.AreEqual(-1, h.Version);
        }

        [Test]
        public void ValidCurrent()
        {
            var data = MakeSave();
            Assert.AreEqual(0xEF0A4, data.Length);
            Assert.AreEqual(true, SaveValidator.VerifyHash(data));
            CollectionAssert.AreEqual(SaveValidator.StoredHash(data), SaveValidator.ComputeHash(data));
            var r = SaveValidator.Validate(data);
            Assert.IsTrue(r.IsValid);
            Assert.IsEmpty(r.Problems);
        }

        [Test]
        public void ValidAllKnownVersions()
        {
            for (var v = 0x25; v <= 0x34; v++)
            {
                var data = MakeSave(v);
                Assert.AreEqual(SaveLayout.ExpectedSize(v).Value, data.Length, "Version " + v);
                Assert.AreEqual(true, SaveValidator.VerifyHash(data), "Version " + v);
            }
        }

        [Test]
        public void WrongHash()
        {
            var data = MakeSave(validHash: false);
            Assert.AreEqual(false, SaveValidator.VerifyHash(data));
            var r = SaveValidator.Validate(data);
            Assert.IsFalse(r.IsValid);
            Assert.AreEqual(false, r.HashValid);
            Assert.IsTrue(r.Problems.Contains("MD5 stimmt nicht"));
        }

        [Test]
        public void FlippedPayloadByte()
        {
            var data = MakeSave();
            data[0x1000] ^= 1;
            Assert.AreEqual(false, SaveValidator.VerifyHash(data));
        }

        [Test]
        public void TooLongHashCoversOnlyExpectedLength()
        {
            var data = MakeSave().Concat(new byte[8]).ToArray();
            Assert.AreEqual(true, SaveValidator.VerifyHash(data));
            var r = SaveValidator.Validate(data);
            Assert.AreEqual(false, r.SizeOk);
            Assert.IsFalse(r.IsValid);
            Assert.IsNotEmpty(r.Problems);
        }

        [Test]
        public void Truncated()
        {
            var data = MakeSave().Take(0xEF0A4 - 1).ToArray();
            Assert.Throws<SaveFormatException>(() => SaveValidator.VerifyHash(data));
            var r = SaveValidator.Validate(data);
            Assert.AreEqual(false, r.SizeOk);
            Assert.IsNull(r.HashValid);
            Assert.IsFalse(r.IsValid);
        }

        [Test]
        public void TruncatedBelowHashField()
        {
            var data = MakeSave().Take(0x1000).ToArray();
            Assert.Throws<SaveFormatException>(() => SaveValidator.VerifyHash(data));
            Assert.Throws<SaveFormatException>(() => SaveValidator.StoredHash(data));
        }

        [Test]
        public void TooShortForHeader()
        {
            Assert.Throws<SaveFormatException>(() => SaveValidator.ReadHeader(new byte[] { 0x34, 0x00 }));
            var r = SaveValidator.Validate(new byte[2]);
            Assert.IsFalse(r.HasHeader);
            Assert.IsFalse(r.IsValid);
            Assert.IsNotEmpty(r.Problems);
        }

        [Test]
        public void UnknownVersion()
        {
            var data = MakeSave();
            BitConverter.GetBytes(0x35).CopyTo(data, 0);
            Assert.Throws<SaveFormatException>(() => SaveValidator.VerifyHash(data));
            var r = SaveValidator.Validate(data);
            Assert.IsNull(r.HashValid);
            Assert.IsNull(r.ExpectedSize);
            Assert.IsFalse(r.IsValid);
            Assert.IsTrue(r.Problems.Any(p => p.Contains("unbekannte Version")));
        }

        [Test]
        public void OldVersionNotChecked()
        {
            var data = new byte[104];
            BitConverter.GetBytes(0x20).CopyTo(data, 0);
            Assert.IsNull(SaveValidator.VerifyHash(data));
            Assert.IsFalse(SaveValidator.Validate(data).IsValid);
        }

        [Test]
        public void HashIgnoresStoredHashBytes()
        {
            var data = MakeSave();
            var other = (byte[])data.Clone();
            for (var i = 0; i < 16; i++) other[SaveLayout.HashOffset + i] = 0x11;
            CollectionAssert.AreEqual(SaveValidator.ComputeHash(data), SaveValidator.ComputeHash(other));
        }

        [Test]
        public void ComputeHashDoesNotMutateInput()
        {
            var data = MakeSave(validHash: false);
            var before = (byte[])data.Clone();
            SaveValidator.ComputeHash(data);
            SaveValidator.Validate(data);
            CollectionAssert.AreEqual(before, data);
        }

        // FixHash

        [Test]
        public void FixHashReturnsCopyOnly()
        {
            var bad = MakeSave(validHash: false);
            var before = (byte[])bad.Clone();
            var fixedData = SaveWriter.FixHash(bad);
            CollectionAssert.AreEqual(before, bad);
            Assert.AreNotSame(bad, fixedData);
            Assert.AreEqual(true, SaveValidator.VerifyHash(fixedData));
            Assert.AreEqual(bad.Length, fixedData.Length);
            CollectionAssert.AreEqual(bad.Take(SaveLayout.HashOffset), fixedData.Take(SaveLayout.HashOffset));
            CollectionAssert.AreEqual(bad.Skip(SaveLayout.HashEnd), fixedData.Skip(SaveLayout.HashEnd));
        }

        [Test]
        public void FixHashOnValidDataKeepsBytes()
        {
            var good = MakeSave();
            CollectionAssert.AreEqual(good, SaveWriter.FixHash(good));
        }

        [Test]
        public void FixHashRejectsOldVersionUnknownVersionAndTruncated()
        {
            var old = new byte[104];
            BitConverter.GetBytes(0x20).CopyTo(old, 0);
            Assert.Throws<SaveFormatException>(() => SaveWriter.FixHash(old));

            var unknown = MakeSave();
            BitConverter.GetBytes(0x35).CopyTo(unknown, 0);
            Assert.Throws<SaveFormatException>(() => SaveWriter.FixHash(unknown));

            Assert.Throws<SaveFormatException>(() => SaveWriter.FixHash(MakeSave().Take(5000).ToArray()));
        }
    }
}
