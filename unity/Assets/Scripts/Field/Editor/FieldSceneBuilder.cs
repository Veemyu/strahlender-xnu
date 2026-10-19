using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Xnu.Core.Display;
using Xnu.Input;

namespace Xnu.Field.Editor
{
    // Erzeugt Assets/Scenes/FieldTest.unity und FieldTest2.unity: nur eigene Objekte (Kamera, DisplayController, GameInput,
    // FieldController), keine Spieldaten. Die Karte entsteht zur Laufzeit aus den Bundles.
    // FieldTest2 ist die Szene der Scheibe 2 (Streaming, Zonenwechsel, Spielerfigur, NPCs, Interaktion).
    public static class FieldSceneBuilder
    {
        public const string ScenePath = "Assets/Scenes/FieldTest.unity";
        public const string Scene2Path = "Assets/Scenes/FieldTest2.unity";

        [MenuItem("Xnu/Field/Create FieldTest Scene")]
        public static void CreateScene() => Create(ScenePath, false);

        [MenuItem("Xnu/Field/Create FieldTest2 Scene")]
        public static void CreateScene2() => Create(Scene2Path, true);

        static void Create(string path, bool slice2)
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.45f, 0.62f, 0.85f);
            cam.fieldOfView = 17.5f;
            cam.nearClipPlane = 0.5f;
            cam.farClipPlane = 400f;
            camGo.transform.SetPositionAndRotation(new Vector3(0f, 20f, -22f), Quaternion.Euler(45f, 0f, 0f));

            var display = new GameObject("Display").AddComponent<DisplayController>();
            display.TargetCamera = cam;
            display.FrameRate = FrameRateMode.Original30;
            display.Aspect = AspectMode.Aspect16x9;

            new GameObject("GameInput").AddComponent<GameInput>();

            var fieldGo = new GameObject("Field");
            var field = fieldGo.AddComponent<FieldController>();
            field.zoneId = 422;
            field.cameraOverride = cam;
            field.streaming = slice2;
            field.usePlayerModel = slice2;
            field.showNpcs = slice2;
            field.useGeneratedShaders = false;

            EditorSceneManager.SaveScene(scene, path);
            AssetDatabase.Refresh();
            Debug.Log("[Field] Szene gespeichert: " + path);
        }
    }
}
