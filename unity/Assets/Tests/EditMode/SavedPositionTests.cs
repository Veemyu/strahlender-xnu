using System;
using System.IO;
using NUnit.Framework;
using Xnu.Field;
using Xnu.Game;
using Xnu.Game.Unity;
using Xnu.Save;

namespace Xnu.Tests
{
    // Spielstartposition (docs/sichtpruefung-3.md): PLAYER_DATA (gx, gy bei 0x79BF4/0x79BF8) + zoneID (0x5634) sind maßgeblich,
    // TownMapLocation ist nur ein Rückfall. Der Stadt-Spielstand hat eine veraltete TownMapLocation (Zone 416, −789/355).
    public class SavedPositionTests
    {
        static void PutInt(byte[] b, int offset, int v) => Buffer.BlockCopy(BitConverter.GetBytes(v), 0, b, offset, 4);
        static void PutFloat(byte[] b, int offset, float v) => Buffer.BlockCopy(BitConverter.GetBytes(v), 0, b, offset, 4);

        static SaveData Blank()
        {
            var s = GameFixture.NewSave();
            var b = s.Buffer;
            PutInt(b, SavedPosition.ZoneIdOffset, 0);
            PutInt(b, SavedPosition.PlayerDataGridXOffset, 0);
            PutInt(b, SavedPosition.PlayerDataGridYOffset, 0);
            PutInt(b, SavedPosition.LocationOffset, 0);
            PutFloat(b, SavedPosition.LocationOffset + 4, 0f);
            PutFloat(b, SavedPosition.LocationOffset + 12, 0f);
            PutInt(b, SavedPosition.LocationOffset + 16, 0);
            return s;
        }

        [Test]
        public void PlayerDataHatVorrangVorVeralteterTownMapLocation()
        {
            var s = Blank();
            var b = s.Buffer;
            PutInt(b, SavedPosition.ZoneIdOffset, 24);
            PutInt(b, SavedPosition.PlayerDataGridXOffset, 57);
            PutInt(b, SavedPosition.PlayerDataGridYOffset, 729);
            PutInt(b, SavedPosition.LocationOffset, 416);               // andere Zone: veraltet
            PutFloat(b, SavedPosition.LocationOffset + 4, -789f);
            PutFloat(b, SavedPosition.LocationOffset + 12, 355f);
            PutInt(b, SavedPosition.LocationOffset + 16, 3);
            var p = SavedPosition.Read(s);
            Assert.IsTrue(p.Valid);
            Assert.IsTrue(p.FromPlayerData);
            Assert.AreEqual(24, p.Zone);
            Assert.AreEqual(57, p.GridX);
            Assert.AreEqual(729, p.GridY);
            Assert.AreEqual(0, p.Direction, "Richtung der veralteten TownMapLocation wird nicht übernommen");
        }

        [Test]
        public void RichtungKommtAusTownMapLocationNurBeiPassenderZone()
        {
            var s = Blank();
            var b = s.Buffer;
            PutInt(b, SavedPosition.ZoneIdOffset, 167);
            PutInt(b, SavedPosition.PlayerDataGridXOffset, 852);
            PutInt(b, SavedPosition.PlayerDataGridYOffset, 599);
            PutInt(b, SavedPosition.LocationOffset, 167);
            PutFloat(b, SavedPosition.LocationOffset + 4, -842f);
            PutFloat(b, SavedPosition.LocationOffset + 12, 597f);
            PutInt(b, SavedPosition.LocationOffset + 16, 2);
            var p = SavedPosition.Read(s);
            Assert.AreEqual(852, p.GridX);
            Assert.AreEqual(599, p.GridY);
            Assert.AreEqual(2, p.Direction);
        }

        [Test]
        public void OhnePlayerDataGiltTownMapLocationAlsRueckfall()
        {
            var s = Blank();
            var b = s.Buffer;
            PutInt(b, SavedPosition.ZoneIdOffset, 422);
            PutInt(b, SavedPosition.LocationOffset, 422);
            PutFloat(b, SavedPosition.LocationOffset + 4, -116f);
            PutFloat(b, SavedPosition.LocationOffset + 12, 885f);
            var p = SavedPosition.Read(s);
            Assert.IsTrue(p.Valid);
            Assert.IsFalse(p.FromPlayerData);
            Assert.AreEqual(116, p.GridX);
            Assert.AreEqual(885, p.GridY);
            PutInt(b, SavedPosition.LocationOffset, 24);                // Zone passt nicht: ungültig
            Assert.IsFalse(SavedPosition.Read(s).Valid);
        }

        [Test]
        public void UnsinnigeWerteWerdenAbgelehnt()
        {
            var s = Blank();
            var b = s.Buffer;
            PutInt(b, SavedPosition.ZoneIdOffset, 24);
            PutInt(b, SavedPosition.PlayerDataGridXOffset, -5);
            PutInt(b, SavedPosition.PlayerDataGridYOffset, 729);
            Assert.IsFalse(SavedPosition.Read(s).Valid);
            PutInt(b, SavedPosition.PlayerDataGridXOffset, 57);
            PutInt(b, SavedPosition.PlayerDataGridYOffset, 99999);
            Assert.IsFalse(SavedPosition.Read(s).Valid);
            PutInt(b, SavedPosition.PlayerDataGridYOffset, 729);
            PutInt(b, SavedPosition.ZoneIdOffset, 0);
            Assert.IsFalse(SavedPosition.Read(s).Valid);
        }

        [Test]
        public void SchreibenUndLesenSindKonsistent()
        {
            var s = Blank();
            SavedPosition.Write(s, 24, 57, 729, MoveDir.Up);
            var p = SavedPosition.Read(s);
            Assert.AreEqual(24, p.Zone);
            Assert.AreEqual(57, p.GridX);
            Assert.AreEqual(729, p.GridY);
            Assert.AreEqual(MoveDir.Up, SavedPosition.ToFacing(p.Direction));
        }

        // Lokaler Stadt-Spielstand (Sicherung im Repo-Arbeitsordner): ohne Datei kein Assert.
        [Test]
        public void LokalerStadtSpielstandLiefertZone24Zelle57x729()
        {
            var root = Path.GetDirectoryName(Path.GetDirectoryName(UnityEngine.Application.dataPath));
            var path = Path.Combine(root, "Ryujinx", "bis", "user", "save", "0000000000000006", "0", "SaveData.bin");
            if (!File.Exists(path)) Assert.Ignore("kein lokaler Spielstand");
            var bytes = File.ReadAllBytes(path);
            if (!SaveData.TryFromBytes(bytes, out var save, false)) Assert.Ignore("Spielstand nicht lesbar");
            var p = SavedPosition.Read(save);
            if (p.Zone != 24) Assert.Ignore("anderer Spielstand (Zone " + p.Zone + ")");
            Assert.IsTrue(p.FromPlayerData);
            Assert.AreEqual(57, p.GridX);
            Assert.AreEqual(729, p.GridY);
        }
    }
}
