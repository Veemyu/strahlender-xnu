using System;
using System.Collections.Generic;
using System.Linq;

namespace Xnu.Render
{
    public enum GlobalKind { Float, Vector, Matrix, Texture }

    public struct GlobalSpec
    {
        public string Name;
        public GlobalKind Kind;
        public float DefaultX;   // Platzhalter, kein Originalwert (docs/material-remap.md, Abschnitt 5)
        public string UsedBy;    // Beispiel-Shader aus dem Inventar

        public GlobalSpec(string name, GlobalKind kind, float defaultX, string usedBy)
        {
            Name = name; Kind = kind; DefaultX = defaultX; UsedBy = usedBy;
        }
    }

    // Senke für Shader.SetGlobal*; die Unity-Fassung steht in UnityGlobalSink.
    public interface IGlobalSink
    {
        void SetFloat(string name, float value);
        void SetVector(string name, float x, float y, float z, float w);
        void SetMatrix(string name, float[] rowMajor16);
        void SetTexture(string name, object texture);
    }

    // Die Spiel-Globals der Original-Shader: Namen, die weder Material-Eigenschaft noch von Unity gesetzt sind
    // und die das Spiel selbst per Shader.SetGlobal* liefert (35 Namen aus den 64 Bundle-Shadern, Herleitung in
    // docs/material-remap.md). Engine-Werte (unity_*, _Time, _WorldSpaceCameraPos ...) setzt Unity selbst.
    public sealed class GameGlobals
    {
        public static readonly IReadOnlyList<GlobalSpec> Specs = new[]
        {
            new GlobalSpec("_CloudParam", GlobalKind.Vector, 0, "Delphis/Map/Standard"),
            new GlobalSpec("_CloudShadowBase", GlobalKind.Float, 1, "Delphis/Map/Standard"),   // Original: 1 − Szenenwert (Szenenwert 0 → 1); 0 würde die ganze Karte in den Schatten legen
            new GlobalSpec("_CloudShadowScale", GlobalKind.Float, 1, "Delphis/Map/Standard"),
            new GlobalSpec("_CloudShadowTex", GlobalKind.Texture, 0, "Delphis/Map/Standard"),
            new GlobalSpec("_ShadowColor", GlobalKind.Vector, 0, "Delphis/Map/Standard"),
            new GlobalSpec("_GlobalLightPower", GlobalKind.Float, 0, "Delphis/Map/Standard"),   // Original: globalLightPower (Standard 1) − 1 = 0
            new GlobalSpec("_GlobalBumpScale", GlobalKind.Float, 1, "Delphis/Map/Standard"),
            new GlobalSpec("_EmissionScale", GlobalKind.Float, 1, "Delphis/Map/Standard"),
            new GlobalSpec("_EmissionThreshold", GlobalKind.Float, 0, "Delphis/Map/Standard"),
            new GlobalSpec("_VertexColorScale", GlobalKind.Float, 1, "Delphis/Map/Standard"),
            new GlobalSpec("_ReflectorColor", GlobalKind.Vector, 0, "Delphis/Map/FlowmapWater"),
            new GlobalSpec("_ReflectionVP", GlobalKind.Matrix, 1, "Delphis/Map/Standard"),
            new GlobalSpec("_ReflectionTex", GlobalKind.Texture, 0, "Delphis/Map/Standard"),
            new GlobalSpec("_EnvironmentMap", GlobalKind.Texture, 0, "Delphis/Map/Standard"),
            new GlobalSpec("_SnowTex", GlobalKind.Texture, 0, "Delphis/Map/Standard"),
            new GlobalSpec("_SnowNormalTex", GlobalKind.Texture, 0, "Delphis/Map/Standard"),
            new GlobalSpec("_OpaqueDepthTexture", GlobalKind.Texture, 0, "Delphis/Map/FlowmapWater"),
            new GlobalSpec("_CharacterLightColor", GlobalKind.Vector, 0, "Delphis/Character/Standard"),
            new GlobalSpec("_CharacterReflectorColor", GlobalKind.Vector, 0, "Delphis/Character/Standard"),
            new GlobalSpec("_NoiseTex", GlobalKind.Texture, 0, "Delphis/Character/Standard"),
            new GlobalSpec("_UVOffset", GlobalKind.Vector, 0, "Delphis/Character/Standard"),
            new GlobalSpec("_PokeLightColor", GlobalKind.Vector, 0, "Mitake/MitakeStandardBumpShader"),
            new GlobalSpec("_PokeReflectorColor", GlobalKind.Vector, 0, "Mitake/MitakeStandardBumpShader"),
            new GlobalSpec("_EnvMatrix", GlobalKind.Matrix, 1, "TextMeshPro/Distance Field"),
            new GlobalSpec("_FocalCoefficient", GlobalKind.Vector, 0, "Custom/CaptureFocus"),
            new GlobalSpec("_FocusTex", GlobalKind.Texture, 0, "Custom/Downsample2x2Focus"),
            new GlobalSpec("_GlobalDepthTexture", GlobalKind.Texture, 0, "Custom/CaptureFocus"),
            new GlobalSpec("_AdditionalBlurry", GlobalKind.Float, 0, "Custom/DepthOfField"),
            new GlobalSpec("_BloomThreshold", GlobalKind.Float, 0, "Custom/Bloom Setup"),
            new GlobalSpec("_BlurOffsetX", GlobalKind.Vector, 0, "Custom/Gaussian7x7"),
            new GlobalSpec("_BlurOffsetY", GlobalKind.Vector, 0, "Custom/Gaussian7x7"),
            new GlobalSpec("_DelayFrameTexture", GlobalKind.Texture, 0, "Dpr/PostEffect/FeedbackBlur"),
            new GlobalSpec("_RcpGridSize", GlobalKind.Float, 1, "Custom/ProceduralPlane/Footprint"),
            new GlobalSpec("_Corner", GlobalKind.Vector, 0, "Delphis/Snowfield/Snowfield"),
            new GlobalSpec("g_BackgroundTexture", GlobalKind.Texture, 0, "FxSystem/Particle"),
        };

        static readonly Dictionary<string, GlobalSpec> ByName = Specs.ToDictionary(s => s.Name, StringComparer.Ordinal);

        readonly IGlobalSink _sink;
        readonly HashSet<string> _set = new HashSet<string>(StringComparer.Ordinal);

        public GameGlobals(IGlobalSink sink)
        {
            _sink = sink ?? throw new ArgumentNullException(nameof(sink));
        }

        public static bool IsGameGlobal(string name) => name != null && ByName.ContainsKey(name);

        public static bool TryGetSpec(string name, out GlobalSpec spec) => ByName.TryGetValue(name ?? "", out spec);

        public int CountSet => _set.Count;

        // Namen, die noch nie gesetzt wurden (Texturen eingeschlossen).
        public IEnumerable<string> Unset => Specs.Where(s => !_set.Contains(s.Name)).Select(s => s.Name);

        public void SetFloat(string name, float v) { Check(name, GlobalKind.Float); _sink.SetFloat(name, v); _set.Add(name); }

        public void SetVector(string name, float x, float y, float z, float w)
        {
            Check(name, GlobalKind.Vector); _sink.SetVector(name, x, y, z, w); _set.Add(name);
        }

        public void SetMatrix(string name, float[] rowMajor16)
        {
            Check(name, GlobalKind.Matrix);
            if (rowMajor16 == null || rowMajor16.Length != 16) throw new ArgumentException("Matrix braucht 16 Werte", nameof(rowMajor16));
            _sink.SetMatrix(name, rowMajor16); _set.Add(name);
        }

        public void SetTexture(string name, object texture)
        {
            Check(name, GlobalKind.Texture); _sink.SetTexture(name, texture); _set.Add(name);
        }

        // Setzt alle Zahlenwerte auf ihre Platzhalter (Einheitsmatrix, Multiplikatoren 1, sonst 0). Texturen bleiben unberührt.
        public void SetDefaults()
        {
            foreach (var s in Specs)
            {
                switch (s.Kind)
                {
                    case GlobalKind.Float: SetFloat(s.Name, s.DefaultX); break;
                    case GlobalKind.Vector: SetVector(s.Name, s.DefaultX, s.DefaultX, s.DefaultX, s.DefaultX); break;
                    case GlobalKind.Matrix: SetMatrix(s.Name, Identity()); break;
                }
            }
        }

        public static float[] Identity() => new float[] { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 };

        static void Check(string name, GlobalKind kind)
        {
            if (!ByName.TryGetValue(name ?? "", out var s)) throw new ArgumentException("Kein Spiel-Global: " + name, nameof(name));
            if (s.Kind != kind) throw new ArgumentException(name + " ist " + s.Kind + ", nicht " + kind, nameof(name));
        }
    }
}
