using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Xnu.Boot;
using Xnu.Core.Display;

namespace Xnu.Build.Editor
{
    // Erzeugt Assets/Scenes/Boot.unity: Kamera, Anzeigesteuerung und das Auswahlmenü (BootMenu). Nur eigene Objekte.
    public static class BootSceneBuilder
    {
        public const string ScenePath = "Assets/Scenes/Boot.unity";

        [MenuItem("Xnu/Build/Boot-Szene erzeugen")]
        public static void CreateMenu() => Ensure(true);

        // Legt die Szene an, wenn sie fehlt (oder force gesetzt ist); gibt true zurück, wenn sie neu geschrieben wurde.
        public static bool Ensure(bool force = false)
        {
            if (!force && File.Exists(ScenePath)) return false;
            var previous = SceneManager.GetActiveScene().path;
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var camGo = new GameObject("Main Camera") { tag = "MainCamera" };
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.07f, 0.08f, 0.1f);
            cam.orthographic = true;

            var display = new GameObject("Display").AddComponent<DisplayController>();
            display.TargetCamera = cam;
            new GameObject("Boot").AddComponent<BootMenu>();

            Directory.CreateDirectory(Path.GetDirectoryName(ScenePath));
            EditorSceneManager.SaveScene(scene, ScenePath);
            if (!string.IsNullOrEmpty(previous) && File.Exists(previous)) EditorSceneManager.OpenScene(previous);
            Debug.Log("[XnuBuild] Boot-Szene geschrieben: " + ScenePath);
            return true;
        }
    }
}
