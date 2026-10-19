using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Data;
using Xnu.Render;

namespace Xnu.Tests
{
    // Variantenwahl, Variantenverzeichnis, Materialexport und Spiel-Globals mit synthetischen Daten (keine Spieldaten).
    public class RenderRemapTests
    {
        static ShaderVariantIndex FixtureIndex(out Dictionary<string, object> root)
        {
            root = BattleFixtures.Load("variant_resolution_cases.json");
            // Dieselbe Datei wie in scripts/tests/test_material_variants.py.
            var json = System.IO.File.ReadAllText(System.IO.Path.Combine(BattleFixtures.Dir(), "variant_resolution_cases.json"));
            return ShaderVariantIndex.FromJson(json, "T/");
        }

        static string[] Strs(object o) => ((List<object>)o).Select(x => (string)x).ToArray();

        [Test]
        public void SharedCases_AgreeWithReference()
        {
            var idx = FixtureIndex(out var root);
            var resolver = new ShaderVariantResolver(idx);
            foreach (Dictionary<string, object> c in (List<object>)root["cases"])
            {
                var env = new RenderEnvironment { Instancing = (bool)c["instancing"] };
                var r = resolver.Resolve((string)c["shader"], Convert.ToInt32(c["pass"]), Strs(c["keywords"]), env);
                var e = (Dictionary<string, object>)c["expect"];
                var name = (string)c["name"];
                var file = e["file"] as string;
                Assert.AreEqual(file == null ? null : "T/" + file.Replace(".shader", ""), r.Entry?.UnityName, name);
                var q = (string)e["quality"];
                var want = q == "exact" ? ResolveQuality.Exact : q == "relaxed" ? ResolveQuality.EnvironmentRelaxed
                    : q == "nearest" ? ResolveQuality.Nearest : ResolveQuality.Unavailable;
                Assert.AreEqual(want, r.Quality, name);
                if (e.ContainsKey("role"))
                {
                    var role = (string)e["role"];
                    Assert.AreEqual(role == "shadow" ? PassRole.ShadowCaster : role == "add" ? PassRole.ForwardAdd : PassRole.Forward, r.Role, name);
                }
                if (e.ContainsKey("ignored")) CollectionAssert.AreEqual(Strs(e["ignored"]), r.IgnoredMaterialKeywords, name);
                if (e.ContainsKey("missing")) CollectionAssert.AreEqual(Strs(e["missing"]), r.MissingKeywords, name);
            }
        }

        [Test]
        public void Index_SkipsFailedAndOtherSubShaders()
        {
            var idx = FixtureIndex(out _);
            Assert.IsTrue(idx.HasShader("Test/Lit"));
            Assert.IsFalse(idx.HasShader("Test/Broken"));
            Assert.IsFalse(idx.HasShader("Test/Sub1"));
            Assert.AreEqual(12, idx.Count);
            CollectionAssert.AreEqual(new[] { 0, 1 }, idx.Passes("Test/Lit").ToArray());
        }

        [Test]
        public void ResolveAll_ListsEveryPassWithRole()
        {
            var resolver = new ShaderVariantResolver(FixtureIndex(out _));
            var all = resolver.ResolveAll("Test/Lit", new string[0]);
            Assert.AreEqual(2, all.Count);
            Assert.AreEqual(PassRole.Forward, all[0].Role);
            Assert.AreEqual(PassRole.ShadowCaster, all[1].Role);
            Assert.AreEqual(0, resolver.ResolveAll("Unbekannt/Shader", new string[0]).Count);
        }

        [Test]
        public void Resolve_IsDeterministicAndIgnoresKeywordOrder()
        {
            var resolver = new ShaderVariantResolver(FixtureIndex(out _));
            var a = resolver.Resolve("Test/Lit", 0, new[] { "_ALPHATEST_ON", "_CASCADE_MULTI" });
            var b = resolver.Resolve("Test/Lit", 0, new[] { "_CASCADE_MULTI", "_ALPHATEST_ON" });
            Assert.AreEqual(a.Entry.UnityName, b.Entry.UnityName);
            Assert.AreEqual(ResolveQuality.Nearest, a.Quality);
        }

        [Test]
        public void Resolve_NullKeywordsAreEmpty()
        {
            var resolver = new ShaderVariantResolver(FixtureIndex(out _));
            Assert.AreEqual(ResolveQuality.Exact, resolver.Resolve("Test/Lit", 0, null).Quality);
        }

        const string MaterialJson = @"{""format"":1,""bundle"":""Test/b"",""materials"":[
 {""name"":""M1"",""pathId"":5,""shader"":""Test/Lit"",""keywords"":[""_B"",""_A""],""renderQueue"":2450,""instancing"":true,
  ""tags"":{""RenderType"":""Opaque""},""disabledPasses"":[],""floats"":{""_Cutoff"":0.25},""ints"":{},
  ""colors"":{""_Color"":[1.0,0.5,0.25,1.0]},
  ""textures"":{""_MainTex"":{""file"":0,""pathId"":7,""texName"":""T_X"",""width"":64,""height"":32,""format"":12,""scale"":[2.0,3.0],""offset"":[0.5,0.0]},
                ""_BumpTex"":{""scale"":[1.0,1.0],""offset"":[0.0,0.0]}}},
 {""name"":""M2"",""pathId"":6,""shader"":""Test/Lit"",""keywords"":[""_A""],""renderQueue"":-1,""floats"":{},""colors"":{},""textures"":{}},
 {""name"":""M2"",""pathId"":8,""shader"":""Test/Lit"",""keywords"":[""_C""],""renderQueue"":-1,""floats"":{},""colors"":{},""textures"":{}},
 {""error"":""x"",""pathId"":9}]}";

        [Test]
        public void Catalog_ParsesExport()
        {
            var cat = new MaterialCatalog();
            cat.LoadJson(MaterialJson);
            Assert.AreEqual(3, cat.Count);
            Assert.AreEqual(1, cat.Duplicates);
            var m = cat.Find("Test/b", "M1");
            Assert.AreEqual("Test/Lit", m.Shader);
            CollectionAssert.AreEqual(new[] { "_A", "_B" }, m.Keywords);
            Assert.AreEqual(2450, m.RenderQueue);
            Assert.IsTrue(m.Instancing);
            Assert.AreEqual(0.25f, m.Floats["_Cutoff"]);
            CollectionAssert.AreEqual(new[] { 1f, 0.5f, 0.25f, 1f }, m.Colors["_Color"]);
            var t = m.Textures["_MainTex"];
            Assert.IsFalse(t.IsNull);
            Assert.AreEqual("T_X", t.TextureName);
            Assert.AreEqual(64, t.Width);
            Assert.AreEqual(2f, t.ScaleX);
            Assert.AreEqual(0.5f, t.OffsetX);
            Assert.IsTrue(m.Textures["_BumpTex"].IsNull);
            Assert.AreEqual("Opaque", m.Tags["RenderType"]);
        }

        [Test]
        public void Catalog_DuplicateNamesChooseByKeywords()
        {
            var cat = new MaterialCatalog();
            cat.LoadJson(MaterialJson);
            Assert.AreEqual(6, cat.Find("Test/b", "M2", new[] { "_A" }).PathId);
            Assert.AreEqual(8, cat.Find("Test/b", "M2", new[] { "_C" }).PathId);
            Assert.AreEqual(6, cat.Find("Test/b", "M2").PathId);
            Assert.AreEqual(6, cat.Find("Test/b", "M2", new[] { "_Z" }).PathId);
            Assert.IsNull(cat.Find("Test/b", "Gibtsnicht"));
            Assert.IsNull(cat.Find("Test/anders", "M1"));
        }

        sealed class FakeSink : IGlobalSink
        {
            public readonly Dictionary<string, object> Values = new Dictionary<string, object>();
            public void SetFloat(string name, float value) => Values[name] = value;
            public void SetVector(string name, float x, float y, float z, float w) => Values[name] = new[] { x, y, z, w };
            public void SetMatrix(string name, float[] m) => Values[name] = m;
            public void SetTexture(string name, object texture) => Values[name] = texture;
        }

        [Test]
        public void GameGlobals_SpecIsComplete()
        {
            Assert.AreEqual(35, GameGlobals.Specs.Count);
            Assert.AreEqual(35, GameGlobals.Specs.Select(s => s.Name).Distinct().Count());
            foreach (var n in new[] { "_CloudParam", "_PokeLightColor", "_PokeReflectorColor", "_CharacterLightColor", "_ReflectionVP", "_EnvMatrix", "_CloudShadowTex" })
                Assert.IsTrue(GameGlobals.IsGameGlobal(n), n);
            Assert.IsFalse(GameGlobals.IsGameGlobal("_Time"));
            Assert.IsFalse(GameGlobals.IsGameGlobal("unity_ObjectToWorld"));
            Assert.AreEqual(GlobalKind.Matrix, GameGlobals.Specs.First(s => s.Name == "_ReflectionVP").Kind);
        }

        [Test]
        public void GameGlobals_SetForwardsToSinkAndChecksKind()
        {
            var sink = new FakeSink();
            var g = new GameGlobals(sink);
            g.SetVector("_CloudParam", 1, 2, 3, 4);
            g.SetFloat("_GlobalLightPower", 0.5f);
            g.SetMatrix("_EnvMatrix", GameGlobals.Identity());
            var tex = new object();
            g.SetTexture("_CloudShadowTex", tex);
            CollectionAssert.AreEqual(new[] { 1f, 2f, 3f, 4f }, (float[])sink.Values["_CloudParam"]);
            Assert.AreEqual(0.5f, (float)sink.Values["_GlobalLightPower"]);
            Assert.AreSame(tex, sink.Values["_CloudShadowTex"]);
            Assert.AreEqual(4, g.CountSet);
            Assert.Throws<ArgumentException>(() => g.SetFloat("_CloudParam", 1));
            Assert.Throws<ArgumentException>(() => g.SetVector("_Time", 0, 0, 0, 0));
            Assert.Throws<ArgumentException>(() => g.SetMatrix("_EnvMatrix", new float[3]));
        }

        [Test]
        public void GameGlobals_DefaultsCoverEverythingExceptTextures()
        {
            var sink = new FakeSink();
            var g = new GameGlobals(sink);
            g.SetDefaults();
            var textures = GameGlobals.Specs.Where(s => s.Kind == GlobalKind.Texture).Select(s => s.Name).OrderBy(x => x).ToArray();
            CollectionAssert.AreEqual(textures, g.Unset.OrderBy(x => x).ToArray());
            Assert.AreEqual(GameGlobals.Specs.Count - textures.Length, sink.Values.Count);
            Assert.AreEqual(0f, (float)sink.Values["_GlobalLightPower"]);   // wie das Original im Ruhezustand: 1 − 1
            CollectionAssert.AreEqual(GameGlobals.Identity(), (float[])sink.Values["_ReflectionVP"]);
        }

        [Test]
        public void Environment_DefaultsAndInstancing()
        {
            var env = RenderEnvironment.Default;
            Assert.IsFalse(env.Instancing);
            CollectionAssert.AreEqual(new[] { "DIRECTIONAL", "SHADOWS_SCREEN" }, env.Forward);
            CollectionAssert.AreEqual(new[] { "SHADOWS_DEPTH" }, env.ShadowCaster);
        }
    }
}
