using System;
using Xnu.Data;

namespace Xnu.Field
{
    public enum TransitionKind
    {
        Warp,       // Warp-Rechteck (Treppe, Höhlen-/Raumeingang aus dem Gebiet, Ausgangstür eines Raumes)
        Door,       // Außentür (gesperrte Türzelle, Spieler läuft hinein)
        ZoneEdge,   // Zonengrenze im Zonenraster (Nachbarblock gehört zu anderer Zone), ohne Spawn
    }

    // Beschreibt einen Zonenwechsel, ohne ihn auszuführen. Der Ablauf (Fade, Laden, Platzieren) liegt in FieldController.
    public sealed class ZoneTransition
    {
        public TransitionKind Kind;
        public int FromZone;
        public int TargetZone;
        public bool HasSpawn;
        public SpawnPoint Spawn;
        public bool NeedsMapLoad;        // anderes Kartenbundle: Bundle laden, alte Karte entladen
        public bool NeedsFade;
        public FieldWarp Warp;           // bei Kind Warp
        public DoorLink Door;            // bei Kind Door
        public override string ToString() => Kind + " " + FromZone + " -> " + TargetZone +
            (HasSpawn ? " bei (" + Spawn.GridX + ", " + Spawn.GridY + ") " + Spawn.Facing : " (Position bleibt)") +
            (NeedsMapLoad ? ", Karte laden" : "") + (NeedsFade ? ", Fade" : "");
    }

    // Entscheidet aus Spielerbewegungen, ob ein Zonenwechsel auslöst, und löst Spawnpunkte auf (Locator → Zelle und Blick).
    public sealed class FieldZoneRouter
    {
        readonly WarpTable _warps;
        readonly IZoneDirectory _zones;

        public FieldZoneRouter(WarpTable warps, IZoneDirectory zones)
        {
            _warps = warps ?? throw new ArgumentNullException(nameof(warps));
            _zones = zones ?? throw new ArgumentNullException(nameof(zones));
        }

        public WarpTable Warps => _warps;

        // Locator der Zielzone: Zelle (x, y), Blick aus z (Viertel). Unbelegte Locators (0, 0) gelten als ungültig.
        public bool TryResolveSpawn(int zone, int locator, out SpawnPoint spawn)
        {
            spawn = default;
            if (!_zones.TryGetZone(zone, out var z)) return false;
            if (locator < 0 || locator >= z.Locators.Length) return false;
            var l = z.Locators[locator];
            if (l.X == 0f && l.Y == 0f) return false;
            spawn = new SpawnPoint(zone, (int)Math.Round(l.X), (int)Math.Round(l.Y), Facing.FromQuarter((int)Math.Round(l.Z)), locator);
            return true;
        }

        // Gleiches Kartenbundle (z. B. zwei Zonen desselben Gebiets): kein Neuladen nötig.
        public bool SameMap(int zoneA, int zoneB)
        {
            if (zoneA == zoneB) return true;
            if (!_zones.TryGetZone(zoneA, out var a) || !_zones.TryGetZone(zoneB, out var b)) return false;
            return !string.IsNullOrEmpty(a.AssetBundleName) && a.AssetBundleName == b.AssetBundleName;
        }

        // Spieler hat die Zelle (gx, gy) betreten (Schritt beendet).
        public ZoneTransition OnArrived(int zone, int gx, int gy)
        {
            var w = _warps.FindWarp(zone, gx, gy);
            if (w != null && TryResolveSpawn(w.TargetZone, w.TargetLocator, out var sp))
                return Make(TransitionKind.Warp, zone, sp, w, null);
            // Nicht gesperrte Türzelle: Betreten genügt.
            var d = _warps.FindDoor(zone, gx, gy, MoveDir.None);
            if (d != null && TryResolveSpawn(d.TargetZone, d.TargetLocator, out var sp2))
                return Make(TransitionKind.Door, zone, sp2, null, d);
            return null;
        }

        // Schritt in die Zelle (gx + dx, gy + dy) wurde abgelehnt: Außentür, wenn dort eine liegt und der Spieler hineinläuft.
        public ZoneTransition OnBump(int zone, int gx, int gy, MoveDir facing)
        {
            if (facing == MoveDir.None) return null;
            var d = facing.GridDelta();
            var door = _warps.FindDoor(zone, gx + d.Dx, gy + d.Dy, facing);
            if (door == null || !TryResolveSpawn(door.TargetZone, door.TargetLocator, out var sp)) return null;
            return Make(TransitionKind.Door, zone, sp, null, door);
        }

        // Feldzone (Zonenraster) unter der Zelle; bei Innenräumen und außerhalb des Rasters bleibt die Zone.
        public int ZoneAtCell(int currentZone, int gx, int gy)
        {
            if (!_zones.TryGetZone(currentZone, out var z) || !z.IsField || string.IsNullOrEmpty(z.ZoneGridName)) return currentZone;
            var id = _zones.ZoneAtCell(z.ZoneGridName, gx, gy);
            return id >= 0 ? id : currentZone;
        }

        // Prüft, ob die Zelle zu einer anderen Zone gehört (Rand-Übergang). Die Position bleibt; nur bei anderem Bundle wird geladen.
        public ZoneTransition OnZoneGridChange(int currentZone, int gx, int gy)
        {
            var now = ZoneAtCell(currentZone, gx, gy);
            if (now == currentZone) return null;
            var t = new ZoneTransition { Kind = TransitionKind.ZoneEdge, FromZone = currentZone, TargetZone = now };
            t.NeedsMapLoad = !SameMap(currentZone, now);
            t.NeedsFade = t.NeedsMapLoad;
            return t;
        }

        ZoneTransition Make(TransitionKind kind, int from, SpawnPoint sp, FieldWarp w, DoorLink d)
        {
            var load = !SameMap(from, sp.Zone);
            return new ZoneTransition
            {
                Kind = kind, FromZone = from, TargetZone = sp.Zone, HasSpawn = true, Spawn = sp,
                NeedsMapLoad = load, NeedsFade = true, Warp = w, Door = d,
            };
        }
    }
}
