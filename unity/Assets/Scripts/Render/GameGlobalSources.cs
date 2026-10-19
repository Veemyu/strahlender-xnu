using System;
using System.Collections.Generic;
using System.Linq;

namespace Xnu.Render
{
    public enum GlobalSourceKind
    {
        EnvironmentSettings,   // Wert steht im EnvironmentSettings-Asset der Zone (je Tagesabschnitt), wird in SetLight überblendet
        SceneObject,           // serialisiertes Feld des EnvironmentController im Szenenobjekt (Prefab)
        Runtime,               // aus Spielzustand/Konstante berechnet (Uhrzeit, statische Felder)
        CameraRig,             // von einem Kamera-Aufbau (Reflexionskamera, Tiefenaufnahme) per Aufnahme erzeugt
        PostEffect,            // von einem Nachbearbeitungsschritt (CommandBuffer) erzeugt
        PerObject,             // je Renderer als MaterialPropertyBlock/Material gesetzt, kein echtes Global
        PackageCode,           // von einem eingebundenen Paket (TextMeshPro) gesetzt
    }

    public struct GlobalSource
    {
        public string Name;
        public string Setter;       // Klasse.Methode im Spielcode (Il2Cpp-Namen)
        public GlobalSourceKind Kind;
        public string Data;         // Wertequelle in Worten (keine Werte)
        public bool Ported;         // in dieser Codebasis umgesetzt (EnvironmentState, DepthOfFieldMath, Runtime/*)

        public GlobalSource(string name, string setter, GlobalSourceKind kind, string data, bool ported)
        {
            Name = name; Setter = setter; Kind = kind; Data = data; Ported = ported;
        }
    }

    // Wer setzt welches Spiel-Global und woher kommt der Wert (docs/shader-globals.md, Abschnitt 1). Ein Eintrag je GameGlobals.Specs.
    public static class GameGlobalSources
    {
        const string OnUpdate = "EnvironmentController.OnUpdate";

        public static readonly IReadOnlyList<GlobalSource> All = new[]
        {
            new GlobalSource("_CloudParam", OnUpdate, GlobalSourceKind.SceneObject, "Uhrzeit · 60 · _CloudSpeed (modulo 1/_CloudTiling); _CloudTiling", true),
            new GlobalSource("_CloudShadowBase", OnUpdate, GlobalSourceKind.SceneObject, "1 − EnvironmentController._CloudShadowBase", true),
            new GlobalSource("_CloudShadowScale", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.CloudShadowScale (SetLight)", true),
            new GlobalSource("_CloudShadowTex", OnUpdate, GlobalSourceKind.SceneObject, "EnvironmentController._CloudShadowTex, sonst schwarz", true),
            new GlobalSource("_ShadowColor", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.ShadowColor · 0,5; bei Schnee _SnowShadowColor (Szenenobjekt) · 0,5", true),
            new GlobalSource("_GlobalLightPower", OnUpdate, GlobalSourceKind.Runtime, "statisches globalLightPower − 1; 0 bei throughGlobal", true),
            new GlobalSource("_GlobalBumpScale", OnUpdate, GlobalSourceKind.Runtime, "statisches globalBumpScale", true),
            new GlobalSource("_EmissionScale", OnUpdate, GlobalSourceKind.SceneObject, "EnvironmentController._EmissionScale", true),
            new GlobalSource("_EmissionThreshold", "EnvironmentController.SetLight / SceneConnector.OnUpdate", GlobalSourceKind.Runtime, "(Tagesabschnitt + Fortschritt) · 0,2", true),
            new GlobalSource("_VertexColorScale", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.VertexColorScale", true),
            new GlobalSource("_ReflectorColor", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.ReflectorColor", true),
            new GlobalSource("_ReflectionVP", "ReflectionCameraFollower.LateUpdate", GlobalSourceKind.CameraRig, "GPU-Projektion · Welt→Kamera der gespiegelten Reflexionskamera", true),
            new GlobalSource("_ReflectionTex", "ReflectionCameraFollower.OnEnable/LateUpdate", GlobalSourceKind.CameraRig, "Zieltextur der Reflexionskamera (Bildschirmgröße, Tiefe 24, Mips)", true),
            new GlobalSource("_EnvironmentMap", OnUpdate, GlobalSourceKind.SceneObject, "EnvironmentController._EnvironmentMap, sonst weiß", true),
            new GlobalSource("_SnowTex", OnUpdate, GlobalSourceKind.SceneObject, "EnvironmentController._SnowTex", true),
            new GlobalSource("_SnowNormalTex", OnUpdate, GlobalSourceKind.SceneObject, "EnvironmentController._SnowNormalTex, sonst Normalen-Standardtextur", true),
            new GlobalSource("_OpaqueDepthTexture", "MultipleCameraCompositor.OnReset", GlobalSourceKind.CameraRig, "CommandBuffer nach ForwardOpaque: BuiltinRenderTextureType.Depth", true),
            new GlobalSource("_CharacterLightColor", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.CharacterLightColor · (I, I, I, 1), I = CharacterLightIntensity + Zusatz", true),
            new GlobalSource("_CharacterReflectorColor", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.CharacterReflectorColor", true),
            new GlobalSource("_NoiseTex", OnUpdate, GlobalSourceKind.SceneObject, "EnvironmentController._NoiseTex, sonst Grau", true),
            new GlobalSource("_UVOffset", "FieldCharacterEntity.OnUpdate", GlobalSourceKind.PerObject, "MaterialPropertyBlock je Augen-/Mundrenderer (Muster- und Blinzelkurve)", false),
            new GlobalSource("_PokeLightColor", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.PokeLightColor · (I, I, I, 1), I = PokeLightIntensity + Zusatz", true),
            new GlobalSource("_PokeReflectorColor", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.PokeReflectorColor", true),
            new GlobalSource("_EnvMatrix", "TMPro.TMP_Text (Paket)", GlobalSourceKind.PackageCode, "Materialeigenschaft des TextMeshPro-Shaders (Rotation der Umgebungsabbildung)", false),
            new GlobalSource("_FocalCoefficient", "SmartPoint.Rendering.DepthOfField.Update", GlobalSourceKind.PostEffect, "(Entfernung, Tiefenschärfe, 1/Tiefenschärfe, 1/max(Entfernung + Tiefenschärfe, 0,001))", true),
            new GlobalSource("_FocusTex", "SmartPoint.Rendering.DepthOfField.Build", GlobalSourceKind.PostEffect, "CommandBuffer: Fokuskarte", false),
            new GlobalSource("_GlobalDepthTexture", "MultipleCameraCompositor.OnReset", GlobalSourceKind.CameraRig, "CommandBuffer vor ForwardOpaque: Tiefenpuffer der gemeinsamen Zieltextur", true),
            new GlobalSource("_AdditionalBlurry", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.Blurry", true),
            new GlobalSource("_BloomThreshold", OnUpdate, GlobalSourceKind.EnvironmentSettings, "Parameters.BloomThreshold", true),
            new GlobalSource("_BlurOffsetX", "SmartPoint.Rendering.DepthOfField.Build / Bloom.Build", GlobalSourceKind.PostEffect, "CommandBuffer.SetGlobalVector je Weichzeichner-Durchgang (Konstanten des Kerns)", false),
            new GlobalSource("_BlurOffsetY", "SmartPoint.Rendering.DepthOfField.Build / Bloom.Build", GlobalSourceKind.PostEffect, "CommandBuffer.SetGlobalVector je Weichzeichner-Durchgang (Konstanten des Kerns)", false),
            new GlobalSource("_DelayFrameTexture", "Dpr.Rendering.FeedbackBlur.Build", GlobalSourceKind.PostEffect, "CommandBuffer: Bild des Vorbildes (Rückkopplung)", false),
            new GlobalSource("_RcpGridSize", "ProceduralPlane (nur Property-ID)", GlobalSourceKind.PerObject, "Materialeigenschaft des Footprint-Materials; im Code kein SetFloat", false),
            new GlobalSource("_Corner", "Snowfield.OnUpdate", GlobalSourceKind.PerObject, "MaterialPropertyBlock je Fußabdruck", false),
            new GlobalSource("g_BackgroundTexture", "Effect.EffectManager.SetupBackgroundTexture", GlobalSourceKind.PostEffect, "DepthOfField.renderTexture (verkleinertes Szenenbild)", false),
        };

        static readonly Dictionary<string, GlobalSource> ByName = All.ToDictionary(s => s.Name, StringComparer.Ordinal);

        public static bool TryGet(string name, out GlobalSource source) => ByName.TryGetValue(name ?? "", out source);
    }
}
