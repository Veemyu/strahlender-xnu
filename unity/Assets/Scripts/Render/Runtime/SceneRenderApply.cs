using UnityEngine;

namespace Xnu.Render
{
    // Überträgt die RenderSettings der Feldszene (EnvironmentScene.json) auf Unity: kein Skybox-Material (Umgebungslicht und
    // Reflexion bleiben dadurch schwarz), kein Nebel, Umgebungslicht-Modus und Unterschattenfarbe wie in der Originalszene.
    public static class SceneRenderApply
    {
        public static void Apply(SceneRenderSettings s)
        {
            if (s == null) return;
            if (!s.HasSkybox) RenderSettings.skybox = null;
            RenderSettings.ambientMode = s.AmbientMode == 1 ? UnityEngine.Rendering.AmbientMode.Trilight
                : s.AmbientMode == 3 ? UnityEngine.Rendering.AmbientMode.Flat : UnityEngine.Rendering.AmbientMode.Skybox;
            RenderSettings.ambientSkyColor = ToColor(s.AmbientSky);
            RenderSettings.ambientEquatorColor = ToColor(s.AmbientEquator);
            RenderSettings.ambientGroundColor = ToColor(s.AmbientGround);
            RenderSettings.ambientIntensity = s.AmbientIntensity;
            RenderSettings.subtractiveShadowColor = ToColor(s.SubtractiveShadow);
            RenderSettings.fog = s.Fog;
            RenderSettings.defaultReflectionMode = s.ReflectionMode == 1 ? UnityEngine.Rendering.DefaultReflectionMode.Custom
                : UnityEngine.Rendering.DefaultReflectionMode.Skybox;
            RenderSettings.reflectionIntensity = s.ReflectionIntensity;
            DynamicGI.UpdateEnvironment();
        }

        // Hauptkamera der Feldszene: Volle Farbe (schwarz, Alpha 0), HDR an, MSAA erlaubt, Ebenenmaske, Clip-Ebenen.
        // Die Kamera der Karte darf die Nah-/Fern-Ebene und das Sichtfeld selbst setzen (dann cameraFields = false).
        public static void ApplyCamera(Camera cam, SceneCameraInfo info, bool clipPlanes = true)
        {
            if (cam == null || info == null) return;
            cam.clearFlags = info.ClearFlags == 1 ? CameraClearFlags.Skybox : info.ClearFlags == 2 ? CameraClearFlags.SolidColor
                : info.ClearFlags == 3 ? CameraClearFlags.Depth : CameraClearFlags.Nothing;
            cam.backgroundColor = ToColor(info.Background);
            cam.allowHDR = info.Hdr;
            cam.allowMSAA = info.Msaa;
            if (clipPlanes) { cam.nearClipPlane = info.Near; cam.farClipPlane = info.Far; }
            cam.cullingMask = (int)info.CullingMask;
        }

        static Color ToColor(Rgba c) => new Color(c.R, c.G, c.B, c.A);
    }
}
