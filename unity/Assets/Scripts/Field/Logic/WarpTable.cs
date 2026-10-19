using System;
using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.Field
{
    // Warp-Rechteck einer Karte (MapWarp.SheetData). Position und Größe sind Rasterzellen (Position = Mitte);
    // eine Zelle gehört zum Warp, wenn ihre Mitte im halboffenen Rechteck [Mitte - Größe/2, Mitte + Größe/2) liegt
    // (Größen unter 1 zählen als 1). Beispiel: Position (5,75; 10), Größe (1,5; 1) deckt die Zellen (5, 10) und (6, 10).
    public sealed class FieldWarp
    {
        public string SetName = "";
        public int SourceZone;
        public float CenterX, CenterY;
        public float SizeX = 1f, SizeY = 1f;
        public int TargetZone;
        public int TargetLocator;            // Index in MapInfo.Locators der Zielzone
        public MoveDir InputDirection;       // InputDir (0 oben, 1 rechts, 2 unten, 3 links); Auslöser siehe docs/feld-szene-2.md
        public int GroupId, FlagIndex, ScriptLabel, ExitLabel;
        public string ConnectionName = "";

        public bool Covers(int gx, int gy)
        {
            var hx = Math.Max(SizeX, 1f) * 0.5f;
            var hy = Math.Max(SizeY, 1f) * 0.5f;
            return gx >= CenterX - hx && gx < CenterX + hx && gy >= CenterY - hy && gy < CenterY + hy;
        }
    }

    // Außentür: Zelle im Feld, in die der Spieler läuft (die Zelle ist meist durch Stop 128 gesperrt), und die zugehörige
    // Innenraum-Zone. Abgeleitet aus dem Ausgang des Raumes (Gegenrichtung des Locators), siehe WarpTable.Build.
    public sealed class DoorLink
    {
        public int Zone;
        public int DoorX, DoorY;
        public MoveDir Approach;             // Richtung, in die der Spieler läuft, um die Tür zu öffnen
        public int TargetZone;
        public int TargetLocator;
        public string ConnectionName = "";
    }

    // Zugriff auf Zonenstammdaten (für Tests ersetzbar).
    public interface IZoneDirectory
    {
        bool TryGetZone(int zoneId, out ZoneInfoRecord zone);
        // Zone des Zonenrasters an der Zelle; -1 = keine.
        int ZoneAtCell(string gridName, int gx, int gy);
        // Zonen, deren Kartenbundle (letzter Namensteil, groß) so heißt.
        IReadOnlyList<int> ZonesWithMapName(string upperName);
    }

    // Ort, an dem der Spieler nach einem Zonenwechsel steht.
    public readonly struct SpawnPoint
    {
        public readonly int Zone;
        public readonly int GridX, GridY;
        public readonly MoveDir Facing;
        public readonly int Locator;

        public SpawnPoint(int zone, int gx, int gy, MoveDir facing, int locator)
        {
            Zone = zone; GridX = gx; GridY = gy; Facing = facing; Locator = locator;
        }
    }

    // Alle Warps und Außentüren. Aufbau (Befund aus den Stammdaten):
    // - MapWarp-Instanzen heißen "MapWarp_<ZoneID-Name>" (Raum) oder "MapWarp_A<nn>" (Feldgebiet, Zellen des Gebiets).
    //   Der Name der Raumzone steht im Enum ZoneID des Spiels (zoneNames); fehlt er, wird nach Kartenbundle-Namen gesucht.
    // - WarpIndex = Index des Locators der Zielzone; der Locator trägt Zelle (x, y) und Blickrichtung (z, Viertel).
    public sealed class WarpTable
    {
        readonly Dictionary<int, List<FieldWarp>> _byZone = new Dictionary<int, List<FieldWarp>>();
        readonly Dictionary<int, List<DoorLink>> _doors = new Dictionary<int, List<DoorLink>>();

        public int WarpCount { get; private set; }
        public int DoorCount { get; private set; }
        public int ResolvedByName { get; private set; }
        public int ResolvedByBundle { get; private set; }
        public int ResolvedByPosition { get; private set; }
        public int UnresolvedWarps { get; private set; }   // Warps, deren Zone nicht bestimmt werden konnte
        public int WarpsWithoutTarget { get; private set; }
        public int BadLocators { get; private set; }

        public IReadOnlyList<FieldWarp> WarpsOf(int zone) =>
            _byZone.TryGetValue(zone, out var l) ? l : (IReadOnlyList<FieldWarp>)Array.Empty<FieldWarp>();

        public IReadOnlyList<DoorLink> DoorsOf(int zone) =>
            _doors.TryGetValue(zone, out var l) ? l : (IReadOnlyList<DoorLink>)Array.Empty<DoorLink>();

        public FieldWarp FindWarp(int zone, int gx, int gy)
        {
            if (!_byZone.TryGetValue(zone, out var list)) return null;
            foreach (var w in list) if (w.Covers(gx, gy)) return w;
            return null;
        }

        public DoorLink FindDoor(int zone, int gx, int gy, MoveDir approach)
        {
            if (!_doors.TryGetValue(zone, out var list)) return null;
            foreach (var d in list)
                if (d.DoorX == gx && d.DoorY == gy && (approach == MoveDir.None || d.Approach == approach)) return d;
            return null;
        }

        public static WarpTable Build(IEnumerable<MapWarpSet> sets, IReadOnlyDictionary<string, int> zoneNames, IZoneDirectory zones)
        {
            if (sets == null) throw new ArgumentNullException(nameof(sets));
            if (zones == null) throw new ArgumentNullException(nameof(zones));
            var t = new WarpTable();
            const string prefix = "MapWarp_";
            foreach (var set in sets)
            {
                var name = set.Name != null && set.Name.StartsWith(prefix, StringComparison.Ordinal) ? set.Name.Substring(prefix.Length) : set.Name ?? "";
                var fixedZone = -1;
                if (zoneNames != null && zoneNames.TryGetValue(name, out var zn)) { fixedZone = zn; t.ResolvedByName++; }
                else
                {
                    var candidates = zones.ZonesWithMapName(name.ToUpperInvariant());
                    if (candidates.Count == 1) { fixedZone = candidates[0]; t.ResolvedByBundle++; }
                }

                foreach (var r in set.Warps)
                {
                    if (r.WarpZone < 0) { t.WarpsWithoutTarget++; continue; }
                    var zone = fixedZone;
                    var gx = (int)Math.Floor(r.Position.X + 0.5f);
                    var gy = (int)Math.Floor(r.Position.Z + 0.5f);
                    if (zone < 0)
                    {
                        // Feldgebiet: Zone aus dem Zonenraster an der Warp-Zelle (Hauptwelt, sonst Safari-Raster).
                        foreach (var grid in new[] { "Sinnoh", "Safari" })
                        {
                            var z = zones.ZoneAtCell(grid, gx, gy);
                            if (z >= 0 && zones.TryGetZone(z, out var zi) && zi.IsField) { zone = z; t.ResolvedByPosition++; break; }
                        }
                    }
                    if (zone < 0) { t.UnresolvedWarps++; continue; }

                    var w = new FieldWarp
                    {
                        SetName = name, SourceZone = zone, CenterX = r.Position.X, CenterY = r.Position.Z,
                        SizeX = r.Size.X, SizeY = r.Size.Y, TargetZone = r.WarpZone, TargetLocator = r.WarpIndex,
                        InputDirection = Facing.FromQuarter(r.InputDirection), GroupId = r.GroupId, FlagIndex = r.FlagIndex,
                        ScriptLabel = r.ScriptLabel, ExitLabel = r.ExitLabel, ConnectionName = r.ConnectionName ?? "",
                    };
                    if (!t._byZone.TryGetValue(zone, out var list)) t._byZone[zone] = list = new List<FieldWarp>();
                    list.Add(w);
                    t.WarpCount++;
                }
            }
            t.BuildDoors(zones);
            return t;
        }

        // Außentüren: Jeder Raumausgang in eine Feldzone landet auf einem Locator, der von der Tür wegschaut; die Tür liegt
        // eine Zelle hinter dem Locator, der Spieler läuft in Gegenrichtung hinein. Der Raum-Locator, auf dem der Spieler beim
        // Betreten steht, ist derjenige, dessen Zelle im Warp-Rechteck liegt (Ausgangstür des Raumes).
        void BuildDoors(IZoneDirectory zones)
        {
            foreach (var kv in _byZone)
            {
                if (!zones.TryGetZone(kv.Key, out var room) || room.IsField) continue;
                foreach (var w in kv.Value)
                {
                    if (!zones.TryGetZone(w.TargetZone, out var field) || !field.IsField) continue;
                    if (w.TargetLocator < 0 || w.TargetLocator >= field.Locators.Length) { BadLocators++; continue; }
                    var loc = field.Locators[w.TargetLocator];
                    if (loc.X == 0f && loc.Y == 0f) { BadLocators++; continue; }
                    var face = Facing.FromQuarter((int)Math.Round(loc.Z));
                    var d = face.GridDelta();
                    var lx = (int)Math.Round(loc.X);
                    var ly = (int)Math.Round(loc.Y);

                    var entry = -1;
                    for (var i = 0; i < room.Locators.Length; i++)
                    {
                        var l = room.Locators[i];
                        if (l.X == 0f && l.Y == 0f) continue;
                        if (w.Covers((int)Math.Round(l.X), (int)Math.Round(l.Y))) { entry = i; break; }
                    }
                    if (entry < 0) { BadLocators++; continue; }

                    var link = new DoorLink
                    {
                        Zone = w.TargetZone, DoorX = lx - d.Dx, DoorY = ly - d.Dy, Approach = face.Opposite(),
                        TargetZone = kv.Key, TargetLocator = entry, ConnectionName = w.ConnectionName,
                    };
                    if (!_doors.TryGetValue(link.Zone, out var list)) _doors[link.Zone] = list = new List<DoorLink>();
                    list.Add(link);
                    DoorCount++;
                }
            }
        }
    }
}
