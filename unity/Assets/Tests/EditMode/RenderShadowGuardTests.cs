using NUnit.Framework;
using UnityEngine;
using Xnu.Render;

namespace Xnu.Tests
{
    // Bildschirmschatten-Wächter (Zone 422 war nach Zone 54 rund 19 % dunkler: _ShadowMapTexture blieb als freigegebener Verweis
    // stehen), Szenen-RenderSettings und die Konstanten der Nachbearbeitung (docs/sichtpruefung-2.md).
    public class RenderShadowGuardTests
    {
        [Test]
        public void Reset_ReplacesNullGlobalWithWhite()
        {
            Shader.SetGlobalTexture(ShadowMapGuard.GlobalName, (Texture)null);
            Assert.That(Shader.GetGlobalTexture(ShadowMapGuard.GlobalName), Is.Null);
            ShadowMapGuard.Reset();
            Assert.That(Shader.GetGlobalTexture(ShadowMapGuard.GlobalName), Is.SameAs(Texture2D.whiteTexture));
        }

        [Test]
        public void Install_IsIdempotent_AndResetsBeforeCameraRender()
        {
            ShadowMapGuard.Install();
            ShadowMapGuard.Install();
            Assert.That(ShadowMapGuard.Installed, Is.True);
            Shader.SetGlobalTexture(ShadowMapGuard.GlobalName, (Texture)null);
            var go = new GameObject("ShadowGuardCam", typeof(Camera));
            var rt = new RenderTexture(16, 16, 16);
            try
            {
                var cam = go.GetComponent<Camera>();
                cam.targetTexture = rt;
                cam.Render();
                Assert.That(Shader.GetGlobalTexture(ShadowMapGuard.GlobalName), Is.Not.Null);
            }
            finally
            {
                go.GetComponent<Camera>().targetTexture = null;
                Object.DestroyImmediate(rt);
                Object.DestroyImmediate(go);
                ShadowMapGuard.Uninstall();
            }
            Assert.That(ShadowMapGuard.Installed, Is.False);
        }

        [Test]
        public void SceneRenderApply_NoSkyboxNoFog_AndRestores()
        {
            var oldSkybox = RenderSettings.skybox; var oldFog = RenderSettings.fog; var oldMode = RenderSettings.ambientMode;
            var oldIntensity = RenderSettings.ambientIntensity;
            try
            {
                RenderSettings.fog = true;
                SceneRenderApply.Apply(new SceneRenderSettings { Fog = false, HasSkybox = false, AmbientMode = 0, AmbientIntensity = 1f });
                Assert.That(RenderSettings.skybox, Is.Null);
                Assert.That(RenderSettings.fog, Is.False);
                Assert.That(RenderSettings.ambientMode, Is.EqualTo(UnityEngine.Rendering.AmbientMode.Skybox));
            }
            finally
            {
                RenderSettings.skybox = oldSkybox; RenderSettings.fog = oldFog; RenderSettings.ambientMode = oldMode; RenderSettings.ambientIntensity = oldIntensity;
            }
        }

        [Test]
        public void SceneRenderApply_Camera_UsesSceneValues()
        {
            var go = new GameObject("SceneCam", typeof(Camera));
            try
            {
                var cam = go.GetComponent<Camera>();
                SceneRenderApply.ApplyCamera(cam, new SceneCameraInfo { ClearFlags = 2, Hdr = true, Msaa = true, Near = 0.1f, Far = 1500f, CullingMask = 4456247 });
                Assert.That(cam.clearFlags, Is.EqualTo(CameraClearFlags.SolidColor));
                Assert.That(cam.allowHDR, Is.True);
                Assert.That(cam.farClipPlane, Is.EqualTo(1500f));
                Assert.That(cam.cullingMask, Is.EqualTo(4456247));
                SceneRenderApply.ApplyCamera(cam, new SceneCameraInfo { ClearFlags = 4, Near = 3f, Far = 9f }, clipPlanes: false);
                Assert.That(cam.clearFlags, Is.EqualTo(CameraClearFlags.Nothing));
                Assert.That(cam.farClipPlane, Is.EqualTo(1500f));
            }
            finally { Object.DestroyImmediate(go); }
        }

        [Test]
        public void PostChain_BlurOffset_IsTheOriginalKernel()
        {
            Assert.That(PostChain.BlurOffset.x, Is.EqualTo(-2.2186f).Within(1e-3));
            Assert.That(PostChain.BlurOffset.y, Is.EqualTo(2.2186f).Within(1e-3));
            Assert.That(PostChain.BlurOffset.z, Is.EqualTo(-0.6075f).Within(1e-3));
            Assert.That(PostChain.BlurOffset.w, Is.EqualTo(0.6075f).Within(1e-3));
            Assert.That(PostChain.Layers, Is.EqualTo(5));
        }
    }
}
