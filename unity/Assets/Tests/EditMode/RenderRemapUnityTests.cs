using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using Xnu.Render;

namespace Xnu.Tests
{
    // Unity-gebundener Teil: Material-Umbau und Spiel-Globals mit eingebautem Shader als Stellvertreter (keine Spieldaten).
    public class RenderRemapUnityTests
    {
        const string Stand = "Sprites/Default"; // hat _MainTex, _Color, _EnableExternalAlpha

        static ShaderVariantIndex Index()
        {
            var json = System.IO.File.ReadAllText(System.IO.Path.Combine(BattleFixtures.Dir(), "variant_resolution_cases.json"));
            return ShaderVariantIndex.FromJson(json, "T/");
        }

        static MaterialRecord Record()
        {
            var r = new MaterialRecord { Bundle = "Test/b", Name = "M", Shader = "Test/Lit", Keywords = new[] { "_ALPHATEST_ON" }, RenderQueue = 2450 };
            r.Floats["_EnableExternalAlpha"] = 1f;
            r.Floats["_Color"] = 0.1f; // veralteter Float-Eintrag neben der Farbe: maßgeblich ist der Typ im Shader
            r.Colors["_Color"] = new[] { 0.25f, 0.5f, 0.75f, 1f };
            r.Colors["_NichtImShader"] = new[] { 1f, 1f, 1f, 1f };
            r.Tags["RenderType"] = "TransparentCutout";
            r.Textures["_MainTex"] = new MaterialTextureRef { Property = "_MainTex", TextureName = "T_X", ScaleX = 2, ScaleY = 3, OffsetX = 0.5f };
            return r;
        }

        MaterialRemapper Remapper(System.Func<MaterialTextureRef, Texture> tex = null) =>
            new MaterialRemapper(new ShaderVariantResolver(Index()), n => Shader.Find(Stand), tex);

        readonly List<Object> _garbage = new List<Object>();

        [TearDown]
        public void Cleanup()
        {
            foreach (var o in _garbage) if (o != null) Object.DestroyImmediate(o);
            _garbage.Clear();
        }

        [Test]
        public void Remap_WithoutSource_AppliesRecord()
        {
            Assert.IsNotNull(Shader.Find(Stand), "Stellvertreter-Shader fehlt");
            var tex = new Texture2D(2, 2) { name = "T_X" };
            _garbage.Add(tex);
            var res = Remapper(t => tex).Remap(null, Record());
            _garbage.AddRange(res.Forward);
            if (res.ShadowCaster != null) _garbage.Add(res.ShadowCaster);
            Assert.AreEqual(1, res.Forward.Count);
            Assert.IsNotNull(res.ShadowCaster);
            Assert.IsTrue(res.Complete, string.Join("; ", res.Notes));
            var m = res.Forward[0];
            Assert.AreEqual(2450, m.renderQueue);
            Assert.AreEqual(1f, m.GetFloat("_EnableExternalAlpha"));
            Assert.AreEqual(0.75f, m.GetVector("_Color").z, 1e-6f);
            Assert.AreSame(tex, m.GetTexture("_MainTex"));
            Assert.AreEqual(new Vector2(2, 3), m.GetTextureScale("_MainTex"));
            Assert.AreEqual(0.5f, m.GetTextureOffset("_MainTex").x, 1e-6f);
            Assert.AreEqual("TransparentCutout", m.GetTag("RenderType", false));
            Assert.IsFalse(m.enableInstancing);
            CollectionAssert.IsEmpty(MaterialRemapper.Verify(m, Record()));
        }

        [Test]
        public void Remap_WithSource_KeepsStoredValues()
        {
            var src = new Material(Shader.Find(Stand)) { name = "Quelle" };
            src.SetColor("_Color", Color.red);
            src.SetFloat("_EnableExternalAlpha", 0f);
            _garbage.Add(src);
            var rec = Record();
            var res = Remapper().Remap(src, rec);
            _garbage.AddRange(res.Forward);
            if (res.ShadowCaster != null) _garbage.Add(res.ShadowCaster);
            var m = res.Forward[0];
            Assert.AreEqual(Color.red, m.GetColor("_Color"));        // gespeicherter Wert der Quelle gewinnt
            Assert.AreEqual(0f, m.GetFloat("_EnableExternalAlpha")); // auch gegen den Export (doppelte Namen)
            Assert.AreEqual(src.renderQueue, m.renderQueue);
            Assert.AreEqual("Quelle#p0", m.name);
            Assert.AreNotSame(src, m);
        }

        [Test]
        public void Remap_InstancingVariantEnablesInstancing()
        {
            var rec = Record();
            rec.Keywords = new string[0];
            var res = Remapper().Remap(null, rec, new RenderEnvironment { Instancing = true });
            _garbage.AddRange(res.Forward);
            if (res.ShadowCaster != null) _garbage.Add(res.ShadowCaster);
            Assert.IsTrue(res.Forward[0].enableInstancing);
        }

        [Test]
        public void Remap_MissingShaderOrRecord_ReportsAndReturnsNothing()
        {
            var none = new MaterialRemapper(new ShaderVariantResolver(Index()), n => null);
            var r1 = none.Remap(null, Record());
            Assert.IsFalse(r1.HasForward);
            Assert.IsFalse(r1.Complete);
            Assert.IsTrue(r1.Notes.Any(n => n.Contains("Shader fehlt")));
            Assert.IsFalse(Remapper().Remap(null, null).HasForward);
            var unknown = Record(); unknown.Shader = "Unbekannt/Shader";
            var r2 = Remapper().Remap(null, unknown);
            Assert.IsFalse(r2.HasForward);
            Assert.IsTrue(r2.Notes.Count > 0);
            var noName = Record(); noName.Shader = null;
            Assert.IsFalse(Remapper().Remap(null, noName).HasForward);
        }

        [Test]
        public void Remap_NearestVariantIsNotComplete()
        {
            var rec = Record();
            rec.Keywords = new[] { "_ALPHATEST_ON", "_CASCADE_MULTI" };
            var res = Remapper().Remap(null, rec);
            _garbage.AddRange(res.Forward);
            if (res.ShadowCaster != null) _garbage.Add(res.ShadowCaster);
            Assert.IsTrue(res.HasForward);
            Assert.IsFalse(res.Complete);
        }

        [Test]
        public void TextureIndex_FindsByNameAndSize()
        {
            var a = new Texture2D(4, 4) { name = "T_A" };
            var b = new Texture2D(8, 4) { name = "T_A" };
            _garbage.Add(a); _garbage.Add(b);
            var idx = new LoadedTextureIndex();
            idx.Add(a); idx.Add(b); idx.Add(null);
            Assert.AreEqual(2, idx.Count);
            Assert.AreSame(a, idx.Find(new MaterialTextureRef { TextureName = "T_A", Width = 4, Height = 4 }));
            Assert.AreSame(b, idx.Find(new MaterialTextureRef { TextureName = "T_A", Width = 8, Height = 4 }));
            Assert.IsNull(idx.Find(new MaterialTextureRef { TextureName = "T_A", Width = 2, Height = 2 }));
            Assert.IsNull(idx.Find(new MaterialTextureRef { IsNull = true }));
            Assert.AreEqual(2, idx.Misses);
        }

        [Test]
        public void GameGlobals_UnitySinkRoundTrip()
        {
            var g = new GameGlobals(new UnityGlobalSink());
            g.SetVector("_CloudParam", 1, 2, 3, 4);
            g.SetFloat("_GlobalLightPower", 0.75f);
            var m = new float[16]; for (var i = 0; i < 16; i++) m[i] = i;
            g.SetMatrix("_ReflectionVP", m);
            Assert.AreEqual(new Vector4(1, 2, 3, 4), Shader.GetGlobalVector("_CloudParam"));
            Assert.AreEqual(0.75f, Shader.GetGlobalFloat("_GlobalLightPower"));
            var got = Shader.GetGlobalMatrix("_ReflectionVP");
            Assert.AreEqual(6f, got[1, 2]);
            Assert.AreEqual(12f, got[3, 0]);
            var t = new Texture2D(1, 1); _garbage.Add(t);
            g.SetTexture("_CloudShadowTex", t);
            Assert.AreSame(t, Shader.GetGlobalTexture("_CloudShadowTex"));
        }

        [Test]
        public void GameGlobals_UnitySinkMapsDefaultTextureTokens()
        {
            var g = new GameGlobals(new UnityGlobalSink());
            g.SetTexture("_NoiseTex", DefaultTextures.Gray);
            g.SetTexture("_SnowNormalTex", DefaultTextures.Bump);
            g.SetTexture("_CloudShadowTex", DefaultTextures.Black);
            Assert.AreSame(Texture2D.grayTexture, Shader.GetGlobalTexture("_NoiseTex"));
            Assert.AreSame(Texture2D.normalTexture, Shader.GetGlobalTexture("_SnowNormalTex"));
            Assert.AreSame(Texture2D.blackTexture, Shader.GetGlobalTexture("_CloudShadowTex"));
        }
    }
}
