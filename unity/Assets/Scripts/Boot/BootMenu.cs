using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Profiling;
using UnityEngine.SceneManagement;
using Xnu.Core;

namespace Xnu.Boot
{
    // Startszene des Players: zeigt Zustand der Spieldaten und eine Auswahlliste der übrigen Szenen aus den Build-Szenen.
    // Mit "-xnuScene <Name>" oder XNU_START_SCENE wird die Szene ohne Eingabe gestartet (Messläufe, iPad per devicectl).
    // Nach dem Wechsel bleibt nur eine kleine Schaltfläche "Menü" oben rechts. Alles IMGUI, keine Spieldaten, kein Ton.
    [DisallowMultipleComponent]
    public sealed class BootMenu : MonoBehaviour
    {
        public const string BootSceneName = "Boot";
        public float memoryLogInterval = 10f;

        private readonly List<string> _scenes = new List<string>();
        private string _status = "";
        private string _startScene;
        private float _autoStartAt = -1f;
        private float _nextLog;
        private int _frames;
        private float _fpsTime;
        private float _fps;
        private GUIStyle _label, _button, _title;

        private static BootMenu _instance;

        private void Awake()
        {
            // Beim Zurückkehren in die Boot-Szene bleibt die erste Instanz die gültige.
            if (_instance != null && _instance != this) { Destroy(gameObject); return; }
            _instance = this;
            DontDestroyOnLoad(gameObject);
            for (var i = 0; i < SceneManager.sceneCountInBuildSettings; i++)
            {
                var path = SceneUtility.GetScenePathByBuildIndex(i);
                if (BootOptions.SceneName(path) != BootSceneName) _scenes.Add(path);
            }
            _startScene = BootOptions.ResolveStartScene(Environment.GetCommandLineArgs(), Environment.GetEnvironmentVariable);
            _status = Describe();
            Debug.Log("[Boot] " + _status.Replace("\n", "\n[Boot] "));
            if (_startScene != null)
            {
                var path = BootOptions.FindScenePath(_scenes.ToArray(), _startScene);
                if (path == null) Debug.LogError("[Boot] Startszene nicht in den Build-Szenen: " + _startScene);
                else { _startScene = path; _autoStartAt = Time.realtimeSinceStartup + 1f; }
            }
            _nextLog = Time.realtimeSinceStartup + memoryLogInterval;
        }

        private void Update()
        {
            _frames++;
            var now = Time.realtimeSinceStartup;
            if (now - _fpsTime >= 1f) { _fps = _frames / (now - _fpsTime); _frames = 0; _fpsTime = now; }
            if (_autoStartAt > 0 && now >= _autoStartAt)
            {
                _autoStartAt = -1f;
                Load(_startScene);
            }
            if (memoryLogInterval > 0 && now >= _nextLog)
            {
                _nextLog = now + memoryLogInterval;
                Debug.Log("[Boot] t=" + now.ToString("F0") + " s, Szene " + SceneManager.GetActiveScene().name + ", " + _fps.ToString("F1") + " FPS, "
                          + Memory());
            }
        }

        private static string Memory() =>
            "Unity belegt " + Profiler.GetTotalAllocatedMemoryLong() / (1024 * 1024) + " MB (reserviert " + Profiler.GetTotalReservedMemoryLong() / (1024 * 1024)
            + " MB), Mono " + Profiler.GetMonoUsedSizeLong() / (1024 * 1024) + " MB, Grafik " + Profiler.GetAllocatedMemoryForGraphicsDriver() / (1024 * 1024) + " MB";

        private void Load(string path)
        {
            Debug.Log("[Boot] Lade " + path);
            SceneManager.LoadScene(path);
        }

        private static string Describe()
        {
            var root = GameDataPaths.Root;
            var env = Environment.GetEnvironmentVariable(GameDataPaths.EnvVar);
            var source = !string.IsNullOrEmpty(env) ? GameDataPaths.EnvVar : Directory.Exists(Path.Combine(Application.streamingAssetsPath, GameDataPaths.BundledFolder)) ? "im Paket (StreamingAssets)" : "Anwendungsordner";
            var bundles = Directory.Exists(GameDataPaths.AssetAssistant);
            var master = Directory.Exists(Path.Combine(root, "masterdata"));
            return "Xnu " + Application.version + ", Unity " + Application.unityVersion + ", " + Application.platform + "\n"
                   + "Gerät: " + SystemInfo.deviceModel + ", " + SystemInfo.systemMemorySize + " MB RAM, Grafik " + SystemInfo.graphicsDeviceName + " (" + SystemInfo.graphicsDeviceType + ")\n"
                   + "Spieldaten: " + root + " [" + source + "]\n"
                   + "Bundles (AssetAssistant): " + (bundles ? "vorhanden" : "FEHLT") + ", Stammdaten: " + (master ? "vorhanden" : "FEHLT") + "\n"
                   + "Ton: " + (AudioListener.pause || AudioListener.volume == 0f ? "aus (AudioSafety)" : "AN?") + "\n"
                   + "Freier Speicher am Datenordner: " + FreeSpace();
        }

        // Freier Platz des Datenträgers unter persistentDataPath (iPadOS: Gerätespeicher); "unbekannt", wenn die Plattform es nicht liefert.
        private static string FreeSpace()
        {
            try
            {
                var free = new DriveInfo(Application.persistentDataPath).AvailableFreeSpace;
                return (free / (1024 * 1024 * 1024)) + " GB";
            }
            catch (Exception) { return "unbekannt"; }
        }

        private void OnGUI()
        {
            var scale = Mathf.Max(1f, Screen.height / 720f);
            GUI.matrix = Matrix4x4.Scale(new Vector3(scale, scale, 1f));
            var w = Screen.width / scale;
            var h = Screen.height / scale;
            EnsureStyles();

            if (SceneManager.GetActiveScene().name != BootSceneName)
            {
                if (GUI.Button(new Rect(w - 110, 8, 100, 36), "Menü", _button)) Load(SceneUtility.GetScenePathByBuildIndex(0));
                return;
            }

            GUI.Label(new Rect(24, 16, w - 48, 40), "Xnu – Testszenen", _title);
            GUI.Label(new Rect(24, 64, w - 48, 130), _status + "\n" + _fps.ToString("F0") + " FPS, " + Memory(), _label);
            var y = 210f;
            if (_scenes.Count == 0) GUI.Label(new Rect(24, y, w - 48, 30), "Keine weiteren Szenen im Build.", _label);
            foreach (var path in _scenes)
            {
                if (y + 48 > h) break;
                if (GUI.Button(new Rect(24, y, Mathf.Min(420, w - 48), 44), BootOptions.SceneName(path), _button)) Load(path);
                y += 52;
            }
            if (_startScene != null && _autoStartAt > 0)
                GUI.Label(new Rect(24, h - 40, w - 48, 30), "Startet " + BootOptions.SceneName(_startScene) + " …", _label);
        }

        private void EnsureStyles()
        {
            if (_label != null) return;
            _label = new GUIStyle(GUI.skin.label) { fontSize = 15, wordWrap = true };
            _label.normal.textColor = Color.white;
            _title = new GUIStyle(_label) { fontSize = 26, fontStyle = FontStyle.Bold };
            _button = new GUIStyle(GUI.skin.button) { fontSize = 20 };
        }
    }
}
