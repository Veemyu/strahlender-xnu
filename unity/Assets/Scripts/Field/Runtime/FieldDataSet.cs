using System;
using System.Collections.Generic;
using System.IO;
using Xnu.Core;
using Xnu.Data;

namespace Xnu.Field
{
    // Stammdaten für das Feld: Zonen, Kameras, Zonenraster, Attributmatrizen/-blöcke, Attributcodes.
    // Quelle sind die JSON-Dateien des Stammdaten-Exporters (work/masterdata), siehe docs/masterdata.md.
    public sealed class FieldDataSet : IZoneDirectory
    {
        public const string MasterDataEnvVar = "XNU_MASTERDATA";

        public MapInfoTables MapInfo { get; private set; }
        public List<ZoneGridRecord> ZoneGrids { get; private set; }
        public AttributeCodeTable Codes { get; private set; }
        public WarpTable Warps { get; private set; }
        public FieldZoneRouter Router { get; private set; }
        public PlacementDirectory Placements { get; private set; }

        readonly Dictionary<int, ZoneInfoRecord> _zones = new Dictionary<int, ZoneInfoRecord>();
        readonly Dictionary<string, List<int>> _zonesByMapName = new Dictionary<string, List<int>>(StringComparer.Ordinal);
        readonly Dictionary<string, AttributeBlockRecord> _blocks = new Dictionary<string, AttributeBlockRecord>(StringComparer.Ordinal);
        readonly Dictionary<string, AttributeMatrixRecord> _matrices = new Dictionary<string, AttributeMatrixRecord>(StringComparer.Ordinal);

        public int BlockCount => _blocks.Count;
        public int MatrixCount => _matrices.Count;

        // Standardordner der Stammdaten-JSON: XNU_MASTERDATA, sonst <GameData-Root>/masterdata.
        public static string DefaultDirectory
        {
            get
            {
                var env = Environment.GetEnvironmentVariable(MasterDataEnvVar);
                return !string.IsNullOrEmpty(env) ? env : Path.Combine(GameDataPaths.Root, "masterdata");
            }
        }

        // Lädt Zonen und Attribute; Warps, Platzierungen und Zonennamen, soweit die Dateien vorhanden sind
        // (fehlt PlaceData oder MapWarp, bleiben Warps/Platzierungen leer, das Feld läuft ohne Zonenwechsel).
        public static FieldDataSet Load(string masterDataDirectory)
        {
            var reader = new MasterData2Reader(masterDataDirectory);
            var d = Build(reader.LoadMapInfo(), reader.LoadZoneGrids(), reader.LoadAttributeBlocks(),
                reader.LoadAttributeMatrices(), reader.LoadMapAttributeCodes());
            List<MapWarpSet> sets = null;
            List<PlacementRecord> places = null;
            Dictionary<string, int> names = null;
            try { sets = reader.LoadMapWarps(); } catch (FileNotFoundException) { }
            var placePath = Path.Combine(masterDataDirectory, PlacementParser.PlaceDataPath);
            if (File.Exists(placePath)) places = PlacementParser.Parse(File.ReadAllText(placePath));
            var namePath = Path.Combine(masterDataDirectory, ZoneNames.RelativePath);
            if (File.Exists(namePath)) names = ZoneNames.Parse(File.ReadAllText(namePath));
            d.AttachWorld(sets, names, places);
            return d;
        }

        public static FieldDataSet Build(MapInfoTables mapInfo, List<ZoneGridRecord> grids, List<AttributeBlockRecord> blocks,
            List<AttributeMatrixRecord> matrices, List<MapAttributeCodeRecord> codes)
        {
            var d = new FieldDataSet { MapInfo = mapInfo, ZoneGrids = grids, Codes = new AttributeCodeTable(codes) };
            foreach (var z in mapInfo.Zones)
            {
                d._zones[z.ZoneId] = z;
                if (!string.IsNullOrEmpty(z.AssetBundleName))
                {
                    var key = z.AssetBundleName.Substring(z.AssetBundleName.LastIndexOf('/') + 1).ToUpperInvariant();
                    if (!d._zonesByMapName.TryGetValue(key, out var l)) d._zonesByMapName[key] = l = new List<int>();
                    l.Add(z.ZoneId);
                }
            }
            foreach (var b in blocks) d._blocks[b.Name] = b;
            foreach (var m in matrices) d._matrices[m.Name] = m;
            d.AttachWorld(null, null, null);
            return d;
        }

        // Verbindet Warps und Platzierungen mit den Zonen (für Tests mit synthetischen Daten direkt aufrufbar).
        public void AttachWorld(IEnumerable<MapWarpSet> warpSets, IReadOnlyDictionary<string, int> zoneNames, IEnumerable<PlacementRecord> placements)
        {
            Warps = WarpTable.Build(warpSets ?? new MapWarpSet[0], zoneNames, this);
            Router = new FieldZoneRouter(Warps, this);
            Placements = new PlacementDirectory(placements ?? new PlacementRecord[0]);
        }

        public bool TryGetZone(int zoneId, out ZoneInfoRecord zone) => _zones.TryGetValue(zoneId, out zone);

        public int ZoneAtCell(string gridName, int gx, int gy)
        {
            var g = FindGrid(gridName);
            if (g == null || gx < 0 || gy < 0) return -1;
            var col = gx >> 5;
            var row = gy >> 5;
            if (col >= g.Width || row >= g.Height) return -1;
            return g.ZoneAt(col, row);
        }

        public IReadOnlyList<int> ZonesWithMapName(string upperName) =>
            _zonesByMapName.TryGetValue(upperName, out var l) ? l : (IReadOnlyList<int>)Array.Empty<int>();

        // Die Kameratabelle (MapInfo.Camera) hat je Zone eine Zeile (Index = Zonen-ID, 658 Zeilen); ariaID ist das
        // zugehörige Gebiet und wiederholt sich.
        public bool TryGetCamera(int zoneId, out ZoneCameraRecord camera)
        {
            camera = null;
            if (zoneId < 0 || zoneId >= MapInfo.Cameras.Count) return false;
            camera = MapInfo.Cameras[zoneId];
            return true;
        }

        public ZoneGridRecord FindGrid(string name)
        {
            if (string.IsNullOrEmpty(name)) return null;
            foreach (var g in ZoneGrids) if (g.Name == name) return g;
            return null;
        }

        // Blöcke (Spalte, Zeile) des Zonenrasters, die zu dieser Zone gehören; ohne Raster (Innenräume) nur (0, 0).
        public List<(int Column, int Row)> ZoneBlocks(ZoneInfoRecord zone)
        {
            var result = new List<(int, int)>();
            var grid = FindGrid(zone.ZoneGridName);
            if (grid == null) { result.Add((0, 0)); return result; }
            for (var i = 0; i < grid.ZoneIds.Length; i++)
                if (grid.ZoneIds[i] == zone.ZoneId) result.Add((i % grid.Width, i / grid.Width));
            return result;
        }

        public AttributeLayer BuildLayer(string matrixName)
        {
            if (string.IsNullOrEmpty(matrixName) || !_matrices.TryGetValue(matrixName, out var m)) return null;
            return new AttributeLayer(m, n => _blocks.TryGetValue(n, out var b) ? b : null);
        }

        public FieldCollision BuildCollision(ZoneInfoRecord zone)
        {
            var main = BuildLayer(zone.AttributeName);
            if (main == null) throw new InvalidDataException("Attributmatrix der Zone " + zone.ZoneId + " fehlt: " + zone.AttributeName);
            return new FieldCollision(main, BuildLayer(zone.AttributeExName), Codes);
        }
    }
}
