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
            // Platzierung am Startpunkt: Liegt der Boden über der Ausgangshöhe (Zone 367: Boden bei y = 2, Ausgang 0), von oben suchen.
            if (SpawnSearch && Physics.Raycast(new Vector3(worldX, SpawnSearchHeight, worldZ), Vector3.down, out hit, SpawnSearchHeight + _depth, _mask, QueryTriggerInteraction.Ignore))
            {
                y = hit.point.y;
                return true;
            }
            y = fromY;
            return false;
        }

        public bool SpawnSearch;
        public float SpawnSearchHeight = 60f;
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
        [Tooltip("Erzeugte Shader (Xnu/Render/Sync Generated Shaders) für den Material-Umbau, solange variants.json, Shader und Materialexport vorhanden sind; " +
                 "sonst sauber das Ersatzmaterial (MaterialMode nennt den Grund). Umgebungsvariable XNU_GENERATED_SHADERS=0 schaltet aus, =1 erzwingt ein.")]
        public bool useGeneratedShaders = true;
        [Tooltip("Mit dem Material-Umbau: Tiefentexturen (Wasser), Reflexionskamera und Nachbearbeitung (Bloom, Nebel, FXAA) an der Kamera. " +
                 "Ohne sie zeichnet das Wasser eine einfarbige Fläche.")]
        public bool useRenderRig = true;
        public bool useReflection = true;
        public bool usePostProcessing = true;
        [Tooltip("Nachbearbeitung auch auf einer von außen übergebenen Kamera (cameraOverride). Aus: das Spiel zeichnet seine Oberfläche (Screen Space - Camera) " +
                 "auf dieser Kamera, Bloom und FXAA würden sie mit verändern; der Original-Compositor trennt Welt- und Oberflächenkamera, das ist hier noch offen.")]
        public bool postOnSharedCamera = false;
        [Tooltip("Debug-Text oben links (nur ohne externe Spielschleife).")]
        public bool showHud = true;
        [Tooltip("Spielwerte der Zone (EnvironmentSettings: Licht, Schatten, Spiel-Globals) per EnvironmentDriver setzen, solange der Umbau " +
                 "mit erzeugten Shadern aktiv ist; sonst Platzhalter-Globals und weißes Licht (docs/sichtpruefung-1.md).")]
        public bool useGameEnvironment = true;
        [Tooltip("Stunde (0 bis 24) für die Tageszeit; negativ = lokale Uhr. Umgebungsvariable XNU_ENV_HOUR überschreibt.")]
        public float environmentHour = -1f;
        [Tooltip("Gier der Kamera im Freien. 180 = Blick nach −Z: Zellraster x nach rechts, y nach unten, Haustür unten im Bild (Sichtprüfung Zone 422, docs/sichtpruefung-1.md). " +
                 "0 = Blick nach +Z (frühere Annahme aus docs/feld-szene-1.md: dann liegt die Tür hinter dem Haus).")]
        public float fieldCameraYaw = 180f;
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
        public float CameraYaw { get => _yaw; set => _yaw = value; }
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
        ShaderVariantIndex _index;
        int _shadersFindable, _shadersTotal;
        FieldRenderRig _rig;
        IMapMaterialSource _playerMaterials;
        NpcModels _npcModels;
        public string RigNote => _rig != null ? _rig.ToString() : "aus";
        public int NpcModelCount => _npcs != null ? _npcs.ModelCount : 0;
        public string NpcModelNote => _npcModels != null ? _npcModels.Created + " Modelle, " + _npcModels.Unresolved + " nicht auflösbar" : "";
        Light _sun;
        EnvironmentDriver _envDriver;
        EnvironmentSettingsCatalog _envCatalog;
        bool _envCatalogTried;
        public string EnvironmentNote { get; private set; } = "";

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
                Interaction = new FieldInteraction(Data.Placements, Flags) { Handler = Interaction?.Handler ?? new LoggingInteractionHandler { Log = Debug.Log } };
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
            _yaw = zone.IsField ? fieldCameraYaw : roomCameraYaw;
            if (_camera == null) { _camPitch = cam.Pitch; _camFov = cam.Fov; _camRange = cam.TargetRange; }
            var list = new List<PlacementRecord>();
            var key = string.IsNullOrEmpty(zone.AssetBundleName) ? "" : zone.AssetBundleName.Substring(zone.AssetBundleName.LastIndexOf('/') + 1).ToUpperInvariant();
            // Innenräume teilen sich das Kartenbundle mit gleichartigen Räumen anderer Städte: nur die eigenen Platzierungen zeigen.
            if (zone.IsField) foreach (var z in Data.ZonesWithMapName(key)) list.AddRange(Data.Placements.InZone(z));
            if (list.Count == 0) list.AddRange(Data.Placements.InZone(id));
            _mapPlacements = list;
            ApplyEnvironmentSettings();
        }

        // Wechselt zur Zone (mit Überblendung): lädt Karte und platziert den Spieler am Locator `spawnLocator`.
        public IEnumerator SwitchZone(int newZoneId) => RunTransition(SwitchTransition(newZoneId));

        ZoneTransition SwitchTransition(int newZoneId)
        {
            if (!Data.Router.TryResolveSpawn(newZoneId, spawnLocator, out var sp))
                sp = new SpawnPoint(newZoneId, 0, 0, MoveDir.Down, spawnLocator);
            return new ZoneTransition
            {
                Kind = TransitionKind.Warp, FromZone = zoneId, TargetZone = newZoneId, HasSpawn = sp.GridX != 0 || sp.GridY != 0,
                Spawn = sp, NeedsMapLoad = true, NeedsFade = true,
            };
        }

        // Zonenwechsel für den Spielkern (MAP_CHANGE): Locator der Zielzone, Überblendung, Karte neu laden. false: läuft schon einer.
        public bool BeginSwitchZone(int newZoneId, int locator)
        {
            if (InTransition || Data == null) return false;
            spawnLocator = locator;
            BeginTransition(SwitchTransition(newZoneId));
            return true;
        }

        // Spielerstart an einer Zelle statt am Locator (Spielstand laden); nur vor dem ersten Laden wirksam.
        public void SetStartCell(int gx, int gy, MoveDir facing) => _spawn = new SpawnPoint(zoneId, gx, gy, facing, -1);

        // Flaggen der Ereignisschicht (Work-Flags): bestimmen, welche Objekte aktiv/sichtbar sind.
        public IFieldFlags Flags { get; set; }

        // true: FieldController tickt die Logik nicht selbst; der Spielschleifen-Treiber ruft LogicTickExternal mit 30 Hz.
        public bool ExternalTick { get; set; }

        // Zonenwechsel (nach dem Laden und Einblenden): Zielzone.
        public event Action<int> ZoneChanged;

        public void RefreshNpcsNow() => RefreshNpcs();

        // Ein Logikschritt des Treibers (Eingabe aus GameInput, inklusive A-Taste für Ansprechen).
        public MoveEvents LogicTickExternal(float dt)
        {
            if (!Loaded) return MoveEvents.None;
            var input = GameInput.Instance;
            if (input != null) { input.ApplyOverrideNow(); if (input.WasPressedThisFrame(GameButton.A)) _aLatch = true; }
            return LogicTick(dt);
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
        bool GeneratedShadersWanted()
        {
            var env = Environment.GetEnvironmentVariable("XNU_GENERATED_SHADERS");
            if (env == "0") return false;
            return env == "1" || useGeneratedShaders;
        }

        // Erzeugte Shader, die der Player findet, und die Variantentabelle (einmal je Controller); null mit Grund in MaterialMode.
        ShaderVariantIndex LoadShaderIndex()
        {
            if (_index != null) return _index;
            var index = GeneratedShaderLibrary.LoadIndex(out _);
            if (index == null) { MaterialMode = "Ersatzmaterial (keine variants.json: Xnu/Render/Sync Generated Shaders)"; return null; }
            var findable = GeneratedShaderLibrary.CountFindable(index, out var total);
            if (findable == 0) { MaterialMode = "Ersatzmaterial (erzeugte Shader nicht im Projekt, 0/" + total + ")"; return null; }
            _shadersFindable = findable; _shadersTotal = total;
            _index = index;
            return index;
        }

        // Materialumbau für ein Modellbundle (Figur, NPC); Ersatzmaterial, wenn es keinen Export oder keine Shader gibt.
        IMapMaterialSource CreateModelMaterials(string bundleName)
        {
            try
            {
                if (!GeneratedShadersWanted()) return _fallback;
                var index = LoadShaderIndex();
                var file = index != null ? GeneratedShaderLibrary.FindMaterialFile(bundleName) : null;
                if (file == null) return _fallback;
                var catalog = new MaterialCatalog();
                catalog.LoadJson(File.ReadAllText(file));
                return new RemappedMaterials(_fallback, catalog, index, bundleName);
            }
            catch (Exception e)
            {
                Debug.LogWarning("[Field] Materialumbau für " + bundleName + " nicht möglich: " + e.Message);
                return _fallback;
            }
        }

        IMapMaterialSource CreateMaterials(string bundleName)
        {
            MaterialMode = "Ersatzmaterial";
            if (!GeneratedShadersWanted()) return _fallback;
            try
            {
                var index = LoadShaderIndex();
                if (index == null) return _fallback;
                var file = GeneratedShaderLibrary.FindMaterialFile(bundleName);
                if (file == null) { MaterialMode = "Ersatzmaterial (kein Materialexport " + Path.GetFileName(GeneratedShaderLibrary.MaterialFileFor(bundleName)) + ")"; return _fallback; }
                var catalog = new MaterialCatalog();
                catalog.LoadJson(File.ReadAllText(file));
                MaterialMode = "Umbau (Shader " + _shadersFindable + "/" + _shadersTotal + ", " + catalog.Count + " Materialeinträge)";
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
            AttachRenderRig();
            if (GameInput.Instance == null) new GameObject("GameInput").AddComponent<GameInput>();
            RefreshNpcs();
            ApplyPlayerTransform();
        }

        // Die erzeugten Shader lesen Licht und Spiel-Globals: ein Richtungslicht (ohne Licht bleibt das Forward-Bild schwarz, siehe
        // SunLight) und die Spiel-Globals. Mit useGameEnvironment setzt ein EnvironmentDriver sie je Bild aus den EnvironmentSettings
        // der Zone; ohne Katalog oder ohne Settings der Zone bleiben die Platzhalter (keine Originalwerte, docs/material-remap.md Abschnitt 6).
        void EnsureRenderEnvironment()
        {
            if (!_globalsSet)
            {
                new GameGlobals(new UnityGlobalSink()).SetDefaults();
                _globalsSet = true;
            }
            if (_sun == null) _sun = SunLight.Ensure(transform, LightShadows.Soft);
            if (_envDriver == null && useGameEnvironment)
            {
                _envDriver = _sun.GetComponent<EnvironmentDriver>() ?? _sun.gameObject.AddComponent<EnvironmentDriver>();
                _envDriver.Sun = _sun;
                _envDriver.HourProvider = CurrentHour;
            }
            ApplyEnvironmentSettings();
        }

        // Tiefentexturen, Reflexion und Nachbearbeitung an der Kamera (einmal; bleibt über Zonenwechsel). Hintergrund wie die Hauptkamera
        // der Originalszene: Schwarz (docs/sichtpruefung-2.md, Abschnitt 4).
        void AttachRenderRig()
        {
            if (_rig != null || !useRenderRig || _camera == null || !(_materials is RemappedMaterials)) return;
            _rig = FieldRenderRig.Attach(_camera, _envDriver, useReflection, usePostProcessing && (cameraOverride == null || postOnSharedCamera));
            _camera.backgroundColor = Color.black;
            Memory.Mark("Kamera-Ausstattung: " + _rig);
        }

        // Stunde der Tageszeit: XNU_ENV_HOUR, sonst environmentHour, sonst lokale Uhr.
        public float CurrentHour()
        {
            var env = Environment.GetEnvironmentVariable("XNU_ENV_HOUR");
            if (!string.IsNullOrEmpty(env) && float.TryParse(env, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var h)) return Mathf.Repeat(h, 24f);
            if (environmentHour >= 0f) return Mathf.Repeat(environmentHour, 24f);
            return EnvironmentDriver.SystemHours();
        }

        // Settings der aktuellen Zone in den Treiber; ohne Katalog/Settings wird der Treiber abgeschaltet (Platzhalterwerte bleiben).
        void ApplyEnvironmentSettings()
        {
            if (_envDriver == null) return;
            if (!_envCatalogTried)
            {
                _envCatalogTried = true;
                try
                {
                    var dir = FieldDataSet.DefaultDirectory;
                    var s = Path.Combine(dir, "EnvironmentSettings.json");
                    var z = Path.Combine(dir, "MapRenderSettings.json");
                    if (File.Exists(s) && File.Exists(z))
                    {
                        var c = new EnvironmentSettingsCatalog();
                        c.LoadSettingsJson(File.ReadAllText(s));
                        c.LoadZonesJson(File.ReadAllText(z));
                        _envCatalog = c;
                    }
                }
                catch (Exception e) { Debug.LogWarning("[Field] Umgebungsdaten nicht lesbar: " + e.Message); }
            }
            var settings = _envCatalog?.ForZone(zoneId);
            _envDriver.Settings = settings;
            _envDriver.ZoneFixedTime = _envCatalog?.Zone(zoneId)?.FixedTime ?? false;
            _envDriver.enabled = settings != null;
            EnvironmentNote = settings != null ? "Spielwerte " + settings.Name + ", Stunde " + CurrentHour().ToString("F1")
                : _envCatalog == null ? "Platzhalter (kein EnvironmentSettings.json)" : "Platzhalter (Zone " + zoneId + " ohne Settings)";
        }

        int CountBlocks()
        {
            var n = 0;
            foreach (var _ in Streamer.Available) n++;
            return n;
        }

        void CreateMover(int gx, int gy, MoveDir facing, GridMover previous)
        {
            _ground.SpawnSearch = true;
            Mover = new GridMover(Collision, _ground, gx, gy, facing);
            if (previous != null) { Mover.Bicycle = previous.Bicycle; Mover.Swim = previous.Swim; Mover.WalkSpeed = previous.WalkSpeed; Mover.RunSpeed = previous.RunSpeed; }
            Mover.Teleport(gx, gy, facing);
            _ground.SpawnSearch = false;
            Mover.IsOccupied = (x, y) => Data.Placements.IsNpcAt(Data.Router.ZoneAtCell(zoneId, x, y), x, y, Flags);
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
                _playerMaterials = CreateModelMaterials(playerModelBundle);
                Avatar = PlayerAvatar.Create(_provider, _playerMaterials, playerModelBundle, _player, out var note);
                AvatarNote = note + (ReferenceEquals(_playerMaterials, _fallback) ? " [Ersatzmaterial]" : " [Umbau " + ((RemappedMaterials)_playerMaterials).Remapped + " Materialien, Ersatz " + ((RemappedMaterials)_playerMaterials).FellBack + "]");
                if (Avatar != null) _capsule.SetActive(false);
                else Debug.LogWarning("[Field] " + note);
                Memory.Mark("Spielerfigur: " + AvatarNote);
            }
            if (_npcs == null && showNpcs)
            {
                _npcs = new FieldNpcView(transform, _fallback.Shader);
                if (Data?.CharacterGraphics != null)
                {
                    _npcModels = new NpcModels(_provider, Data.CharacterGraphics, CreateModelMaterials);
                    _npcs.ModelFactory = _npcModels.Create;
                }
            }
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
            _npcs.Refresh(_mapPlacements, Mover.GridX, Mover.GridY, EffectiveLoadDistance, Flags,
                (x, y) => _ground.TryGetHeight(FieldCoords.WorldX(x), FieldCoords.WorldZ(y), Mover.Height, out var h) ? h : Mover.Height);
        }

        void Update()
        {
            Fade.Tick(Time.unscaledDeltaTime);
            if (!Loaded) return;
            _fpsFrames++; _fpsTimer += Time.unscaledDeltaTime;
            if (_fpsTimer >= 0.5f) { _fps = _fpsFrames / _fpsTimer; _fpsFrames = 0; _fpsTimer = 0f; }
            var input = GameInput.Instance;
            if (ExternalTick) return;
            if (input != null && input.WasPressedThisFrame(GameButton.A)) _aLatch = true;

            _accumulator += Mathf.Min(Time.unscaledDeltaTime, 0.25f);
            while (_accumulator >= LogicStep)
            {
                _accumulator -= LogicStep;
                LogicTick(LogicStep);
            }
        }

        MoveEvents LogicTick(float dt)
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
            return TickLogic(dt, held, run);
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
            if (ok) ZoneChanged?.Invoke(zoneId);
            var report = t + (ok ? "" : " – FEHLER " + Error) + ": " + ((Time.realtimeSinceStartup - started) * 1000f).ToString("F0") + " ms" +
                         (Memory.Entries.Count > before ? "; " + Memory.Entries[Memory.Entries.Count - 1] : "");
            TransitionReports.Add(report);
            Debug.Log("[Field] Wechsel " + report);
        }

        // Nur eine Instanz zeichnet den Text (zwei Controller übereinander ergaben unleserlichen Überdruck), und nicht mit externer
        // Spielschleife (dort gehört die Anzeige dem Spiel).
        static FieldController _hudOwner;

        bool HudAllowed()
        {
            if (!showHud || ExternalTick) return false;
            if (_hudOwner == null || !_hudOwner.isActiveAndEnabled) _hudOwner = this;
            return _hudOwner == this;
        }

        void OnGUI()
        {
            if (HudAllowed() && !Loaded)
            {
                GUI.Label(new Rect(8, 8, 600, 24), Error != null ? "Fehler: " + Error : "Lade Zone " + zoneId + " ...");
            }
            else if (HudAllowed())
            {
                var cell = Collision.CellAt(Mover.GridX, Mover.GridY);
                _hud = "Zone " + zoneId + "  Zelle (" + Mover.GridX + ", " + Mover.GridY + ")  Höhe " + Mover.Height.ToString("F2") +
                       "\nAttribut Code " + cell.Code + " Stop " + cell.Stop + "  Blick " + Mover.Facing + "  Sperre " + Mover.LastBlock +
                       "\nBlöcke " + (Streamer != null ? Streamer.Loaded.Count : 0) + " (Laden " + (Streamer != null ? Streamer.LoadCount : 0) + ", Entladen " + (Streamer != null ? Streamer.UnloadCount : 0) +
                       "), NPCs " + NpcCount + " (Modelle " + NpcModelCount + "), Budget " + Budget + "\n" + _fps.ToString("F0") + " fps, Logik 30 Hz, Schritte " + Mover.StepsTaken;
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
            _npcModels?.Destroy();
            _npcModels = null;
            Avatar?.Destroy();
            Avatar = null;
            if (_playerMaterials != null && !ReferenceEquals(_playerMaterials, _fallback)) _playerMaterials.Destroy();
            _playerMaterials = null;
            _rig?.Detach();
            _rig = null;
            if (_player != null) FieldDestroy.Kill(_player.gameObject);
            _player = null;
            _capsule = null;
            _fallback?.Destroy();
            _fallback = null;
        }
    }
}
