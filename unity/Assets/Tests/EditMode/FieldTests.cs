using System;
using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Boot;
using Xnu.Data;
using Xnu.Field;
using Xnu.Input;

namespace Xnu.Tests
{
    // Gemeinsame synthetische Karten für die Feldtests (keine Spieldaten).
    static class FieldFixtures
    {
        // Codes: 0 Boden, 2 Gras, 16 Wasser, 100 Brücke (113 = BRIDGE_GROUND), 215 Absprungkante, 1 gesperrt (Entry 0)
        public static AttributeCodeTable Table()
        {
            return new AttributeCodeTable(new[]
            {
                new MapAttributeCodeRecord { Code = 0, Attribute = 0, Entry = true },
                new MapAttributeCodeRecord { Code = 1, Attribute = 255, Entry = false },
                new MapAttributeCodeRecord { Code = 2, Attribute = 2, Entry = true, Encounter = true },
                new MapAttributeCodeRecord { Code = 3, Attribute = 3, Entry = true, Encounter = true },
                new MapAttributeCodeRecord { Code = 16, Attribute = 16, Entry = true, Water = true },
                new MapAttributeCodeRecord { Code = 113, Attribute = 113, Entry = true },
                new MapAttributeCodeRecord { Code = 118, Attribute = 118, Entry = true },
                new MapAttributeCodeRecord { Code = 115, Attribute = 115, Entry = true, Water = true },
                new MapAttributeCodeRecord { Code = 215, Attribute = 215, Entry = true },
            });
        }

        public static int[] Block(int fill = 0)
        {
            var b = new int[32 * 32];
            for (var i = 0; i < b.Length; i++) b[i] = fill;
            return b;
        }

        public static void Set(int[] block, int x, int y, int raw) => block[y * 32 + x] = raw;

        public static FieldCollision Collision(int[] block, int[] exBlock = null)
        {
            var main = new AttributeLayer("t", 1, new[] { block });
            var ex = exBlock == null ? null : new AttributeLayer("t_ex", 1, new[] { exBlock });
            return new FieldCollision(main, ex, Table());
        }
    }

    public class FieldCoordsTests
    {
        [Test]
        public void RasterUndWeltSindGespiegelteX()
        {
            Assert.AreEqual(-116f, FieldCoords.WorldX(116));
            Assert.AreEqual(886f, FieldCoords.WorldZ(886));
            Assert.AreEqual(116, FieldCoords.GridX(-116f));
            Assert.AreEqual(886, FieldCoords.GridY(886f));
        }

        [Test]
        public void ZellgrenzenLiegenAmHalbenSchritt()
        {
            // Zelle gx = 5 reicht von x = -5.5 (ausschließlich) bis -4.5.
            Assert.AreEqual(5, FieldCoords.GridX(-5.4f));
            Assert.AreEqual(5, FieldCoords.GridX(-4.6f));
            Assert.AreEqual(4, FieldCoords.GridX(-4.4f));
            Assert.AreEqual(10, FieldCoords.GridY(9.6f));
            Assert.AreEqual(9, FieldCoords.GridY(9.4f));
        }

        [Test]
        public void BlockUndZelleImBlock()
        {
            Assert.AreEqual(3, FieldCoords.BlockOf(116));
            Assert.AreEqual(20, FieldCoords.CellInBlock(116));
            Assert.AreEqual(27, FieldCoords.BlockOf(886));
            Assert.AreEqual(22, FieldCoords.CellInBlock(886));
            Assert.AreEqual(-96f, FieldCoords.BlockOriginX(3));
            Assert.AreEqual(864f, FieldCoords.BlockOriginZ(27));
            Assert.AreEqual(3, FieldCoords.BlockColumnOfOriginX(-96f));
            Assert.AreEqual(27, FieldCoords.BlockRowOfOriginZ(864f));
        }
    }

    public class FieldAttributeTests
    {
        [Test]
        public void ZellwertWirdInCodeUndStopZerlegt()
        {
            Assert.AreEqual(0, AttributeCell.Decode(0).Code);
            Assert.AreEqual(128, AttributeCell.Decode(128).Stop);
            Assert.IsTrue(AttributeCell.Decode(128).IsBlocked);
            var water = AttributeCell.Decode(16000);
            Assert.AreEqual(16, water.Code);
            Assert.AreEqual(0, water.Stop);
            var door = AttributeCell.Decode(105128);
            Assert.AreEqual(105, door.Code);
            Assert.AreEqual(128, door.Stop);
            Assert.IsTrue(door.IsBlocked);
            Assert.AreEqual(999, AttributeCell.Decode(999).Stop);
        }

        [Test]
        public void ExHoeheUnterscheidetObenUndUnten()
        {
            // Rohwert = Höhe * 1_000_000 + oben * 1000 + unten; Höhe 100 entspricht Spielerhöhe 0.
            var raw = 100 * 1000000 + 115 * 1000 + 16;
            Assert.IsTrue(ExAttribute.IsHigh(raw, 0f));
            Assert.AreEqual(115, ExAttribute.HeightAttribute(raw, 0f));
            var raised = 102 * 1000000 + 115 * 1000 + 16;
            Assert.IsFalse(ExAttribute.IsHigh(raised, 1.0f));
            Assert.AreEqual(16, ExAttribute.HeightAttribute(raised, 1.0f));
            Assert.IsTrue(ExAttribute.IsHigh(raised, 1.6f));
        }

        [Test]
        public void LayerLiestBlockweiseUndBehandeltLuecken()
        {
            var a = FieldFixtures.Block();
            var b = FieldFixtures.Block();
            FieldFixtures.Set(a, 3, 4, 128);
            FieldFixtures.Set(b, 31, 31, 16000);
            // Matrix 2 breit, zweite Zeile: nur linker Block.
            var layer = new AttributeLayer("m", 2, new[] { a, b, null, a });
            Assert.AreEqual(128, layer.GetRaw(3, 4));
            Assert.AreEqual(16000, layer.GetRaw(32 + 31, 31));
            Assert.AreEqual(128, layer.GetRaw(32 + 3, 32 + 4));
            Assert.IsTrue(layer.HasBlockAt(40, 40));
            Assert.IsFalse(layer.HasBlockAt(5, 40));       // Block fehlt
            Assert.AreEqual(0, layer.GetRaw(5, 40));        // wie im Original: ohne Block begehbar
            Assert.IsFalse(layer.HasBlockAt(-1, 0));
            Assert.IsFalse(layer.HasBlockAt(64, 0));
            Assert.AreEqual(0, layer.GetRaw(-3, 2));
            Assert.AreEqual(2, layer.BlockColumns);
        }

        [Test]
        public void LayerAusMatrixUndBloecken()
        {
            var block = new AttributeBlockRecord { Name = "b0", Width = 32, Attributes = FieldFixtures.Block(0) };
            block.Attributes[5 * 32 + 7] = 2000;
            var matrix = new AttributeMatrixRecord { Name = "M", Width = 2, BlockNames = new[] { "", "b0" } };
            var layer = new AttributeLayer(matrix, n => n == "b0" ? block : null);
            Assert.IsFalse(layer.HasBlockAt(0, 0));
            Assert.AreEqual(2000, layer.GetRaw(32 + 7, 5));
            Assert.AreEqual(2, layer.Get(32 + 7, 5).Code);
        }

        [Test]
        public void BlockMitFalscherBreiteWirdAbgelehnt()
        {
            var block = new AttributeBlockRecord { Name = "b0", Width = 16, Attributes = new int[256] };
            var matrix = new AttributeMatrixRecord { Name = "M", Width = 1, BlockNames = new[] { "b0" } };
            Assert.Throws<ArgumentException>(() => new AttributeLayer(matrix, n => block));
        }

        [Test]
        public void GrasUndLanggrasNachOriginal()
        {
            Assert.IsTrue(AttributeCodes.IsGrass(2));
            Assert.IsFalse(AttributeCodes.IsGrass(3));
            Assert.IsTrue(AttributeCodes.IsLongGrass(3));
            Assert.IsTrue(AttributeCodes.IsGrass(5));
            Assert.IsTrue(AttributeCodes.IsGrass(9));
            Assert.IsTrue(AttributeCodes.IsGrass(10));
            Assert.IsFalse(AttributeCodes.IsGrass(8));
            Assert.IsTrue(AttributeCodes.IsGrass(0xA9));
        }
    }

    public class FieldCollisionTests
    {
        [Test]
        public void BodenIstBegehbarWandUndStopNicht()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 1, 0, 128);          // nur Stop
            FieldFixtures.Set(b, 2, 0, 1000);         // Code 1: Entry 0
            FieldFixtures.Set(b, 3, 0, 2000);         // Gras
            var c = FieldFixtures.Collision(b);
            Assert.IsTrue(c.CanEnter(0, 0, 0f, false, false).CanEnter);
            Assert.AreEqual(BlockReason.Stop, c.CanEnter(1, 0, 0f, false, false).Reason);
            Assert.AreEqual(BlockReason.NoEntry, c.CanEnter(2, 0, 0f, false, false).Reason);
            Assert.IsTrue(c.CanEnter(3, 0, 0f, false, false).CanEnter);
        }

        [Test]
        public void WasserNurZumSchwimmen()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 4, 4, 16000);
            var c = FieldFixtures.Collision(b);
            Assert.AreEqual(BlockReason.Water, c.CanEnter(4, 4, 0f, false, false).Reason);
            Assert.IsTrue(c.CanEnter(4, 4, 0f, false, true).CanEnter);
            Assert.AreEqual(BlockReason.Land, c.CanEnter(5, 5, 0f, false, true).Reason);
        }

        [Test]
        public void AbsprungkanteZuFussGesperrtMitFahrradNicht()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 6, 6, 215000);
            var c = FieldFixtures.Collision(b);
            Assert.AreEqual(BlockReason.Ledge, c.CanEnter(6, 6, 0f, false, false).Reason);
            Assert.IsTrue(c.CanEnter(6, 6, 0f, true, false).CanEnter);
        }

        [Test]
        public void FahrradNichtAufLanggras()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 7, 7, 3000);
            var c = FieldFixtures.Collision(b);
            Assert.IsTrue(c.CanEnter(7, 7, 0f, false, false).CanEnter);
            Assert.AreEqual(BlockReason.BicycleNoEntry, c.CanEnter(7, 7, 0f, true, false).Reason);
        }

        [Test]
        public void BrueckeObenGehenUntenSchwimmen()
        {
            var b = FieldFixtures.Block();
            var ex = FieldFixtures.Block(100 * 1000000);
            // Wasserbrücke (115): oben = 115 (Wasser), unten = 16 (Wasser); wir testen mit Code 115 als Hauptcode.
            FieldFixtures.Set(b, 8, 8, 115000);
            FieldFixtures.Set(ex, 8, 8, 101 * 1000000 + 115 * 1000 + 16);
            var c = FieldFixtures.Collision(b, ex);
            // Spieler auf Höhe >= 1: oben, Wasserzelle: zu Fuß erlaubt (über das Wasser); Schwimmen bleibt wegen der Wasserzelle möglich.
            Assert.IsTrue(c.CanEnter(8, 8, 1f, false, false).CanEnter);
            Assert.IsTrue(c.CanEnter(8, 8, 1f, false, true).CanEnter);
            // Spieler auf Höhe 0: unter der Brücke, Schwimmen erlaubt, Laufen nicht.
            Assert.IsTrue(c.CanEnter(8, 8, 0f, false, true).CanEnter);
            Assert.IsFalse(c.CanEnter(8, 8, 0f, false, false).CanEnter);
        }

        [Test]
        public void SenkrechteBrueckeVonObenQuerGesperrt()
        {
            var b = FieldFixtures.Block();
            var ex = FieldFixtures.Block(100 * 1000000);
            FieldFixtures.Set(b, 9, 9, 118000);   // BRIDGEV_GROUND
            FieldFixtures.Set(ex, 9, 9, 100 * 1000000 + 118 * 1000);
            var c = FieldFixtures.Collision(b, ex);
            Assert.AreEqual(BlockReason.Bridge, c.CanEnter(9, 9, 0f, false, false).Reason);
            Assert.IsTrue(c.CanEnter(9, 9, 0f, true, false).CanEnter);
        }

        [Test]
        public void ZellenAusserhalbDerKarteSindStandardmaessigGesperrt()
        {
            var c = FieldFixtures.Collision(FieldFixtures.Block());
            Assert.IsFalse(c.CanEnter(-1, 0, 0f, false, false).CanEnter);
            Assert.IsFalse(c.CanEnter(0, 40, 0f, false, false).CanEnter);
            c.OutsideBlocked = false;
            Assert.IsTrue(c.CanEnter(0, 40, 0f, false, false).CanEnter);
        }

        [Test]
        public void UnbekannterCodeIstNichtBetretbar()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 2, 2, 77000);
            var c = FieldFixtures.Collision(b);
            Assert.AreEqual(BlockReason.NoEntry, c.CanEnter(2, 2, 0f, false, false).Reason);
        }
    }

    public class FieldInputAndCameraTests
    {
        [Test]
        public void VierWegBegrenzungWieImOriginal()
        {
            Assert.AreEqual(MoveDir.None, FieldInputMath.LimitToFourWay(0f, 0f));
            Assert.AreEqual(MoveDir.Up, FieldInputMath.LimitToFourWay(0.3f, 0.9f));
            Assert.AreEqual(MoveDir.Down, FieldInputMath.LimitToFourWay(-0.3f, -0.9f));
            Assert.AreEqual(MoveDir.Right, FieldInputMath.LimitToFourWay(0.9f, 0.3f));
            Assert.AreEqual(MoveDir.Left, FieldInputMath.LimitToFourWay(-0.9f, 0.3f));
            // Gleichstand: horizontal gewinnt (|y| <= |x|).
            Assert.AreEqual(MoveDir.Right, FieldInputMath.LimitToFourWay(0.7f, 0.7f));
            Assert.AreEqual(MoveDir.Left, FieldInputMath.LimitToFourWay(-0.7f, 0.7f));
        }

        [Test]
        public void RichtungenSindSpiegelbildlichInX()
        {
            Assert.AreEqual((0, 1), MoveDir.Up.GridDelta());
            Assert.AreEqual((-1, 0), MoveDir.Right.GridDelta());
            Assert.AreEqual((1, 0), MoveDir.Left.GridDelta());
            Assert.AreEqual((0, -1), MoveDir.Down.GridDelta());
            Assert.AreEqual(90f, MoveDir.Right.YawDegrees());
        }

        [Test]
        public void KameraStehtHinterUndUeberDemBrennpunkt()
        {
            var focus = FieldCameraMath.Focus(-116f, 1f, 886f);
            Assert.AreEqual(1.5f, focus.Y, 1e-5f);
            var pos = FieldCameraMath.Position(focus, 42.5f, 0f, 30f);
            Assert.AreEqual(-116f, pos.X, 1e-4f);
            Assert.AreEqual(1.5f + 30f * (float)Math.Sin(42.5 * Math.PI / 180), pos.Y, 1e-3f);
            Assert.AreEqual(886f - 30f * (float)Math.Cos(42.5 * Math.PI / 180), pos.Z, 1e-3f);
        }

        [Test]
        public void KameraMitGierDreht()
        {
            var f = FieldCameraMath.Forward(0f, 180f);
            Assert.AreEqual(0f, f.X, 1e-5f);
            Assert.AreEqual(-1f, f.Z, 1e-5f);
        }

        [Test]
        public void FolgenBegrenztDenSchritt()
        {
            var c = (X: 0f, Y: 0f, Z: 0f);
            var g = (X: 10f, Y: 0f, Z: 0f);
            Assert.AreEqual(5f, FieldCameraMath.Follow(c, g, 15f, 1f / 30f).X, 1e-4f);
            Assert.AreEqual(10f, FieldCameraMath.Follow(c, g, 100f, 1f).X, 1e-4f);
            Assert.AreEqual(0f, FieldCameraMath.Follow(c, g, -5f, 1f).X, 1e-4f);
        }
    }

    public class FieldMoverTests
    {
        const float Dt = 1f / 30f;

        static GridMover Mover(FieldCollision c, int x = 5, int y = 5, IGroundHeight g = null) => new GridMover(c, g ?? new FlatGround(), x, y);

        [Test]
        public void EinSchrittDauertEineZelleDurchGeschwindigkeit()
        {
            var m = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            var ticks = 0;
            MoveEvents all = MoveEvents.None;
            while (m.GridY == 5 && ticks < 100) { all |= m.Tick(Dt, MoveDir.Up, false); ticks++; }
            Assert.AreEqual(6, m.GridY);
            Assert.AreEqual(5, m.GridX);
            // 3,7 Zellen/s bei 30 Hz: ceil(30 / 3,7) = 9 Ticks (8,1 Schritte ...) für die erste Zelle.
            Assert.AreEqual((int)Math.Ceiling(1f / (GridMover.DefaultWalkSpeed * Dt)), ticks);
            Assert.IsTrue((all & MoveEvents.Started) != 0);
            Assert.IsTrue((all & MoveEvents.Arrived) != 0);
        }

        [Test]
        public void GehalteneRichtungVerkettetSchritteOhnePause()
        {
            var m = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            for (var i = 0; i < 60; i++) m.Tick(Dt, MoveDir.Up, false);   // 2 s
            // 2 s * 3,7 Zellen/s = 7,4 Zellen
            Assert.AreEqual(5 + 7, m.GridY);
            Assert.AreEqual(7, m.StepsTaken);
            Assert.AreEqual(0.4f, m.Progress, 0.05f);
        }

        [Test]
        public void LaufenIstSchneller()
        {
            var walk = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            var run = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            for (var i = 0; i < 30; i++) { walk.Tick(Dt, MoveDir.Up, false); run.Tick(Dt, MoveDir.Up, true); }
            Assert.Greater(run.StepsTaken, walk.StepsTaken);
            Assert.AreEqual(3, walk.StepsTaken);
            Assert.AreEqual(7, run.StepsTaken);
        }

        [Test]
        public void RechtsLaufenVerkleinertGx()
        {
            var m = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            for (var i = 0; i < 30; i++) m.Tick(Dt, MoveDir.Right, false);
            Assert.Less(m.GridX, 5);
            Assert.Greater(m.WorldX, -5f + 1f);   // Welt-X wächst nach rechts
            Assert.AreEqual(MoveDir.Right, m.Facing);
        }

        [Test]
        public void WandBlocktUndDrehtNur()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 6, 128);
            var m = Mover(FieldFixtures.Collision(b));
            var ev = m.Tick(Dt, MoveDir.Up, false);
            Assert.IsTrue((ev & MoveEvents.Bumped) != 0);
            Assert.AreEqual(BlockReason.Stop, m.LastBlock);
            Assert.AreEqual(MoveDir.Up, m.Facing);
            Assert.IsFalse(m.IsMoving);
            Assert.AreEqual(5, m.GridY);
        }

        [Test]
        public void WasserSperrtZuFussUndSchwimmerKommenHinein()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 6, 16000);
            var m = Mover(FieldFixtures.Collision(b));
            m.Tick(Dt, MoveDir.Up, false);
            Assert.AreEqual(BlockReason.Water, m.LastBlock);
            Assert.AreEqual(5, m.GridY);
            m.Swim = true;
            for (var i = 0; i < 20; i++) m.Tick(Dt, MoveDir.Up, false);
            Assert.AreEqual(6, m.GridY);   // im Wasser, nächste Zelle ist Land: gesperrt
            Assert.AreEqual(BlockReason.Land, m.LastBlock);
        }

        [Test]
        public void RichtungswechselErstAnDerZellgrenze()
        {
            var m = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            m.Tick(Dt, MoveDir.Up, false);
            Assert.IsTrue(m.IsMoving);
            m.Tick(Dt, MoveDir.Right, false);    // mitten im Schritt: Ziel bleibt oben
            Assert.AreEqual(6, m.TargetY);
            Assert.AreEqual(5, m.TargetX);
            for (var i = 0; i < 12; i++) m.Tick(Dt, MoveDir.None, false);
            Assert.AreEqual(6, m.GridY);
            Assert.IsFalse(m.IsMoving);
        }

        [Test]
        public void KeineEingabeKeineBewegung()
        {
            var m = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            for (var i = 0; i < 30; i++) Assert.AreEqual(MoveEvents.None, m.Tick(Dt, MoveDir.None, false));
            Assert.AreEqual(5, m.GridX);
            Assert.AreEqual(5, m.GridY);
        }

        [Test]
        public void GrosserZeitschrittVerliertKeineZellen()
        {
            var m = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            m.Tick(1.0f, MoveDir.Up, false);
            Assert.AreEqual(5 + 3, m.GridY);
        }

        [Test]
        public void StufenUeberBodenhoehe()
        {
            var stairs = new StairGround();
            var b = FieldFixtures.Block();
            var m = new GridMover(FieldFixtures.Collision(b), stairs, 5, 5);
            Assert.AreEqual(0f, m.Height, 1e-5f);
            for (var i = 0; i < 40; i++) m.Tick(Dt, MoveDir.Up, false);
            Assert.Greater(m.Height, 0.5f);
            Assert.AreEqual(Math.Min(2f, Math.Max(0f, (m.WorldZ - 7f) * 0.5f)), m.Height, 0.01f);
        }

        [Test]
        public void HoeheBestimmtObenUntenAnDerBruecke()
        {
            var b = FieldFixtures.Block();
            var ex = FieldFixtures.Block(100 * 1000000);
            FieldFixtures.Set(b, 5, 6, 115000);
            FieldFixtures.Set(ex, 5, 6, 101 * 1000000 + 115 * 1000 + 16);
            var c = FieldFixtures.Collision(b, ex);
            var low = new GridMover(c, new FlatGround(0f), 5, 5);
            low.Tick(Dt, MoveDir.Up, false);
            Assert.AreEqual(BlockReason.Water, low.LastBlock);      // unten: Wasser, zu Fuß gesperrt
            var high = new GridMover(c, new FlatGround(1.5f), 5, 5);
            high.Tick(Dt, MoveDir.Up, false);
            Assert.IsTrue(high.IsMoving);                            // oben: über das Wasser gehen
        }

        [Test]
        public void TeleportSetztZustandZurueck()
        {
            var m = Mover(FieldFixtures.Collision(FieldFixtures.Block()));
            m.Tick(Dt, MoveDir.Up, false);
            m.Teleport(10, 12, MoveDir.Left);
            Assert.AreEqual(10, m.GridX);
            Assert.AreEqual(12, m.GridY);
            Assert.IsFalse(m.IsMoving);
            Assert.AreEqual(MoveDir.Left, m.Facing);
            Assert.AreEqual(-10f, m.WorldX);
        }

        sealed class StairGround : IGroundHeight
        {
            public bool TryGetHeight(float x, float z, float fromY, out float y)
            {
                y = Math.Min(2f, Math.Max(0f, (z - 7f) * 0.5f));
                return true;
            }
        }
    }

    public class FieldDataSetTests
    {
        static FieldDataSet MakeData()
        {
            var info = new MapInfoTables();
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 10, AreaId = 1, ZoneGridName = "G", AttributeName = "M", AttributeExName = "M_Ex", AssetBundleName = "fields/x" });
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 11, AreaId = 2, AttributeName = "R", AssetBundleName = "prefab_map/r" });
            for (var i = 0; i < 12; i++) info.Cameras.Add(new ZoneCameraRecord { AreaId = 1, Pitch = 45f, Fov = 20f, TargetRange = 30f });
            info.Cameras[10] = new ZoneCameraRecord { AreaId = 1, Pitch = 42.5f, Fov = 18f, TargetRange = 30f };
            var grids = new List<ZoneGridRecord>
            {
                new ZoneGridRecord { Name = "G", Width = 3, ZoneIds = new[] { -1, 10, -1, -1, 10, 11 } },
            };
            var block = new AttributeBlockRecord { Name = "b", Width = 32, Attributes = FieldFixtures.Block() };
            block.Attributes[0] = 128;
            var blocks = new List<AttributeBlockRecord> { block };
            var matrices = new List<AttributeMatrixRecord>
            {
                new AttributeMatrixRecord { Name = "M", Width = 3, BlockNames = new[] { "", "b", "", "", "b", "" } },
                new AttributeMatrixRecord { Name = "R", Width = 1, BlockNames = new[] { "b" } },
            };
            var codes = new List<MapAttributeCodeRecord> { new MapAttributeCodeRecord { Code = 0, Entry = true } };
            return FieldDataSet.Build(info, grids, blocks, matrices, codes);
        }

        [Test]
        public void ZonenBloeckeAusRasterUndInnenraum()
        {
            var d = MakeData();
            Assert.IsTrue(d.TryGetZone(10, out var z));
            var blocks = d.ZoneBlocks(z);
            CollectionAssert.AreEquivalent(new[] { (1, 0), (1, 1) }, blocks);
            Assert.IsTrue(d.TryGetZone(11, out var room));
            CollectionAssert.AreEqual(new[] { (0, 0) }, d.ZoneBlocks(room));
        }

        [Test]
        public void KollisionAusMatrixUndBlock()
        {
            var d = MakeData();
            d.TryGetZone(10, out var z);
            var c = d.BuildCollision(z);
            Assert.IsTrue(c.CellAt(32, 0).IsBlocked);        // Block (1, 0), Zelle (0, 0)
            Assert.IsTrue(c.CanEnter(33, 0, 0f, false, false).CanEnter);
            Assert.IsFalse(c.CanEnter(0, 0, 0f, false, false).CanEnter);    // Block fehlt: gesperrt
        }

        [Test]
        public void KameraUndZoneNachschlagen()
        {
            var d = MakeData();
            Assert.IsTrue(d.TryGetCamera(10, out var cam));
            Assert.AreEqual(42.5f, cam.Pitch);
            Assert.IsTrue(d.TryGetCamera(11, out var cam11));
            Assert.AreEqual(45f, cam11.Pitch);
            Assert.IsFalse(d.TryGetCamera(12, out _));
            Assert.IsFalse(d.TryGetCamera(-1, out _));
            Assert.IsFalse(d.TryGetZone(99, out _));
            d.TryGetZone(10, out var z);
            Assert.IsNull(d.BuildLayer("fehlt"));
            Assert.IsNotNull(d.BuildLayer(z.AttributeName));
        }

        [Test]
        public void ZoneOhneMatrixWirdAbgelehnt()
        {
            var d = MakeData();
            Assert.Throws<System.IO.InvalidDataException>(() => d.BuildCollision(new ZoneInfoRecord { ZoneId = 5, AttributeName = "fehlt" }));
        }
    }

    public class FieldBundleFilterTests
    {
        sealed class FakeHandle : IBundleHandle
        {
            public bool Unloaded;
            public string[] GetAllAssetNames() => new string[0];
            public bool IsStreamedSceneBundle => false;
            public UnityEngine.Object LoadAsset(string assetName, Type type) => null;
            public void Unload(bool all) { Unloaded = true; }
        }

        sealed class FakeSource : IBundleSource
        {
            public readonly List<string> Loaded = new List<string>();
            public IBundleHandle Load(string path) { Loaded.Add(path); return new FakeHandle(); }
        }

        static BundleCatalog Catalog()
        {
            var shaders = new BundleRecord { Project = "Dpr", Name = "shaders", AssetPaths = new[] { "assets/shaders/a.shader" } };
            var tex = new BundleRecord { Project = "Environments", Name = "common/tex" };
            var map = new BundleRecord { Project = "Environments", Name = "prefab_map/x", Dependencies = new[] { "shaders", "common/tex" } };
            return new BundleCatalog(new[] { shaders, tex, map });
        }

        [Test]
        public void ShaderBundlesWerdenErkannt()
        {
            var c = Catalog();
            Assert.IsTrue(FieldController.IsShaderBundle(c.GetBundle("Dpr/shaders")));
            Assert.IsFalse(FieldController.IsShaderBundle(c.GetBundle("Environments/prefab_map/x")));
            Assert.IsTrue(FieldController.IsShaderBundle(new BundleRecord { Name = "fx/effects", AssetPaths = new[] { "assets/a.shader" } }));
        }

        [Test]
        public void AbhaengigkeitsfilterLaedtDasShaderBundleNicht()
        {
            var src = new FakeSource();
            var p = new BundleProvider(Catalog(), "/root", src) { DependencyFilter = r => !FieldController.IsShaderBundle(r) };
            p.Acquire("Environments/prefab_map/x");
            Assert.AreEqual(2, p.LoadedBundleCount);
            Assert.IsFalse(p.IsLoaded("Dpr/shaders"));
            Assert.IsTrue(p.IsLoaded("Environments/common/tex"));
            Assert.IsTrue(p.Release("Environments/prefab_map/x"));
            Assert.AreEqual(0, p.LoadedBundleCount);
        }

        [Test]
        public void OhneFilterBleibtVerhaltenUnveraendert()
        {
            var src = new FakeSource();
            var p = new BundleProvider(Catalog(), "/root", src);
            p.Acquire("Environments/prefab_map/x");
            Assert.AreEqual(3, p.LoadedBundleCount);
            p.Release("Environments/prefab_map/x");
            Assert.AreEqual(0, p.LoadedBundleCount);
        }
    }
}
