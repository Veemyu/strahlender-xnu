using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xnu.Render
{
    public sealed class RemapResult
    {
        public MaterialRecord Record;
        public List<PassResolution> Passes = new List<PassResolution>();
        // Sichtbar zu zeichnende Materialien (Forward-Pässe in Passreihenfolge, meist eines).
        public List<Material> Forward = new List<Material>();
        // Material mit dem Schatten-Pass (nur für den Schattenwurf; nie als sichtbares Material zuweisen).
        public Material ShadowCaster;
        // Materialien mit ForwardAdd-Pass (zusätzliche Lichter), ebenfalls nicht sichtbar zuweisen.
        public List<Material> Additional = new List<Material>();
        public List<string> Notes = new List<string>();

        public bool HasForward => Forward.Count > 0;

        // Alle Pässe gefunden und die Forward-Pässe exakt oder nur durch Umgebungs-Lockerung abweichend.
        public bool Complete { get; internal set; }

        public void DestroyAll()
        {
            foreach (var m in Forward) if (m != null) UnityEngine.Object.DestroyImmediate(m);
            foreach (var m in Additional) if (m != null) UnityEngine.Object.DestroyImmediate(m);
            if (ShadowCaster != null) UnityEngine.Object.DestroyImmediate(ShadowCaster);
            Forward.Clear(); Additional.Clear(); ShadowCaster = null;
        }
    }

    // Baut aus einem Bundle-Material (Shader fehlt, Eigenschaften bleiben erhalten) und seinem Exporteintrag
    // das Material mit dem erzeugten Shader (docs/material-remap.md). Originalshader werden nie geladen.
    public sealed class MaterialRemapper
    {
        readonly ShaderVariantResolver _resolver;
        readonly Func<string, Shader> _find;
        readonly Func<MaterialTextureRef, Texture> _textures;

        public MaterialRemapper(ShaderVariantResolver resolver, Func<string, Shader> shaderLookup = null,
            Func<MaterialTextureRef, Texture> textureLookup = null)
        {
            _resolver = resolver ?? throw new ArgumentNullException(nameof(resolver));
            _find = shaderLookup ?? Shader.Find;
            _textures = textureLookup;
        }

        // source darf null sein (Material nicht geladen): dann kommen alle Werte aus dem Export.
        public RemapResult Remap(Material source, MaterialRecord rec, RenderEnvironment env = null)
        {
            var res = new RemapResult { Record = rec };
            if (rec == null) { res.Notes.Add("kein Exporteintrag"); return res; }
            if (string.IsNullOrEmpty(rec.Shader)) { res.Notes.Add("Shadername nicht aufgelöst"); return res; }
            res.Passes = _resolver.ResolveAll(rec.Shader, rec.Keywords, env);
            if (res.Passes.Count == 0) { res.Notes.Add("keine erzeugte Variante für " + rec.Shader); return res; }

            var complete = true;
            foreach (var p in res.Passes)
            {
                if (p.Entry == null) { complete = false; res.Notes.Add("Pass " + p.Pass + ": keine Variante"); continue; }
                var shader = _find(p.Entry.UnityName);
                if (shader == null) { complete = false; res.Notes.Add("Pass " + p.Pass + ": Shader fehlt: " + p.Entry.UnityName); continue; }
                var m = Build(source, rec, shader, p);
                if (p.Role == PassRole.Forward) res.Forward.Add(m);
                else if (p.Role == PassRole.ShadowCaster) res.ShadowCaster = m;
                else res.Additional.Add(m);
                if (p.Role == PassRole.Forward && p.Quality == ResolveQuality.Nearest) complete = false;
            }
            res.Complete = complete && res.Forward.Count > 0;
            return res;
        }

        Material Build(Material source, MaterialRecord rec, Shader shader, PassResolution pass)
        {
            // Kopie behält die gespeicherten Eigenschaften (auch ohne passenden Shader); danach Shader tauschen.
            var m = source != null ? new Material(source) : new Material(shader);
            m.shader = shader;
            m.name = (source != null ? source.name : rec.Name) + (pass.Role == PassRole.ShadowCaster ? "#shadow" : "#p" + pass.Pass);
            m.hideFlags = HideFlags.HideAndDontSave;
            // Mit Quelle (geladenes Bundle-Material) gelten deren gespeicherte Werte: der Export unterscheidet doppelte
            // Materialnamen nicht sicher. Ohne Quelle kommen alle Werte aus dem Export.
            if (source == null)
            {
                ApplyRecord(m, rec, true);
                if (rec.RenderQueue >= 0) m.renderQueue = rec.RenderQueue;
            }
            m.enableInstancing = Array.IndexOf(pass.Entry.Keywords, "INSTANCING_ON") >= 0;
            foreach (var t in rec.Tags) m.SetOverrideTag(t.Key, t.Value);
            return m;
        }

        // Der Export führt manchmal denselben Namen als Float und als Farbe (veralteter Eintrag eines früheren Shaders);
        // maßgeblich ist der Typ, den der Zielshader deklariert.
        static bool IsScalar(Material m, string name)
        {
            var i = m.shader.FindPropertyIndex(name);
            if (i < 0) return false;
            var t = m.shader.GetPropertyType(i);
            return t == UnityEngine.Rendering.ShaderPropertyType.Float || t == UnityEngine.Rendering.ShaderPropertyType.Range;
        }

        static bool IsVector(Material m, string name)
        {
            var i = m.shader.FindPropertyIndex(name);
            if (i < 0) return false;
            var t = m.shader.GetPropertyType(i);
            return t == UnityEngine.Rendering.ShaderPropertyType.Color || t == UnityEngine.Rendering.ShaderPropertyType.Vector;
        }

        // Schreibt Floats, Farben, Kachelung/Versatz (immer) und Texturen (nur wenn leer oder allowTextureOverwrite)
        // aus dem Exporteintrag. Nur Eigenschaften, die der Zielshader mit passendem Typ hat.
        public void ApplyRecord(Material m, MaterialRecord rec, bool allowTextureOverwrite)
        {
            foreach (var kv in rec.Floats) if (IsScalar(m, kv.Key)) m.SetFloat(kv.Key, kv.Value);
            foreach (var kv in rec.Colors)
                if (IsVector(m, kv.Key) && kv.Value.Length == 4)
                    m.SetVector(kv.Key, new Vector4(kv.Value[0], kv.Value[1], kv.Value[2], kv.Value[3]));
            foreach (var kv in rec.Textures)
            {
                var t = kv.Value;
                if (!m.HasProperty(kv.Key)) continue;
                m.SetTextureScale(kv.Key, new Vector2(t.ScaleX, t.ScaleY));
                m.SetTextureOffset(kv.Key, new Vector2(t.OffsetX, t.OffsetY));
                if (t.IsNull || _textures == null) continue;
                if (allowTextureOverwrite || m.GetTexture(kv.Key) == null)
                {
                    var tex = _textures(t);
                    if (tex != null) m.SetTexture(kv.Key, tex);
                }
            }
        }

        // Vergleicht ein Material mit dem Exporteintrag (nur Eigenschaften des Shaders); leere Liste = alles gleich.
        public static List<string> Verify(Material m, MaterialRecord rec)
        {
            var bad = new List<string>();
            foreach (var kv in rec.Floats)
                if (IsScalar(m, kv.Key) && Math.Abs(m.GetFloat(kv.Key) - kv.Value) > 1e-6f) bad.Add("float " + kv.Key);
            foreach (var kv in rec.Colors)
            {
                if (!IsVector(m, kv.Key)) continue;
                var v = m.GetVector(kv.Key);
                if (Math.Abs(v.x - kv.Value[0]) > 1e-6f || Math.Abs(v.y - kv.Value[1]) > 1e-6f ||
                    Math.Abs(v.z - kv.Value[2]) > 1e-6f || Math.Abs(v.w - kv.Value[3]) > 1e-6f) bad.Add("color " + kv.Key);
            }
            foreach (var kv in rec.Textures)
            {
                if (!m.HasProperty(kv.Key)) continue;
                var tex = m.GetTexture(kv.Key);
                if (kv.Value.IsNull != (tex == null)) bad.Add("texture " + kv.Key + (tex == null ? " fehlt" : " unerwartet"));
                else if (!kv.Value.IsNull && kv.Value.TextureName != null && tex.name != kv.Value.TextureName) bad.Add("texture " + kv.Key + " Name");
                var s = m.GetTextureScale(kv.Key);
                var o = m.GetTextureOffset(kv.Key);
                if (Math.Abs(s.x - kv.Value.ScaleX) > 1e-6f || Math.Abs(s.y - kv.Value.ScaleY) > 1e-6f ||
                    Math.Abs(o.x - kv.Value.OffsetX) > 1e-6f || Math.Abs(o.y - kv.Value.OffsetY) > 1e-6f) bad.Add("tiling " + kv.Key);
            }
            return bad;
        }
    }
}
