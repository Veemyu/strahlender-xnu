using System;
using System.Collections.Generic;
using System.Globalization;
using Xnu.Data;

namespace Xnu.Field
{
    // Eintrag aus PlaceData (NPCs, Schilder, Item-Bälle, Auslöseflächen). Nur Daten; keine Spieltexte.
    // Koordinaten: Position ist Rasterzelle (x = gx, y = gy). Ältere Raumobjekte tragen die Weltposition (x = -gx, negativ);
    // GridX nimmt deshalb den Betrag (Befund: 2.858 von 2.955 sichtbaren NPCs stehen auf begehbaren Zellen).
    public sealed class PlacementRecord
    {
        public string SetName = "";
        public string Id = "";
        public int ZoneId;
        public int TrainerId;
        public int GraphicIndex;        // -1 = unsichtbar (Schild, Fernseher, Auslösefläche)
        public int ColorIndex;
        public float X, Y;              // Rohwerte
        public int HeightLayer;
        public bool HeightIgnore;
        public float SizeX, SizeY;      // Fläche in Zellen (0 = eine Zelle)
        public int RotationDegrees;
        public float MoveLimitX, MoveLimitY;
        public int EventType;
        public int MoveCode;            // Laufmuster (0 steht still); Bedeutung der Codes nicht ermittelt
        public int MoveParam0, MoveParam1, MoveParam2;
        public string TalkLabel = "";   // Skriptlabel beim Ansprechen
        public string ContactLabel = "";// Skriptlabel beim Berühren/Sichtkontakt
        public int WorkFlag = 4000;     // EvWork.FLAG_INDEX (4000 = keins)
        public int DoNotLoadFlag = 4000;
        public bool LoadFirst;
        public float TalkRange = 1.25f;
        public float TalkSizeX, TalkSizeY;
        public int TalkBit = 15;        // Bitmaske, Bedeutung der Bits nicht belegt

        public bool IsVisibleNpc => GraphicIndex >= 0;
        public bool HasTalk => !string.IsNullOrEmpty(TalkLabel);
        public bool HasContact => !string.IsNullOrEmpty(ContactLabel);
        public int GridX => (int)Math.Floor(Math.Abs(X) + 0.5f);
        public int GridY => (int)Math.Floor(Y + 0.5f);
        public MoveDir Facing => Xnu.Field.Facing.FromDegrees(RotationDegrees);

        // Zellen der Fläche: Mitte ± Größe/2 (halboffen), mindestens eine Zelle.
        public bool Covers(int gx, int gy)
        {
            var hx = Math.Max(SizeX, 1f) * 0.5f;
            var hy = Math.Max(SizeY, 1f) * 0.5f;
            var cx = (float)GridX;
            var cy = (float)GridY;
            return gx >= cx - hx && gx < cx + hx && gy >= cy - hy && gy < cy + hy;
        }
    }

    public static class PlacementParser
    {
        public const string PlaceDataPath = "dpr_masterdatas/PlaceData.json";

        // Format: {"class":"PlaceData","instances":[{"name":"PlaceData_<Karte>","data":{"Data":[{...}]}}]}.
        public static List<PlacementRecord> Parse(string json)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object> ?? throw new FormatException("Wurzel ist kein JSON-Objekt");
            if (Str(root, "class") != "PlaceData") throw new FormatException("Klasse ist nicht PlaceData");
            var result = new List<PlacementRecord>();
            foreach (var inst in List(root, "instances"))
            {
                var name = Str(inst, "name");
                const string prefix = "PlaceData_";
                if (name.StartsWith(prefix, StringComparison.Ordinal)) name = name.Substring(prefix.Length);
                var data = inst["data"] as Dictionary<string, object> ?? throw new FormatException("data fehlt");
                foreach (var r in List(data, "Data"))
                {
                    result.Add(new PlacementRecord
                    {
                        SetName = name,
                        Id = Str(r, "ID"),
                        ZoneId = Int(r, "zoneID"),
                        TrainerId = Int(r, "TrainerID"),
                        GraphicIndex = Int(r, "ObjectGraphicIndex"),
                        ColorIndex = Int(r, "ColorIndex"),
                        X = Vec(r, "Position", "x"), Y = Vec(r, "Position", "y"),
                        HeightLayer = Int(r, "HeightLayer"),
                        HeightIgnore = Int(r, "HeightIgnore") != 0,
                        SizeX = Vec(r, "Size", "x"), SizeY = Vec(r, "Size", "y"),
                        RotationDegrees = Int(r, "Rotation"),
                        MoveLimitX = Vec(r, "MoveLimit", "x"), MoveLimitY = Vec(r, "MoveLimit", "y"),
                        EventType = Int(r, "EventType"),
                        MoveCode = Int(r, "MoveCode"),
                        MoveParam0 = Int(r, "MoveParam0"), MoveParam1 = Int(r, "MoveParam1"), MoveParam2 = Int(r, "MoveParam2"),
                        TalkLabel = Str(r, "TalkLabel"), ContactLabel = Str(r, "ContactLabel"),
                        WorkFlag = Int(r, "Work"), DoNotLoadFlag = Int(r, "DoNotLoad"),
                        LoadFirst = Int(r, "LoadFirst") != 0,
                        TalkRange = (float)Dbl(r, "TalkToRange"),
                        TalkSizeX = Vec(r, "TalkToSize", "x"), TalkSizeY = Vec(r, "TalkToSize", "y"),
                        TalkBit = Int(r, "TalkBit"),
                    });
                }
            }
            return result;
        }

        static List<Dictionary<string, object>> List(Dictionary<string, object> d, string key)
        {
            if (!d.TryGetValue(key, out var v) || !(v is List<object> l)) throw new FormatException("Liste '" + key + "' fehlt");
            var res = new List<Dictionary<string, object>>(l.Count);
            foreach (var e in l) res.Add(e as Dictionary<string, object> ?? throw new FormatException("Eintrag in '" + key + "' ist kein Objekt"));
            return res;
        }

        static object Field(Dictionary<string, object> d, string key) =>
            d.TryGetValue(key, out var v) && v != null ? v : throw new FormatException("Feld '" + key + "' fehlt");

        static string Str(Dictionary<string, object> d, string key) => Field(d, key) as string ?? throw new FormatException("'" + key + "' ist kein String");
        static int Int(Dictionary<string, object> d, string key) => Convert.ToInt32(Field(d, key), CultureInfo.InvariantCulture);
        static double Dbl(Dictionary<string, object> d, string key) => Convert.ToDouble(Field(d, key), CultureInfo.InvariantCulture);

        static float Vec(Dictionary<string, object> d, string key, string comp)
        {
            var o = Field(d, key) as Dictionary<string, object> ?? throw new FormatException("'" + key + "' ist kein Objekt");
            return (float)Convert.ToDouble(Field(o, comp), CultureInfo.InvariantCulture);
        }
    }

    // Abfrage der Platzierungen je Zone.
    public sealed class PlacementDirectory
    {
        readonly Dictionary<int, List<PlacementRecord>> _byZone = new Dictionary<int, List<PlacementRecord>>();

        public int Count { get; private set; }

        public PlacementDirectory(IEnumerable<PlacementRecord> records)
        {
            foreach (var r in records)
            {
                if (!_byZone.TryGetValue(r.ZoneId, out var l)) _byZone[r.ZoneId] = l = new List<PlacementRecord>();
                l.Add(r);
                Count++;
            }
        }

        public IReadOnlyList<PlacementRecord> InZone(int zone) =>
            _byZone.TryGetValue(zone, out var l) ? l : (IReadOnlyList<PlacementRecord>)Array.Empty<PlacementRecord>();

        // Platzierungen (sichtbar nach Flags) einer Zone, deren Fläche die Zelle deckt; sichtbare NPCs zuerst.
        public PlacementRecord FindAt(int zone, int gx, int gy, IFieldFlags flags = null)
        {
            PlacementRecord best = null;
            foreach (var p in InZone(zone))
            {
                if (!p.Covers(gx, gy) || !IsActive(p, flags)) continue;
                if (best == null || (p.IsVisibleNpc && !best.IsVisibleNpc)) best = p;
            }
            return best;
        }

        // NPCs sperren ihre Zelle (ohne Laufmuster-Simulation, Position = Grundstellung).
        public bool IsNpcAt(int zone, int gx, int gy, IFieldFlags flags = null)
        {
            foreach (var p in InZone(zone))
                if (p.IsVisibleNpc && p.GridX == gx && p.GridY == gy && IsActive(p, flags)) return true;
            return false;
        }

        // Aktiv: "Work"-Flag gesetzt (oder 4000 = keins) und "nicht laden"-Flag nicht gesetzt. Ohne Flaggenquelle (null) gelten
        // alle Flags als nicht gesetzt: Objekte mit Work-Flag (Ereignisfiguren, z. B. die Rivalen-Mutter auf der Türzelle des
        // Spielerhauses) bleiben dann unsichtbar. Die Deutung von Work als Sichtbarkeitsflag ist aus den Daten erschlossen.
        public static bool IsActive(PlacementRecord p, IFieldFlags flags) =>
            (p.WorkFlag == 4000 || (flags != null && flags.IsSet(p.WorkFlag))) &&
            (p.DoNotLoadFlag == 4000 || flags == null || !flags.IsSet(p.DoNotLoadFlag));
    }

    // Spielflags (EvWork-Flags); der spätere Event-Interpreter liefert sie.
    public interface IFieldFlags
    {
        bool IsSet(int flagIndex);
    }
}
