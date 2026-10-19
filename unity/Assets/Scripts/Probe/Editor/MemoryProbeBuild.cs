using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Xnu.Probe.Editor
{
    // Baut die Mess-App MemoryProbe als eigenes Xcode-Projekt. Die Build-Settings-Szenenliste des Projekts
    // bleibt unberührt (nur die Probe-Szene wird gebaut); Bundle-ID, Produktname und ProMotion-Schalter werden
    // nach dem Build zurückgesetzt. Team-ID und Signatur setzt scripts/ios_deploy.sh.
    public static class MemoryProbeBuild
    {
        public const string ScenePath = "Assets/Scenes/MemoryProbe.unity";
        private const string ShaderPath = "Assets/Scripts/Probe/Shaders/ProbeLoad.shader";
        private const string VariantPath = "Assets/Scripts/Probe/Resources/MemoryProbeVariant.txt";
        private const string ProbeBundleId = "dev.local.xnumemprobe";
        // Muss mit IosPostBuild.DisableSessionKey übereinstimmen (Assembly-übergreifend als Text, damit nur iOS-Ziel kompiliert).
        private const string DisableSessionKey = "Xnu.Build.NoIncreasedMemoryLimit";

        [MenuItem("Xnu/Probe/Build iPad (Entitlement an)")]
        public static void BuildWithEntitlement() => Build(true, false);

        [MenuItem("Xnu/Probe/Build iPad (Entitlement aus)")]
        public static void BuildWithoutEntitlement() => Build(false, false);

        [MenuItem("Xnu/Probe/Build iPad (Entitlement an, ProMotion-Schlüssel an)")]
        public static void BuildWithEntitlementPromotion() => Build(true, true);

        [MenuItem("Xnu/Probe/Build iPad (nur Bildrate, Entitlement an)")]
        public static void BuildFpsOnly() => Build(true, false, true);

        public static string OutputDir(bool entitlement, bool promotion, bool fpsOnly = false) =>
            Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "work", "builds", "ios",
                "memprobe-" + (entitlement ? "ent" : "noent") + (promotion ? "-promo" : "") + (fpsOnly ? "-fps" : "")));

        public static void Build(bool entitlement, bool promotion, bool fpsOnly = false)
        {
            var root = Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
            var tag = (entitlement ? "ent-on" : "ent-off") + (promotion ? "_promo-on" : "") + (fpsOnly ? "_fps" : "");
            var logDir = Path.Combine(root, "work", "measurement");
            Directory.CreateDirectory(logDir);
            var logFile = Path.Combine(logDir, "build_" + tag + ".txt");
            File.WriteAllText(logFile, "start " + DateTime.Now.ToString("s") + "\n");

            var group = UnityEditor.Build.NamedBuildTarget.iOS;
            var oldId = PlayerSettings.GetApplicationIdentifier(group);
            var oldName = PlayerSettings.productName;
            var oldPromo = SetProMotionKey(null);
            try
            {
                EnsureScene();
                File.WriteAllText(Path.Combine(root, "unity", VariantPath), "ent=" + (entitlement ? "on" : "off") + ";promo=" + (promotion ? "1" : "0") + (fpsOnly ? ";mode=fps" : ""));
                AssetDatabase.ImportAsset(VariantPath, ImportAssetOptions.ForceUpdate);

                SessionState.SetBool(DisableSessionKey, !entitlement);
                PlayerSettings.SetApplicationIdentifier(group, ProbeBundleId);
                PlayerSettings.productName = "MemoryProbe";
                SetProMotionKey(promotion);
                ApplyPlayerSettings();

                var output = OutputDir(entitlement, promotion, fpsOnly);
                if (Directory.Exists(output)) Directory.Delete(output, true);
                Directory.CreateDirectory(Path.GetDirectoryName(output));
                var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
                {
                    scenes = new[] { ScenePath },
                    locationPathName = output,
                    target = BuildTarget.iOS,
                    options = BuildOptions.None,
                });
                var s = report.summary;
                File.AppendAllText(logFile, "result " + s.result + " errors=" + s.totalErrors + " warnings=" + s.totalWarnings
                                            + " seconds=" + s.totalTime.TotalSeconds.ToString("F0") + " output=" + output + "\n");
            }
            catch (Exception e)
            {
                File.AppendAllText(logFile, "exception " + e + "\n");
                throw;
            }
            finally
            {
                SessionState.EraseBool(DisableSessionKey);
                PlayerSettings.SetApplicationIdentifier(group, oldId);
                PlayerSettings.productName = oldName;
                SetProMotionKey(oldPromo);
                AssetDatabase.SaveAssets();
                File.AppendAllText(logFile, "restored " + oldId + " / " + oldName + "\n");
            }
        }

        // Setzt den ProMotion-Schalter (Info.plist-Schlüssel CADisableMinimumFrameDurationOnPhone) und liefert den alten Wert.
        // Das SerializedObject wird jeweils frisch angelegt, damit keine veralteten Felder (Bundle-ID) zurückgeschrieben werden.
        private static bool SetProMotionKey(bool? value)
        {
            var so = new SerializedObject(Unsupported.GetSerializedAssetInterfaceSingleton("PlayerSettings"));
            var prop = so.FindProperty("appleEnableProMotion");
            if (prop == null) return false;
            var old = prop.boolValue;
            if (value.HasValue && value.Value != old)
            {
                prop.boolValue = value.Value;
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            return old;
        }

        // Gleiche Grundeinstellungen wie das Hauptprojekt: IL2CPP, nur Metal, iPhone und iPad.
        private static void ApplyPlayerSettings()
        {
            PlayerSettings.SetScriptingBackend(UnityEditor.Build.NamedBuildTarget.iOS, ScriptingImplementation.IL2CPP);
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.iOS, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.iOS, new[] { UnityEngine.Rendering.GraphicsDeviceType.Metal });
            PlayerSettings.iOS.targetDevice = iOSTargetDevice.iPhoneAndiPad;
            PlayerSettings.iOS.appleEnableAutomaticSigning = true;
        }

        private static void EnsureScene()
        {
            if (File.Exists(ScenePath)) return;
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Additive);
            var cam = new GameObject("Kamera", typeof(Camera));
            var camera = cam.GetComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.08f, 0.08f, 0.1f);
            var probe = new GameObject("MemoryProbe", typeof(MemoryProbe)).GetComponent<MemoryProbe>();
            probe.loadShader = AssetDatabase.LoadAssetAtPath<Shader>(ShaderPath);
            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorSceneManager.CloseScene(scene, true);
        }
    }
}
