using System;
using System.Collections.Generic;
using System.Globalization;
using Xnu.Data;

namespace Xnu.Render
{
    public struct Rgba
    {
        public float R, G, B, A;

        public Rgba(float r, float g, float b, float a) { R = r; G = g; B = b; A = a; }

        public static Rgba Lerp(Rgba a, Rgba b, float t)
        {
            t = t < 0 ? 0 : (t > 1 ? 1 : t);   // wie UnityEngine.Color.Lerp
            return new Rgba(a.R + (b.R - a.R) * t, a.G + (b.G - a.G) * t, a.B + (b.B - a.B) * t, a.A + (b.A - a.A) * t);
        }

        public static Rgba operator *(Rgba a, Rgba b) => new Rgba(a.R * b.R, a.G * b.G, a.B * b.B, a.A * b.A);
        public static Rgba operator *(Rgba a, float f) => new Rgba(a.R * f, a.G * f, a.B * f, a.A * f);
    }

    // EnvironmentSettings.Parameters: Licht-, Reflektor-, Nebel- und Schattenwerte eines Tagesabschnitts (Feldnamen wie im Spiel).
    // Die Werte kommen aus dem Export (scripts/environment_export.py); im Repo stehen keine Spielwerte.
    public sealed class EnvironmentParameters
    {
        public float LightYaw, LightPitch;
        public Rgba LightColor;
        public float LightIntensity;
        public Rgba ReflectorColor;
        public Rgba CharacterLightColor;
        public float CharacterLightIntensity;
        public Rgba CharacterReflectorColor;
        public Rgba PokeLightColor;
        public float PokeLightIntensity;
        public Rgba PokeReflectorColor;
        public bool ColorGradingEnable;
        public long ColorGradingLookup;       // Verweis (path_id) der Lookup-Textur, 0 = keine
        public float ColorGradingInfluence;
        public long NextColorGradingLookup;
        public float ColorGradingBlendWeight;
        public float VertexColorScale;
        public float BloomThreshold;
        public bool FogEnable;
        public float FogStart, FogEnd, FogDensity;
        public Rgba FogNearColor, FogFarColor;
        public Rgba ShadowColor;
        public float CloudShadowScale;
        public float Blurry;

        public EnvironmentParameters Clone() => (EnvironmentParameters)MemberwiseClone();

        public static EnvironmentParameters FromJson(Dictionary<string, object> d)
        {
            return new EnvironmentParameters
            {
                LightYaw = F(d, "LightYaw"), LightPitch = F(d, "LightPitch"), LightColor = C(d, "LightColor"),
                LightIntensity = F(d, "LightIntensity"), ReflectorColor = C(d, "ReflectorColor"),
                CharacterLightColor = C(d, "CharacterLightColor"), CharacterLightIntensity = F(d, "CharacterLightIntensity"),
                CharacterReflectorColor = C(d, "CharacterReflectorColor"), PokeLightColor = C(d, "PokeLightColor"),
                PokeLightIntensity = F(d, "PokeLightIntensity"), PokeReflectorColor = C(d, "PokeReflectorColor"),
                ColorGradingEnable = B(d, "ColorGradingEnable"), ColorGradingLookup = P(d, "ColorGradingLookup"),
                ColorGradingInfluence = F(d, "ColorGradingInfluence"), VertexColorScale = F(d, "VertexColorScale"),
                BloomThreshold = F(d, "BloomThreshold"), FogEnable = B(d, "FogEnable"), FogStart = F(d, "FogStart"),
                FogEnd = F(d, "FogEnd"), FogDensity = F(d, "FogDensity"), FogNearColor = C(d, "FogNearColor"),
                FogFarColor = C(d, "FogFarColor"), ShadowColor = C(d, "ShadowColor"), CloudShadowScale = F(d, "CloudShadowScale"),
                Blurry = F(d, "Blurry"),
            };
        }

        static float F(Dictionary<string, object> d, string k) =>
            d.TryGetValue(k, out var v) && v != null ? Convert.ToSingle(v, CultureInfo.InvariantCulture) : 0f;

        static bool B(Dictionary<string, object> d, string k) =>
            d.TryGetValue(k, out var v) && v != null && (v is bool b ? b : Convert.ToInt64(v, CultureInfo.InvariantCulture) != 0);

        static long P(Dictionary<string, object> d, string k) =>
            d.TryGetValue(k, out var v) && v is Dictionary<string, object> o && o.TryGetValue("m_PathID", out var id)
                ? Convert.ToInt64(id, CultureInfo.InvariantCulture) : 0;

        static Rgba C(Dictionary<string, object> d, string k)
        {
            if (!d.TryGetValue(k, out var v) || !(v is Dictionary<string, object> c)) return default;
            return new Rgba(F(c, "r"), F(c, "g"), F(c, "b"), F(c, "a"));
        }
    }

    // EnvironmentSettings (ScriptableObject): fünf Tagesabschnitte plus Schalter. Ein Asset je Zone/Szene (Zuordnung: MapInfo.RenderSettings).
    public sealed class EnvironmentSettingsData
    {
        public string Name;
        public long PathId;
        public bool CloudShadowEnable;
        public bool FixedTime;
        public int FogMode;
        public readonly EnvironmentParameters[] Periods = new EnvironmentParameters[5];

        public EnvironmentParameters this[PeriodOfDay p] => Periods[(int)p];

        // EnvironmentSettings.GetTransition: Werte des Abschnitts, zum nächsten Abschnitt überblendet mit weight.
        public EnvironmentParameters GetTransition(PeriodOfDay period, float weight)
        {
            var next = TimeOfDay.Next(period);
            if (weight < 0.0001f) return this[period];
            if (weight > 0.9999f) return this[next];
            var a = this[period];
            var b = this[next];
            if (a == null || b == null) return a ?? b;
            var r = new EnvironmentParameters
            {
                LightColor = Rgba.Lerp(a.LightColor, b.LightColor, weight),
                LightIntensity = EnvMath.Lerp(a.LightIntensity, b.LightIntensity, weight),
                ReflectorColor = Rgba.Lerp(a.ReflectorColor, b.ReflectorColor, weight),
                CharacterLightColor = Rgba.Lerp(a.CharacterLightColor, b.CharacterLightColor, weight),
                CharacterLightIntensity = EnvMath.Lerp(a.CharacterLightIntensity, b.CharacterLightIntensity, weight),
                CharacterReflectorColor = Rgba.Lerp(a.CharacterReflectorColor, b.CharacterReflectorColor, weight),
                PokeLightColor = Rgba.Lerp(a.PokeLightColor, b.PokeLightColor, weight),
                PokeLightIntensity = EnvMath.Lerp(a.PokeLightIntensity, b.PokeLightIntensity, weight),
                PokeReflectorColor = Rgba.Lerp(a.PokeReflectorColor, b.PokeReflectorColor, weight),
                VertexColorScale = EnvMath.Lerp(a.VertexColorScale, b.VertexColorScale, weight),
                BloomThreshold = EnvMath.Lerp(a.BloomThreshold, b.BloomThreshold, weight),
                ShadowColor = Rgba.Lerp(a.ShadowColor, b.ShadowColor, weight),
                CloudShadowScale = EnvMath.Lerp(a.CloudShadowScale, b.CloudShadowScale, weight),
                Blurry = EnvMath.Lerp(a.Blurry, b.Blurry, weight),
                LightYaw = a.LightYaw + ShortestAngle(b.LightYaw - a.LightYaw) * weight,
                LightPitch = a.LightPitch + ShortestAngle(b.LightPitch - a.LightPitch) * weight,
            };
            BlendFog(a, b, weight, r);
            BlendColorGrading(a, b, weight, r);
            return r;
        }

        // d - rund(d / 360) · 360 (Rundung: halb weg von null)
        public static float ShortestAngle(float d) => d - (float)(int)(d * 0.002777778f + (d >= 0 ? 0.5f : -0.5f)) * 360.0f;

        static void BlendFog(EnvironmentParameters a, EnvironmentParameters b, float w, EnvironmentParameters r)
        {
            r.FogEnable = a.FogEnable || b.FogEnable;
            if (!r.FogEnable) return;
            var src = a.FogEnable ? a : b;
            r.FogStart = src.FogStart; r.FogEnd = src.FogEnd; r.FogDensity = src.FogDensity;
            r.FogNearColor = src.FogNearColor; r.FogFarColor = src.FogFarColor;
            if (a.FogEnable && b.FogEnable)
            {
                r.FogStart = a.FogStart + (b.FogStart - a.FogStart) * w;
                r.FogEnd = a.FogEnd + (b.FogEnd - a.FogEnd) * w;
                r.FogDensity = a.FogDensity + (b.FogDensity - a.FogDensity) * w;
                r.FogNearColor = Lerp4(a.FogNearColor, b.FogNearColor, w);
                r.FogFarColor = Lerp4(a.FogFarColor, b.FogFarColor, w);
            }
            else if (b.FogEnable)   // Nebel blendet ein: nur der Alphakanal der Farben wächst mit w
            {
                r.FogNearColor.A *= w; r.FogFarColor.A *= w;
            }
            else                    // Nebel blendet aus
            {
                r.FogNearColor.A *= 1 - w; r.FogFarColor.A *= 1 - w;
            }
        }

        // a + (b - a) · w ohne Begrenzung von w
        static Rgba Lerp4(Rgba a, Rgba b, float w) =>
            new Rgba(a.R + (b.R - a.R) * w, a.G + (b.G - a.G) * w, a.B + (b.B - a.B) * w, a.A + (b.A - a.A) * w);

        static void BlendColorGrading(EnvironmentParameters a, EnvironmentParameters b, float w, EnvironmentParameters r)
        {
            r.ColorGradingEnable = a.ColorGradingEnable || b.ColorGradingEnable;
            if (!r.ColorGradingEnable) return;
            if (a.ColorGradingEnable)
            {
                r.ColorGradingLookup = a.ColorGradingLookup;
                if (b.ColorGradingEnable)
                {
                    r.ColorGradingInfluence = a.ColorGradingInfluence + (b.ColorGradingInfluence - a.ColorGradingInfluence) * w;
                    r.ColorGradingBlendWeight = w;
                    r.NextColorGradingLookup = b.ColorGradingLookup;
                }
                else
                {
                    r.ColorGradingInfluence = 1 - w;
                    r.NextColorGradingLookup = 0;
                }
            }
            else
            {
                r.ColorGradingLookup = b.ColorGradingLookup;
                r.ColorGradingInfluence = b.ColorGradingInfluence * w;
                r.NextColorGradingLookup = 0;
            }
        }
    }

    static class EnvMath
    {
        public static float Lerp(float a, float b, float t) { t = t < 0 ? 0 : (t > 1 ? 1 : t); return a + (b - a) * t; }
    }

    public sealed class ZoneRenderRecord
    {
        public int Index;
        public int ZoneId;
        public string Settings;      // Name des EnvironmentSettings-Assets, null = keines
        public int Weather;          // SYS_WEATHER des Kartendatensatzes
        public bool FixedTime;
        public bool ReflectionCamera;
    }

    // Lädt EnvironmentSettings.json / MapRenderSettings.json (scripts/environment_export.py).
    public sealed class EnvironmentSettingsCatalog
    {
        readonly Dictionary<string, EnvironmentSettingsData> _byName = new Dictionary<string, EnvironmentSettingsData>(StringComparer.Ordinal);
        readonly Dictionary<int, ZoneRenderRecord> _zones = new Dictionary<int, ZoneRenderRecord>();

        public int SettingsCount => _byName.Count;
        public int ZoneCount => _zones.Count;

        public static readonly string[] PeriodNames = { "Morning", "Daytime", "Evening", "Night", "Midnight" };

        public void LoadSettingsJson(string json)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object> ?? throw new FormatException("EnvironmentSettings: Objekt erwartet");
            foreach (var o in (List<object>)root["settings"])
            {
                var d = (Dictionary<string, object>)o;
                var s = new EnvironmentSettingsData
                {
                    Name = (string)d["name"],
                    PathId = d.TryGetValue("pathId", out var pid) && pid != null ? Convert.ToInt64(pid, CultureInfo.InvariantCulture) : 0,
                    CloudShadowEnable = d["cloudShadowEnable"] is bool c && c,
                    FixedTime = d["fixedTime"] is bool f && f,
                    FogMode = Convert.ToInt32(d["fogMode"], CultureInfo.InvariantCulture),
                };
                var periods = (Dictionary<string, object>)d["periods"];
                for (var i = 0; i < 5; i++)
                    if (periods.TryGetValue(PeriodNames[i], out var p)) s.Periods[i] = EnvironmentParameters.FromJson((Dictionary<string, object>)p);
                _byName[s.Name] = s;
            }
        }

        public void LoadZonesJson(string json)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object> ?? throw new FormatException("MapRenderSettings: Objekt erwartet");
            foreach (var o in (List<object>)root["zones"])
            {
                var d = (Dictionary<string, object>)o;
                var z = new ZoneRenderRecord
                {
                    Index = Convert.ToInt32(d["index"], CultureInfo.InvariantCulture),
                    ZoneId = d["zoneId"] == null ? -1 : Convert.ToInt32(d["zoneId"], CultureInfo.InvariantCulture),
                    Settings = d["settings"] as string,
                    Weather = Convert.ToInt32(d["weather"], CultureInfo.InvariantCulture),
                    FixedTime = d["fixedTime"] is bool f && f,
                    ReflectionCamera = d["reflectionCamera"] is bool r && r,
                };
                _zones[z.Index] = z;
            }
        }

        public EnvironmentSettingsData Find(string name) => name != null && _byName.TryGetValue(name, out var s) ? s : null;

        public ZoneRenderRecord Zone(int index) => _zones.TryGetValue(index, out var z) ? z : null;

        // Settings der Zone (MapInfo.ZoneData[index].RenderSettings), null wenn die Zone keine hat.
        public EnvironmentSettingsData ForZone(int index) => Find(Zone(index)?.Settings);
    }
}
