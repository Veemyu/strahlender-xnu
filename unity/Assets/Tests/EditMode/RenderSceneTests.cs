using System.Linq;
using NUnit.Framework;
using Xnu.Render;

namespace Xnu.Tests
{
    // Szenenwerte der Feldszene (synthetische Werte, keine Spieldaten): scripts/environment_export.py -> EnvironmentSceneData.
    public class RenderSceneTests
    {
        const string Json = @"{
 ""controller"": {""_ShadowDistance"": 45.0, ""_ShadowNearPlaneOffset"": 15.0, ""_ShadowNormalBias"": 0.1, ""_EmissionScale"": 2.0,
   ""_CloudShadowBase"": 0.25, ""_WeatherMode"": 2, ""_Wetness"": 0.5, ""cloudSpeed"": [0.5, 0.25], ""cloudTiling"": [0.03, 0.04],
   ""snowShadowColor"": [0.4, 0.5, 0.8, 1.0], ""textures"": {""_NoiseTex"": ""noise"", ""_CloudShadowTex"": null}},
 ""renderSettings"": {""fog"": false, ""ambientMode"": 0, ""ambientSky"": [0.2, 0.2, 0.3, 1.0], ""ambientIntensity"": 1.0, ""skybox"": false,
   ""reflectionMode"": 0, ""reflectionIntensity"": 1.0, ""subtractiveShadow"": [0.4, 0.5, 0.6, 1.0]},
 ""cameras"": [{""name"": ""Main Camera"", ""clearFlags"": 2, ""background"": [0, 0, 0, 0], ""near"": 0.1, ""far"": 1500.0, ""fov"": 60.0,
   ""cullingMask"": 4456247, ""hdr"": true, ""msaa"": true, ""depth"": 0.0, ""enabled"": 1},
   {""name"": ""Compositor"", ""clearFlags"": 4, ""background"": [0.1, 0.2, 0.3, 0], ""near"": 0.3, ""far"": 1000.0, ""fov"": 60.0,
   ""cullingMask"": 0, ""hdr"": true, ""msaa"": true, ""depth"": 4.0, ""enabled"": 1}],
 ""lights"": [{""name"": ""EnvironmentController"", ""type"": 1, ""intensity"": 1.5, ""shadows"": 2, ""bias"": 0.05, ""normalBias"": 0.4, ""cullingMask"": 261943}]
}";

        [Test]
        public void Controller_Values()
        {
            var d = EnvironmentSceneData.FromJson(Json);
            var p = d.Params;
            Assert.That(p.ShadowDistance, Is.EqualTo(45f));
            Assert.That(p.ShadowNearPlaneOffset, Is.EqualTo(15f));
            Assert.That(p.ShadowNormalBias, Is.EqualTo(0.1f).Within(1e-6));
            Assert.That(p.EmissionScale, Is.EqualTo(2f));
            Assert.That(p.CloudShadowBase, Is.EqualTo(0.25f));
            Assert.That(p.WeatherMode, Is.EqualTo(2));
            Assert.That(p.CloudSpeedX, Is.EqualTo(0.5f));
            Assert.That(p.CloudSpeedY, Is.EqualTo(0.25f));
            Assert.That(p.CloudTilingY, Is.EqualTo(0.04f).Within(1e-6));
            Assert.That(p.SnowShadowColor.B, Is.EqualTo(0.8f).Within(1e-6));
            Assert.That(d.TextureNames["_NoiseTex"], Is.EqualTo("noise"));
            Assert.That(d.TextureNames["_CloudShadowTex"], Is.Null);
        }

        [Test]
        public void RenderSettings_NoSkyboxNoFog()
        {
            var r = EnvironmentSceneData.FromJson(Json).Render;
            Assert.That(r.HasSkybox, Is.False);
            Assert.That(r.Fog, Is.False);
            Assert.That(r.AmbientSky.B, Is.EqualTo(0.3f).Within(1e-6));
            Assert.That(r.SubtractiveShadow.G, Is.EqualTo(0.5f).Within(1e-6));
        }

        [Test]
        public void Cameras_AndLights()
        {
            var d = EnvironmentSceneData.FromJson(Json);
            Assert.That(d.Cameras.Select(c => c.Name), Is.EqualTo(new[] { "Main Camera", "Compositor" }));
            var m = d.Camera("Main Camera");
            Assert.That(m.ClearFlags, Is.EqualTo(2));
            Assert.That(m.Hdr, Is.True);
            Assert.That(m.CullingMask, Is.EqualTo(4456247L));
            Assert.That(m.Far, Is.EqualTo(1500f));
            Assert.That(d.Camera("fehlt"), Is.Null);
            Assert.That(d.Lights.Single().Shadows, Is.EqualTo(2));
            Assert.That(d.Lights.Single().NormalBias, Is.EqualTo(0.4f).Within(1e-6));
        }

        [Test]
        public void MissingSections_Defaults()
        {
            var d = EnvironmentSceneData.FromJson("{}");
            Assert.That(d.Params.EmissionScale, Is.EqualTo(1f));
            Assert.That(d.Params.ShadowDistance, Is.EqualTo(0f));
            Assert.That(d.Cameras, Is.Empty);
        }

        [Test]
        public void Garbage_Throws() => Assert.Throws<System.FormatException>(() => EnvironmentSceneData.FromJson("[1]"));
    }
}
