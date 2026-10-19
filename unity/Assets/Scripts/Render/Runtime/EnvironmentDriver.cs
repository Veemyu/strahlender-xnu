using System;
using UnityEngine;

namespace Xnu.Render
{
    // Port der Per-Bild-Logik von SceneConnector.OnUpdate + EnvironmentController.OnUpdate (docs/shader-globals.md, Abschnitt 2):
    // wählt aus den EnvironmentSettings der Zone Tagesabschnitt und Überblendung, setzt alle Spiel-Globals und stellt Richtungslicht
    // und Schatten-Qualität ein. Die Datenquellen (Katalog, Szenenwerte, Uhrzeit) liefert der Aufrufer.
    public sealed class EnvironmentDriver : MonoBehaviour
    {
        public Light Sun;                                  // Richtungslicht der Szene (EnvironmentController._light)
        public EnvironmentSettingsData Settings;           // MapInfo.ZoneData[zone].RenderSettings
        public bool ZoneFixedTime;                         // MapInfo.ZoneData[zone].FixedTime
        public EnvironmentState State = new EnvironmentState();
        public Func<float> HourProvider;                   // GameManager.elapsedTimeOfDay; ohne: Systemuhr

        GameGlobals _globals;
        bool _sceneTried;

        // Szenenwerte der Feldszene (Schattenentfernung 45, Wolken, RenderSettings …); ohne Vorgabe aus
        // <XNU_MASTERDATA | GameData/masterdata>/EnvironmentScene.json (scripts/environment_export.py), falls vorhanden.
        public EnvironmentSceneData SceneData;
        public bool AutoLoadScene = true;
        public const string SceneFileName = "EnvironmentScene.json";

        public EnvironmentLightOutput LastLight { get; private set; }

        void OnEnable()
        {
            _globals = new GameGlobals(new UnityGlobalSink());
            ShadowMapGuard.Install();
            TryLoadScene();
        }

        public static string SceneFilePath
        {
            get
            {
                var env = Environment.GetEnvironmentVariable("XNU_MASTERDATA");
                var dir = !string.IsNullOrEmpty(env) ? env : System.IO.Path.Combine(Xnu.Core.GameDataPaths.Root, "masterdata");
                return System.IO.Path.Combine(dir, SceneFileName);
            }
        }

        void TryLoadScene()
        {
            if (_sceneTried) return;
            _sceneTried = true;
            if (SceneData == null && AutoLoadScene)
            {
                try
                {
                    var p = SceneFilePath;
                    if (System.IO.File.Exists(p)) SceneData = EnvironmentSceneData.FromJson(System.IO.File.ReadAllText(p));
                }
                catch (Exception e) { Debug.LogWarning("[Render] EnvironmentScene.json nicht lesbar: " + e.Message); }
            }
            if (SceneData == null) return;
            State.Scene = SceneData.Params;
            SceneRenderApply.Apply(SceneData.Render);
        }

        public static float SystemHours() => TimeOfDay.ElapsedHours(DateTime.Now.Ticks, 0, 1);

        // Ein Bild: genau die Reihenfolge des Originals (SceneConnector wählt, EnvironmentController setzt).
        public void Tick()
        {
            if (_globals == null) _globals = new GameGlobals(new UnityGlobalSink());
            var hours = HourProvider != null ? HourProvider() : SystemHours();
            FieldLighting.Update(State, Settings, ZoneFixedTime, hours);
            var o = State.Apply(_globals, hours);
            LastLight = o;
            if (!Mathf.Approximately(QualitySettings.shadowDistance, o.ShadowDistance) && o.ShadowDistance > 0)
                QualitySettings.shadowDistance = o.ShadowDistance;
            if (!Mathf.Approximately(QualitySettings.shadowNearPlaneOffset, o.ShadowNearPlaneOffset))
                QualitySettings.shadowNearPlaneOffset = o.ShadowNearPlaneOffset;
            if (Sun != null)
            {
                Sun.intensity = o.LightIntensity;
                Sun.color = new Color(o.LightColor.R, o.LightColor.G, o.LightColor.B, o.LightColor.A);
                Sun.transform.eulerAngles = new Vector3(o.Pitch, o.Yaw, 0);
                Sun.shadowNormalBias = o.ShadowNormalBias;
            }
        }

        void Update() => Tick();
    }

    // QualitySettings des Originals (Stufe „Ultra“ aus globalgamemanagers): Schatten an, hohe Auflösung, StableFit, eine
    // Kaskade, Schattenentfernung 20. Entspricht der letzten Stufe der ProjectSettings; zur Absicherung zur Laufzeit.
    public static class OriginalQuality
    {
        public static void Apply()
        {
            QualitySettings.shadows = ShadowQuality.All;
            QualitySettings.shadowResolution = ShadowResolution.High;
            QualitySettings.shadowProjection = ShadowProjection.StableFit;
            QualitySettings.shadowCascades = 1;
            QualitySettings.shadowDistance = 20f;
            QualitySettings.shadowNearPlaneOffset = 3f;
            QualitySettings.antiAliasing = 0;
        }
    }
}
