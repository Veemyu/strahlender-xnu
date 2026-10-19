using System;
using System.Collections.Generic;
using System.Globalization;
using Xnu.Data;

namespace Xnu.Render
{
    // RenderSettings der Feldszene (Szene Dpr/scenes/field, docs/sichtpruefung-2.md Abschnitt 3): kein Skybox-Material, kein Nebel,
    // Umgebungslicht aus der (fehlenden) Skybox, daher schwarz.
    public sealed class SceneRenderSettings
    {
        public bool Fog;
        public Rgba FogColor;
        public int FogMode;
        public float FogDensity, FogStart, FogEnd;
        public int AmbientMode;                 // Unity: 0 Skybox, 1 Trilight, 3 Flat, 4 Custom
        public Rgba AmbientSky, AmbientEquator, AmbientGround;
        public float AmbientIntensity = 1f;
        public Rgba SubtractiveShadow;
        public bool HasSkybox;
        public int ReflectionMode;              // 0 Skybox, 1 Custom
        public float ReflectionIntensity = 1f;
    }

    // Kamera der Feldszene (serialisierte Werte).
    public sealed class SceneCameraInfo
    {
        public string Name;
        public int ClearFlags;                  // Unity: 1 Skybox, 2 Volle Farbe, 3 Nur Tiefe, 4 Nichts
        public Rgba Background;
        public float Near, Far, Fov, Depth;
        public long CullingMask;
        public bool Hdr, Msaa, Enabled;
    }

    // Licht der Feldszene (EnvironmentController-Objekt: Richtungslicht mit weichen Schatten).
    public sealed class SceneLightInfo
    {
        public string Name;
        public int Type;                        // 1 = Richtungslicht
        public float Intensity, Bias, NormalBias;
        public int Shadows;                     // 0 keine, 1 hart, 2 weich
        public long CullingMask;
    }

    // Szenenwerte der Feldszene aus work/masterdata/EnvironmentScene.json (scripts/environment_export.py).
    public sealed class EnvironmentSceneData
    {
        public EnvironmentSceneParams Params = new EnvironmentSceneParams();
        public SceneRenderSettings Render = new SceneRenderSettings();
        public readonly List<SceneCameraInfo> Cameras = new List<SceneCameraInfo>();
        public readonly List<SceneLightInfo> Lights = new List<SceneLightInfo>();
        // Namen der Szenentexturen (_NoiseTex, _SnowTex, _CloudShadowTex, …); null = nicht gesetzt oder nicht auflösbar.
        public readonly Dictionary<string, string> TextureNames = new Dictionary<string, string>(StringComparer.Ordinal);

        public SceneCameraInfo Camera(string name)
        {
            foreach (var c in Cameras) if (c.Name == name) return c;
            return null;
        }

        public static EnvironmentSceneData FromJson(string json)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object> ?? throw new FormatException("EnvironmentScene: Objekt erwartet");
            var d = new EnvironmentSceneData();
            var c = Obj(root, "controller");
            var p = d.Params;
            p.CloudSpeedX = Arr(c, "cloudSpeed", 0, p.CloudSpeedX); p.CloudSpeedY = Arr(c, "cloudSpeed", 1, p.CloudSpeedY);
            p.CloudTilingX = Arr(c, "cloudTiling", 0, 0); p.CloudTilingY = Arr(c, "cloudTiling", 1, 0);
            p.EmissionScale = F(c, "_EmissionScale", 1);
            p.CloudShadowBase = F(c, "_CloudShadowBase", 0);
            p.Wetness = F(c, "_Wetness", 0);
            p.WeatherMode = (int)F(c, "_WeatherMode", 0);
            p.SnowShadowColor = Col(c, "snowShadowColor");
            p.ShadowDistance = F(c, "_ShadowDistance", 0);
            p.ShadowNearPlaneOffset = F(c, "_ShadowNearPlaneOffset", 0);
            p.ShadowNormalBias = F(c, "_ShadowNormalBias", 0);
            if (c.TryGetValue("textures", out var t) && t is Dictionary<string, object> tx)
                foreach (var kv in tx) d.TextureNames[kv.Key] = kv.Value as string;

            var r = Obj(root, "renderSettings");
            var s = d.Render;
            s.Fog = B(r, "fog"); s.FogColor = Col(r, "fogColor"); s.FogMode = (int)F(r, "fogMode", 0);
            s.FogDensity = F(r, "fogDensity", 0); s.FogStart = F(r, "fogStart", 0); s.FogEnd = F(r, "fogEnd", 0);
            s.AmbientMode = (int)F(r, "ambientMode", 0); s.AmbientSky = Col(r, "ambientSky");
            s.AmbientEquator = Col(r, "ambientEquator"); s.AmbientGround = Col(r, "ambientGround");
            s.AmbientIntensity = F(r, "ambientIntensity", 1); s.SubtractiveShadow = Col(r, "subtractiveShadow");
            s.HasSkybox = B(r, "skybox"); s.ReflectionMode = (int)F(r, "reflectionMode", 0);
            s.ReflectionIntensity = F(r, "reflectionIntensity", 1);

            if (root.TryGetValue("cameras", out var cams) && cams is List<object> cl)
                foreach (var o in cl)
                {
                    if (!(o is Dictionary<string, object> m)) continue;
                    d.Cameras.Add(new SceneCameraInfo
                    {
                        Name = Str(m, "name"), ClearFlags = (int)F(m, "clearFlags", 0), Background = Col(m, "background"),
                        Near = F(m, "near", 0), Far = F(m, "far", 0), Fov = F(m, "fov", 0), Depth = F(m, "depth", 0),
                        CullingMask = (long)F(m, "cullingMask", 0), Hdr = B(m, "hdr"), Msaa = B(m, "msaa"), Enabled = F(m, "enabled", 1) != 0,
                    });
                }
            if (root.TryGetValue("lights", out var lis) && lis is List<object> ll)
                foreach (var o in ll)
                {
                    if (!(o is Dictionary<string, object> m)) continue;
                    d.Lights.Add(new SceneLightInfo
                    {
                        Name = Str(m, "name"), Type = (int)F(m, "type", 0), Intensity = F(m, "intensity", 0), Shadows = (int)F(m, "shadows", 0),
                        Bias = F(m, "bias", 0), NormalBias = F(m, "normalBias", 0), CullingMask = (long)F(m, "cullingMask", 0),
                    });
                }
            return d;
        }

        static Dictionary<string, object> Obj(Dictionary<string, object> d, string k) =>
            d.TryGetValue(k, out var v) && v is Dictionary<string, object> o ? o : new Dictionary<string, object>();

        static float F(Dictionary<string, object> d, string k, float def) =>
            d.TryGetValue(k, out var v) && v != null && !(v is string) && !(v is bool) ? Convert.ToSingle(v, CultureInfo.InvariantCulture) : def;

        static bool B(Dictionary<string, object> d, string k) =>
            d.TryGetValue(k, out var v) && v != null && (v is bool b ? b : Convert.ToInt64(v, CultureInfo.InvariantCulture) != 0);

        static string Str(Dictionary<string, object> d, string k) => d.TryGetValue(k, out var v) ? v as string : null;

        static float Arr(Dictionary<string, object> d, string k, int i, float def) =>
            d.TryGetValue(k, out var v) && v is List<object> l && i < l.Count && l[i] != null ? Convert.ToSingle(l[i], CultureInfo.InvariantCulture) : def;

        static Rgba Col(Dictionary<string, object> d, string k)
        {
            if (!d.TryGetValue(k, out var v) || !(v is List<object> l) || l.Count < 4) return default;
            return new Rgba(Convert.ToSingle(l[0], CultureInfo.InvariantCulture), Convert.ToSingle(l[1], CultureInfo.InvariantCulture),
                            Convert.ToSingle(l[2], CultureInfo.InvariantCulture), Convert.ToSingle(l[3], CultureInfo.InvariantCulture));
        }
    }
}
