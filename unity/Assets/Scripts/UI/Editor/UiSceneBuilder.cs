using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Xnu.Core.Display;
using Xnu.Input;

namespace Xnu.UI.Editor
{
    // Erzeugt Assets/Scenes/UiTest.unity: nur eigene Objekte (Kamera, DisplayController, GameInput, TextboxView, UiTestDriver).
    public static class UiSceneBuilder
    {
        public const string ScenePath = "Assets/Scenes/UiTest.unity";

        [MenuItem("Xnu/UI/Create UiTest Scene")]
        public static void CreateScene()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.36f, 0.50f, 0.66f);
            cam.orthographic = true;
            cam.transform.position = new Vector3(0f, 0f, -10f);

            var display = new GameObject("Display").AddComponent<DisplayController>();
            display.TargetCamera = cam;
            display.FrameRate = FrameRateMode.Original30;
            display.Aspect = AspectMode.Aspect16x9;

            new GameObject("GameInput").AddComponent<GameInput>();

            var uiGo = new GameObject("Ui");
            var view = uiGo.AddComponent<TextboxView>();
            view.Configure(cam, 1, true, Xnu.Text.MessageSpeed.Normal);
            uiGo.AddComponent<UiTestDriver>();

            EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.Refresh();
            Debug.Log("[UI] Szene gespeichert: " + ScenePath);
        }
    }
}
