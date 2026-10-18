using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using Xnu.PokePara;
using Xnu.Save;

namespace Xnu.Tests
{
    // Hilfen für SaveWrite*/SaveStorage*-Tests: synthetische Saves (deterministisch, keine echten Daten) und Zugriff auf den lokalen Save.
    static class SaveTestSupport
    {
        public const string BrilliantDiamond = SaveInspector.BrilliantDiamondTitleId;

        // Version 0x34, Rest deterministisches Rauschen (damit unberührte Bereiche auffallen), leere kodierte Pokémon-Slots, gültiger Hash.
        public static byte[] NewSave(uint seed = 1)
        {
            var buf = new byte[SaveLayout.TotalSize];
            var s = seed * 2654435761u + 1;
            for (var i = 0; i < buf.Length; i++)
            {
                s = s * 1664525u + 1013904223u;
                buf[i] = (byte)(s >> 24);
            }
            buf[0] = SaveLayout.CurrentVersion;
            buf[1] = buf[2] = buf[3] = 0;
            var empty = PokemonParam.CreateEmpty();
            for (var i = 0; i < PokeLayout.PartyCapacity; i++) PokeSaveSlots.WriteParty(buf, i, empty);
            PokeSaveSlots.SetPartyCount(buf, 1);
            for (var t = 0; t < PokeLayout.TrayCount; t++)
                for (var p = 0; p < PokeLayout.TraySlots; p++)
                    PokeSaveSlots.WriteBox(buf, t, p, empty);
            return SaveWriter.FixHash(buf);
        }

        public static PokemonParam Sample(ushort species = 483, uint rnd = 0x00006000)
        {
            var p = new PokemonParam();
            p.Core.PersonalRnd = rnd;
            p.Core.SpeciesNo = species;
            p.Core.HeldItem = 234;
            p.Core.TrainerId = 0xA1B2C3D4;
            p.Core.Exp = 125000;
            p.Core.Nickname = "Testwesen";
            p.Core.HasNickname = true;
            p.Core.SetMove(0, 57);
            p.Core.CurrentHp = 100;
            p.Core.TrainerName = "Spieler";
            p.Level = 50;
            p.MaxHp = 207;
            return p;
        }

        // Anzahl abweichender Bytes und ob alle in erlaubten [start, end)-Bereichen liegen.
        public static int Diff(byte[] a, byte[] b, IEnumerable<(int Start, int End)> allowed, out bool outside)
        {
            Assert.AreEqual(a.Length, b.Length);
            var list = new List<(int Start, int End)>(allowed);
            var count = 0;
            outside = false;
            for (var i = 0; i < a.Length; i++)
            {
                if (a[i] == b[i]) continue;
                count++;
                var ok = false;
                foreach (var r in list)
                    if (i >= r.Start && i < r.End) { ok = true; break; }
                if (!ok) outside = true;
            }
            return count;
        }

        public static (int Start, int End) HashRange => (SaveLayout.HashOffset, SaveLayout.HashEnd);

        // Lokaler echter Save (nur lesen). XNU_REAL_SAVE überschreibt; sonst vom Arbeitsverzeichnis/Testordner nach oben suchen.
        public static string FindRealSave(string file = "SaveData.bin")
        {
            var env = Environment.GetEnvironmentVariable("XNU_REAL_SAVE");
            if (!string.IsNullOrEmpty(env) && File.Exists(env)) return env;
            foreach (var start in new[] { Environment.CurrentDirectory, AppContext.BaseDirectory })
            {
                var dir = start;
                for (var i = 0; i < 10 && dir != null; i++, dir = Path.GetDirectoryName(dir))
                {
                    var c = Path.Combine(dir, "Ryujinx", "bis", "user", "save", "0000000000000006", "0", file);
                    if (File.Exists(c)) return c;
                }
            }
            return null;
        }

        public static byte[] RequireRealSave(out string path, string file = "SaveData.bin")
        {
            path = FindRealSave(file);
            if (path == null) Assert.Ignore("lokaler Save nicht vorhanden (Ryujinx/bis/user/save/0000000000000006/0/" + file + ")");
            return File.ReadAllBytes(path);
        }

        public static string NewTempDir()
        {
            var d = Path.Combine(Path.GetTempPath(), "xnu-save-test-" + Guid.NewGuid().ToString("N").Substring(0, 12));
            Directory.CreateDirectory(d);
            return d;
        }

        public static void Cleanup(string dir)
        {
            if (dir != null && Directory.Exists(dir)) Directory.Delete(dir, true);
        }

        // Baut den kleinsten imkvdb.arc (Aufbau wie am lokalen Index gemessen) mit den gegebenen Einträgen.
        public static byte[] BuildIndex(params (ulong Program, byte Type, ulong SaveId)[] entries)
        {
            using (var ms = new MemoryStream())
            using (var w = new BinaryWriter(ms))
            {
                w.Write(new[] { (byte)'I', (byte)'M', (byte)'K', (byte)'V' });
                w.Write(0u);
                w.Write((uint)entries.Length);
                foreach (var e in entries)
                {
                    w.Write(new[] { (byte)'I', (byte)'M', (byte)'E', (byte)'N' });
                    w.Write(0x40u);
                    w.Write(0x40u);
                    var key = new byte[0x40];
                    BitConverter.GetBytes(e.Program).CopyTo(key, 0);
                    key[0x20] = e.Type;
                    w.Write(key);
                    var val = new byte[0x40];
                    BitConverter.GetBytes(e.SaveId).CopyTo(val, 0);
                    w.Write(val);
                }
                return ms.ToArray();
            }
        }
    }
}
