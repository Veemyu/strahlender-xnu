using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xnu.Render
{
    // Nachbearbeitung der Feldkamera mit den erzeugten Shadern (Built-in-Pipeline, OnRenderImage). Nachbau von
    // SmartPoint.Rendering.Bloom.Build und Fxaa.Build (docs/sichtpruefung-2.md, Abschnitt 2); die Kette im Original steht im
    // PostProcessFilter der Feldszene in der Reihenfolge Bloom, DepthOfField, FXAA (Tiefenschärfe ist hier nicht nachgebaut).
    //
    // Bloom (belegt aus dem dekompilierten Build):
    //   5 Ebenen, Ebene i hat Breite/Höhe >> (i + 2), Format ARGBHalf, je ein Paar Puffer (A, B);
    //   Ebene 0: Quelle -> A0 mit „Bloom Setup“ (Schwelle _BloomThreshold, Global), Ebene i > 0: A(i-1) -> A(i) einfaches Verkleinern;
    //   je Ebene: _BlurOffsetX = (-2,2186, 2,2186, -0,6075, 0,6075), _BlurOffsetY = 0, A -> B mit „Gaussian7x7“, danach
    //   X = 0, Y = Versatz, B -> A; zuletzt Quelle -> Ziel mit „Bloom Finalize“ (A(i) als globale Texturen _SubTex0..4,
    //   Nebel: Schlüsselwort _FOGMODE_*, _FogParam, _Color, _FarColor aus Bloom.SetFogParameters).
    // FXAA: ein Durchgang „Fxaa“ (Farbkorrektur-LUT aus den EnvironmentSettings ist hier nicht angebunden: _GRADING_NONE).
    // Die Gewichte der Ebenen im Finalize-Durchgang sind im erzeugten Shader eingebrannt.
    [RequireComponent(typeof(Camera))]
    public sealed class PostChain : MonoBehaviour
    {
        public const string BloomSetupShader = "Custom/Bloom Setup";
        public const string GaussianShader = "Custom/Gaussian7x7";
        public const string BloomFinalizeShader = "Custom/Bloom Finalize";
        public const string FxaaShader = "Custom/Fxaa";
        public const int Layers = 5;

        // Versatz des 7-Tap-Gauß mit bilinearen Abtastungen (get_blurOffset, Bitmuster 0xC00DF8DF, 0x400DF8DF, 0xBF1B9852, 0x3F1B9852).
        public static readonly Vector4 BlurOffset = new Vector4(
            BitConverter.Int32BitsToSingle(unchecked((int)0xC00DF8DF)), BitConverter.Int32BitsToSingle(0x400DF8DF),
            BitConverter.Int32BitsToSingle(unchecked((int)0xBF1B9852)), BitConverter.Int32BitsToSingle(0x3F1B9852));

        public bool EnableBloom = true;
        public bool EnableFxaa = true;
        public bool EnableFog = true;
        public EnvironmentDriver Driver;          // liefert Nebelwerte der Zone (State.Current); null = kein Nebel
        public ShaderVariantIndex Index;          // Variantentabelle der erzeugten Shader; null = GeneratedShaderLibrary.LoadIndex

        public string Status { get; private set; } = "nicht initialisiert";
        public int Blits { get; private set; }

        Material _setup, _gauss;
        readonly Dictionary<string, Material> _variants = new Dictionary<string, Material>(StringComparer.Ordinal);
        ShaderVariantResolver _resolver;
        bool _built;
        static readonly int[] SubTexIds = { Shader.PropertyToID("_SubTex0"), Shader.PropertyToID("_SubTex1"), Shader.PropertyToID("_SubTex2"), Shader.PropertyToID("_SubTex3"), Shader.PropertyToID("_SubTex4") };
        static readonly int BlurX = Shader.PropertyToID("_BlurOffsetX"), BlurY = Shader.PropertyToID("_BlurOffsetY");

        void OnEnable()
        {
            var cam = GetComponent<Camera>();
            cam.depthTextureMode |= DepthTextureMode.Depth;   // Nebel liest die Tiefe (_GlobalDepthTexture)
            if (cam.GetComponent<DepthCaptureDriver>() == null) gameObject.AddComponent<DepthCaptureDriver>();
        }

        void OnDisable() => ReleaseMaterials();

        void ReleaseMaterials()
        {
            foreach (var m in _variants.Values) if (m != null) DestroyImmediate(m);
            _variants.Clear();
            if (_setup != null) DestroyImmediate(_setup);
            if (_gauss != null) DestroyImmediate(_gauss);
            _setup = _gauss = null;
            _built = false;
        }

        Material Build(string shader, params string[] keywords)
        {
            foreach (var p in _resolver.ResolveAll(shader, keywords, null))
            {
                if (p.Entry == null || p.Role != PassRole.Forward) continue;
                var s = Shader.Find(p.Entry.UnityName);
                if (s == null) continue;
                return new Material(s) { hideFlags = HideFlags.HideAndDontSave };
            }
            return null;
        }

        // Variante zur Laufzeit gewählter Keywords (Nebel im Finalize-Durchgang, Farbkorrektur im FXAA-Durchgang): jede Menge ist ein
        // eigener erzeugter Shader (scripts/runtime_variants.json nennt sie für das Strippen).
        Material Variant(string shader, string keyword)
        {
            var key = shader + "|" + keyword;
            if (_variants.TryGetValue(key, out var m)) return m;
            m = Build(shader, keyword);
            _variants[key] = m;
            return m;
        }

        void EnsureMaterials()
        {
            if (_built) return;
            _built = true;
            var idx = Index ?? GeneratedShaderLibrary.LoadIndex(out _);
            if (idx == null) { Status = "keine variants.json"; return; }
            _resolver = new ShaderVariantResolver(idx);
            _setup = Build(BloomSetupShader);
            _gauss = Build(GaussianShader);
            var miss = new List<string>();
            if (_setup == null) miss.Add("Bloom Setup");
            if (_gauss == null) miss.Add("Gaussian7x7");
            if (Variant(BloomFinalizeShader, "_FOGMODE_NONE") == null) miss.Add("Bloom Finalize");
            if (Variant(FxaaShader, "_GRADING_NONE") == null) miss.Add("Fxaa");
            Status = miss.Count == 0 ? "bereit" : "fehlt: " + string.Join(", ", miss);
        }

        // Nebelwerte wie EnvironmentController.OnUpdate -> Bloom.SetFogParameters (Tabellenwerte aus den EnvironmentSettings der Zone).
        Material FinalizeMaterial()
        {
            if (_resolver == null) return null;
            var p = EnableFog && Driver != null ? Driver.State.Current : null;
            var settings = Driver != null ? Driver.Settings : null;
            var mode = p != null && p.FogEnable && settings != null ? settings.FogMode : 0;   // 1 linear, 2 exp, 3 exp2
            var kw = mode == 1 ? "_FOGMODE_LINEAR" : mode == 2 ? "_FOGMODE_EXP" : mode == 3 ? "_FOGMODE_EXP2" : "_FOGMODE_NONE";
            var fin = Variant(BloomFinalizeShader, kw);
            if (fin == null) { mode = 0; fin = Variant(BloomFinalizeShader, "_FOGMODE_NONE"); }
            if (fin == null || mode == 0) return fin;
            var k2 = 1f / Mathf.Max(p.FogEnd - p.FogStart, 0.1f);
            float x = p.FogEnd;
            if (mode != 1) { k2 *= p.FogDensity; x = p.FogStart; }
            fin.SetVector("_FogParam", new Vector4(x, k2, 0f, GetComponent<Camera>().farClipPlane));
            fin.SetColor("_Color", new Color(p.FogNearColor.R, p.FogNearColor.G, p.FogNearColor.B, p.FogNearColor.A));
            fin.SetColor("_FarColor", new Color(p.FogFarColor.R, p.FogFarColor.G, p.FogFarColor.B, p.FogFarColor.A));
            return fin;
        }

        void OnRenderImage(RenderTexture src, RenderTexture dst)
        {
            EnsureMaterials();
            Blits = 0;
            var fin = EnableBloom && _setup != null && _gauss != null ? FinalizeMaterial() : null;
            var bloom = fin != null;
            var fx = EnableFxaa && _resolver != null ? Variant(FxaaShader, "_GRADING_NONE") : null;
            var fxaa = fx != null;
            if (!bloom && !fxaa) { Graphics.Blit(src, dst); return; }

            var current = src;
            RenderTexture bloomOut = null;
            if (bloom)
            {
                var a = new RenderTexture[Layers]; var b = new RenderTexture[Layers];
                for (var i = 0; i < Layers; i++)
                {
                    var w = Mathf.Max(1, src.width >> (i + 2)); var h = Mathf.Max(1, src.height >> (i + 2));
                    a[i] = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGBHalf);
                    b[i] = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGBHalf);
                    a[i].filterMode = FilterMode.Bilinear; b[i].filterMode = FilterMode.Bilinear;
                }
                for (var i = 0; i < Layers; i++)
                {
                    if (i == 0) Graphics.Blit(src, a[0], _setup); else Graphics.Blit(a[i - 1], a[i]);
                    Shader.SetGlobalVector(BlurX, BlurOffset); Shader.SetGlobalVector(BlurY, Vector4.zero);
                    Graphics.Blit(a[i], b[i], _gauss);
                    Shader.SetGlobalVector(BlurX, Vector4.zero); Shader.SetGlobalVector(BlurY, BlurOffset);
                    Graphics.Blit(b[i], a[i], _gauss);
                    Blits += 3;
                }
                for (var i = 0; i < Layers; i++) Shader.SetGlobalTexture(SubTexIds[i], a[i]);
                var noise = Shader.GetGlobalTexture("_NoiseTex");
                if (noise != null) fin.SetTexture("_NoiseTex", noise);
                bloomOut = RenderTexture.GetTemporary(src.width, src.height, 0, RenderTextureFormat.ARGBHalf);
                Graphics.Blit(src, bloomOut, fin);
                Blits++;
                for (var i = 0; i < Layers; i++) { RenderTexture.ReleaseTemporary(a[i]); RenderTexture.ReleaseTemporary(b[i]); }
                current = bloomOut;
            }
            if (fxaa) { Graphics.Blit(current, dst, fx); Blits++; } else Graphics.Blit(current, dst);
            if (bloomOut != null) RenderTexture.ReleaseTemporary(bloomOut);
        }
    }
}
