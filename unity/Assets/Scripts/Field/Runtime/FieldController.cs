using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using Xnu.Boot;
using Xnu.Core;
using Xnu.Data;
using Xnu.Input;

namespace Xnu.Field
{
    // Bodenhöhe per Strahl nach unten gegen die Boden-Collider (Ebenenmaske), nur Collider der gebauten Karte.
    public sealed class RaycastGround : IGroundHeight
    {
        readonly int _mask;
        readonly float _above;
        readonly float _depth;

        public RaycastGround(int layerMask, float above = 1.2f, float depth = 8f)
        {
            _mask = layerMask; _above = above; _depth = depth;
        }

        public bool TryGetHeight(float worldX, float worldZ, float fromY, out float y)
        {
            var origin = new Vector3(worldX, fromY + _above, worldZ);
            if (Physics.Raycast(origin, Vector3.down, out var hit, _above + _depth, _mask, QueryTriggerInteraction.Ignore))
            {
                y = hit.point.y;
                return true;
            }
            y = fromY;
            return false;
        }
    }

    // Erste Feld-Szene: lädt eine Zone aus den Original-Bundles (Karte mit Ersatz-Materialien), liest Attribute und
    // Kamera aus den Stammdaten und steuert den Spieler per Rasterbewegung mit Kollision. Logik läuft mit 30 Hz.
    // Nur Hauptthread; keine Spieldaten im Szenenasset, alles entsteht zur Laufzeit.
    [DisallowMultipleComponent]
    public sealed class FieldController : MonoBehaviour
    {
        public const float LogicStep = 1f / 30f;

        [Header("Zone")]
        [Tooltip("Zonen-ID aus ZoneTable/MapInfo. 422 = Zwieblüh-Start (Twinleaf Town, Feldkarte fields/area001); 425 = Spielerhaus 1. Stock.")]
        public int zoneId = 422;
        [Tooltip("Nachbarblöcke (je 32 Zellen), die zusätzlich zur Zone gebaut werden (nur Feldkarten).")]
        [Range(0, 3)] public int blockRadius = 1;
        [Tooltip("Index des Startpunkts in den Locators der Zone.")]
        public int spawnLocator;
        [Tooltip("Ebenen (Layer-Nummern, durch Komma) mit Bodenkollision für die Höhe.")]
        public string groundLayers = "10";
        public bool unloadBundleAfterBuild = true;

        [Header("Kamera")]
        public Camera cameraOverride;
        [Tooltip("Folgegeschwindigkeit des Brennpunkts (Annahme, Originalwert nicht ermittelt).")]
        public float cameraFollowRate = 12f;

        public FieldDataSet Data { get; private set; }
        public ZoneInfoRecord Zone { get; private set; }
        public FieldCollision Collision { get; private set; }
        public GridMover Mover { get; private set; }
        public FieldMemoryLog Memory { get; private set; }
        public MapBuildStats BuildStats { get; private set; }
        public GameObject MapRoot { get; private set; }
        public bool Loaded { get; private set; }
        public string Error { get; private set; }
        public int ForeignMaterials { get; private set; } = -1;
        public int LogicTicks { get; private set; }
        public Transform Player => _player;

        BundleProvider _provider;
        FallbackMaterials _materials;
        Transform _player;
        Camera _camera;
        float _accumulator;
        (float X, float Y, float Z) _focus;
        FieldCameraSettings _camSettings;
        string _bundleName;
        string _hud = "";
        float _fpsTimer; int _fpsFrames; float _fps;

        void Start() => StartCoroutine(Load());

        void OnDestroy() => Unload();

        public IEnumerator Load()
        {
            Memory = new FieldMemoryLog();
            Memory.Mark("Start");
            try { Prepare(); }
            catch (Exception e) { Fail(e); yield break; }

            GameObject prefab = null;
            try { prefab = LoadMapPrefab(); }
            catch (Exception e) { Fail(e); yield break; }

            try { BuildScene(prefab); }
            catch (Exception e) { Fail(e); yield break; }

            prefab = null;
            if (unloadBundleAfterBuild && _bundleName != null)
            {
                _provider.Release(_bundleName);
                _bundleName = null;
                Memory.Mark("Bundle entladen (Objekte bleiben)");
                var op = Resources.UnloadUnusedAssets();
                while (!op.isDone) yield return null;
                Memory.Mark("Ungenutzte Assets entladen");
            }
            Loaded = true;
            Debug.Log("[Field] Zone " + zoneId + " geladen.\n" + BuildStats + "\n" + Memory);
        }

        void Fail(Exception e)
        {
            Error = e.Message;
            Debug.LogError("[Field] " + e);
        }

        void Prepare()
        {
            if (_provider == null)
            {
                var report = BootSequence.Run(GameDataPaths.AssetAssistant, new UnityBundleSource());
                if (!report.Success) throw new InvalidOperationException("Spieldaten nicht nutzbar (XNU_GAMEDATA prüfen).");
                _provider = report.Provider;
                _provider.UnloadAllLoadedObjects = false;
                _provider.DependencyFilter = r => !IsShaderBundle(r);
                Memory.Mark("Katalog gelesen");
            }

            if (Data == null)
            {
                Data = FieldDataSet.Load(FieldDataSet.DefaultDirectory);
                Memory.Mark("Stammdaten (Zonen, Attribute) gelesen");
            }
            if (!Data.TryGetZone(zoneId, out var zone)) throw new InvalidDataException("Unbekannte Zone " + zoneId);
            Zone = zone;
            Collision = Data.BuildCollision(zone);

            if (!Data.TryGetCamera(zone.ZoneId, out var cam)) throw new InvalidDataException("Keine Kamera für Zone " + zone.ZoneId);
            _camSettings = new FieldCameraSettings(cam.Pitch, cam.Fov, cam.TargetRange);
            _materials = new FallbackMaterials();
        }

        // Wechselt zur Zone (entlädt die alte Karte, lädt die neue; Katalog und Stammdaten bleiben im Speicher).
        public IEnumerator SwitchZone(int newZoneId)
        {
            Unload();
            yield return null;
            var op = Resources.UnloadUnusedAssets();
            while (!op.isDone) yield return null;
            zoneId = newZoneId;
            yield return Load();
        }

        // Shader-Bundles der Originalspiel-Shader dürfen nicht geladen werden (Switch-Binärcode, Editor-Absturz).
        public static bool IsShaderBundle(BundleRecord r)
        {
            if (r.Name == "shaders" || r.Name.EndsWith("/shaders", StringComparison.Ordinal)) return true;
            foreach (var p in r.AssetPaths)
                if (p.EndsWith(".shader", StringComparison.OrdinalIgnoreCase) || p.EndsWith(".shadervariants", StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        GameObject LoadMapPrefab()
        {
            if (string.IsNullOrEmpty(Zone.AssetBundleName)) throw new InvalidDataException("Zone " + zoneId + " hat kein Kartenbundle");
            _bundleName = "Environments/" + Zone.AssetBundleName;
            var handle = _provider.Acquire(_bundleName);
            Memory.Mark("Bundle " + _bundleName + " geöffnet");
            var names = handle.GetAllAssetNames();
            if (names.Length == 0) throw new InvalidDataException("Bundle ohne Assets: " + _bundleName);
            var prefab = handle.LoadAsset(names[0], typeof(GameObject)) as GameObject;
            if (prefab == null) throw new InvalidDataException("Kartenprefab nicht ladbar: " + names[0]);
            Memory.Mark("Prefab geladen (Meshes, Texturen, Materialien)");
            return prefab;
        }

        void BuildScene(GameObject prefab)
        {
            var wanted = new HashSet<(int, int)>();
            foreach (var (c, r) in Data.ZoneBlocks(Zone))
                for (var dc = -blockRadius; dc <= blockRadius; dc++)
                    for (var dr = -blockRadius; dr <= blockRadius; dr++)
                        wanted.Add((c + dc, r + dr));

            var builder = new FieldMapBuilder(_materials)
            {
                // Feldkarten: unter "Offset" liegen die Blockcontainer an (-32 * Spalte, 0, 32 * Zeile).
                IncludeBranch = (node, depth) =>
                {
                    if (node.parent == null || node.parent.name != "Offset") return true;
                    var p = node.localPosition;
                    return wanted.Contains((FieldCoords.BlockColumnOfOriginX(p.x), FieldCoords.BlockRowOfOriginZ(p.z)));
                },
            };
            MapRoot = builder.Build(prefab, transform);
            MapRoot.name = "Map_" + zoneId;
            BuildStats = builder.Stats;
            ForeignMaterials = builder.CountForeignMaterials(MapRoot);
            if (ForeignMaterials != 0) throw new InvalidOperationException("Karte enthält " + ForeignMaterials + " Materialien ohne Fallback-Shader");
            Memory.Mark("Karte gebaut (" + BuildStats.Renderers + " Renderer, " + _materials.MaterialsCreated + " Ersatzmaterialien)");

            // Startpunkt: Locator (x, y) = Rasterzelle; bei Innenräumen steht z für die Höhe/Blickrichtung (nicht ausgewertet).
            var loc = Zone.Locators.Length > spawnLocator ? Zone.Locators[spawnLocator] : default;
            var sx = Mathf.RoundToInt(loc.X);
            var sy = Mathf.RoundToInt(loc.Y);
            var ground = new RaycastGround(ParseMask(groundLayers));
            Mover = new GridMover(Collision, ground, sx, sy, MoveDir.Down);
            Mover.Teleport(sx, sy, MoveDir.Down);

            CreatePlayer();
            SetupCamera();
            if (GameInput.Instance == null) new GameObject("GameInput").AddComponent<GameInput>();
            ApplyPlayerTransform();
        }

        static int ParseMask(string layers)
        {
            var mask = 0;
            foreach (var s in (layers ?? "").Split(','))
                if (int.TryParse(s.Trim(), out var l) && l >= 0 && l < 32) mask |= 1 << l;
            return mask;
        }

        void CreatePlayer()
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            go.name = "Player";
            go.hideFlags = HideFlags.DontSave;
            DestroyImmediate(go.GetComponent<Collider>());
            go.transform.SetParent(transform, false);
            go.transform.localScale = new Vector3(0.6f, 0.45f, 0.6f);
            var mr = go.GetComponent<MeshRenderer>();
            var m = new Material(_materials.Shader) { color = new Color(0.9f, 0.2f, 0.2f), hideFlags = HideFlags.HideAndDontSave };
            mr.sharedMaterial = m;
            _player = go.transform;
        }

        void SetupCamera()
        {
            _camera = cameraOverride != null ? cameraOverride : Camera.main;
            if (_camera == null) _camera = new GameObject("FieldCamera", typeof(Camera)).GetComponent<Camera>();
            _camera.fieldOfView = _camSettings.FovDegrees;
            _camera.nearClipPlane = 0.5f;
            _camera.farClipPlane = 400f;
            _camera.clearFlags = CameraClearFlags.SolidColor;
            _camera.backgroundColor = new Color(0.45f, 0.62f, 0.85f);
            _focus = FieldCameraMath.Focus(Mover.WorldX, Mover.Height, Mover.WorldZ);
            ApplyCamera();
        }

        void ApplyCamera()
        {
            var pos = FieldCameraMath.Position(_focus, _camSettings.PitchDegrees, 0f, _camSettings.TargetRange);
            _camera.transform.SetPositionAndRotation(new Vector3(pos.X, pos.Y, pos.Z), Quaternion.Euler(_camSettings.PitchDegrees, 0f, 0f));
        }

        void ApplyPlayerTransform()
        {
            _player.position = new Vector3(Mover.WorldX, Mover.Height + 0.45f, Mover.WorldZ);
            _player.rotation = Quaternion.Euler(0f, Mover.Facing.YawDegrees(), 0f);
        }

        void Update()
        {
            if (!Loaded) return;
            _fpsFrames++; _fpsTimer += Time.unscaledDeltaTime;
            if (_fpsTimer >= 0.5f) { _fps = _fpsFrames / _fpsTimer; _fpsFrames = 0; _fpsTimer = 0f; }

            _accumulator += Mathf.Min(Time.unscaledDeltaTime, 0.25f);
            while (_accumulator >= LogicStep)
            {
                _accumulator -= LogicStep;
                LogicTick(LogicStep);
            }
        }

        void LogicTick(float dt)
        {
            var held = MoveDir.None;
            var run = false;
            var input = GameInput.Instance;
            if (input != null)
            {
                var m = input.Move;
                held = FieldInputMath.LimitToFourWay(m.x, m.y);
                run = input.IsPressed(GameButton.B);
            }
            TickLogic(dt, held, run);
        }

        // Ein Logikschritt mit gegebener Eingabe (auch für Tests und Skripte).
        public MoveEvents TickLogic(float dt, MoveDir held, bool run)
        {
            var ev = Mover.Tick(dt, held, run);
            LogicTicks++;
            ApplyPlayerTransform();
            var goal = FieldCameraMath.Focus(Mover.WorldX, Mover.Height, Mover.WorldZ);
            _focus = FieldCameraMath.Follow(_focus, goal, cameraFollowRate, dt);
            ApplyCamera();
            return ev;
        }

        void OnGUI()
        {
            if (!Loaded)
            {
                GUI.Label(new Rect(8, 8, 600, 24), Error != null ? "Fehler: " + Error : "Lade Zone " + zoneId + " ...");
                return;
            }
            var cell = Collision.CellAt(Mover.GridX, Mover.GridY);
            _hud = "Zone " + zoneId + "  Zelle (" + Mover.GridX + ", " + Mover.GridY + ")  Höhe " + Mover.Height.ToString("F2") +
                   "\nAttribut Code " + cell.Code + " Stop " + cell.Stop + "  Blick " + Mover.Facing + "  Sperre " + Mover.LastBlock +
                   "\n" + _fps.ToString("F0") + " fps, Logik 30 Hz, Schritte " + Mover.StepsTaken;
            GUI.Label(new Rect(8, 8, 700, 60), _hud);
        }

        public void Unload()
        {
            if (_provider != null)
            {
                if (_bundleName != null) { try { _provider.Release(_bundleName); } catch (Exception) { } _bundleName = null; }
            }
            if (MapRoot != null) Destroy(MapRoot);
            if (_player != null) Destroy(_player.gameObject);
            _materials?.Destroy();
            Loaded = false;
        }
    }
}
