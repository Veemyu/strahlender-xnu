# Visual Review 3: Field Rendering with Generated Shaders, Player/NPCs, Pokémon, and Town Save (Todo `ap-effects-fidelity`, Part 5)

> **Historical report:** This describes the deprecated Unity rebuild. The native static recompilation is the current product; this report is retained as project history.

Status: 2026-10-19, Unity 6000.3.26f1 (lab `work/unity-shader-lab` and main Editor `unity/`), Built-in Render Pipeline, Gamma, Metal, Apple M1 Pro. Only our generated shaders are drawn (no original shader loaded), no audio. Images, exports, and generated shaders live under `work/` (`work/visual/fieldrender/`, `…/stadt/`), not in the repository; this document records measurements and findings. Capture: main camera to a 1280 × 720 `RenderTexture` at end of frame (`FieldShot.CaptureAtFrameEnd`, main Editor) or `EffectsRunner` (lab).

Notation: **confirmed** = measured/observed; *suspected* = inference without a test.

## 1. Summary

| Question | Result |
|---|---|
| Default | Material remapping with generated shaders is **the default** (`useGeneratedShaders = true`; `XNU_GENERATED_SHADERS=0` disables it, `=1` forces it). Without `variants.json`, a matching shader, or a material export, it falls back cleanly to the replacement material; `MaterialMode` reports the reason. |
| Camera setup | New `FieldRenderRig`: depth textures (`_OpaqueDepthTexture`, `_GlobalDepthTexture`), reflection camera (`_ReflectionTex`), post-processing (bloom, fog, FXAA), black background as in original. |
| Player and NPCs | Player character and all NPC models render with generated shaders (in color). NPCs use character models with idle animations; markers remain fallback. |
| NPC model resolution | Overall: of 4,197 placements, 1,639 have a character index (all 130 distinct model bundles are available), 1,365 have object index ≥142 (unresolved), 1,193 are invisible. Zones: 422: 5/5; 425: 2/2; 54: 14 characters, 12 objects; 367: 18 characters, 10 objects; zone 24 (town): 12 characters, 4 objects. |
| Vertex data | Looks correct (section 4). The “broken” appearance did not come from the meshes. |
| Black/cyan Pokémon | **Cause found and fixed:** integer uniforms in shader wrapper (section 5). Not a translator NaN issue. |
| Zone 167 (user screenshot) | White quads, flat water, smeared rock walls: fixed with generated shaders and camera setup (section 3). |
| Town save (zone 24) | Position read from `PLAYER_DATA` (57, 729); screen-space shadows failed under iOS target, fixed (section 6). |
| Tests | Unity EditMode **763/763** (main Editor), lab 63/63, `test_shader_wrap` 40/40. |

## 2. User screenshot checklist (zone 167, Mac preview)

| # | Observation | Cause | Fix | Evidence |
|---:|---|---|---|---|
| 1 | White rectangular areas at Pokémon Center entrance | Replacement material was the default: glass/fade surfaces (`M_C_001_Grad_01`, `_ALPHABLEND_ON`, `_DEPTHDENSITY_ON`) rendered white without alpha blending (*suspected*, from material dump and image comparison) | Generated shaders as default (variant with `_ALPHABLEND_ON`) | Lab, same cells (840–846, 599): white quads before, glass door after |
| 2 | Water is a flat blue color | Replacement shader has no water support; generated `FlowmapWater` without depth textures rendered a flat color | `FieldRenderRig` (depth, reflection); waves, sparkles, and depth color now appear | Images `after_167`, `after2_167`, town `z24_fix` |
| 3 | Rock walls stretched/smeared, diagonal triangle band | Replacement shader uses one main texture instead of the two-UV `_Cascade` blend (*suspected*, not isolated); no vertex-data fault (section 4) | Generated shaders (`_CASCADE_*` variants) | `before_167` (replacement) vs. `after_167`: stone texture on rock steps, no band |
| 4 | Player character is white/gray | Replacement character shader | Remap model bundle materials (13 remapped, 8 replacements for inactive parts) | Red cap, face, and clothing render in color |
| 5 | HUD text overdrawn | Two `FieldController` instances or two `OnGUI` draws overlap; game scene also has debug text | Only one instance draws (`HudAllowed`); none with external game loop (`ExternalTick`); `showHud` | Source inspection; not measured in image |
| 6 | Black bars left and right | Intentional: `DisplayController` constrains camera to 16:9 (`AspectMath.Fit`), background camera is black | No change (game target aspect ratio) | Camera `rect` (0.09/0.83) in 1814 × 934 window |

Checkpoint cell (840, 599) belongs to the old save. User screenshot shows zone 167 at (88x, 599).

## 3. Defaults, render rig, build

- `FieldController`: `GeneratedShadersWanted()`, `LoadShaderIndex()` (once, with count of available shaders), `CreateModelMaterials(bundle)` for player and NPCs (catalog via `GeneratedShaderLibrary.FindMaterialFile`: material folder, then sibling `<…>_all`), `AttachRenderRig()`. When an external camera is provided (`cameraOverride`, game scene with UI), post-processing is disabled (`postOnSharedCamera`) to avoid changing the UI with bloom/FXAA.
- `GeneratedShaderLibrary`: shader search order `combined_all`, `combined`, root; `GeneratedShaderSync.FindSourceDirectory`, `GeneratedShaderBuildSync` (pre-build step copies shaders to `Assets/XnuGenerated/Resources` before every player build; if source is missing, warn only).
- `scripts/build_all.sh`: `assets` stage additionally copies character material exports (`work/materials_all/Characters__*.json`, 412 files, 7.7 MB) to `materials/` so the player can remap player/NPCs. Pokémon exports (statues, battle) stay out.
- Debug hook `XNU_FIELD_START="Zone,gx,gy[,facing]"` starts the field at a cell (for verification runs).

## 4. Vertex data (confirmed, lab and main Editor)

Scan of all meshes in loaded map and models (`EffectsRunner.MeshScan`, zone 54: 105 meshes, 20 skinned; zone 167: 96 meshes):

- **Channels:** map: `Position Float32x3, Normal Float32x3 (or Float16x4), Tangent Float32x4 (or Float16x4), Color UNorm8x4, TexCoord0 Float32x2 (or Float16x2), TexCoord1 Float32x2`; water: `Position, [Color], TexCoord0 Float16x2` without normals; characters/Pokémon stream 0 `Position/Normal/Tangent`, stream 1 `Color UNorm8x4, TexCoord0`, stream 2 `BlendWeight Float32x2/x4, BlendIndices UInt32x2/x4`. All layouts are valid Unity formats; indices are 16-bit (0 meshes with 32-bit indices), 203 submeshes.
- **Values:** 0 meshes with NaN/Inf, 0 without normals, 0 without UV0, no UV values above 64, tangent W ±1, normal lengths are valid (among readable meshes only: 2 of 96; remaining meshes are marked unreadable and live in GPU memory, so `isReadable` limits the inspection; *suspected*: equally valid).
- **Shader inputs:** `POSITION, NORMAL, TANGENT, COLOR, TEXCOORD0, TEXCOORD1` (map), or without COLOR (Mitake, Pokémon: `a0..a4 = POSITION, NORMAL, TANGENT, TEXCOORD0, TEXCOORD1`). Generated wrapper mapping matches mesh channels; Unity reads missing channels (water has no normals) as zero.
- **Collider meshes:** 10 `MeshCollider`s are attached to visible renderers (sky planes and `P_C_001_InOut_01`, layer 0); ground layer 10: 27 renderers, all ground (stairs, floor), no collider-only meshes visible. `FieldMapBuilder` builds renderers only with `MeshFilter` + `MeshRenderer`; collider-only objects are not drawn.
- **Conclusion:** the “vertex collision” look (stretched, diagonal surfaces) came from the replacement shader (wrong texture/blending), not vertex data; generated shaders remove it.

## 5. Black/cyan Pokémon: integer uniforms in wrapper

**Finding.** `Mitake/MitakeStandardBumpShader` rendered the Pokémon black with cyan (zone 54 at noon: 3 cyan pixels in texture loop, otherwise black silhouette). Testing white textures (per slot), globals (`_CloudShadowTex`, `_ShadowMapTexture`), material floats, sphere/capsule instead of model, and disabling bloom/FXAA had no effect; shader output was the cause.

**Cause (confirmed).** Original reads some material constants as integers (`float(int(mx_cb3[2][1]))` for `_SpecularMaskEnable`, `_BaseColorAddEnable`, `_EmissionMaskUse`, `_SphereMaskEnable`, `_RimMaskEnable`, `_ColorMapUvIndex`, `_Layer1UvIndex`, …). Wrapper populated constant buffer with the **floating-point bit pattern** (`asuint(1.0)` = 1065353216); shader converted this to integer 1065353216, multiplied by it, and produced Inf/NaN. Affected: 55 of 119 generated shaders (Mitake Pokémon, character variants, and most `Delphis/Map/Standard` variants that read `_Cascade` as integer; breakdown was not counted individually).

**Fix.** `scripts/shader_wrap.py` (`build_stage_block`): words read as `int`/`uint` by shader are written as `asuint(int(<property>))` (detected from HLSL, no name list). Test `test_int_uniform_words_are_converted`; 55 files regenerated (`work/shaders/combined_all`).

**Evidence.** Pokémon `pm0387_00_00` (Turtwig) in lab, zone 54: black silhouette before (`pk54_orig`), green-brown with leaf after (`probe1`/`pkBF`). Pixel (805, 385): (35, 34, 34) → (163, 178, 117).

**Open.** Earlier “fp16 overflow in translator” hypothesis (`docs/shader-translator.md`, section 11.3, 15 `Map/Standard` pairs) is disproved for Mitake group; whether the same cause explains those 15 harness pairs has not been checked (harness sets uniforms itself).

## 6. Town save (SaveData SHA-256 0396a4a62735)

**Position.** Town save: `zoneID` (0x5634) = 24 (C02), `PLAYER_DATA` (0x79BF4/0x79BF8) = (57, 729), height 1.0; `TownMapLocation` (0x8FB04+0x54) = zone 416, (−789, 355), stale. Older save: zone 167, `PLAYER_DATA` (852, 599), height 6.0, `TownMapLocation` (842, 597): height 6.00 in zone 167 image and row 599 support `PLAYER_DATA` *[A]*. `SavedPosition.Read` now prefers `PLAYER_DATA` + `zoneID`, with `TownMapLocation` as fallback (facing only if its zone matches); `Write` writes both locations. Six new tests (`SavedPositionTests`), one reads local save (skipped if file absent).

**Rendering (main Editor, zone 24, hour 12).** Map with 4–6 blocks (1,068 renderers), spawn at (57, 729) works (lab image at 0/6 used wrong cell 789/355). Counts: 389 draw calls, 201 SetPass, 335,620 triangles, 280,980 vertices (Editor game window). Image: waves on water at left, gray-violet paving, blue roof with turquoise door, Pokémon Center above, evergreens to right, brown-haired NPC and colorful player, clear shadows.

**Issue: screen-space shadows failed (cause found and fixed).** In main Editor with **iOS** build target active, entire image was too dark (zone 24 mean 62/74/82, zone 422 64/71/43 vs. 87/102/111 and 99/110/64 under macOS target in lab). Quality, cascades, bias, near plane, rig, post-processing, sky, and each shadow caster changed nothing; only “shadows off” produced a bright image. Project files differ in **Graphics Tiers**: for iOS, `cascadedShadowMaps` is off. Unity then creates no screen-space shadow pass, while shaders still read `_ShadowMapTexture`; everything renders in shadow. Test: change lab to iOS: (62, 74, 82), same as main Editor; set `cascadedShadowMaps = true`: (87, 102, 110). Fix: `RenderProjectSettings` (Editor, on load, idempotent) enables the tier for iOS and macOS (`ProjectSettings/GraphicsSettings.asset`), test `IosStufenSchaltenCascadedShadowsFuerDenBildschirmschattenEin`. This also affects iPad app (*suspected*, not tested on device) and explains why shadows looked “too dark” in Mac preview.

## 7. Comparison with Ryujinx image (`ref_01_feld_weiter`, zone 24, hour 12.4)

Fetched reference (`scripts/ryujinx_fetch_shots.sh fetch`, 2 new images), comparison `visual_compare.py ref compare`:

| Metric | Before tier fix | After tier fix |
|---|---|---|
| Reference RGB mean | 106.2 / 120.0 / 118.3 | – |
| Unity RGB mean | 62.4 / 75.0 / 82.7 | 87.1 / 102.2 / 110.6 |
| SSIM (matched) | 0.408 | 0.394 (camera/character offset) |
| MAD raw → matched | 34.9 → 26.8 | 35.2 → 27.1 |
| Unity/reference brightness | 0.82 | 0.82 |

Description (left: reference, center: Unity, right: heatmap): same layout (blue-roofed house, planter, row of trees, two shades of violet paving, Pokémon Center above). Largest differences: (1) **Water** at upper left: reference turquoise with bright foam; Unity bluer/darker with sparkles. (2) **Brightness/contrast:** Unity about 18% darker, paving reference (141/129/165), Unity (113/108/138). Shadow/light strength (`_ShadowColor`, light color) is inferred *[A]*; bloom and color grading LUT are missing. (3) **Trees:** reference brighter and more yellow-green (52/105/37 vs. 46/88/36). (4) **Camera offset** (−68, −24) px: characters stand differently (reference NPC beside player, ours farther right), likely a different cell/animation phase; SSIM remains low as a result. Camera (pitch 40°, FOV 18°, yaw 180) matches original game data; perspective looks correct.

Still missing: color grading LUT (`ColorGradingLookup`), depth of field, HDR bloom (section 5.4 in `docs/sichtpruefung-2.md`), and water color (reflection/environment texture `_EnvironmentMap` unavailable). The 18% brightness gap is the largest open metric at this stage; *suspected*: LUT and HDR bloom account for most of it.

Second reference image (`ref_05_vor_pokecenter`, Pokémon Center with brown copper roof, white supports, and glass front) shows a **different building** from the Pokémon Center in our zone 24 (red roof with dome, `SM_C_001_PokeCen_01`). *Suspected:* different location (another town building model); it is unclear whether the reference image was taken in the same area. No comparison possible.

## 8. NPCs: counts and implementation

- `CharacterGraphicsTable` (`dpr_masterdatas/CharacterGraphics.json`, 142 entries: `FieldGraphic`, `Scale`) resolves `ObjectGraphicIndex` 0–141 to bundle `Characters/persons/field/fcNNNN_00`; `NpcModels` builds a model per placement (material remapping per model bundle, `PlayerAvatar.Create` with name and scale). Animation: `idling_f`, otherwise clip containing “idl”/“wait”, otherwise first clip; many NPC bundles have only 1 of 3 clips (no run/walk), and walking patterns are not played.
- Lab runs: zone 422: 3 of 3 placements as models (3 models); 54: 5/5; 367: 3/4 (one unresolved: object index 500 etc.). Zone 24: 12 placements with character index, all model bundles available (visible: player with NPC, woman with hair ornament as model, capsule for object); count of simultaneously built models was not measured.
- Unresolved: object indices ≥142 (500 item ball, 501 cut tree, 502/503 …, 556 wall, 540000 duck model, 4221100 …): 1,365 placements with 132 distinct indices; mapping to `Characters/objects/obNNNN` (128 bundles) and Pokémon models remains open. They still appear as markers (blue capsule, e.g. `C02_KODUCK` in town).

## 9. Measurements (lab, macOS target, 1280 × 720, noon)

| Zone | State | Draw calls | SetPass | Triangles | RGB mean | Frame time |
|---|---|---:|---:|---:|---|---|
| 422 | before (replacement) | 98 | 29 | 32,351 | 96/104/63 | 1.5 ms (Editor, no VSync) |
| 422 | after (generated, rig) | 904 | 204 | 281,504 | 99/110/64 | 4.1 ms |
| 425 | before | 105 | 49 | 16,458 | 120/139/163 | 1.3 ms |
| 425 | after | 692 | 267 | 123,942 | 52/42/28 (room against black) | 3.1 ms |
| 54 | before | 146 | 62 | 66,740 | 148/133/102 | 1.3 ms |
| 54 | after | 1,141 | 340 | 484,957 | 144/128/98 | 3.3 ms |
| 24 (main Editor) | after | 389 | 201 | 335,620 | 87/102/111 | VSync-limited 30 fps |

Frame time is capture only (CPU and GPU on M1 Pro in Editor, not a player build). Generated shaders cost 3–8× more draw calls, with 244–475 shadow casters, still well below 30 fps target (33 ms). iPad measurement pending.

## 10. Changed files

`Field/Runtime/{FieldController,FieldNpcView,PlayerAvatar,FieldDataSet,NpcModels (new)}.cs`, `Field/Logic/CharacterGraphicsTable.cs` (new), `Field/Editor/FieldShot.cs` (`CaptureAtFrameEnd`), `Render/Runtime/{GeneratedShaderLibrary,FieldRenderRig (new)}.cs`, `Render/Editor/{GeneratedShaderSync,GeneratedShaderBuildSync (new),RenderProjectSettings (new)}.cs`, `Game/Runtime/SaveSlotService.cs` (`SavedPosition`), `scripts/shader_wrap.py`, `scripts/build_all.sh`, `unity/ProjectSettings/GraphicsSettings.asset`, tests `FieldFidelityTests`, `SavedPositionTests`, `test_shader_wrap.py`.

## 11. Gaps

1. Color grading LUT, depth of field, HDR bloom; water color versus reference.
2. Object placements (index ≥142) and Pokémon companions remain markers.
3. NPC animation: idle only; movement patterns and facing-direction animation are missing.
4. Player/iPad measurements of new defaults (shaders in `Resources`, tier fix) pending; first Mac player test by main agent.
5. Second reference image (different Pokémon Center) unresolved.
6. Post-processing runs only on own camera; disabled in game scene (camera with UI) because compositor separation is missing.
