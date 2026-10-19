using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Xnu.Core.Display;
using Xnu.Input;

namespace Xnu.Game.Unity.Editor
{
    // Erzeugt Assets/Scenes/Game.unity: nur eigene Objekte (Kamera, DisplayController, GameInput, GameDriver). Die Welt entsteht zur Laufzeit.
    public static class GameSceneBuilder
    {
        public const string ScenePath = "Assets/Scenes/Game.unity";

        [MenuItem("Xnu/Game/Spielszene erzeugen")]
        public static void CreateMenu() => Create();

        public static void Create()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var camGo = new GameObject("Main Camera") { tag = "MainCamera" };
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.08f, 0.1f, 0.18f);
            cam.fieldOfView = 17.5f;
            cam.nearClipPlane = 0.5f;
            cam.farClipPlane = 400f;
            camGo.transform.SetPositionAndRotation(new Vector3(0f, 20f, -22f), Quaternion.Euler(45f, 0f, 0f));

            var display = new GameObject("Display").AddComponent<DisplayController>();
            display.TargetCamera = cam;
            display.FrameRate = FrameRateMode.Original30;
            display.Aspect = AspectMode.Aspect16x9;

            new GameObject("GameInput").AddComponent<GameInput>();
            new GameObject("Game").AddComponent<GameDriver>();

            EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.Refresh();
            Debug.Log("[Game] Szene gespeichert: " + ScenePath);
        }
    }
}
