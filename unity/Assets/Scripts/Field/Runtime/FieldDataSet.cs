using System;
using System.Collections.Generic;
using System.IO;
using Xnu.Core;
using Xnu.Data;

namespace Xnu.Field
{
    // Stammdaten für das Feld: Zonen, Kameras, Zonenraster, Attributmatrizen/-blöcke, Attributcodes.
    // Quelle sind die JSON-Dateien des Stammdaten-Exporters (work/masterdata), siehe docs/masterdata.md.
    public sealed class FieldDataSet
    {
        public const string MasterDataEnvVar = "XNU_MASTERDATA";

        public MapInfoTables MapInfo { get; private set; }
        public List<ZoneGridRecord> ZoneGrids { get; private set; }
        public AttributeCodeTable Codes { get; private set; }

        readonly Dictionary<int, ZoneInfoRecord> _zones = new Dictionary<int, ZoneInfoRecord>();
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

        public static FieldDataSet Load(string masterDataDirectory)
        {
            var reader = new MasterData2Reader(masterDataDirectory);
            return Build(reader.LoadMapInfo(), reader.LoadZoneGrids(), reader.LoadAttributeBlocks(),
                reader.LoadAttributeMatrices(), reader.LoadMapAttributeCodes());
        }

        public static FieldDataSet Build(MapInfoTables mapInfo, List<ZoneGridRecord> grids, List<AttributeBlockRecord> blocks,
            List<AttributeMatrixRecord> matrices, List<MapAttributeCodeRecord> codes)
        {
            var d = new FieldDataSet { MapInfo = mapInfo, ZoneGrids = grids, Codes = new AttributeCodeTable(codes) };
            foreach (var z in mapInfo.Zones) d._zones[z.ZoneId] = z;
            foreach (var b in blocks) d._blocks[b.Name] = b;
            foreach (var m in matrices) d._matrices[m.Name] = m;
            return d;
        }

        public bool TryGetZone(int zoneId, out ZoneInfoRecord zone) => _zones.TryGetValue(zoneId, out zone);

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
