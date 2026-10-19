using System;
using System.Collections.Generic;
using System.Globalization;
using Xnu.Data;

namespace Xnu.Field
{
    // Namen des Spiel-Enums ZoneID (Name → Zonen-ID). Die Namen der MapWarp-/PlaceData-Instanzen folgen diesem Enum.
    // Quelle: scripts/field_zone_names.py schreibt work/masterdata/field/ZoneNames.json aus work/il2cpp/dump.cs
    // ({"ZoneID": {"T01R0201": 425, ...}}). Ohne die Datei sucht WarpTable nach Kartenbundle-Namen (unvollständig).
    public static class ZoneNames
    {
        public const string RelativePath = "field/ZoneNames.json";

        public static Dictionary<string, int> Parse(string json)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object> ?? throw new FormatException("Wurzel ist kein JSON-Objekt");
            if (!root.TryGetValue("ZoneID", out var v) || !(v is Dictionary<string, object> map)) throw new FormatException("Objekt 'ZoneID' fehlt");
            var result = new Dictionary<string, int>(map.Count, StringComparer.Ordinal);
            foreach (var kv in map) result[kv.Key] = Convert.ToInt32(kv.Value, CultureInfo.InvariantCulture);
            return result;
        }
    }
}
