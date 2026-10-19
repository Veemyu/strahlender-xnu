using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;

namespace Xnu.Build.Editor
{
    // Einstieg für scripts/build_all.sh (Stufe unity-build, Batchmodus) und für das Menü Xnu/Build.
    // Aufruf: Unity -batchmode -quit -projectPath unity -buildTarget <Ziel> -executeMethod Xnu.Build.Editor.BuildScript.BuildMacOS|BuildIos
    //         -xnuOutput <Pfad>    (alternativ -buildOutput, das setzt `unity build --output-path`)
    //         -xnuScenes a;b       (optional, Standard: aktivierte Szenen der Build Settings, sonst DefaultScenes)
    // Die Spieldaten kommen aus Assets/StreamingAssets (gitignoriert, Stufe assets). Team-ID und Signatur
    // setzt scripts/ios_deploy.sh bzw. Xcode, nie dieses Skript.
    public static class BuildScript
    {
        // Rückfall, solange die Build Settings keine Szene enthalten; die erste Szene ist der Einstieg.
        internal static readonly string[] DefaultScenes =
        {
            "Assets/Scenes/FieldTest.unity",
            "Assets/Scenes/InputTest.unity",
        };

        private const string Tag = "[XnuBuild] ";
        private const int ExitFailure = 1;

        [MenuItem("Xnu/Build/macOS (arm64, IL2CPP)")]
        public static void BuildMacOS() => Run(BuildTarget.StandaloneOSX, "work/builds/macos/xnu.app");

        [MenuItem("Xnu/Build/iOS und iPadOS (Xcode-Projekt)")]
        public static void BuildIos() => Run(BuildTarget.iOS, "work/builds/ios/xnu");

        // Wendet nur Einstellungen an, die der Build braucht; Qualitäts- und Farbraumwerte bleiben unberührt.
        internal static void ApplyPlayerSettings(BuildTarget target)
        {
            var named = target == BuildTarget.iOS ? NamedBuildTarget.iOS : NamedBuildTarget.Standalone;
            PlayerSettings.SetScriptingBackend(named, ScriptingImplementation.IL2CPP);
            PlayerSettings.SetUseDefaultGraphicsAPIs(target, false);
            PlayerSettings.SetGraphicsAPIs(target, new[] { GraphicsDeviceType.Metal });

            if (target == BuildTarget.iOS)
            {
                PlayerSettings.iOS.targetDevice = iOSTargetDevice.iPhoneAndiPad;
                PlayerSettings.iOS.appleEnableAutomaticSigning = true;
            }
            else
            {
                SetMacArchitectureArm64();
            }
        }

        // Über Reflection, damit der Code auch ohne das macOS-Modul übersetzt.
        private static void SetMacArchitectureArm64()
        {
            var type = Type.GetType("UnityEditor.OSXStandalone.UserBuildSettings, UnityEditor.OSXStandalone.Extensions");
            var property = type?.GetProperty("architecture");
            if (property == null || !property.PropertyType.IsEnum || !Enum.IsDefined(property.PropertyType, "ARM64"))
            {
                Debug.LogWarning(Tag + "macOS-Architektur nicht setzbar (macOS-Modul?), Standard des Editors bleibt.");
                return;
            }
            property.SetValue(null, Enum.Parse(property.PropertyType, "ARM64"));
        }

        internal static string[] ResolveScenes(string overrideList)
        {
            IEnumerable<string> scenes;
            if (!string.IsNullOrEmpty(overrideList))
                scenes = overrideList.Split(';');
            else
            {
                scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path);
                if (!scenes.Any()) scenes = DefaultScenes;
            }
            return scenes.Where(s => !string.IsNullOrWhiteSpace(s)).Select(s => s.Trim()).ToArray();
        }

        // Liest "-name wert" aus der Kommandozeile; null, wenn nicht vorhanden.
        internal static string Arg(string[] args, string name)
        {
            for (var i = 0; i < args.Length - 1; i++)
                if (args[i] == name) return args[i + 1];
            return null;
        }

        private static void Run(BuildTarget target, string defaultRelativeOutput)
        {
            var batch = Application.isBatchMode;
            try
            {
                var args = Environment.GetCommandLineArgs();
                var output = Arg(args, "-xnuOutput") ?? Arg(args, "-buildOutput");
                if (string.IsNullOrEmpty(output))
                    output = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", defaultRelativeOutput));

                var scenes = ResolveScenes(Arg(args, "-xnuScenes"));
                var missing = scenes.Where(s => !File.Exists(s)).ToArray();
                if (scenes.Length == 0 || missing.Length > 0)
                    throw new BuildFailedException("Szenenliste leer oder Szene fehlt: " + string.Join(", ", missing));

                var bundled = Path.Combine(Application.dataPath, "StreamingAssets", "GameData");
                if (!Directory.Exists(bundled))
                    Debug.LogWarning(Tag + "Assets/StreamingAssets/GameData fehlt (Stufe assets): der Player enthält keine Spieldaten.");

                Directory.CreateDirectory(Path.GetDirectoryName(output));
                ApplyPlayerSettings(target);

                var options = new BuildPlayerOptions
                {
                    scenes = scenes,
                    locationPathName = output,
                    target = target,
                    options = BuildOptions.None,
                };
                Debug.Log(Tag + "Ziel " + target + " -> " + output + ", Szenen: " + string.Join(", ", scenes));
                var report = BuildPipeline.BuildPlayer(options);
                var summary = report.summary;
                Debug.Log(Tag + "Ergebnis " + summary.result + ", " + summary.totalErrors + " Fehler, "
                          + summary.totalWarnings + " Warnungen, " + (summary.totalSize / (1024 * 1024)) + " MB, "
                          + summary.totalTime.TotalSeconds.ToString("F0") + " s");
                if (summary.result != BuildResult.Succeeded)
                    throw new BuildFailedException("Build " + summary.result);
                if (batch) EditorApplication.Exit(0);
            }
            catch (Exception e)
            {
                Debug.LogError(Tag + "Fehlgeschlagen: " + e.Message);
                if (batch) EditorApplication.Exit(ExitFailure);
                else throw;
            }
        }
    }
}
