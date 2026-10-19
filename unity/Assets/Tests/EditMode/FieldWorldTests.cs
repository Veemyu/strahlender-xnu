using System;
using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Data;
using Xnu.Field;

namespace Xnu.Tests
{
    // Synthetische Welt für Zonenwechsel, Platzierungen und Interaktion (keine Spieldaten).
    static class WorldFixtures
    {
        public static Vec4 Loc(float x, float y, float z) => new Vec4 { X = x, Y = y, Z = z };

        public static FieldDataSet MakeWorld(out List<MapWarpSet> sets)
        {
            var empty = Loc(0, 0, 0);
            var info = new MapInfoTables();
            // Feldzonen 422 und 354 teilen sich das Gebiet area001, 500 liegt im Gebiet area002.
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 422, IsField = true, ZoneGridName = "Sinnoh", AssetBundleName = "fields/area001", Locators = new[] { Loc(10, 20, 0), Loc(5, 5, 2), empty } });
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 354, IsField = true, ZoneGridName = "Sinnoh", AssetBundleName = "fields/area001", Locators = new[] { Loc(40, 5, 0) } });
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 500, IsField = true, ZoneGridName = "Sinnoh", AssetBundleName = "fields/area002", Locators = new[] { Loc(40, 40, 0) } });
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 425, AssetBundleName = "prefab_map/t01r0201", Locators = new[] { Loc(6, 10, 2), Loc(10, 3, 3), empty } });
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 426, AssetBundleName = "prefab_map/t01r0202", Locators = new[] { Loc(3, 6, 2), Loc(8, 4, 1) } });
            var grids = new List<ZoneGridRecord> { new ZoneGridRecord { Name = "Sinnoh", Width = 2, ZoneIds = new[] { 422, 354, 422, 500 } } };
            var d = FieldDataSet.Build(info, grids, new List<AttributeBlockRecord>(), new List<AttributeMatrixRecord>(), new List<MapAttributeCodeRecord>());

            var room = new MapWarpSet { Name = "MapWarp_T01R0201" };
            room.Warps.Add(new MapWarpRecord
            {
                Position = new Vec3 { X = 5.75f, Y = 0, Z = 10 }, Size = new Vec2 { X = 1.5f, Y = 1 }, WarpZone = 422, WarpIndex = 0,
                InputDirection = 2, ConnectionName = "T01R0201_D01",
            });
            room.Warps.Add(new MapWarpRecord
            {
                Position = new Vec3 { X = 10, Y = 0, Z = 3 }, Size = new Vec2 { X = 1, Y = 1.5f }, WarpZone = 426, WarpIndex = 1, InputDirection = 1,
            });
            var area = new MapWarpSet { Name = "MapWarp_A01" };
            area.Warps.Add(new MapWarpRecord { Position = new Vec3 { X = 10, Y = 1, Z = 40 }, Size = new Vec2 { X = 1, Y = 1 }, WarpZone = 425, WarpIndex = 1 });
            area.Warps.Add(new MapWarpRecord { Position = new Vec3 { X = 12, Y = 1, Z = 40 }, Size = new Vec2 { X = 1, Y = 1 }, WarpZone = -1, WarpIndex = 0 });
            sets = new List<MapWarpSet> { room, area };
            d.AttachWorld(sets, new Dictionary<string, int> { { "T01R0201", 425 } }, null);
            return d;
        }
    }

    public class FieldFacingTests
    {
        [Test]
        public void ViertelFolgenObenRechtsUntenLinks()
        {
            Assert.AreEqual(MoveDir.Up, Facing.FromQuarter(0));
            Assert.AreEqual(MoveDir.Right, Facing.FromQuarter(1));
            Assert.AreEqual(MoveDir.Down, Facing.FromQuarter(2));
            Assert.AreEqual(MoveDir.Left, Facing.FromQuarter(3));
            Assert.AreEqual(MoveDir.Up, Facing.FromQuarter(4));
            Assert.AreEqual(MoveDir.Left, Facing.FromQuarter(-1));
            Assert.AreEqual(MoveDir.Down, Facing.FromDegrees(180));
            Assert.AreEqual(2, MoveDir.Down.ToQuarter());
        }

        [Test]
        public void GegenrichtungUndKamerareGier()
        {
            Assert.AreEqual(MoveDir.Down, MoveDir.Up.Opposite());
            Assert.AreEqual(MoveDir.Left, MoveDir.Right.Opposite());
            Assert.AreEqual(MoveDir.None, MoveDir.None.Opposite());
            Assert.AreEqual(MoveDir.Down, FieldInputMath.ScreenToGrid(MoveDir.Up, 180f));
            Assert.AreEqual(MoveDir.Left, FieldInputMath.ScreenToGrid(MoveDir.Right, 180f));
            Assert.AreEqual(MoveDir.Up, FieldInputMath.ScreenToGrid(MoveDir.Up, 0f));
            Assert.AreEqual(MoveDir.None, FieldInputMath.ScreenToGrid(MoveDir.None, 180f));
        }
    }

    public class FieldWarpTests
    {
        [Test]
        public void WarpRechteckDecktHalboffeneZellen()
        {
            var w = new FieldWarp { CenterX = 5.75f, CenterY = 10f, SizeX = 1.5f, SizeY = 1f };
            Assert.IsTrue(w.Covers(5, 10));
            Assert.IsTrue(w.Covers(6, 10));
            Assert.IsFalse(w.Covers(7, 10));
            Assert.IsFalse(w.Covers(4, 10));
            Assert.IsFalse(w.Covers(6, 11));
            Assert.IsFalse(w.Covers(6, 9));
        }

        [Test]
        public void KleineGroessenZaehlenAlsEineZelle()
        {
            var w = new FieldWarp { CenterX = 80f, CenterY = 843f, SizeX = 0.2f, SizeY = 0f };
            Assert.IsTrue(w.Covers(80, 843));
            Assert.IsFalse(w.Covers(81, 843));
        }

        [Test]
        public void TabelleLoestRaeumeUndFeldgebieteAuf()
        {
            var d = WorldFixtures.MakeWorld(out _);
            // Raum über den Enum-Namen, Feldgebiet über das Zonenraster (Zelle (10, 40) = Block (0, 1) = Zone 422).
            Assert.AreEqual(2, d.Warps.WarpsOf(425).Count);
            Assert.AreEqual(1, d.Warps.WarpsOf(422).Count);
            Assert.AreEqual(1, d.Warps.ResolvedByName);
            Assert.AreEqual(1, d.Warps.ResolvedByPosition);
            Assert.AreEqual(1, d.Warps.WarpsWithoutTarget);
            Assert.AreEqual(3, d.Warps.WarpCount);
        }

        [Test]
        public void RaumNameOhneEnumSuchtNachBundleName()
        {
            var info = new MapInfoTables();
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 7, AssetBundleName = "prefab_map/c01r0101", Locators = new[] { WorldFixtures.Loc(2, 2, 0) } });
            var d = FieldDataSet.Build(info, new List<ZoneGridRecord>(), new List<AttributeBlockRecord>(), new List<AttributeMatrixRecord>(), new List<MapAttributeCodeRecord>());
            var set = new MapWarpSet { Name = "MapWarp_C01R0101" };
            set.Warps.Add(new MapWarpRecord { Position = new Vec3 { X = 3, Z = 3 }, Size = new Vec2 { X = 1, Y = 1 }, WarpZone = 7, WarpIndex = 0 });
            d.AttachWorld(new[] { set }, null, null);
            Assert.AreEqual(1, d.Warps.ResolvedByBundle);
            Assert.AreEqual(1, d.Warps.WarpsOf(7).Count);
        }

        [Test]
        public void MehrdeutigerBundleNameOhneEnumWirdNichtGeraten()
        {
            var info = new MapInfoTables();
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 7, AssetBundleName = "prefab_map/x", Locators = new[] { WorldFixtures.Loc(2, 2, 0) } });
            info.Zones.Add(new ZoneInfoRecord { ZoneId = 8, AssetBundleName = "prefab_map/x", Locators = new[] { WorldFixtures.Loc(2, 2, 0) } });
            var d = FieldDataSet.Build(info, new List<ZoneGridRecord>(), new List<AttributeBlockRecord>(), new List<AttributeMatrixRecord>(), new List<MapAttributeCodeRecord>());
            var set = new MapWarpSet { Name = "MapWarp_X" };
            set.Warps.Add(new MapWarpRecord { Position = new Vec3 { X = 3, Z = 3 }, Size = new Vec2 { X = 1, Y = 1 }, WarpZone = 7 });
            d.AttachWorld(new[] { set }, null, null);
            Assert.AreEqual(0, d.Warps.WarpCount);
            Assert.AreEqual(1, d.Warps.UnresolvedWarps);
        }

        [Test]
        public void AussentuerKommtAusDemRaumausgang()
        {
            var d = WorldFixtures.MakeWorld(out _);
            Assert.AreEqual(1, d.Warps.DoorCount);
            // Locator 0 von 422 = (10, 20), Blick oben: Tür eine Zelle dahinter (10, 19), der Spieler läuft nach unten hinein.
            var door = d.Warps.FindDoor(422, 10, 19, MoveDir.Down);
            Assert.IsNotNull(door);
            Assert.AreEqual(425, door.TargetZone);
            Assert.AreEqual(0, door.TargetLocator);   // Locator (6, 10) liegt im Ausgangsrechteck
            Assert.AreEqual("T01R0201_D01", door.ConnectionName);
            Assert.IsNull(d.Warps.FindDoor(422, 10, 19, MoveDir.Left));
            Assert.IsNull(d.Warps.FindDoor(422, 10, 18, MoveDir.Down));
        }
    }

    public class FieldZoneRouterTests
    {
        static FieldZoneRouter Router(out FieldDataSet d)
        {
            d = WorldFixtures.MakeWorld(out _);
            return d.Router;
        }

        [Test]
        public void SpawnAusLocatorMitBlickrichtung()
        {
            var r = Router(out _);
            Assert.IsTrue(r.TryResolveSpawn(425, 1, out var sp));
            Assert.AreEqual((10, 3), (sp.GridX, sp.GridY));
            Assert.AreEqual(MoveDir.Left, sp.Facing);
            Assert.IsFalse(r.TryResolveSpawn(425, 2, out _), "unbelegter Locator");
            Assert.IsFalse(r.TryResolveSpawn(425, 9, out _), "Index außerhalb");
            Assert.IsFalse(r.TryResolveSpawn(999, 0, out _), "unbekannte Zone");
        }

        [Test]
        public void TreppeImRaumLoestWarpInAnderenRaum()
        {
            var r = Router(out _);
            var t = r.OnArrived(425, 10, 3);
            Assert.IsNotNull(t);
            Assert.AreEqual(TransitionKind.Warp, t.Kind);
            Assert.AreEqual(426, t.TargetZone);
            Assert.AreEqual((8, 4), (t.Spawn.GridX, t.Spawn.GridY));
            Assert.AreEqual(MoveDir.Right, t.Spawn.Facing);
            Assert.IsTrue(t.NeedsMapLoad);
            Assert.IsTrue(t.NeedsFade);
        }

        [Test]
        public void AusgangstuerDesRaumesLandetAmFeldLocator()
        {
            var r = Router(out _);
            foreach (var x in new[] { 5, 6 })
            {
                var t = r.OnArrived(425, x, 10);
                Assert.IsNotNull(t, "x " + x);
                Assert.AreEqual(422, t.TargetZone);
                Assert.AreEqual((10, 20), (t.Spawn.GridX, t.Spawn.GridY));
                Assert.AreEqual(MoveDir.Up, t.Spawn.Facing);
            }
            Assert.IsNull(r.OnArrived(425, 7, 10));
            Assert.IsNull(r.OnArrived(425, 6, 9));
        }

        [Test]
        public void AussentuerNurBeimHineinlaufen()
        {
            var r = Router(out _);
            var t = r.OnBump(422, 10, 20, MoveDir.Down);
            Assert.IsNotNull(t);
            Assert.AreEqual(TransitionKind.Door, t.Kind);
            Assert.AreEqual(425, t.TargetZone);
            Assert.AreEqual((6, 10), (t.Spawn.GridX, t.Spawn.GridY));
            Assert.AreEqual(MoveDir.Down, t.Spawn.Facing);
            Assert.IsNull(r.OnBump(422, 10, 20, MoveDir.Up));
            Assert.IsNull(r.OnBump(422, 10, 20, MoveDir.None));
            Assert.IsNull(r.OnBump(422, 11, 20, MoveDir.Down));
        }

        [Test]
        public void FeldwarpAusDemGebietLoestBeiBetretenAus()
        {
            var r = Router(out _);
            var t = r.OnArrived(422, 10, 40);
            Assert.IsNotNull(t);
            Assert.AreEqual(425, t.TargetZone);
            Assert.AreEqual((10, 3), (t.Spawn.GridX, t.Spawn.GridY));
        }

        [Test]
        public void ZonengrenzeImGleichenGebietLaedtNichtNeu()
        {
            var r = Router(out _);
            Assert.IsNull(r.OnZoneGridChange(422, 10, 5));
            var t = r.OnZoneGridChange(422, 40, 5);   // Block (1, 0) = Zone 354, gleiches Bundle
            Assert.IsNotNull(t);
            Assert.AreEqual(TransitionKind.ZoneEdge, t.Kind);
            Assert.AreEqual(354, t.TargetZone);
            Assert.IsFalse(t.HasSpawn);
            Assert.IsFalse(t.NeedsMapLoad);
            Assert.IsFalse(t.NeedsFade);
        }

        [Test]
        public void ZonengrenzeInAnderesGebietLaedtNeuMitFade()
        {
            var r = Router(out _);
            var t = r.OnZoneGridChange(422, 40, 40);   // Block (1, 1) = Zone 500, anderes Bundle
            Assert.IsNotNull(t);
            Assert.AreEqual(500, t.TargetZone);
            Assert.IsTrue(t.NeedsMapLoad);
            Assert.IsTrue(t.NeedsFade);
        }

        [Test]
        public void InnenraeumeKennenKeineZonengrenze()
        {
            var r = Router(out _);
            Assert.AreEqual(425, r.ZoneAtCell(425, 40, 40));
            Assert.IsNull(r.OnZoneGridChange(425, 40, 40));
        }

        [Test]
        public void ZellenAusserhalbDesRastersBehaltenDieZone()
        {
            var r = Router(out _);
            Assert.AreEqual(422, r.ZoneAtCell(422, 500, 500));
            Assert.AreEqual(422, r.ZoneAtCell(422, -3, 5));
        }

        [Test]
        public void GleichesBundleErkennung()
        {
            var r = Router(out _);
            Assert.IsTrue(r.SameMap(422, 354));
            Assert.IsFalse(r.SameMap(422, 500));
            Assert.IsFalse(r.SameMap(425, 426));
            Assert.IsTrue(r.SameMap(425, 425));
            Assert.IsFalse(r.SameMap(425, 999));
        }
    }

    public class FieldFadeTests
    {
        [Test]
        public void AusHaltenEin()
        {
            var f = new ScreenFade { OutSeconds = 0.5f, InSeconds = 0.25f };
            Assert.AreEqual(FadePhase.Clear, f.Phase);
            f.Begin();
            Assert.AreEqual(FadePhase.Out, f.Phase);
            f.Tick(0.25f);
            Assert.AreEqual(0.5f, f.Alpha, 1e-4f);
            Assert.IsFalse(f.IsBlack);
            f.Tick(0.25f);
            Assert.IsTrue(f.IsBlack);
            Assert.AreEqual(1f, f.Alpha);
            f.Tick(10f);
            Assert.IsTrue(f.IsBlack, "bleibt schwarz bis zur Freigabe");
            f.Release();
            Assert.AreEqual(FadePhase.In, f.Phase);
            f.Tick(0.125f);
            Assert.AreEqual(0.5f, f.Alpha, 1e-4f);
            f.Tick(0.2f);
            Assert.AreEqual(FadePhase.Clear, f.Phase);
            Assert.AreEqual(0f, f.Alpha);
            Assert.IsFalse(f.Active);
        }

        [Test]
        public void NullDauernSpringenDirekt()
        {
            var f = new ScreenFade { OutSeconds = 0f, InSeconds = 0f };
            f.Begin();
            Assert.IsTrue(f.IsBlack);
            f.Release();
            Assert.AreEqual(FadePhase.Clear, f.Phase);
        }

        [Test]
        public void ReleaseOhneSchwarzIstWirkungslos()
        {
            var f = new ScreenFade();
            f.Release();
            Assert.AreEqual(FadePhase.Clear, f.Phase);
            f.Begin();
            f.Release();
            Assert.AreEqual(FadePhase.Out, f.Phase);
        }
    }

    public class FieldStreamingTests
    {
        static List<BlockId> Grid(int cols, int rows)
        {
            var l = new List<BlockId>();
            for (var r = 0; r < rows; r++) for (var c = 0; c < cols; c++) l.Add(new BlockId(c, r));
            return l;
        }

        [Test]
        public void AbstandZumBlockrechteck()
        {
            var b = new BlockId(2, 3);   // Zellen x 64..95, y 96..127
            Assert.AreEqual(0, BlockStreamingMath.DistanceToBlock(64, 96, b));
            Assert.AreEqual(0, BlockStreamingMath.DistanceToBlock(95, 127, b));
            Assert.AreEqual(1, BlockStreamingMath.DistanceToBlock(63, 100, b));
            Assert.AreEqual(5, BlockStreamingMath.DistanceToBlock(100, 100, b));
            Assert.AreEqual(10, BlockStreamingMath.DistanceToBlock(70, 86, b));
            Assert.AreEqual(10, BlockStreamingMath.DistanceToBlock(54, 86, b), "Chebyshev: Maximum beider Achsen");
        }

        [Test]
        public void NurNaheBloeckeWerdenGeladen()
        {
            var loaded = new HashSet<BlockId>();
            var sel = BlockStreamingMath.Select(16, 16, Grid(4, 4), loaded, 10, 18);
            // Zelle (16, 16) liegt in Block (0, 0); Nachbarn beginnen bei 32 (Abstand 16) und sind außerhalb von 10.
            CollectionAssert.AreEqual(new[] { new BlockId(0, 0) }, sel.Load);
            Assert.AreEqual(0, sel.Unload.Count);
        }

        [Test]
        public void BlockrandLaedtDenNachbarn()
        {
            var loaded = new HashSet<BlockId> { new BlockId(0, 0) };
            var sel = BlockStreamingMath.Select(28, 16, Grid(4, 4), loaded, 10, 18);   // 4 Zellen vor Spalte 1
            CollectionAssert.Contains(sel.Load, new BlockId(1, 0));
            CollectionAssert.DoesNotContain(sel.Load, new BlockId(2, 0));
            Assert.AreEqual(0, sel.Unload.Count);
        }

        [Test]
        public void HystereseVerhindertFlackern()
        {
            var loaded = new HashSet<BlockId> { new BlockId(0, 0), new BlockId(1, 0) };
            // Spieler in Block 1 nahe der Grenze: Block 0 hat Abstand 5 (zwischen Laden 10 und Entladen 18): bleibt.
            var sel = BlockStreamingMath.Select(37, 16, Grid(4, 4), loaded, 10, 18);
            Assert.AreEqual(0, sel.Unload.Count);
            // Weit weg: Abstand 25 > 18 → entladen.
            var far = BlockStreamingMath.Select(32 + 31 + 25, 16, Grid(4, 4), loaded, 10, 18);
            CollectionAssert.Contains(far.Unload, new BlockId(0, 0));
            CollectionAssert.Contains(far.Unload, new BlockId(1, 0));
        }

        [Test]
        public void EntladeabstandNieKleinerAlsLadeabstand()
        {
            var loaded = new HashSet<BlockId> { new BlockId(1, 0) };
            var sel = BlockStreamingMath.Select(0, 0, Grid(4, 4), loaded, 40, 5);
            Assert.AreEqual(0, sel.Unload.Count, "Block liegt innerhalb des (angehobenen) Entladeabstands 40");
        }

        [Test]
        public void VerschwundeneBloeckeWerdenEntladen()
        {
            var loaded = new HashSet<BlockId> { new BlockId(9, 9) };
            var sel = BlockStreamingMath.Select(0, 0, Grid(2, 2), loaded, 10, 18);
            CollectionAssert.AreEqual(new[] { new BlockId(9, 9) }, sel.Unload);
        }

        [Test]
        public void GeladenerBlockWirdNichtDoppeltAngefordert()
        {
            var loaded = new HashSet<BlockId> { new BlockId(0, 0) };
            var sel = BlockStreamingMath.Select(5, 5, Grid(2, 2), loaded, 40, 50);
            CollectionAssert.DoesNotContain(sel.Load, new BlockId(0, 0));
            Assert.AreEqual(3, sel.Load.Count);
        }

        [Test]
        public void SichtweiteDerFeldkameraIstKleinerAlsEinBlock()
        {
            // Zone 422: Neigung 45°, Sichtfeld 17,5°, Abstand 30; Route 201: 35°, 15°, 30.
            var a = BlockStreamingMath.VisibleRadius(45f, 17.5f, 30f, 16f / 9f);
            var b = BlockStreamingMath.VisibleRadius(35f, 15f, 30f, 16f / 9f);
            Assert.That(a, Is.InRange(6f, 16f));
            Assert.That(b, Is.InRange(6f, 16f));
            var dist = BlockStreamingMath.LoadDistanceFor(a);
            Assert.That(dist, Is.InRange(14, 28));
        }

        [Test]
        public void SteilereKameraSiehtWenigerWeit()
        {
            var steep = BlockStreamingMath.VisibleRadius(70f, 17.5f, 30f, 1f);
            var flat = BlockStreamingMath.VisibleRadius(35f, 17.5f, 30f, 1f);
            Assert.Less(steep, flat);
        }

        [Test]
        public void SpeicherbudgetStufenUndLadeabstand()
        {
            var b = new MemoryBudget(1000L * 1024 * 1024);
            Assert.AreEqual(BudgetState.Ok, b.Evaluate(500L * 1024 * 1024));
            Assert.AreEqual(BudgetState.Warning, b.Evaluate(800L * 1024 * 1024));
            Assert.AreEqual(BudgetState.Critical, b.Evaluate(950L * 1024 * 1024));
            Assert.AreEqual(24, b.AdjustLoadDistance(24, BudgetState.Ok));
            Assert.AreEqual(18, b.AdjustLoadDistance(24, BudgetState.Warning));
            Assert.AreEqual(12, b.AdjustLoadDistance(24, BudgetState.Critical));
            Assert.AreEqual(12, b.AdjustLoadDistance(14, BudgetState.Warning), "Untergrenze 12");
            Assert.AreEqual(8, b.AdjustLoadDistance(10, BudgetState.Critical), "Untergrenze 8");
            Assert.Throws<ArgumentOutOfRangeException>(() => new MemoryBudget(0));
        }

        [Test]
        public void StandardbudgetIstZweieinhalbGigabyte()
        {
            Assert.AreEqual(2500L * 1024 * 1024, new MemoryBudget().TotalBytes);
        }
    }

    public class FieldPlacementTests
    {
        static string Entry(string id, int zone, float x, float y, int graphic, int rotation = 0, string talk = "", string contact = "",
            float sx = 0, float sy = 0, int trainer = 0, int doNotLoad = 4000, float range = 1.25f)
        {
            return "{\"ID\":\"" + id + "\",\"zoneID\":" + zone + ",\"TrainerID\":" + trainer + ",\"ObjectGraphicIndex\":" + graphic + ",\"ColorIndex\":0," +
                   "\"Position\":{\"x\":" + x.ToString(System.Globalization.CultureInfo.InvariantCulture) + ",\"y\":" + y.ToString(System.Globalization.CultureInfo.InvariantCulture) + "}," +
                   "\"HeightLayer\":0,\"HeightIgnore\":0,\"Size\":{\"x\":" + sx.ToString(System.Globalization.CultureInfo.InvariantCulture) + ",\"y\":" + sy.ToString(System.Globalization.CultureInfo.InvariantCulture) + "}," +
                   "\"Rotation\":" + rotation + ",\"MoveLimit\":{\"x\":1.0,\"y\":1.0},\"EventType\":0,\"MoveCode\":2,\"MoveParam0\":0,\"MoveParam1\":0,\"MoveParam2\":0," +
                   "\"TalkLabel\":\"" + talk + "\",\"ContactLabel\":\"" + contact + "\",\"Work\":4000,\"Dowsing\":0,\"LoadFirst\":0,\"DoNotLoad\":" + doNotLoad + "," +
                   "\"TalkToRange\":" + range.ToString(System.Globalization.CultureInfo.InvariantCulture) + ",\"TalkToSize\":{\"x\":0.0,\"y\":0.0},\"TalkBit\":15}";
        }

        static string Json(params string[] entries) =>
            "{\"class\":\"PlaceData\",\"instances\":[{\"name\":\"PlaceData_T01R0201\",\"data\":{\"Data\":[" + string.Join(",", entries) + "]}}]}";

        static PlacementDirectory Dir(params string[] entries) => new PlacementDirectory(PlacementParser.Parse(Json(entries)));

        sealed class Flags : IFieldFlags
        {
            public readonly HashSet<int> Set = new HashSet<int>();
            public bool IsSet(int i) => Set.Contains(i);
        }

        sealed class Recorder : IFieldInteractionHandler
        {
            public readonly List<InteractionRequest> Requests = new List<InteractionRequest>();
            public bool Busy { get; set; }
            public bool Accept = true;
            public bool Handle(InteractionRequest r) { Requests.Add(r); return Accept; }
        }

        [Test]
        public void ParserLiestFelderUndSetName()
        {
            var list = PlacementParser.Parse(Json(Entry("MAMA", 425, 7, 8, 12, 180, talk: "ev_mama", trainer: 0)));
            Assert.AreEqual(1, list.Count);
            var p = list[0];
            Assert.AreEqual("T01R0201", p.SetName);
            Assert.AreEqual("MAMA", p.Id);
            Assert.AreEqual(425, p.ZoneId);
            Assert.AreEqual((7, 8), (p.GridX, p.GridY));
            Assert.AreEqual(MoveDir.Down, p.Facing);
            Assert.IsTrue(p.IsVisibleNpc);
            Assert.IsTrue(p.HasTalk);
            Assert.IsFalse(p.HasContact);
            Assert.AreEqual(1.25f, p.TalkRange);
            Assert.AreEqual(15, p.TalkBit);
        }

        [Test]
        public void ParserLehntFalscheKlasseUndFehlendeFelderAb()
        {
            Assert.Throws<FormatException>(() => PlacementParser.Parse("{\"class\":\"X\",\"instances\":[]}"));
            Assert.Throws<FormatException>(() => PlacementParser.Parse("{\"class\":\"PlaceData\",\"instances\":[{\"name\":\"PlaceData_A\",\"data\":{\"Data\":[{\"ID\":\"a\"}]}}]}"));
            Assert.Throws<FormatException>(() => PlacementParser.Parse("[]"));
        }

        [Test]
        public void NegativeRaumPositionenNehmenDenBetrag()
        {
            var p = PlacementParser.Parse(Json(Entry("TV", 425, -7, 5, -1, sx: 2, sy: 1)))[0];
            Assert.AreEqual((7, 5), (p.GridX, p.GridY));
            Assert.IsFalse(p.IsVisibleNpc);
            // Fläche 2 x 1 um (7, 5): Zellen 6 und 7.
            Assert.IsTrue(p.Covers(6, 5));
            Assert.IsTrue(p.Covers(7, 5));
            Assert.IsFalse(p.Covers(8, 5));
            Assert.IsFalse(p.Covers(7, 6));
        }

        [Test]
        public void FindAtBevorzugtSichtbareNpcs()
        {
            var d = Dir(Entry("AREA", 425, 7, 8, -1, sx: 3, sy: 3, talk: "a"), Entry("NPC", 425, 7, 8, 5, talk: "b"));
            Assert.AreEqual("NPC", d.FindAt(425, 7, 8).Id);
            Assert.AreEqual("AREA", d.FindAt(425, 8, 9).Id);
            Assert.IsNull(d.FindAt(425, 20, 20));
            Assert.IsNull(d.FindAt(999, 7, 8));
        }

        [Test]
        public void NpcSperrtNurSeineZelle()
        {
            var d = Dir(Entry("NPC", 425, 7, 8, 5), Entry("SIGN", 425, 3, 3, -1));
            Assert.IsTrue(d.IsNpcAt(425, 7, 8));
            Assert.IsFalse(d.IsNpcAt(425, 7, 9));
            Assert.IsFalse(d.IsNpcAt(425, 3, 3), "unsichtbare Objekte sperren nicht über IsNpcAt");
        }

        [Test]
        public void NichtLadenFlagVersteckt()
        {
            var d = Dir(Entry("NPC", 425, 7, 8, 5, talk: "t", doNotLoad: 450));
            var flags = new Flags();
            Assert.IsNotNull(d.FindAt(425, 7, 8, flags));
            flags.Set.Add(450);
            Assert.IsNull(d.FindAt(425, 7, 8, flags));
            Assert.IsFalse(d.IsNpcAt(425, 7, 8, flags));
        }

        [Test]
        public void WorkFlagMachtEreignisfigurenErstMitFlagSichtbar()
        {
            var d = Dir(Entry("EVENT", 425, 6, 10, 13).Replace("\"Work\":4000", "\"Work\":438"), Entry("ALWAYS", 425, 3, 3, 13));
            var flags = new Flags();
            Assert.IsNull(d.FindAt(425, 6, 10), "ohne Flagquelle unsichtbar");
            Assert.IsNull(d.FindAt(425, 6, 10, flags));
            Assert.IsFalse(d.IsNpcAt(425, 6, 10, flags));
            flags.Set.Add(438);
            Assert.AreEqual("EVENT", d.FindAt(425, 6, 10, flags).Id);
            Assert.IsTrue(d.IsNpcAt(425, 6, 10, flags));
            Assert.IsTrue(d.IsNpcAt(425, 3, 3), "Work 4000 = immer");
        }

        [Test]
        public void AnsprechenBrauchtBlickrichtungUndLabel()
        {
            var d = Dir(Entry("NPC", 425, 7, 8, 5, talk: "ev_npc"), Entry("MUTE", 425, 3, 3, 6));
            var h = new Recorder();
            var i = new FieldInteraction(d) { Handler = h };
            // Spieler (7, 7) schaut nach oben (+gy) auf (7, 8).
            Assert.IsTrue(i.TryTalk(425, 7, 7, MoveDir.Up));
            Assert.AreEqual(1, h.Requests.Count);
            Assert.AreEqual(InteractionKind.Talk, h.Requests[0].Kind);
            Assert.AreEqual("ev_npc", h.Requests[0].Label);
            Assert.AreEqual(MoveDir.Up, h.Requests[0].PlayerFacing);
            Assert.IsFalse(i.TryTalk(425, 7, 7, MoveDir.Down), "falsche Blickrichtung");
            Assert.IsFalse(i.TryTalk(425, 7, 7, MoveDir.None));
            Assert.IsFalse(i.TryTalk(425, 3, 2, MoveDir.Up), "NPC ohne Label");
            Assert.AreEqual(1, h.Requests.Count);
        }

        [Test]
        public void BlickNachRechtsZeigtAufGxMinusEins()
        {
            var d = Dir(Entry("NPC", 425, 6, 8, 5, talk: "ev"));
            var i = new FieldInteraction(d) { Handler = new Recorder() };
            Assert.IsTrue(i.TryTalk(425, 7, 8, MoveDir.Right));
            Assert.IsFalse(i.TryTalk(425, 5, 8, MoveDir.Right));
            Assert.IsTrue(i.TryTalk(425, 5, 8, MoveDir.Left));
        }

        [Test]
        public void TresenObjektMitGroesseremRadiusWirdUeberZweiZellenAngesprochen()
        {
            var d = Dir(Entry("COUNTER", 425, 7, 8, -1, talk: "ev_counter", range: 2.25f));
            var h = new Recorder();
            var i = new FieldInteraction(d) { Handler = h };
            Assert.IsTrue(i.TryTalk(425, 7, 6, MoveDir.Up), "zwei Zellen entfernt, Reichweite >= 2");
            var d2 = Dir(Entry("SIGN", 425, 7, 8, -1, talk: "ev_sign"));
            var i2 = new FieldInteraction(d2) { Handler = h };
            Assert.IsFalse(i2.TryTalk(425, 7, 6, MoveDir.Up), "Standardreichweite 1,25 deckt nur die Nachbarzelle");
        }

        [Test]
        public void BeschaeftigterHandlerBlockiertNeueAnfragen()
        {
            var d = Dir(Entry("NPC", 425, 7, 8, 5, talk: "ev"));
            var h = new Recorder { Busy = true };
            var i = new FieldInteraction(d) { Handler = h };
            Assert.IsTrue(i.Busy);
            Assert.IsFalse(i.TryTalk(425, 7, 7, MoveDir.Up));
            h.Busy = false;
            Assert.IsTrue(i.TryTalk(425, 7, 7, MoveDir.Up));
        }

        [Test]
        public void AbgelehnteAnfrageMeldetFalse()
        {
            var d = Dir(Entry("NPC", 425, 7, 8, 5, talk: "ev"));
            var h = new Recorder { Accept = false };
            var i = new FieldInteraction(d) { Handler = h };
            Assert.IsFalse(i.TryTalk(425, 7, 7, MoveDir.Up));
            Assert.AreEqual(1, h.Requests.Count);
        }

        [Test]
        public void OhneHandlerPassiertNichts()
        {
            var i = new FieldInteraction(Dir(Entry("NPC", 425, 7, 8, 5, talk: "ev")));
            Assert.IsFalse(i.TryTalk(425, 7, 7, MoveDir.Up));
            Assert.IsFalse(i.TryContact(425, 7, 8, MoveDir.Up));
        }

        [Test]
        public void BeruehrungLoestAufDerFlaecheMitContactLabelAus()
        {
            var d = Dir(Entry("TRIGGER", 425, 7, 8, -1, contact: "ev_contact", sx: 3, sy: 1), Entry("NPC", 425, 2, 2, 5, talk: "t"));
            var h = new Recorder();
            var i = new FieldInteraction(d) { Handler = h };
            Assert.IsTrue(i.TryContact(425, 8, 8, MoveDir.Right));
            Assert.AreEqual(InteractionKind.Contact, h.Requests[0].Kind);
            Assert.AreEqual("ev_contact", h.Requests[0].Label);
            Assert.IsFalse(i.TryContact(425, 10, 8, MoveDir.Right), "außerhalb der Fläche");
            Assert.IsFalse(i.TryContact(425, 2, 2, MoveDir.Up), "ohne ContactLabel");
        }

        [Test]
        public void ProtokollHandlerNimmtAlleAn()
        {
            var d = Dir(Entry("NPC", 425, 7, 8, 5, talk: "ev"));
            var lines = new List<string>();
            var h = new LoggingInteractionHandler { Log = lines.Add };
            var i = new FieldInteraction(d) { Handler = h };
            Assert.IsTrue(i.TryTalk(425, 7, 7, MoveDir.Up));
            Assert.AreEqual(1, h.Handled);
            Assert.AreEqual(1, lines.Count);
            StringAssert.Contains("ev", lines[0]);
            Assert.IsFalse(h.Busy);
        }

        [Test]
        public void ZoneNamenParser()
        {
            var m = ZoneNames.Parse("{\"ZoneID\":{\"T01\":422,\"T01R0201\":425}}");
            Assert.AreEqual(425, m["T01R0201"]);
            Assert.Throws<FormatException>(() => ZoneNames.Parse("{}"));
        }
    }

    public class FieldMoverWorldTests
    {
        static GridMover Mover(int[] block, int x, int y, MoveDir f)
        {
            var c = FieldFixtures.Collision(block);
            c.OutsideBlocked = false;
            return new GridMover(c, new FlatGround(), x, y, f);
        }

        static MoveEvents Run(GridMover m, MoveDir held, int ticks)
        {
            var all = MoveEvents.None;
            for (var i = 0; i < ticks; i++) all |= m.Tick(1f / 30f, held, false);
            return all;
        }

        [Test]
        public void AbsprungkanteWirdInLaufrichtungUebersprungen()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 9, 59 * 1000 + 128);   // Kante unten (Down = gy - 1)
            var m = Mover(b, 5, 10, MoveDir.Down);
            var ev = m.Tick(1f / 30f, MoveDir.Down, false);
            Assert.IsTrue((ev & MoveEvents.Jumped) != 0);
            Assert.IsTrue(m.IsJumping);
            Assert.AreEqual((5, 8), (m.TargetX, m.TargetY));
            Run(m, MoveDir.None, 60);
            Assert.AreEqual((5, 8), (m.GridX, m.GridY));
            Assert.IsFalse(m.IsJumping);
            Assert.AreEqual(1, m.JumpsTaken);
        }

        [Test]
        public void SprungDauertZweiZellenBeiGehgeschwindigkeit()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 9, 59 * 1000 + 128);
            var m = Mover(b, 5, 10, MoveDir.Down);
            m.Tick(1f / 30f, MoveDir.Down, true);   // Laufen ändert die Sprungdauer nicht
            var ticks = 1;
            while (m.IsMoving && ticks < 100) { m.Tick(1f / 30f, MoveDir.None, true); ticks++; }
            var seconds = ticks / 30f;
            Assert.That(seconds, Is.EqualTo(2f / GridMover.DefaultWalkSpeed).Within(0.06f));
        }

        [Test]
        public void SprungbogenHatHoeheInDerMitte()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 9, 59 * 1000 + 128);
            var m = Mover(b, 5, 10, MoveDir.Down);
            m.JumpArcHeight = 1f;
            m.Tick(0.27f, MoveDir.Down, false);   // 0,27 s von 0,54 s
            Assert.That(m.JumpOffset, Is.EqualTo(1f).Within(0.05f));
            Run(m, MoveDir.None, 60);
            Assert.AreEqual(0f, m.JumpOffset);
        }

        [Test]
        public void KanteVonDerFalschenSeiteIstWand()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 9, 59 * 1000 + 128);
            var m = Mover(b, 5, 8, MoveDir.Up);
            var ev = m.Tick(1f / 30f, MoveDir.Up, false);
            Assert.IsTrue((ev & MoveEvents.Bumped) != 0);
            Assert.IsFalse(m.IsJumping);
            Assert.AreEqual(BlockReason.Stop, m.LastBlock);
        }

        [Test]
        public void SprungMitGesperrterLandezoneSpringtNicht()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 9, 59 * 1000 + 128);
            FieldFixtures.Set(b, 5, 8, 128);
            var m = Mover(b, 5, 10, MoveDir.Down);
            var ev = m.Tick(1f / 30f, MoveDir.Down, false);
            Assert.IsTrue((ev & MoveEvents.Bumped) != 0);
            Assert.IsFalse(m.IsJumping);
            Assert.AreEqual((5, 10), (m.GridX, m.GridY));
        }

        [Test]
        public void SprungInsWasserIstGesperrt()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 9, 59 * 1000 + 128);
            FieldFixtures.Set(b, 5, 8, 16000);   // Wasser
            var m = Mover(b, 5, 10, MoveDir.Down);
            var ev = m.Tick(1f / 30f, MoveDir.Down, false);
            Assert.IsTrue((ev & MoveEvents.Bumped) != 0);
            Assert.AreEqual(BlockReason.Water, m.LastBlock);
        }

        [Test]
        public void AlleVierKantenRichtungen()
        {
            var cases = new[] { (56, MoveDir.Right), (57, MoveDir.Left), (58, MoveDir.Up), (59, MoveDir.Down) };
            foreach (var (code, dir) in cases)
            {
                Assert.AreEqual(dir, AttributeCodes.JumpDirection(code), "Code " + code);
                var b = FieldFixtures.Block();
                var d = dir.GridDelta();
                FieldFixtures.Set(b, 10 + d.Dx, 10 + d.Dy, code * 1000 + 128);
                var m = Mover(b, 10, 10, dir);
                m.Tick(1f / 30f, dir, false);
                Assert.IsTrue(m.IsJumping, "Code " + code);
                Assert.AreEqual((10 + 2 * d.Dx, 10 + 2 * d.Dy), (m.TargetX, m.TargetY), "Code " + code);
            }
            Assert.AreEqual(MoveDir.None, AttributeCodes.JumpDirection(215));
            Assert.AreEqual(MoveDir.None, AttributeCodes.JumpDirection(0));
        }

        [Test]
        public void NpcSperrtZelle()
        {
            var b = FieldFixtures.Block();
            var m = Mover(b, 5, 10, MoveDir.Up);
            m.IsOccupied = (x, y) => x == 5 && y == 11;
            var ev = m.Tick(1f / 30f, MoveDir.Up, false);
            Assert.IsTrue((ev & MoveEvents.Bumped) != 0);
            Assert.AreEqual(BlockReason.Npc, m.LastBlock);
            Assert.AreEqual((5, 10), (m.GridX, m.GridY));
            m.IsOccupied = null;
            Assert.IsTrue((m.Tick(1f / 30f, MoveDir.Up, false) & MoveEvents.Started) != 0);
        }

        [Test]
        public void NpcHinterDerKanteVerhindertDenSprung()
        {
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 9, 59 * 1000 + 128);
            var m = Mover(b, 5, 10, MoveDir.Down);
            m.IsOccupied = (x, y) => x == 5 && y == 8;
            var ev = m.Tick(1f / 30f, MoveDir.Down, false);
            Assert.IsTrue((ev & MoveEvents.Bumped) != 0);
            Assert.AreEqual(BlockReason.Npc, m.LastBlock);
            Assert.IsFalse(m.IsJumping);
        }

        [Test]
        public void WasserUndBrueckenBleibenUnveraendert()
        {
            // Wasser: Läufer gesperrt, Schwimmer erlaubt.
            var b = FieldFixtures.Block();
            FieldFixtures.Set(b, 5, 11, 16000);
            var walker = Mover(b, 5, 10, MoveDir.Up);
            Assert.IsTrue((walker.Tick(1f / 30f, MoveDir.Up, false) & MoveEvents.Bumped) != 0);
            Assert.AreEqual(BlockReason.Water, walker.LastBlock);
            var swimmer = Mover(b, 5, 11, MoveDir.Down);
            swimmer.Swim = true;
            Assert.IsTrue((swimmer.Tick(1f / 30f, MoveDir.Down, false) & MoveEvents.Bumped) != 0);
            Assert.AreEqual(BlockReason.Land, swimmer.LastBlock);
        }
    }
}
