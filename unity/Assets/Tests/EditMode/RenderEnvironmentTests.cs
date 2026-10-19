using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Render;

namespace Xnu.Tests
{
    // Tageszeit, Umgebungslicht und Herkunft der Spiel-Globals mit synthetischen Werten (keine Spieldaten).
    public class RenderEnvironmentTests
    {
        sealed class EnvSink : IGlobalSink
        {
            public readonly Dictionary<string, object> V = new Dictionary<string, object>();
            public void SetFloat(string n, float v) => V[n] = v;
            public void SetVector(string n, float x, float y, float z, float w) => V[n] = new[] { x, y, z, w };
            public void SetMatrix(string n, float[] m) => V[n] = m;
            public void SetTexture(string n, object t) => V[n] = t;
            public float[] Vec(string n) => (float[])V[n];
            public float Flt(string n) => (float)V[n];
        }

        static EnvironmentParameters P(float seed, float yaw = 0)
        {
            Rgba C(float k) => new Rgba(seed * k, seed * k + 1, seed * k + 2, 1);
            return new EnvironmentParameters
            {
                LightYaw = yaw, LightPitch = seed, LightColor = C(1), LightIntensity = seed, ReflectorColor = C(2),
                CharacterLightColor = C(3), CharacterLightIntensity = seed + 1, CharacterReflectorColor = C(4),
                PokeLightColor = C(5), PokeLightIntensity = seed + 2, PokeReflectorColor = C(6),
                VertexColorScale = seed, BloomThreshold = seed, ShadowColor = C(7), CloudShadowScale = seed, Blurry = seed,
            };
        }

        static EnvironmentSettingsData Settings()
        {
            var s = new EnvironmentSettingsData { Name = "T", CloudShadowEnable = true };
            for (var i = 0; i < 5; i++) s.Periods[i] = P(10 * (i + 1));
            return s;
        }

        [Test]
        public void Period_Boundaries()
        {
            Assert.AreEqual(PeriodOfDay.Night, TimeOfDay.CurrentPeriod(0f));
            Assert.AreEqual(PeriodOfDay.Night, TimeOfDay.CurrentPeriod(1.99f));
            Assert.AreEqual(PeriodOfDay.Midnight, TimeOfDay.CurrentPeriod(2f));
            Assert.AreEqual(PeriodOfDay.Morning, TimeOfDay.CurrentPeriod(4f));
            Assert.AreEqual(PeriodOfDay.Daytime, TimeOfDay.CurrentPeriod(10f));
            Assert.AreEqual(PeriodOfDay.Evening, TimeOfDay.CurrentPeriod(17f));
            Assert.AreEqual(PeriodOfDay.Night, TimeOfDay.CurrentPeriod(20f));
            Assert.AreEqual(PeriodOfDay.Night, TimeOfDay.CurrentPeriod(23.9f));
        }

        [Test]
        public void PeriodEx_WeightRisesOnlyInLastTenMinutes()
        {
            var (p0, pr0, w0) = TimeOfDay.CurrentPeriodEx(4f);
            Assert.AreEqual(PeriodOfDay.Morning, p0);
            Assert.AreEqual(0f, pr0, 1e-6f);
            Assert.AreEqual(0f, w0);
            Assert.AreEqual(0f, TimeOfDay.CurrentPeriodEx(9.8f).weight);            // 20 min vor dem Ende
            var (_, _, wMid) = TimeOfDay.CurrentPeriodEx(10f - 5f / 60f);           // 5 min vor dem Ende
            Assert.AreEqual(0.5f, wMid, 1e-3f);
            Assert.AreEqual(1f, TimeOfDay.CurrentPeriodEx(10f - 1e-4f).weight, 1e-2f);
            Assert.AreEqual(0f, TimeOfDay.CurrentPeriodEx(10f).weight);
            // Mitternacht dauert zwei Stunden, Abend drei, Tag sieben
            Assert.AreEqual(0.5f, TimeOfDay.CurrentPeriodEx(4f - 5f / 60f).weight, 1e-3f);
            Assert.AreEqual(0.5f, TimeOfDay.CurrentPeriodEx(20f - 5f / 60f).weight, 1e-3f);
            Assert.AreEqual(0.5f, TimeOfDay.CurrentPeriodEx(17f - 5f / 60f).weight, 1e-3f);
            // Nacht über Mitternacht: 20..24 und 0..2 sind ein Abschnitt (6 Stunden)
            Assert.AreEqual(PeriodOfDay.Night, TimeOfDay.CurrentPeriodEx(22f).period);
            Assert.AreEqual(5f / 6f, TimeOfDay.CurrentPeriodEx(1f).progress, 1e-5f);
            Assert.AreEqual(0.5f, TimeOfDay.CurrentPeriodEx(2f - 5f / 60f).weight, 1e-3f);
        }

        [Test]
        public void ElapsedHours_FromTicks()
        {
            const long day = TimeOfDay.TicksPerDay;
            Assert.AreEqual(6f, TimeOfDay.ElapsedHours(day / 4, 0, 1), 1e-4f);
            Assert.AreEqual(18f, TimeOfDay.ElapsedHours(day / 4, day / 2, 1), 1e-4f);      // Versatz
            Assert.AreEqual(12f, TimeOfDay.ElapsedHours(day / 4, 0, 2), 1e-4f);            // Zeitraffer
            Assert.AreEqual(6f, TimeOfDay.ElapsedHours(3 * day + day / 4, 0, 1), 1e-4f);   // mehrere Tage
        }

        [Test]
        public void Transition_EndsAndMidpoint()
        {
            var s = Settings();
            Assert.AreSame(s.Periods[1], s.GetTransition(PeriodOfDay.Daytime, 0f));
            Assert.AreSame(s.Periods[2], s.GetTransition(PeriodOfDay.Daytime, 1f));
            Assert.AreSame(s.Periods[0], s.GetTransition(PeriodOfDay.Midnight, 1f));        // Mitternacht → Morgen (Ring)
            var m = s.GetTransition(PeriodOfDay.Daytime, 0.5f);
            Assert.AreEqual(25f, m.LightIntensity, 1e-4f);
            Assert.AreEqual(25f, m.LightColor.R, 1e-4f);
            Assert.AreEqual(1f, m.LightColor.A, 1e-6f);
            Assert.AreEqual((s.Periods[1].ShadowColor.G + s.Periods[2].ShadowColor.G) / 2, m.ShadowColor.G, 1e-4f);
        }

        [Test]
        public void Transition_AngleTakesShortestWay()
        {
            var s = Settings();
            s.Periods[1].LightYaw = 350; s.Periods[2].LightYaw = 10;
            Assert.AreEqual(360f, s.GetTransition(PeriodOfDay.Daytime, 0.5f).LightYaw, 1e-3f);
            s.Periods[1].LightYaw = 10; s.Periods[2].LightYaw = 350;
            Assert.AreEqual(0f, s.GetTransition(PeriodOfDay.Daytime, 0.5f).LightYaw, 1e-3f);
            Assert.AreEqual(20f, EnvironmentSettingsData.ShortestAngle(380f), 1e-4f);
            Assert.AreEqual(-20f, EnvironmentSettingsData.ShortestAngle(-380f), 1e-4f);
        }

        [Test]
        public void Transition_FogFadesAlphaOnly()
        {
            var s = Settings();
            s.Periods[1].FogEnable = false; s.Periods[2].FogEnable = true;
            s.Periods[2].FogNearColor = new Rgba(1, 1, 1, 0.8f); s.Periods[2].FogEnd = 40;
            var t = s.GetTransition(PeriodOfDay.Daytime, 0.25f);
            Assert.IsTrue(t.FogEnable);
            Assert.AreEqual(40f, t.FogEnd);
            Assert.AreEqual(0.2f, t.FogNearColor.A, 1e-5f);
            s.Periods[1].FogEnable = true; s.Periods[2].FogEnable = false;
            s.Periods[1].FogNearColor = new Rgba(1, 1, 1, 0.8f);
            Assert.AreEqual(0.6f, s.GetTransition(PeriodOfDay.Daytime, 0.25f).FogNearColor.A, 1e-5f);
        }

        [Test]
        public void SetLight_EmissionThresholdAndStateCopy()
        {
            var s = Settings();
            var st = new EnvironmentState();
            st.SetLight(s, PeriodOfDay.Evening, 0.5f, 0f);
            Assert.AreEqual((2 + 0.5f) * 0.2f, st.EmissionThreshold, 1e-6f);
            Assert.AreSame(s.Periods[2], st.Current);
            Assert.AreEqual(s.Periods[2].ShadowColor.R, st.ShadowColor.R);
            Assert.IsTrue(st.CloudShadowEnabled);
            st.SetLight(null, PeriodOfDay.Morning, 0, 0);   // ohne Settings bleibt alles
            Assert.AreSame(s.Periods[2], st.Current);
        }

        [Test]
        public void Apply_FormulasMatchTheOriginalSetter()
        {
            var s = Settings();
            var st = new EnvironmentState();
            st.Scene.CloudShadowBase = 0.25f;
            st.Scene.EmissionScale = 3;
            st.AddCharacterLightIntensity = 0.5f;
            st.AddPokeLightIntensity = -0.5f;
            st.AddLightIntensity = 1f;
            st.SetLight(s, PeriodOfDay.Daytime, 0.1f, 0f);
            var sink = new EnvSink();
            var g = new GameGlobals(sink);
            var light = st.Apply(g, 12f);
            var p = s.Periods[1];
            // Licht · (I, I, I, 1)
            var ci = p.CharacterLightIntensity + 0.5f;
            CollectionAssert.AreEqual(new[] { p.CharacterLightColor.R * ci, p.CharacterLightColor.G * ci, p.CharacterLightColor.B * ci, p.CharacterLightColor.A },
                sink.Vec("_CharacterLightColor"));
            var pi = p.PokeLightIntensity - 0.5f;
            Assert.AreEqual(p.PokeLightColor.R * pi, sink.Vec("_PokeLightColor")[0], 1e-5f);
            CollectionAssert.AreEqual(new[] { p.PokeReflectorColor.R, p.PokeReflectorColor.G, p.PokeReflectorColor.B, p.PokeReflectorColor.A }, sink.Vec("_PokeReflectorColor"));
            // Schattenfarbe halbiert (auch Alpha)
            CollectionAssert.AreEqual(new[] { p.ShadowColor.R * 0.5f, p.ShadowColor.G * 0.5f, p.ShadowColor.B * 0.5f, 0.5f }, sink.Vec("_ShadowColor"));
            Assert.AreEqual(0.75f, sink.Flt("_CloudShadowBase"));
            Assert.AreEqual(3f, sink.Flt("_EmissionScale"));
            Assert.AreEqual((1 + 0.1f) * 0.2f, sink.Flt("_EmissionThreshold"), 1e-6f);
            Assert.AreEqual(0f, sink.Flt("_GlobalLightPower"));       // statisch 1 − 1
            Assert.AreEqual(1f, sink.Flt("_GlobalBumpScale"));
            Assert.AreEqual(p.Blurry, sink.Flt("_AdditionalBlurry"));
            Assert.AreEqual(p.VertexColorScale, sink.Flt("_VertexColorScale"));
            Assert.AreEqual(p.BloomThreshold, sink.Flt("_BloomThreshold"));
            Assert.AreEqual(p.LightIntensity + 1f, light.LightIntensity);
            Assert.AreEqual(p.LightPitch, light.Pitch);
            // Texturen ohne Verweis: Ersatztexturen
            Assert.AreEqual(DefaultTextures.Black, sink.V["_CloudShadowTex"]);
            Assert.AreEqual(DefaultTextures.White, sink.V["_EnvironmentMap"]);
            Assert.AreEqual(DefaultTextures.Bump, sink.V["_SnowNormalTex"]);
            Assert.AreEqual(DefaultTextures.Gray, sink.V["_NoiseTex"]);
        }

        [Test]
        public void Apply_GlobalLightPowerAndSnowShadow()
        {
            var s = Settings();
            var st = new EnvironmentState { GlobalLightPower = 1.75f };
            st.Scene.WeatherMode = 2;
            st.Scene.SnowShadowColor = new Rgba(0.2f, 0.4f, 0.6f, 1);
            st.SetLight(s, PeriodOfDay.Morning, 0, 0);
            var sink = new EnvSink();
            st.Apply(new GameGlobals(sink), 0);
            Assert.AreEqual(0.75f, sink.Flt("_GlobalLightPower"));
            CollectionAssert.AreEqual(new[] { 0.1f, 0.2f, 0.3f, 0.5f }, sink.Vec("_ShadowColor"));
            st.ThroughGlobal = true;
            st.Apply(new GameGlobals(sink), 0);
            Assert.AreEqual(0f, sink.Flt("_GlobalLightPower"));
        }

        [Test]
        public void Apply_CloudShadowTexOnlyWhenEnabled()
        {
            var s = Settings();
            var st = new EnvironmentState();
            var tex = new object();
            st.Scene.CloudShadowTex = tex;
            st.SetLight(s, PeriodOfDay.Daytime, 0, 0);
            var sink = new EnvSink();
            st.Apply(new GameGlobals(sink), 0);
            Assert.AreSame(tex, sink.V["_CloudShadowTex"]);
            s.CloudShadowEnable = false;
            st.SetLight(s, PeriodOfDay.Daytime, 0, 0);
            st.Apply(new GameGlobals(sink), 0);
            Assert.AreEqual(DefaultTextures.Black, sink.V["_CloudShadowTex"]);
        }

        [Test]
        public void CloudParam_ModuloByTiling()
        {
            var sc = new EnvironmentSceneParams { CloudSpeedX = 2, CloudSpeedY = 0.5f, CloudTilingX = 0.5f, CloudTilingY = 0 };
            EnvironmentState.CloudParam(3f, sc, out var x, out var y);
            Assert.AreEqual((3f * 60 * 2) % 2f, x, 1e-5f);        // modulo 1/0,5
            Assert.AreEqual(3f * 60 * 0.5f, y, 1e-5f);            // Kachelung 0: kein Modulo
        }

        [Test]
        public void FieldLighting_FixedTimeKeepsDaytime()
        {
            var s = Settings();
            var st = new EnvironmentState();
            FieldLighting.Update(st, s, true, 22f);
            Assert.AreSame(s.Periods[1], st.Current);
            Assert.AreEqual((1f / 3f + 3) * 0.2f, st.EmissionThreshold, 1e-4f);   // Nacht, Fortschritt (22−20)/6
            FieldLighting.Update(st, s, false, 22f);
            Assert.AreSame(s.Periods[3], st.Current);
        }

        [Test]
        public void SetPokemonLight_ChangesOnlyPokeValues()
        {
            var s = Settings();
            var st = new EnvironmentState();
            st.SetLight(s, PeriodOfDay.Morning, 0, 0);
            var before = st.Current;
            st.SetPokemonLight(s, PeriodOfDay.Night);
            Assert.AreEqual(s.Periods[3].PokeLightIntensity, st.Current.PokeLightIntensity);
            Assert.AreEqual(s.Periods[0].LightIntensity, st.Current.LightIntensity);
            Assert.AreSame(before, s.Periods[0]);   // Quelle bleibt unverändert (Kopie)
            Assert.AreNotEqual(s.Periods[0].PokeLightIntensity, s.Periods[3].PokeLightIntensity);
            Assert.AreEqual(s.Periods[0].PokeLightIntensity, before.PokeLightIntensity);
        }

        [Test]
        public void Catalog_ParsesExport()
        {
            const string settings = "{\"settings\":[{\"name\":\"A\",\"pathId\":7,\"cloudShadowEnable\":true,\"fixedTime\":false,\"fogMode\":2,\"periods\":{" +
                "\"Morning\":{\"LightYaw\":15.0,\"LightPitch\":80.0,\"LightColor\":{\"r\":0.5,\"g\":0.25,\"b\":0.125,\"a\":1.0},\"LightIntensity\":1.5,\"ColorGradingEnable\":1,\"ColorGradingLookup\":{\"m_FileID\":0,\"m_PathID\":99},\"FogEnable\":0}}}]}";
            const string zones = "{\"zones\":[{\"index\":0,\"zoneId\":5,\"settings\":\"A\",\"settingsPathId\":7,\"weather\":2,\"fixedTime\":true,\"reflectionCamera\":false}," +
                "{\"index\":1,\"zoneId\":null,\"settings\":null,\"settingsPathId\":0,\"weather\":0,\"fixedTime\":false,\"reflectionCamera\":true}]}";
            var c = new EnvironmentSettingsCatalog();
            c.LoadSettingsJson(settings);
            c.LoadZonesJson(zones);
            Assert.AreEqual(1, c.SettingsCount);
            Assert.AreEqual(2, c.ZoneCount);
            var a = c.ForZone(0);
            Assert.AreEqual("A", a.Name);
            Assert.IsTrue(a.CloudShadowEnable);
            var m = a[PeriodOfDay.Morning];
            Assert.AreEqual(80f, m.LightPitch);
            Assert.AreEqual(0.25f, m.LightColor.G);
            Assert.IsTrue(m.ColorGradingEnable);
            Assert.AreEqual(99, m.ColorGradingLookup);
            Assert.IsNull(a[PeriodOfDay.Daytime]);
            Assert.IsNull(c.ForZone(1));
            Assert.IsTrue(c.Zone(1).ReflectionCamera);
            Assert.AreEqual(-1, c.Zone(1).ZoneId);
            Assert.IsNull(c.ForZone(7));
        }

        [Test]
        public void DepthOfField_FocalCoefficient()
        {
            DepthOfFieldMath.FocalCoefficient(10f, 4f, out var x, out var y, out var z, out var w);
            Assert.AreEqual(10f, x); Assert.AreEqual(4f, y); Assert.AreEqual(0.25f, z, 1e-6f); Assert.AreEqual(1f / 14f, w, 1e-6f);
            DepthOfFieldMath.FocalCoefficient(0f, 1f, out _, out _, out _, out var w2);
            Assert.AreEqual(1f, w2, 1e-6f);
            DepthOfFieldMath.FocalCoefficient(0f, 0.0001f, out _, out _, out _, out var w3);
            Assert.AreEqual(1000f, w3, 1e-3f);                               // Untergrenze 0,001
            // 24-mm-Sensor, 60° Sichtfeld → f = 12 / tan(30°) ≈ 20,78 mm
            Assert.AreEqual(20.7846f, DepthOfFieldMath.FocalLengthFromFov(60f, 24f), 1e-3f);
            // farDepth = Skala · k · d · 0,5 / (f · 0,001)²
            Assert.AreEqual(1f * 0.024f * 10f * 0.5f / (0.02f * 0.02f), DepthOfFieldMath.FarDepth(1f, 0.024f, 10f, 20f), 1e-2f);
        }

        [Test]
        public void Placeholders_MatchTheIdleOriginalState()
        {
            var sink = new EnvSink();
            var g = new GameGlobals(sink);
            g.SetDefaults();
            Assert.AreEqual(0f, sink.Flt("_GlobalLightPower"));    // statisch 1 − 1
            Assert.AreEqual(1f, sink.Flt("_CloudShadowBase"));     // 1 − Szenenwert 0
            Assert.AreEqual(1f, sink.Flt("_GlobalBumpScale"));
        }

        [Test]
        public void Sources_CoverEveryGlobalOnce()
        {
            Assert.AreEqual(GameGlobals.Specs.Count, GameGlobalSources.All.Count);
            CollectionAssert.AreEquivalent(GameGlobals.Specs.Select(x => x.Name), GameGlobalSources.All.Select(x => x.Name));
            Assert.AreEqual(GameGlobalSources.All.Count, GameGlobalSources.All.Select(x => x.Name).Distinct().Count());
            foreach (var s in GameGlobalSources.All)
            {
                Assert.IsFalse(string.IsNullOrEmpty(s.Setter), s.Name);
                Assert.IsFalse(string.IsNullOrEmpty(s.Data), s.Name);
            }
        }

        [Test]
        public void EverythingTheStateSets_IsAPortedGlobal()
        {
            var sink = new EnvSink();
            var st = new EnvironmentState();
            st.SetLight(Settings(), PeriodOfDay.Daytime, 0, 0);
            st.Apply(new GameGlobals(sink), 12);
            foreach (var name in sink.V.Keys)
            {
                Assert.IsTrue(GameGlobalSources.TryGet(name, out var src), name);
                Assert.IsTrue(src.Ported, name);
                Assert.IsTrue(src.Kind == GlobalSourceKind.EnvironmentSettings || src.Kind == GlobalSourceKind.SceneObject || src.Kind == GlobalSourceKind.Runtime, name);
            }
        }
    }
}
