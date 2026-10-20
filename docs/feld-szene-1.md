# First Field Scene (Todo `ap-field`, Slice 1)

> **Historical:** Unity implementation, discontinued. Retained as a reference for scene data and measurements.

Status: 2026-10-19. Code: `unity/Assets/Scripts/Field` (assemblies `Xnu.Field`, `Xnu.Field.Editor`); tests: `unity/Assets/Tests/EditMode/FieldTests.cs` (53 tests, synthetic data); scene: `unity/Assets/Scenes/FieldTest.unity` (camera, `DisplayController`, `GameInput`, `FieldController` only; no game data).
All figures come from main Editor 6000.3.26f1 (macOS, Metal, M1 Pro) and local dump. Maps are built at runtime from original bundles; none of the data is in repository. Evidence (screenshots, Ghidra output) only under `work/field/` and `work/decomp/field/`.

## 1. Summary
- Loading a zone, building map from bundle, and moving player through attribute grid using input layer (`Xnu.Input`) **works** for field map (Zone 422, Twinleaf start) and an interior (Zone 425), using real attribute data, 30 Hz logic, and camera parameters from master data.
- **No material or shader from dump is rendered.** Shader bundle is not loaded; every map material is replaced with a custom Unlit material during construction. After each build, `CountForeignMaterials` counts renderers using foreign shaders (measured: always 0).
- Attribute decoding (code × 1000 + stop; second matrix with height threshold), coordinate system (X mirrored), and collision rules were derived from decompiled game logic (Ghidra, `work/decomp/field/`) and checked against data (start cell walkable, pond is water, stairs are warp).
- Memory: building map only for zone and neighboring blocks, then unloading bundle, saves about 85% of textures vs whole prefab (section 9).
- Gaps in section 11; main ones: movement is cell-step rather than original free circular collision; material textures are not read in player yet (Editor only); no zone transitions (warps), NPC/object collision absent.

## 2. Zone Selection

Zone **422** (`フタバタウン`, Twinleaf Town). Rationale: first story zone, small village (2 grid blocks), includes grass, pond, houses, fences, and trees; interior 425 is nearby:
- Story start (Zones 422–426 in `docs/masterdata.md`, section 16), start point in locator 0 of zone: cell (116, 886).
- Field map in bundle `Environments/fields/area001` (23.4 MB file, 1 prefab): outdoor area with grass, trees, houses, pond—typical field layout.
- Same map also contains Route 201 (Zone 354) and lake (346); block filter (section 4) builds only target zone and neighbors.
- Also **425** (player house, 1st floor, bundle `prefab_map/t01r0201`, 2.8 MB, 94 nodes) as small interior test with door, furniture, and stairs.
Select zone in Inspector (`FieldController.zoneId`); `SwitchZone(id)` changes at runtime. Other checked zones: 54 (`ハクタイシティ`, area003) and 367 (Route 209, area005) for memory measurement.

## 3. Code Structure
| File | Purpose |
|---|---|
| `Logic/FieldCoords` | grid ↔ world (section 5) |
| `Logic/AttributeCell`, `ExAttribute` | decode cell value; height decision for second matrix |
| `Logic/AttributeLayer` | attribute grid from `AttributeMatrix` + `AttributeBlock` (32 × 32 per block) |
| `Logic/AttributeCodeTable` | `MapAttributeTable` (Entry/Water/Encount per code), code names |
| `Logic/FieldCollision` | whether cell can be entered (height, bike, swimming), based on `FieldPlayerEntity.CanEntryAttribute` |
| `Logic/GridMover` | grid movement with fixed timestep, speed in cells/s, ground height via `IGroundHeight` |
| `Logic/MoveDir` | directions (up = +Z, right = +X) and four-direction input limit |
| `Logic/FieldCameraMath` | camera pose from tilt, distance, focal point |
| `Runtime/FieldDataSet` | reads master-data JSON (`XNU_MASTERDATA` or `<GameData>/masterdata`), builds zones, grids, attributes |
| `Runtime/FallbackMaterials` | material replacement; `OriginalMaterialInfo` (Editor) reads main texture/color/queue from serialized data |
| `Runtime/FieldMapBuilder` | builds own hierarchy from prefab asset (without instantiation) with meshes, colliders, fallback materials |
| `Runtime/FieldController` | flow: boot → master data → bundle → map → player/camera → 30-Hz loop; measurement log (`FieldMemoryLog`) |
| `Resources/XnuFieldFallbackUnlit.shader` | custom Unlit shader (main texture, color, optional alpha test) |
| `Editor/FieldSceneBuilder` | menu `Xnu/Field/Create FieldTest Scene` |

Change outside field code: `BundleProvider.DependencyFilter` (optional, disabled by default): dependencies for which filter returns `false` are neither loaded nor counted. Field code uses this to filter out all bundles containing `.shader` assets (section 8).

## 4. Map Construction (Bundle Findings)

- Every map bundle has **one prefab** (field: `assets/bg/fields/areaNNN.prefab`; interior: `assets/prefab_field/prefab_map/<map>.prefab`). Meshes, textures, and materials are in same bundle; only dependency is shader bundle `Dpr/shaders` (catalog: `allDependencies = [shaders]`).
- **Field map `area001`:** 6,697 transforms, 6,257 MeshFilter/-Renderer, 111 meshes (258,574 vertices), 124 materials, 1,805 BoxCollider, 16 SphereCollider, 11 MeshCollider, 38 components without scripts. Hierarchy: `Area001` → `Offset` → **block containers** (`T01` Twinleaf, `R201`, `T02`, `R202`, `C01`, `R203`, `L01` …). Each container sits at `(-32 · column, 0, 32 · row)` of zone grid (T01 at (−96, 0, 864) = grid (3, 27)) and contains ground (`P_T_001_Ground_01`), architecture, fences, trees, flowers, grass objects, signs. Zone ID → blocks comes from `ZoneTable` (Zone 422 = cells (3, 27) and (3, 28)).
- **Interior `t01r0201`:** 94 nodes, 85 renderers, 21 BoxColliders; walls/furniture on layer 9, floor on layer 10, shadow surfaces (`RootShadow`) are simple quads. Room corner at (0, 0, 0), extends toward −X / +Z (grid (0..12, 3..12)).
- Layers: 9 = wall/object collision, 10 = floor (141 colliders in field, floor in every interior), 12 = rare (10). Meaning inferred from use.
- Builder filters block containers: target zone plus `blockRadius` (default 1) neighboring blocks. For Zone 422 this is 1,348 of 6,697 nodes (1,284 renderers, 34 distinct meshes, 42,171 vertices, 216 colliders, 34 fallback materials).

## 5. Coordinate System

From decompiled `FieldObjectEntity.get_gridPosition`/`set_gridPosition`: `gx = (int)(0.5 − x)`, `gy = (int)(z + 0.5)`; inverse `x = −gx`, `z = gy`.
- One cell is **1 world unit**; cell centers use integer coordinates. Y is height.
- **X is mirrored:** larger `gx` means farther left on screen. Camera yaw 0 faces +Z; up = +Z = `gy + 1`, right = +X = `gx − 1`.
- Attribute blocks and zone grid are 32 × 32 cells: block = (`gx >> 5`, `gy >> 5`), cell in block = (`gx & 31`, `gy & 31`); zone-grid index = `width · (gy >> 5) + (gx >> 5)` (`GameManager.GetGridZoneID`). Locators and warp positions are grid cells (warp from Zone 425 to Zone 426 is at (10, 3)—exactly cell with code 95).
- Confirmed against data: locator 0 for Zone 422 = (116, 886) lies in block (3, 27); Twinleaf containers are at world X −96…−133.

## 6. Attributes (Collision, Walkability)

**Cell value** (`GameManager.GetAttribute`): if `raw < 1000`, only *Stop* (code 0); otherwise Code = `raw / 1000`, Stop = `raw % 1000`.
- **Stop 128 blocks** cell (wall, counter, furniture). Main matrices contain only Stop 0 (947,807 cells) and 128 (526,272 cells), plus 8 cells with other values (8, 12, 100).
- **Code** indexes `MapAttributeTable` (row = code, 256 rows): `Entry` (enterable; 136 codes yes, 120 no), `Water` (18 codes), `Encount` (24 codes, grass/water), `Attribute` (subtype, often 255).
- Examples (from dump enum/data): 0 ground; 2/4–7/9/10 grass (`IsGrass`); 3 tall grass; 16 pond; 21 ocean; 22/23 shallow water/swamp (not `Water`); 94/95 right/left stairs; 101 lower door mat; 105 door; 128 counter; 113–125 bridges; 215/216 ledge jump (`Entry` = 0, blocked on foot anyway).
- **Second matrix** (`AttributeEx`, block names suffixed `_Ex`; 1,439 blocks): `raw = H · 1,000,000 + upper · 1000 + lower`. If `H ≤ (int)(height + 100.5)` (height 0 corresponds to H = 100), use middle value (player stands on bridge); otherwise lower value (`HeightAttribute`/`IsHighAttribute`). Evaluated only for bridge codes.
- Outside matrix or absent block, original returns code 0 / Stop 0 (walkable). `FieldCollision.OutsideBlocked` (enabled by default) blocks these cells—intentional deviation.

**Enterability** (`FieldPlayerEntity.CanEntryAttribute`, inputs height, cell, bike, swimming):
1. Stop = 128, no table row, or `Entry` = 0 → no.
2. Bridge code (113–125): player **below** bridge and water cell and swimming → yes; **above**: water cell and not swimming → yes; otherwise on land, on foot: vertical (118–121) or horizontal (122–125) bridge → no.
3. Bike: `Attribute` ∈ {3, 0xA1–0xA8} (tall grass, snow, swamp) → no; on foot: `Attribute` ∈ {215, 216} → no.
4. Result: swimmer only in water, walker only on land (`swimming == Water`).
Bridge code names follow decompiled `AttributeID.MATR_IsBridge*`; bridge branches are tested with synthetic data, but not against a real bridge.

**Stairs and heights:** interior stairs are not elevations, but cells with code 94/95 (`MATR_IsRightStairs`/`IsLeftStairs`) that contain a warp to another floor (`MapWarp_T01R0201`: position (10, 3) → Zone 426). Stair cells themselves have Stop 128. Original player height comes from ground raycasts (`CollisionUtility.CollideGround`); here `IGroundHeight` (scene: raycast down against layer 10). Gives height 1.0 at field start and 0.0 inside house; ramp colliders are hit only near player's height (see gaps).

## 7. Movement, Input, Camera

- **Input:** `GameInput.Move` (stick/D-pad/WASD after dead zone) → `FieldInputMath.LimitToFourWay` = `FieldPlayerEntity.LimitedCrossInput` (larger axis wins; horizontal wins ties). Hold `B` to run. Camera “up” is +Z.
- **Speed** (`FieldPlayerEntity.GetMoveSpeed`, `FieldCommonParam`): on foot 3.7, run 7.14 cells/s; bike 9.76/13.11 (indices 2/3, acceleration values 0.3/0.15); snow/swamp/tall grass slow by factors from indices 132–136 (0.75, 0.5, 0.25, 0.5, 0.5). Only walk/run implemented.
- **30 Hz logic:** `FieldController` accumulates `Time.unscaledDeltaTime` and invokes fixed 1/30 s steps; `DisplayController` with `Original30` sets VSync count/target rate. A time step can cross multiple cells (test: 1 s = 3 cells); loop is capped.
- **Original collision is not cell-based:** `FieldGridCollision.CheckGriCollisionMoveEntity` moves a circle (`entityRadius`) freely against cell edges, sliding along walls, with types None/NoEntry/Water/Npc. `GridMover` is the **simplified cell-based implementation** for this slice (one step = one cell, turns only at cell edges, wall = can only turn).
- **Camera** (`FieldCamera.CameraUpdate`): Euler = (tilt, 0 or 180 when system flag 0x305, 0) + offset angles; FOV = `Fov` + `fovOffset`; focal point = target + offset + (0; 0.5; 0); position = focal point − view direction · `TargetRange`. Values from `MapInfo.Camera`: **one row per zone** (658 rows, index = zone ID; `ariaID` is region and repeats). Zone 422: tilt 45°, FOV 17.5°, distance 30; Zone 425: 45°, 20°, 30; Route 201 (354): 35°, 15°, 30. Original focal-point follow rate (`_cameraLerpRate`) unknown (assumed 12/s). Depth of field (`defocusStart/End`) and shake not implemented.

## 8. Rendering Rule and Material Replacement

- **Never load shader bundle:** `BundleProvider.DependencyFilter` excludes `Dpr/shaders` (and any bundle with `.shader`/`.shadervariants`). Map materials then refer to error shader, but are never drawn: `FieldMapBuilder` does **not** instantiate prefab; it reads Transform/Mesh/Collider from asset and assigns custom fallback materials.
- **Crash finding:** with shader bundle loaded, even reading material/shader properties (`Material.GetTexturePropertyNames`, `Shader.GetPropertyCount`) crashed Editor (SIGSEGV twice during probing). `m.name`, `m.shader.name` were safe. Without shader loaded, prefab/material access via `SerializedObject` (Editor) is stable. Therefore `OriginalMaterialInfo` reads main texture (`_MainTex`), scale/offset, `_Color`, and `m_CustomRenderQueue` directly from `m_SavedProperties`. **Editor only**; in player fallback material remains gray until custom material-reading path (exporter or serialized-data parser) exists.
- Fallback shader `Xnu/FieldFallbackUnlit`: main texture × color, no lighting, does not recreate original look (alpha test at 0.5 only for queue ≥ 2450 and texture with alpha channel). Screenshots (`work/field/shots/field1–4.png`) show map with this shader; gamma color space and Built-in pipeline as in `docs/render-treue.md`.
- Safeguard: after each build `CountForeignMaterials` must equal 0 or loading aborts.

## 9. Memory (Stream, Unload, Peak)

Measurement log: `FieldMemoryLog` per load stage (Unity counters, graphics driver, textures, process memory). Editor itself uses about 300 MB (Unity) and 750–950 MB (process); differences are informative.
Flow: `Acquire` (open bundle, without shader) → load prefab (all prefab textures/meshes) → clone target zone and neighboring blocks only → `Release` (unload bundle, `Unload(false)`) → `Resources.UnloadUnusedAssets`.

| Zone (bundle, file) | Textures before | after prefab load (peak) | after unload | graphics driver before → peak | Fallback materials |
|---|---:|---:|---:|---:|---:|
| 422 (`fields/area001`, 23.4 MB) | 30 MB | 76 MB (+46) | 33 MB (+3) | 139 → 197 MB | 34 |
| 54 (`fields/area003`, 33.2 MB) | 30 MB | 82 MB (+52) | 43 MB (+13) | 152 → 218 MB | 112 |
| 367 (`fields/area005`, 34.5 MB) | 30 MB | 89 MB (+59) | 38 MB (+8) | 166 → 242 MB | 73 |
| 425 (`prefab_map/t01r0201`, 2.8 MB) | 30 MB | 36 MB (+6) | 33 MB (+3) | 134 → 141 MB | 39 |

- Times: catalog 0.5 s, master-data JSON 1.0–1.1 s (20 MB `AttributeBlock.json` briefly adds 150–170 MB to process), bundle open 10 ms, prefab load 0.26–0.30 s (field), build 20–40 ms, unload/cleanup about 0.4 s. Zone switch (`SwitchZone`, catalog/master data retained) takes 0.3–0.4 s without cleanup.
- **Peak** = prefab load: prefab loads all textures for entire region (up to +59 MB texture, +76 MB graphics driver). After build/unload only +3 to +13 MB textures remain; about 85% is freed. Editor process peak 1.0–1.14 GB (about 0.75–0.95 GB Editor baseline).
- These are Editor values (some textures decompressed, Mac graphics memory); iPad/Switch values not measured (`docs/ios-speicher-entitlements.md` gives budget).
- Runtime streaming of blocks while walking does not exist: filtering only happens at load. A proper solution needs bundle splitting by block or loading prefab per zone transition.

## 10. Tests and Reproduction

- `FieldTests.cs`: coordinates (mirror, cell boundaries, blocks), cell-value decoding, height selection, layers (gaps, wrong block width), rules (wall, water, ledge jump, bike, bridges, outside area), input (horizontal tie-break), camera (pose, yaw, follow), `GridMover` (step duration, chaining, running, wall, water/swim, direction change, large timestep, stair height, bridge height, teleport), master data (zone blocks, collision, per-zone camera), and bundle filter (fake source). Full `Xnu.Tests.EditMode`: passing (375 tests, 53 field tests).
- Real data: set `XNU_GAMEDATA=<Repo>/work`, open `FieldTest`, press Play (input works only when Game view focused; `simulate_key` does not work without focus because of `backgroundBehavior`). Without focus, call `FieldController.TickLogic(dt, direction, running)` directly. Sample run: start (116, 886), blocked moving down (Stop), 11 cells right in 3 s, `Water` at pond edge, height 1.00.
- Recreate scene: menu `Xnu/Field/Create FieldTest Scene` or `Xnu.Field.Editor.FieldSceneBuilder.CreateScene()`.

## 11. Gaps and Next Steps
1. **Free movement with circular collision** (`CheckGriCollisionMoveEntity`, `entityRadius`, side/vertical directions, sliding) instead of cell steps; decompiles at `work/decomp/field/b/Dpr_FieldGridCollision.c`.
2. **Zone transitions/warps:** model `MapWarp` per map (grid-cell position, `WarpZone`, entry direction) and connect to `SwitchZone`; enables doors/stairs (codes 94/95/101/105).
3. **Heights/ramps:** ground height via ray only near player height; outdoor stairs (`P_OutStair`) and climbing/ledge jumps (codes 56–59, 215/216, 75/76) missing. Check common floor plane for layer 10.
4. **Material data in player:** main texture/color readable only in Editor. Need material-property exporter or custom serialized-data reader; later shader port (`docs/shader-translator.md`). **Status:** material remapping (export, variant selection, `MaterialRemapper`) is documented in `docs/material-remap.md`; Unity retains serialized material properties even without shader (section 2 there), so a serialization reader is unnecessary.
5. **Block streaming**, water/grass effects, lighting/shadows, fog, weather, day/night (zone's `RenderSettings` object); background music remains off.
6. NPCs, objects (`PlaceData`), trainers, encounters (code → `FieldEncountTable`), bike/swim states (parameters exist), snow/swamp speed.
7. Camera: follow rate, shake, event camera, pan camera (`RoomPanCamera`), depth of field; yaw flag 0x305.
8. Verify bridge codes on real data; store all `AttributeID.MATR_*` as enum (cell → meaning, debug display).
9. Measure on iPad (memory, 30 Hz) and with shader port approved.
