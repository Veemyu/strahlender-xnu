using System;

namespace Xnu.Render
{
    // Platzhalternamen für Texturen, die das Spiel ersatzweise setzt, wenn ein Verweis leer ist
    // (Texture2D.blackTexture usw.). UnityGlobalSink übersetzt sie in die Unity-Standardtexturen.
    public static class DefaultTextures
    {
        public const string Black = "black";
        public const string White = "white";
        public const string Gray = "gray";
        public const string Bump = "bump";   // Texture2D.normalTexture
    }

    // Vom Szenenobjekt (Prefab) gelieferte, serialisierte Felder des EnvironmentController (nicht aus EnvironmentSettings).
    public sealed class EnvironmentSceneParams
    {
        public float CloudSpeedX = 1, CloudSpeedY = 1;
        public float CloudTilingX, CloudTilingY;
        public float EmissionScale = 1;
        public float CloudShadowBase;
        public float Wetness;
        public int WeatherMode;                 // 0 sonnig, 1 Regen, 2 Schnee
        public Rgba SnowShadowColor;
        public float ShadowDistance, ShadowNearPlaneOffset, ShadowNormalBias;
        public object CloudShadowTex, EnvironmentMap, SnowTex, SnowNormalTex, NoiseTex;   // Texturen (oder null)
    }

    // Ergebnis für Licht und Qualitätseinstellungen (EnvironmentController.OnUpdate setzt sie auf Light und QualitySettings).
    public struct EnvironmentLightOutput
    {
        public Rgba LightColor;
        public float LightIntensity;
        public float Pitch, Yaw;             // eulerAngles = (Pitch, Yaw, 0)
        public float ShadowNormalBias;
        public float ShadowDistance, ShadowNearPlaneOffset;
        public float DepthOfFieldBlurry;     // DepthOfField.blurry (statisch)
    }

    // Port von EnvironmentController (SetLight, SetPokemonLight, OnUpdate), soweit sie Shader-Globals und Licht betreffen.
    // Herleitung: docs/shader-globals.md, Abschnitt 2. Rein, ohne UnityEngine; die Unity-Seite ist Runtime/EnvironmentDriver.
    public sealed class EnvironmentState
    {
        public EnvironmentSceneParams Scene = new EnvironmentSceneParams();

        // static float globalBumpScale / globalLightPower (Standard 1, im Spiel von Timeline/Ereignissen gesetzt)
        public float GlobalBumpScale = 1;
        public float GlobalLightPower = 1;
        public bool ThroughGlobal;              // _throughGlobal

        public float AddLightIntensity, AddCharacterLightIntensity, AddPokeLightIntensity;

        // EnvironmentController.parameters (zuletzt gesetzter Abschnitt, bereits überblendet)
        public EnvironmentParameters Current;
        public PeriodOfDay LastPeriod = PeriodOfDay.Daytime;
        public float EmissionThreshold;
        public bool CloudShadowEnabled = true;  // _cloudShadowEnable (aus EnvironmentSettings.CloudShadowEnable)
        public Rgba ShadowColor;                // _ShadowColor (aus EnvironmentSettings.ShadowColor)
        public float CloudShadowScale = 1;
        public float Blurry = 1;

        // SetLight(settings, period, progress, weight)
        public void SetLight(EnvironmentSettingsData settings, PeriodOfDay period, float progress, float weight)
        {
            if (settings == null) return;
            CloudShadowEnabled = settings.CloudShadowEnable;
            LastPeriod = period;
            var t = settings.GetTransition(period, weight);
            if (t == null) return;
            Current = t;
            EmissionThreshold = ((float)(int)period + progress) * 0.2f;
            ShadowColor = t.ShadowColor;
            CloudShadowScale = t.CloudShadowScale;
            Blurry = t.Blurry;
        }

        // SetPokemonLight(settings, period): nur die Pokémon-Lichtwerte, ohne Überblendung
        public void SetPokemonLight(EnvironmentSettingsData settings, PeriodOfDay period)
        {
            var s = settings?[period];
            if (s == null) return;
            if (Current == null) Current = new EnvironmentParameters();
            else Current = Current.Clone();
            Current.PokeLightColor = s.PokeLightColor;
            Current.PokeReflectorColor = s.PokeReflectorColor;
            Current.PokeLightIntensity = s.PokeLightIntensity;
        }

        // _CloudParam: (Zeit · 60 · Geschwindigkeit, modulo 1/Kachelung, wenn Kachelung ≠ 0; Kachelung)
        public static void CloudParam(float hours, EnvironmentSceneParams s, out float x, out float y)
        {
            x = hours * 60.0f * s.CloudSpeedX;
            if (!Approximately(s.CloudTilingX, 0)) x = x % (1.0f / s.CloudTilingX);   // fmodf
            y = hours * 60.0f * s.CloudSpeedY;
            if (!Approximately(s.CloudTilingY, 0)) y = y % (1.0f / s.CloudTilingY);
        }

        // Mathf.Approximately: |a - b| < max(1e-6 · max(|a|, |b|), 8 · Epsilon)
        static bool Approximately(float a, float b) =>
            Math.Abs(b - a) < Math.Max(1e-6f * Math.Max(Math.Abs(a), Math.Abs(b)), 1.1754944e-38f * 8);

        // EnvironmentController.OnUpdate: alle Spiel-Globals dieses Controllers setzen. hours = GameManager.elapsedTimeOfDay.
        public EnvironmentLightOutput Apply(GameGlobals g, float hours)
        {
            var p = Current ?? new EnvironmentParameters();
            var charMul = p.CharacterLightIntensity + AddCharacterLightIntensity;
            var pokeMul = p.PokeLightIntensity + AddPokeLightIntensity;

            SetColor(g, "_CharacterLightColor", p.CharacterLightColor * new Rgba(charMul, charMul, charMul, 1));
            SetColor(g, "_CharacterReflectorColor", p.CharacterReflectorColor);
            SetColor(g, "_PokeLightColor", p.PokeLightColor * new Rgba(pokeMul, pokeMul, pokeMul, 1));
            SetColor(g, "_PokeReflectorColor", p.PokeReflectorColor);
            SetColor(g, "_ReflectorColor", p.ReflectorColor);
            g.SetFloat("_VertexColorScale", p.VertexColorScale);
            g.SetFloat("_BloomThreshold", p.BloomThreshold);
            g.SetFloat("_EmissionScale", Scene.EmissionScale);
            g.SetFloat("_EmissionThreshold", EmissionThreshold);
            g.SetFloat("_CloudShadowScale", CloudShadowScale);
            g.SetFloat("_CloudShadowBase", 1.0f - Scene.CloudShadowBase);
            g.SetFloat("_GlobalBumpScale", GlobalBumpScale);
            g.SetFloat("_GlobalLightPower", ThroughGlobal ? 0.0f : GlobalLightPower - 1.0f);
            g.SetFloat("_AdditionalBlurry", Blurry);
            SetColor(g, "_ShadowColor", (Scene.WeatherMode == 2 ? Scene.SnowShadowColor : ShadowColor) * 0.5f);

            CloudParam(hours, Scene, out var cx, out var cy);
            g.SetVector("_CloudParam", cx, cy, Scene.CloudTilingX, Scene.CloudTilingY);

            g.SetTexture("_CloudShadowTex", Scene.CloudShadowTex != null && CloudShadowEnabled ? Scene.CloudShadowTex : DefaultTextures.Black);
            g.SetTexture("_EnvironmentMap", Scene.EnvironmentMap ?? DefaultTextures.White);
            g.SetTexture("_SnowTex", Scene.SnowTex ?? DefaultTextures.White);
            g.SetTexture("_SnowNormalTex", Scene.SnowNormalTex ?? DefaultTextures.Bump);
            g.SetTexture("_NoiseTex", Scene.NoiseTex ?? DefaultTextures.Gray);

            return new EnvironmentLightOutput
            {
                LightColor = p.LightColor, LightIntensity = p.LightIntensity + AddLightIntensity,
                Pitch = p.LightPitch, Yaw = p.LightYaw, ShadowNormalBias = Scene.ShadowNormalBias,
                ShadowDistance = Scene.ShadowDistance, ShadowNearPlaneOffset = Scene.ShadowNearPlaneOffset,
                DepthOfFieldBlurry = Blurry,
            };
        }

        static void SetColor(GameGlobals g, string name, Rgba c) => g.SetVector(name, c.R, c.G, c.B, c.A);
    }

    // SmartPoint.Rendering.DepthOfField.Update: _FocalCoefficient und Schärfentiefe (docs/shader-globals.md, Abschnitt 5).
    public static class DepthOfFieldMath
    {
        // Brennweite in mm aus Sichtfeld (Grad) und Sensorhöhe (mm), wie Camera.FieldOfViewToFocalLength
        public static float FocalLengthFromFov(float fovDegrees, float sensorHeightMm) =>
            0.5f * sensorHeightMm / (float)Math.Tan(0.5 * fovDegrees * Math.PI / 180.0);

        // farDepth = (Sensorfaktor · k · Entfernung · 0,5) / (f · 0,001)²; k = 0,024 ohne physikalische Kamera, sonst Sensorhöhe · 0,001
        public static float FarDepth(float sensorScale, float k, float distance, float focalLengthMm)
        {
            var f = focalLengthMm * 0.001f;
            return sensorScale * k * distance * 0.5f / (f * f);
        }

        // (Entfernung, Tiefenschärfe, 1/Tiefenschärfe, 1/max(Entfernung + Tiefenschärfe, 0,001))
        public static void FocalCoefficient(float distance, float farDepth, out float x, out float y, out float z, out float w)
        {
            x = distance; y = farDepth; z = 1.0f / farDepth; w = 1.0f / Math.Max(distance + farDepth, 0.001f);
        }
    }

    // SceneConnector.OnUpdate (Feldszene): wählt je Bild Abschnitt/Gewicht und ruft SetLight. FixedTime-Zonen bleiben am Tag.
    public static class FieldLighting
    {
        public static void Update(EnvironmentState state, EnvironmentSettingsData settings, bool zoneFixedTime, float hours)
        {
            if (settings == null) return;
            var (period, progress, weight) = TimeOfDay.CurrentPeriodEx(hours);
            if (zoneFixedTime)
            {
                state.SetLight(settings, PeriodOfDay.Daytime, 0, 0);
                state.EmissionThreshold = (progress + (int)period) * 0.2f;   // die Zeit läuft nur für die Leuchtschwelle weiter
                return;
            }
            state.SetLight(settings, period, progress, weight);
        }
    }
}
