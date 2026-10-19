using System.Collections.Generic;
using UnityEngine;

namespace Xnu.Field
{
    // Eigenschaften eines Original-Materials, soweit ohne dessen Shader lesbar (Haupttextur, Farbe, Queue).
    public struct OriginalMaterialInfo
    {
        public Texture MainTexture;
        public Vector2 TextureScale;
        public Vector2 TextureOffset;
        public Color Color;
        public int CustomRenderQueue;   // -1 = Shader-Standard
        public bool Valid;

        // Liest die gespeicherten Eigenschaften direkt aus den serialisierten Daten. Die Material-API
        // (shader, GetTexture, HasProperty ...) wird bewusst NICHT benutzt: Mit geladenem Original-Shader
        // (Switch-Binärcode) stürzt der Editor dabei ab. Nur im Editor verfügbar; im Player bleibt Valid = false.
        public static OriginalMaterialInfo Read(Material material)
        {
            var info = new OriginalMaterialInfo { Color = Color.white, TextureScale = Vector2.one, CustomRenderQueue = -1 };
#if UNITY_EDITOR
            if (material == null) return info;
            using (var so = new UnityEditor.SerializedObject(material))
            {
                var q = so.FindProperty("m_CustomRenderQueue");
                if (q != null) info.CustomRenderQueue = q.intValue;
                var envs = so.FindProperty("m_SavedProperties.m_TexEnvs");
                for (var i = 0; envs != null && i < envs.arraySize; i++)
                {
                    var e = envs.GetArrayElementAtIndex(i);
                    if (e.FindPropertyRelative("first").stringValue != "_MainTex") continue;
                    info.MainTexture = e.FindPropertyRelative("second.m_Texture").objectReferenceValue as Texture;
                    info.TextureScale = e.FindPropertyRelative("second.m_Scale").vector2Value;
                    info.TextureOffset = e.FindPropertyRelative("second.m_Offset").vector2Value;
                }
                var cols = so.FindProperty("m_SavedProperties.m_Colors");
                for (var i = 0; cols != null && i < cols.arraySize; i++)
                {
                    var e = cols.GetArrayElementAtIndex(i);
                    if (e.FindPropertyRelative("first").stringValue == "_Color") info.Color = e.FindPropertyRelative("second").colorValue;
                }
                info.Valid = true;
            }
#endif
            return info;
        }
    }

    // Material-Ersatz beim Laden: Für jedes Original-Material entsteht (einmalig) ein Material mit dem eigenen
    // Unlit-Shader. Die Originalmaterialien werden nie zugewiesen oder gerendert.
    public sealed class FallbackMaterials : IMapMaterialSource
    {
        public const string ShaderResource = "XnuFieldFallbackUnlit";
        public const string ShaderName = "Xnu/FieldFallbackUnlit";

        readonly Shader _shader;
        readonly Dictionary<int, Material> _cache = new Dictionary<int, Material>();
        readonly HashSet<int> _textureIds = new HashSet<int>();
        Material _missing;

        public int MaterialsCreated => _cache.Count;
        public int UniqueTextures => _textureIds.Count;
        public int WithoutTexture { get; private set; }
        public int CutoutCount { get; private set; }

        public FallbackMaterials()
        {
            _shader = Resources.Load<Shader>(ShaderResource);
            if (_shader == null) _shader = Shader.Find(ShaderName);
            if (_shader == null) throw new System.InvalidOperationException("Fallback-Shader fehlt: " + ShaderName);
        }

        public Shader Shader => _shader;

        public bool IsFallback(Material m) => m != null && m.shader == _shader;

        public bool IsAllowed(Material m) => IsFallback(m);

        // Ersatzmaterial für ein Original (null liefert ein graues Platzhaltermaterial).
        public Material For(Material original)
        {
            if (original == null) return Missing();
            var id = original.GetInstanceID();
            if (_cache.TryGetValue(id, out var m)) return m;

            var info = OriginalMaterialInfo.Read(original);
            m = new Material(_shader) { name = "Fallback_" + original.name, hideFlags = HideFlags.HideAndDontSave };
            m.color = info.Valid ? info.Color : new Color(0.7f, 0.7f, 0.7f, 1f);
            if (info.MainTexture != null)
            {
                m.mainTexture = info.MainTexture;
                m.mainTextureScale = info.TextureScale;
                m.mainTextureOffset = info.TextureOffset;
                _textureIds.Add(info.MainTexture.GetInstanceID());
                // Alpha-Test nur bei Materialien in der Cutout-/Transparent-Queue und Texturen mit Alphakanal.
                if (info.CustomRenderQueue >= 2450 && info.MainTexture is Texture2D t2
                    && UnityEngine.Experimental.Rendering.GraphicsFormatUtility.HasAlphaChannel(t2.graphicsFormat))
                {
                    m.SetFloat("_Cutoff", 0.5f);
                    CutoutCount++;
                }
            }
            else WithoutTexture++;
            _cache[id] = m;
            return m;
        }

        Material Missing()
        {
            if (_missing == null)
                _missing = new Material(_shader) { name = "Fallback_Missing", color = new Color(0.7f, 0.7f, 0.7f, 1f), hideFlags = HideFlags.HideAndDontSave };
            return _missing;
        }

        public void Destroy()
        {
            foreach (var m in _cache.Values) if (m != null) Object.DestroyImmediate(m);
            _cache.Clear();
            if (_missing != null) Object.DestroyImmediate(_missing);
            _missing = null;
        }
    }
}
