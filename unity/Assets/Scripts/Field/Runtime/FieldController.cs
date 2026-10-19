using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Profiling;
using Xnu.Boot;
using Xnu.Core;
using Xnu.Data;
using Xnu.Input;
using Xnu.Render;

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

    // Feld-Szene (Scheibe 2): lädt eine Zone aus den Original-Bundles, streamt die Karte blockweise um den Spieler,
    // wechselt Zonen über Warps, Türen und Zonengrenzen (mit Überblendung und Speichermessung), zeigt Spielerfigur und NPCs
    // und reicht Interaktionen an einen IFieldInteractionHandler weiter. Logik läuft mit 30 Hz. Nur Hauptthread;
    // keine Spieldaten im Szenenasset, alles entsteht zur Laufzeit. Kein Ton.
    [DisallowMultipleComponent]
    public sealed class FieldController : MonoBehaviour
    {
        public const float LogicStep = 1f / 30f;

        [Header("Zone")]
        [Tooltip("Zonen-ID aus ZoneTable/MapInfo. 422 = Zwieblüh-Start (Twinleaf Town, Feldkarte fields/area001); 425 = Spielerhaus 1. Stock.")]
        public int zoneId = 422;
        [Tooltip("Nur ohne Streaming: Nachbarblöcke (je 32 Zellen), die zusätzlich zur Zone gebaut werden.")]
        [Range(0, 3)] public int blockRadius = 1;
        [Tooltip("Index des Startpunkts in den Locators der Zone.")]
        public int spawnLocator;
        [Tooltip("Ebenen (Layer-Nummern, durch Komma) mit Bodenkollision für die Höhe.")]
        public string groundLayers = "10";
        [Tooltip("Nur ohne Streaming: Bundle nach dem Bau entladen (spart Speicher, aber keine weiteren Blöcke).")]
        public bool unloadBundleAfterBuild = true;

        [Header("Streaming")]
        [Tooltip("Blöcke (32 x 32 Zellen) um den Spieler laden/entladen; das Bundle bleibt für das Gebiet geladen.")]
        public bool streaming = true;
        [Tooltip("Ladeabstand in Zellen zum Blockrand; 0 = aus der Kamera berechnet (sichtbarer Radius + 8).")]
        public int loadDistance;
        [Tooltip("Zusätzliche Zellen jenseits des Ladeabstands, ab denen ein Block entladen wird.")]
        public int unloadMargin = 8;
        [Tooltip("Speicherziel in MB (iPad: 2,5 GB gesamt). Bei Überschreitung der Warnschwelle schrumpft der Ladeabstand.")]
        public int memoryBudgetMB = 2500;

        [Header("Darstellung")]
        public bool usePlayerModel = true;
        [Tooltip("Charakter-Bundle der Spielerfigur (fc0001_00 = Junge, fc0002_00 = Mädchen).")]
        public string playerModelBundle = "Characters/persons/field/fc0001_00";
        public bool showNpcs = true;
        [Tooltip("Erzeugte Shader (Xnu/Render/Sync Generated Shaders) für den Material-Umbau; sonst Ersatzmaterial. Standard aus: " +
                 "im Haupt-Editor zeichnete der Umbau schwarz bzw. blockierte den Editor (docs/feld-szene-2.md, Kapitel 6). Umgebungsvariable XNU_GENERATED_SHADERS=1 schaltet ein.")]
        public bool useGeneratedShaders = false;
        [Tooltip("Gier der Kamera in Innenräumen (180 = Tür unten im Bild, Annahme, siehe docs/feld-szene-2.md).")]
        public float roomCameraYaw = 180f;

        [Header("Zonenwechsel")]
        public float fadeOutSeconds = 0.25f;
        public float fadeInSeconds = 0.25f;

        [Header("Kamera")]
        public Camera cameraOverride;
        [HideInInspector] public bool headlessUnload;   // Prüfwerkzeug ohne Spielmodus: Assets sofort entladen
        [Tooltip("Folgegeschwindigkeit des Brennpunkts (Annahme, Originalwert nicht ermittelt).")]
        public float cameraFollowRate = 12f;

        public FieldDataSet Data { get; private set; }
        public ZoneInfoRecord Zone { get; private set; }
        public FieldCollision Collision { get; private set; }
        public GridMover Mover { get; private set; }
        public FieldMemoryLog Memory { get; private set; }
        public MapBuildStats BuildStats { get; private set; }
        public GameObject MapRoot { get; private set; }
        public FieldAreaStreamer Streamer { get; private set; }
        public FieldInteraction Interaction { get; private set; }
        public ScreenFade Fade { get; } = new ScreenFade();
        public PlayerAvatar Avatar { get; private set; }
        public bool Loaded { get; private set; }
        public bool InTransition { get; private set; }
        public string Error { get; private set; }
        public int ForeignMaterials { get; private set; } = -1;
        public int LogicTicks { get; private set; }
        public string MaterialMode { get; private set; } = "";
        public string AvatarNote { get; private set; } = "";
        public BudgetState Budget { get; private set; }
        public int EffectiveLoadDistance { get; private set; }
        public int TransitionsDone { get; private set; }
        public int NpcCount => _npcs != null ? _npcs.LiveCount : 0;
        public readonly List<string> TransitionReports = new List<string>();
        public Transform Player => _player;
        public int ZoneIdNow => zoneId;

        BundleProvider _provider;
        FallbackMaterials _fallback;
        IMapMaterialSource _materials;
        FieldMapBuilder _builder;
        FieldNpcView _npcs;
        Transform _player;
        GameObject _capsule;
        Camera _camera;
        GameObject _prefab;
        float _accumulator;
        (float X, float Y, float Z) _focus;
        FieldCameraSettings _camSettings;
        float _camPitch, _camFov, _camRange;
        float _yaw;
        string _bundleName;
        SpawnPoint? _spawn;
        string _hud = "";
        float _fpsTimer; int _fpsFrames; float _fps;
        bool _aLatch;
        MemoryBudget _budgetCalc;
        RaycastGround _ground;
        List<PlacementRecord> _mapPlacements = new List<PlacementRecord>();
        int _lastStreamX = int.MinValue, _lastStreamY = int.MinValue;
        bool _globalsSet;
        Light _sun;

        void Start()
        {
            if (Interaction == null) EnsureInteraction();
            StartCoroutine(Load());
        }

        void OnDestroy() => Unload();

        void EnsureInteraction()
        {
            Interaction = new FieldInteraction(new PlacementDirectory(new PlacementRecord[0]))
            {
                Handler = new LoggingInteractionHandler { Log = Debug.Log },
            };
        }

        // Ereignisschnittstelle: der spätere Event-Interpreter setzt hier seinen Handler.
        public IFieldInteractionHandler InteractionHandler
        {
            get => Interaction?.Handler;
            set { if (Interaction == null) EnsureInteraction(); Interaction.Handler = value; }
        }

        public IEnumerator Load()
        {
            Memory = Memory ?? new FieldMemoryLog();
            Memory.Mark("Start Zone " + zoneId);
            Error = null;
            try { Prepare(); }
            catch (Exception e) { Fail(e); yield break; }

            try { LoadMapPrefab(); }
            catch (Exception e) { Fail(e); yield break; }

            try { BuildScene(); }
            catch (Exception e) { Fail(e); yield break; }

            if (!streaming && unloadBundleAfterBuild && _bundleName != null)
            {
                _prefab = null;
                _provider.Release(_bundleName);
                _bundleName = null;
                Memory.Mark("Bundle entladen (Objekte bleiben)");
                yield return UnloadUnused();
                Memory.Mark("Ungenutzte Assets entladen");
            }
            Loaded = true;
            Debug.Log("[Field] Zone " + zoneId + " geladen (" + MaterialMode + ").\n" + BuildStats + "\n" + Memory);
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
                Interaction = new FieldInteraction(Data.Placements, null) { Handler = Interaction?.Handler ?? new LoggingInteractionHandler { Log = Debug.Log } };
                Memory.Mark("Stammdaten (Zonen, Attribute, " + Data.Warps.WarpCount + " Warps, " + Data.Placements.Count + " Platzierungen) gelesen");
            }
            if (_fallback == null) _fallback = new FallbackMaterials();
            _budgetCalc = new MemoryBudget(memoryBudgetMB * 1024L * 1024L);
            ApplyZoneData(zoneId);
        }

        // Zonendaten (Kollision, Kamera, Gier) für die Zone; Karte und Spieler bleiben unberührt.
        void ApplyZoneData(int id)
        {
            if (!Data.TryGetZone(id, out var zone)) throw new InvalidDataException("Unbekannte Zone " + id);
            Zone = zone;
            zoneId = id;
            Collision = Data.BuildCollision(zone);
            if (!Data.TryGetCamera(zone.ZoneId, out var cam)) throw new InvalidDataException("Keine Kamera für Zone " + zone.ZoneId);
            _camSettings = new FieldCameraSettings(cam.Pitch, cam.Fov, cam.TargetRange);
            _yaw = zone.IsField ? 0f : roomCameraYaw;
            if (_camera == null) { _camPitch = cam.Pitch; _camFov = cam.Fov; _camRange = cam.TargetRange; }
            var list = new List<PlacementRecord>();
            var key = string.IsNullOrEmpty(zone.AssetBundleName) ? "" : zone.AssetBundleName.Substring(zone.AssetBundleName.LastIndexOf('/') + 1).ToUpperInvariant();
            foreach (var z in Data.ZonesWithMapName(key)) list.AddRange(Data.Placements.InZone(z));
            if (list.Count == 0) list.AddRange(Data.Placements.InZone(id));
            _mapPlacements = list;
        }

        // Wechselt zur Zone (mit Überblendung): lädt Karte und platziert den Spieler am Locator `spawnLocator`.
        public IEnumerator SwitchZone(int newZoneId)
        {
            if (!Data.Router.TryResolveSpawn(newZoneId, spawnLocator, out var sp))
                sp = new SpawnPoint(newZoneId, 0, 0, MoveDir.Down, spawnLocator);
            var t = new ZoneTransition
            {
                Kind = TransitionKind.Warp, FromZone = zoneId, TargetZone = newZoneId, HasSpawn = sp.GridX != 0 || sp.GridY != 0,
                Spawn = sp, NeedsMapLoad = true, NeedsFade = true,
            };
            return RunTransition(t);
        }

        // Shader-Bundles der Originalspiel-Shader dürfen nicht geladen werden (Switch-Binärcode, Editor-Absturz).
        public static bool IsShaderBundle(BundleRecord r)
        {
            if (r.Name == "shaders" || r.Name.EndsWith("/shaders", StringComparison.Ordinal)) return true;
            foreach (var p in r.AssetPaths)
                if (p.EndsWith(".shader", StringComparison.OrdinalIgnoreCase) || p.EndsWith(".shadervariants", StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        void LoadMapPrefab()
        {
            if (string.IsNullOrEmpty(Zone.AssetBundleName)) throw new InvalidDataException("Zone " + zoneId + " hat kein Kartenbundle");
            _bundleName = "Environments/" + Zone.AssetBundleName;
            var handle = _provider.Acquire(_bundleName);
            Memory.Mark("Bundle " + _bundleName + " geöffnet");
            var names = handle.GetAllAssetNames();
            if (names.Length == 0) throw new InvalidDataException("Bundle ohne Assets: " + _bundleName);
            _prefab = handle.LoadAsset(names[0], typeof(GameObject)) as GameObject;
            if (_prefab == null) throw new InvalidDataException("Kartenprefab nicht ladbar: " + names[0]);
            Memory.Mark("Prefab geladen (Meshes, Texturen, Materialien)");
        }

        // Material-Umbau, wenn Shader, Variantentabelle und Materialexport des Bundles vorhanden sind; sonst Ersatzmaterial.
        IMapMaterialSource CreateMaterials(string bundleName)
        {
            MaterialMode = "Ersatzmaterial";
            if (!useGeneratedShaders && Environment.GetEnvironmentVariable("XNU_GENERATED_SHADERS") != "1") return _fallback;
            try
            {
                var index = GeneratedShaderLibrary.LoadIndex(out var src);
                if (index == null) { MaterialMode = "Ersatzmaterial (keine variants.json)"; return _fallback; }
                var file = GeneratedShaderLibrary.MaterialFileFor(bundleName);
                if (!File.Exists(file)) { MaterialMode = "Ersatzmaterial (kein Materialexport " + Path.GetFileName(file) + ")"; return _fallback; }
                var findable = GeneratedShaderLibrary.CountFindable(index, out var total);
                if (findable == 0) { MaterialMode = "Ersatzmaterial (erzeugte Shader nicht im Projekt, 0/" + total + ")"; return _fallback; }
                var catalog = new MaterialCatalog();
                catalog.LoadJson(File.ReadAllText(file));
                MaterialMode = "Umbau (Shader " + findable + "/" + total + ", " + catalog.Count + " Materialeinträge)";
                return new RemappedMaterials(_fallback, catalog, index, bundleName);
            }
            catch (Exception e)
            {
                MaterialMode = "Ersatzmaterial (Umbau-Fehler: " + e.Message + ")";
                return _fallback;
            }
        }

        void BuildScene()
        {
            _materials = CreateMaterials(_bundleName);
            if (_materials is RemappedMaterials) EnsureRenderEnvironment();
            _builder = new FieldMapBuilder(_materials);
            Streamer = new FieldAreaStreamer(_prefab, _builder, transform, "Map_" + zoneId);
            MapRoot = Streamer.Root;
            BuildStats = _builder.Stats;
            Memory.Mark("Kartengerüst gebaut (" + Streamer.ContainersAvailable + " Blockcontainer in " + CountBlocks() + " Blöcken)");

            // Startpunkt: ausdrücklicher Spawn (Zonenwechsel) oder Locator (x, y) = Rasterzelle, z = Blickrichtung (Viertel).
            SpawnPoint sp;
            if (_spawn.HasValue) sp = _spawn.Value;
            else if (!Data.Router.TryResolveSpawn(zoneId, spawnLocator, out sp)) sp = new SpawnPoint(zoneId, 0, 0, MoveDir.Down, spawnLocator);
            _spawn = null;

            _ground = new RaycastGround(ParseMask(groundLayers));
            ComputeLoadDistance();
            _lastStreamX = int.MinValue;
            StreamAt(sp.GridX, sp.GridY, true);
            ForeignMaterials = _builder.CountForeignMaterials(MapRoot);
            if (ForeignMaterials != 0) throw new InvalidOperationException("Karte enthält " + ForeignMaterials + " Materialien ohne erlaubten Shader");
            Memory.Mark("Karte gebaut (" + BuildStats.Renderers + " Renderer, " + Streamer.Loaded.Count + " Blöcke, " + MaterialMode + ")");

            CreateMover(sp.GridX, sp.GridY, sp.Facing, null);
            CreatePlayer();
            SetupCamera();
            if (GameInput.Instance == null) new GameObject("GameInput").AddComponent<GameInput>();
            RefreshNpcs();
            ApplyPlayerTransform();
        }

        // Die erzeugten Shader lesen Licht und Spiel-Globals: ein Richtungslicht (ohne Licht bleibt das Forward-Bild schwarz) und
        // die Platzhalterwerte der Spiel-Globals (keine Originalwerte, docs/material-remap.md Abschnitt 6).
        void EnsureRenderEnvironment()
        {
            if (!_globalsSet)
            {
                new GameGlobals(new UnityGlobalSink()).SetDefaults();
                _globalsSet = true;
            }
            if (_sun == null)
            {
                foreach (var l in FindObjectsByType<Light>(FindObjectsSortMode.None))
                    if (l.type == LightType.Directional) { _sun = l; break; }
            }
            if (_sun == null)
            {
                var go = new GameObject("FieldSun") { hideFlags = HideFlags.DontSave };
                go.transform.SetParent(transform, false);
                go.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
                _sun = go.AddComponent<Light>();
                _sun.type = LightType.Directional;
                _sun.color = Color.white;
                _sun.intensity = 1f;
                _sun.shadows = LightShadows.None;
            }
        }

        int CountBlocks()
        {
            var n = 0;
            foreach (var _ in Streamer.Available) n++;
            return n;
        }

        void CreateMover(int gx, int gy, MoveDir facing, GridMover previous)
        {
            Mover = new GridMover(Collision, _ground, gx, gy, facing);
            if (previous != null) { Mover.Bicycle = previous.Bicycle; Mover.Swim = previous.Swim; Mover.WalkSpeed = previous.WalkSpeed; Mover.RunSpeed = previous.RunSpeed; }
            Mover.Teleport(gx, gy, facing);
            Mover.IsOccupied = (x, y) => Data.Placements.IsNpcAt(Data.Router.ZoneAtCell(zoneId, x, y), x, y);
        }

        void ComputeLoadDistance()
        {
            var aspect = _camera != null && _camera.aspect > 0f ? _camera.aspect : 16f / 9f;
            var radius = BlockStreamingMath.VisibleRadius(_camSettings.PitchDegrees, _camSettings.FovDegrees, _camSettings.TargetRange, aspect);
            EffectiveLoadDistance = loadDistance > 0 ? loadDistance : BlockStreamingMath.LoadDistanceFor(radius);
        }

        // Blöcke um die Zelle laden/entladen. Ohne Streaming: einmal die Blöcke im Radius `blockRadius` (Zone plus Nachbarn).
        void StreamAt(int gx, int gy, bool force)
        {
            if (Streamer == null) return;
            if (!force && gx == _lastStreamX && gy == _lastStreamY) return;
            _lastStreamX = gx; _lastStreamY = gy;
            if (!Streamer.IsStreaming) { Streamer.LoadAll(); return; }
            if (!streaming)
            {
                if (force) Streamer.Update(gx, gy, blockRadius * FieldCoords.BlockSize, int.MaxValue / 2);
                return;
            }
            var dist = _budgetCalc.AdjustLoadDistance(EffectiveLoadDistance, Budget);
            Streamer.Update(gx, gy, dist, dist + unloadMargin);
            Physics.SyncTransforms();
        }

        void EvaluateBudget()
        {
            var used = Profiler.GetTotalAllocatedMemoryLong() + Profiler.GetAllocatedMemoryForGraphicsDriver();
            Budget = _budgetCalc.Evaluate(used);
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
            if (_player == null)
            {
                _player = new GameObject("Player").transform;
                _player.SetParent(transform, false);
                _player.gameObject.hideFlags = HideFlags.DontSave;
            }
            if (_capsule == null)
            {
                _capsule = GameObject.CreatePrimitive(PrimitiveType.Capsule);
                _capsule.name = "PlayerMarker";
                _capsule.hideFlags = HideFlags.DontSave;
                DestroyImmediate(_capsule.GetComponent<Collider>());
                _capsule.transform.SetParent(_player, false);
                _capsule.transform.localScale = new Vector3(0.6f, 0.45f, 0.6f);
                _capsule.transform.localPosition = new Vector3(0f, 0.45f, 0f);
                var m = new Material(_fallback.Shader) { color = new Color(0.9f, 0.2f, 0.2f), hideFlags = HideFlags.HideAndDontSave };
                _capsule.GetComponent<MeshRenderer>().sharedMaterial = m;
            }
            if (Avatar == null && usePlayerModel && !string.IsNullOrEmpty(playerModelBundle))
            {
                Avatar = PlayerAvatar.Create(_provider, _fallback, playerModelBundle, _player, out var note);
                AvatarNote = note;
                if (Avatar != null) _capsule.SetActive(false);
                else Debug.LogWarning("[Field] " + note);
                Memory.Mark("Spielerfigur: " + note);
            }
            if (_npcs == null && showNpcs) _npcs = new FieldNpcView(transform, _fallback.Shader);
        }

        void SetupCamera()
        {
            if (_camera == null)
            {
                _camera = cameraOverride != null ? cameraOverride : Camera.main;
                if (_camera == null) _camera = new GameObject("FieldCamera", typeof(Camera)).GetComponent<Camera>();
                _camera.nearClipPlane = 0.5f;
                _camera.farClipPlane = 400f;
                _camera.clearFlags = CameraClearFlags.SolidColor;
                _camera.backgroundColor = new Color(0.45f, 0.62f, 0.85f);
            }
            _camPitch = _camSettings.PitchDegrees; _camFov = _camSettings.FovDegrees; _camRange = _camSettings.TargetRange;
            _camera.fieldOfView = _camFov;
            _focus = FieldCameraMath.Focus(Mover.WorldX, Mover.Height, Mover.WorldZ);
            ApplyCamera();
        }

        void ApplyCamera()
        {
            var pos = FieldCameraMath.Position(_focus, _camPitch, _yaw, _camRange);
            _camera.fieldOfView = _camFov;
            _camera.transform.SetPositionAndRotation(new Vector3(pos.X, pos.Y, pos.Z), Quaternion.Euler(_camPitch, _yaw, 0f));
        }

        void ApplyPlayerTransform()
        {
            _player.position = new Vector3(Mover.WorldX, Mover.Height + Mover.JumpOffset, Mover.WorldZ);
            _player.rotation = Quaternion.Euler(0f, Mover.Facing.YawDegrees(), 0f);
        }

        void RefreshNpcs()
        {
            if (_npcs == null || Data == null) return;
            _npcs.Refresh(_mapPlacements, Mover.GridX, Mover.GridY, EffectiveLoadDistance, null,
                (x, y) => _ground.TryGetHeight(FieldCoords.WorldX(x), FieldCoords.WorldZ(y), Mover.Height, out var h) ? h : Mover.Height);
        }

        void Update()
        {
            Fade.Tick(Time.unscaledDeltaTime);
            if (!Loaded) return;
            _fpsFrames++; _fpsTimer += Time.unscaledDeltaTime;
            if (_fpsTimer >= 0.5f) { _fps = _fpsFrames / _fpsTimer; _fpsFrames = 0; _fpsTimer = 0f; }
            var input = GameInput.Instance;
            if (input != null && input.WasPressedThisFrame(GameButton.A)) _aLatch = true;

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
            var frozen = InTransition || (Interaction != null && Interaction.Busy);
            if (input != null && !frozen)
            {
                var m = input.Move;
                held = FieldInputMath.ScreenToGrid(FieldInputMath.LimitToFourWay(m.x, m.y), _yaw);
                run = input.IsPressed(GameButton.B);
            }
            if (_aLatch)
            {
                _aLatch = false;
                if (!frozen && !Mover.IsMoving) Interaction?.TryTalk(Zone.ZoneId, Mover.GridX, Mover.GridY, Mover.Facing);
            }
            TickLogic(dt, held, run);
        }

        // Ein Logikschritt mit gegebener Eingabe (auch für Tests und Skripte).
        public MoveEvents TickLogic(float dt, MoveDir held, bool run)
        {
            if (InTransition) { Avatar?.Tick(dt); return MoveEvents.None; }
            var ev = Mover.Tick(dt, held, run);
            LogicTicks++;
            if ((ev & MoveEvents.Arrived) != 0) OnArrived();
            if ((ev & MoveEvents.Bumped) != 0 && !InTransition)
            {
                var t = Data.Router.OnBump(Zone.ZoneId, Mover.GridX, Mover.GridY, Mover.Facing);
                if (t != null) BeginTransition(t);
            }
            if (Avatar != null)
            {
                Avatar.SetState(PlayerAvatar.StateFor(Mover.IsMoving, run));
                Avatar.Tick(dt);
            }
            if (LogicTicks % 30 == 0) EvaluateBudget();
            ApplyPlayerTransform();
            var goal = FieldCameraMath.Focus(Mover.WorldX, Mover.Height, Mover.WorldZ);
            _focus = FieldCameraMath.Follow(_focus, goal, cameraFollowRate, dt);
            var k = Mathf.Clamp01(4f * dt);
            _camPitch = Mathf.Lerp(_camPitch, _camSettings.PitchDegrees, k);
            _camFov = Mathf.Lerp(_camFov, _camSettings.FovDegrees, k);
            _camRange = Mathf.Lerp(_camRange, _camSettings.TargetRange, k);
            ApplyCamera();
            return ev;
        }

        // Schritt beendet: Berührung, Warp, Zonengrenze, Streaming.
        void OnArrived()
        {
            var gx = Mover.GridX;
            var gy = Mover.GridY;
            Interaction?.TryContact(Zone.ZoneId, gx, gy, Mover.Facing);
            var t = Data.Router.OnArrived(Zone.ZoneId, gx, gy) ?? Data.Router.OnZoneGridChange(Zone.ZoneId, gx, gy);
            if (t != null) { BeginTransition(t); return; }
            StreamAt(gx, gy, false);
            RefreshNpcs();
        }

        // Standard: Unity-Coroutine. Prüfwerkzeuge ohne Spielmodus setzen einen eigenen Läufer.
        public Action<IEnumerator> CoroutineRunner;

        public void BeginTransition(ZoneTransition t)
        {
            if (InTransition || t == null) return;
            InTransition = true;
            if (CoroutineRunner != null) CoroutineRunner(RunTransition(t)); else StartCoroutine(RunTransition(t));
        }

        // Streaming sofort an der Spielerzelle ausführen (nach Teleport, in Tests).
        public void ForceStream() { if (Mover != null) StreamAt(Mover.GridX, Mover.GridY, true); }

        // Zonenwechsel: Überblenden, Zone (bei anderem Bundle: Karte entladen und neu laden), Spieler platzieren, einblenden.
        public IEnumerator RunTransition(ZoneTransition t)
        {
            InTransition = true;
            var started = Time.realtimeSinceStartup;
            Memory.Mark("Wechsel " + t);
            var before = Memory.Entries.Count;
            Fade.OutSeconds = t.NeedsFade ? fadeOutSeconds : 0f;
            Fade.InSeconds = t.NeedsFade ? fadeInSeconds : 0f;
            Fade.Begin();
            while (!Fade.IsBlack) yield return null;

            var spawn = t.HasSpawn ? t.Spawn : new SpawnPoint(t.TargetZone, Mover.GridX, Mover.GridY, Mover.Facing, -1);
            var ok = true;
            if (t.NeedsMapLoad)
            {
                var keep = Mover;
                UnloadMap();
                yield return UnloadUnused();
                Memory.Mark("Karte entladen");
                zoneId = t.TargetZone;
                _spawn = spawn;
                yield return Load();
                ok = Error == null;
                if (ok && keep != null) { Mover.Bicycle = keep.Bicycle; Mover.Swim = keep.Swim; }
            }
            else
            {
                try
                {
                    var keep = Mover;
                    ApplyZoneData(t.TargetZone);
                    ComputeLoadDistance();
                    CreateMover(spawn.GridX, spawn.GridY, spawn.Facing, keep);
                    StreamAt(spawn.GridX, spawn.GridY, true);
                    // Weiche Kameraübernahme bei Zonengrenze ohne Sprung; bei Warp harter Schnitt.
                    if (t.Kind != TransitionKind.ZoneEdge) { _focus = FieldCameraMath.Focus(Mover.WorldX, Mover.Height, Mover.WorldZ); _camPitch = _camSettings.PitchDegrees; _camFov = _camSettings.FovDegrees; _camRange = _camSettings.TargetRange; }
                    RefreshNpcs();
                    ApplyPlayerTransform();
                    ApplyCamera();
                    Memory.Mark("Zone " + t.TargetZone + " übernommen (" + Streamer.Loaded.Count + " Blöcke)");
                }
                catch (Exception e) { Fail(e); ok = false; }
            }

            Fade.Release();
            while (Fade.Active) yield return null;
            InTransition = false;
            TransitionsDone++;
            var report = t + (ok ? "" : " – FEHLER " + Error) + ": " + ((Time.realtimeSinceStartup - started) * 1000f).ToString("F0") + " ms" +
                         (Memory.Entries.Count > before ? "; " + Memory.Entries[Memory.Entries.Count - 1] : "");
            TransitionReports.Add(report);
            Debug.Log("[Field] Wechsel " + report);
        }

        void OnGUI()
        {
            if (!Loaded)
            {
                GUI.Label(new Rect(8, 8, 600, 24), Error != null ? "Fehler: " + Error : "Lade Zone " + zoneId + " ...");
            }
            else
            {
                var cell = Collision.CellAt(Mover.GridX, Mover.GridY);
                _hud = "Zone " + zoneId + "  Zelle (" + Mover.GridX + ", " + Mover.GridY + ")  Höhe " + Mover.Height.ToString("F2") +
                       "\nAttribut Code " + cell.Code + " Stop " + cell.Stop + "  Blick " + Mover.Facing + "  Sperre " + Mover.LastBlock +
                       "\nBlöcke " + (Streamer != null ? Streamer.Loaded.Count : 0) + " (Laden " + (Streamer != null ? Streamer.LoadCount : 0) + ", Entladen " + (Streamer != null ? Streamer.UnloadCount : 0) +
                       "), NPCs " + NpcCount + ", Budget " + Budget + "\n" + _fps.ToString("F0") + " fps, Logik 30 Hz, Schritte " + Mover.StepsTaken;
                GUI.Label(new Rect(8, 8, 800, 80), _hud);
            }
            if (Fade.Alpha > 0.001f)
            {
                var old = GUI.color;
                GUI.color = new Color(0f, 0f, 0f, Fade.Alpha);
                GUI.DrawTexture(new Rect(0, 0, Screen.width, Screen.height), Texture2D.whiteTexture);
                GUI.color = old;
            }
        }

        // Nicht mehr referenzierte Assets entladen (nach dem Abbau einer Karte).
        IEnumerator UnloadUnused()
        {
#if UNITY_EDITOR
            if (headlessUnload)
            {
                UnityEditor.EditorUtility.UnloadUnusedAssetsImmediate();
                yield break;
            }
#endif
            var op = Resources.UnloadUnusedAssets();
            while (!op.isDone) yield return null;
        }

        // Karte und Streaming abbauen (Spieler, Daten, Katalog bleiben).
        void UnloadMap()
        {
            Loaded = false;
            _npcs?.Clear();
            if (MapRoot != null) FieldDestroy.Kill(MapRoot);
            MapRoot = null;
            Streamer = null;
            _prefab = null;
            if (_provider != null && _bundleName != null)
            {
                try { _provider.Release(_bundleName); } catch (Exception) { }
                _bundleName = null;
            }
            if (_materials != null && !ReferenceEquals(_materials, _fallback)) _materials.Destroy();
            _materials = null;
        }

        public void Unload()
        {
            UnloadMap();
            _npcs?.Destroy();
            _npcs = null;
            Avatar?.Destroy();
            Avatar = null;
            if (_player != null) FieldDestroy.Kill(_player.gameObject);
            _player = null;
            _capsule = null;
            _fallback?.Destroy();
            _fallback = null;
        }
    }
}
