# Visual Review 2: Characters, Sky, Post-Processing, Brightness Bug, Shadows (Todo `ap-effects-fidelity`, Part 4)

> **Historical report (as of 2026-10-20):** The Unity path has been discontinued. These files were removed from `main` (they remain only on branch `unity`): `scripts/environment_export.py`, `scripts/material_export.py`, `scripts/material_variants.py`, `scripts/runtime_variants.json`, and their related tests. The commands below no longer run on `main`.

Status: 2026-10-19, Unity 6000.3.26f1 (lab Editor `work/unity-shader-lab`, not the main Editor), Built-in Render Pipeline, Gamma, Metal, Apple M1 Pro. Only our generated shaders are drawn (119 of 120 used variants translatable); no original shader loaded, **no audio**. Images, exports, generated shaders, and logs are under `work/` (`work/effects/shots/`, `work/materials_all/`, `work/shaders/combined_all/`), not in the repository; this document records measurements and descriptions. Unless noted otherwise, image measurements use `Camera.Render` into a `RenderTexture` (1280 × 720), RGB mean, zone 422, hour 12, frozen time (`Time.timeScale = 0`).

Notation: **confirmed** = measured or read in source/pseudocode; *suspected* = inference without a test.

## 1. Results

| Question | Result |
|---|---|
| Material export beyond `Environments/` | **All** catalog groups exported (`material_export.py --resolve-external`, about 20 s total): Characters **412 bundles, 2,105 materials**; Pokémon **3,038 bundles, 17,963 materials**; Effects 2,716 bundles, 13,629 materials; UI 25 bundles, 119 materials; remainder (Dpr, Contest, Fureai, …) 35 bundles, 225 materials. No unresolved external texture references: 72,198 from Pokémon materials, 14,335 from Effects. Zero materials without shader names in Characters/Pokémon (UI/Dpr/GMS: 49 materials use built-in default shader). |
| Coverage by variants/wrappers | Characters **2,105/2,105**, Pokémon field/battle **15,232/15,232** (7,616 in each folder), Pokémon statues **148/2,731** (2,583 require `Mitake/MitakeStandardPetrify`; translator reports `hlsl: subgroup shuffle`, section 6). Effects: 13,482 materials using `FxSystem/Particle` (**1,993 variants**) were not generated (counted only, section 6); 147 others are covered. |
| Used variants (`used.json`) | Characters **13**, Pokémon **10**, UI 19, Dpr 29, Effects excluding particles 15; Environment 60. With runtime keywords (section 2.3): **120 variants, 119 generated**, all 119 compile in lab (`Shader 119/119`). |
| Player and opponent in lab | Player `fc0001_00`: **13 materials using `Delphis/Character/Standard`** (2 variants); NPC `fc2039_00`: 5/5; Pokémon `pm0387_00_00`: 7/7 (`Mitake/MitakeStandardBumpShader`, 2 variants). Section 3. |
| Sky | Original: **no skybox material**, camera clears to black (alpha 0); sky is a sphere using `Delphis/Map/Sky` (22 bundles under `Environments/bg/arenas/sky/…`). Lab rendered 3/3 spheres. Section 4. |
| Post-processing | Original chain: **Bloom → Depth of Field → FXAA**. Rebuilt: bloom (5 levels, 17 passes per image), fog in bloom finalization, FXAA; **not** rebuilt: depth of field, color-grading LUT, feedback. Section 5. |
| Brightness bug after zone 54 | **Cause found and fixed:** `_ShadowMapTexture` remained as a released reference (null), so Unity bound black = “everything in shadow.” Zone 422 after 54: (82, 101, 59) → after fix **(101, 124, 72)**, same as fresh load. Section 7. |
| Zone 422 shadows | With original scene values (distance **45**, near plane **15**, one cascade, soft): **22.1% of pixels darker** (>5 levels); image mean (101.8 / 125.0 / 72.5) → (94.2 / 116.8 / 67.2). At distance 20: **zero pixels** changed. Section 8. |
| Tests | Unity lab **57/57** (was 47; 5 new scene-value tests, 5 guard/scene/post-processing tests), `dotnet test work/dotnet-render` **41/41**, Python `test_environment_export` 3, `test_material_variants` 7 passing, translator `make test` passing. Two Python tests from other work (`test_build_all`, `test_build_stages`: `stubs` stage) fail; unrelated to this work. |

## 2. Material export, variants, and stripping

### 2.1 Export

`scripts/material_export.py` was already general-purpose, but had only been run for `Environments/`. Runs per group (`--resolve-external --used … --dir <group>`, output under `work/materials_all/`):

| Group | Bundles with materials | Materials | Duplicate names | No shader name |
|---|---:|---:|---:|---:|
| `Characters` (objects 128, persons/field 160, persons/battle 124) | 412 | 2,105 | 3 | 0 |
| `Pokemon Database` (field 1,304, battle 1,304, statue 430; `common` has textures only) | 3,038 | 17,963 | 0 | 0 |
| `Effects` | 2,716 | 13,629 | 0 | 0 |
| `UIs` | 25 | 119 | 20 | 22 |
| `Dpr`, `Contest`, `FureaiHiroba`, `GMS`, `DigFossil`, `Union`, `UnderGround`, `StatuePlacementEdit` | 35 | 225 | 5 | 27 |
| `Battle` (1,411), `Pml`, `UgFather`, `LightStone` | 0 | – | – | – |

`Battle/btlv` contains scenes and data only, no materials. Pokémon models are under `Pokemon Database/pokemons/{field,battle,statue}`; textures are in `pokemons/common` (dependencies resolved by `--resolve-external`).

### 2.2 Coverage

Across 33,992 materials, `material_variants.py` (reference for variant selection) finds **33,895 exact** forward-pass matches, 96 “nearest” matches (19 × `Custom/Bloom Finalize`, 77 × `FxSystem/Particle`), and zero shaders with no variant. Per subgroup (material has a variant **and** it can be translated):

| Subgroup | Materials | Covered | Note |
|---|---:|---:|---|
| `Characters/objects` | 222 | 222 | `Delphis/Character/Standard` 221, `Delphis/Poffin` 1 |
| `Characters/persons/field` | 966 | 966 | |
| `Characters/persons/battle` | 917 | 917 | |
| `Pokemon/field` | 7,616 | 7,616 | `Mitake/MitakeStandardBumpShader` |
| `Pokemon/battle` | 7,616 | 7,616 | |
| `Pokemon/statue` | 2,731 | **148** | **2,583** use `MitakeStandardPetrify`: variant cannot be translated |
| `Effects` | 13,629 | 147 | 13,482 use `FxSystem/Particle`: not generated (1,993 variants) |
| UI, Dpr, Contest, Fureai, Statue Editor, GMS, Union, Underground, Fossils | 344 | 294 | 49 have no shader name (built-in default shader), 1 has no variant |

The used-variant count per group is small because materials store constants instead of keywords: the Mitake shader selects reflection, rim, and mask using **float constants** (`_SpecularMaskEnable`, `_RimMaskEnable`, `_BaseColorAddEnable` in constant buffer 3), not keywords. Thus all 15,232 Pokémon materials need only 2 variants (`DIRECTIONAL SHADOWS_SCREEN` with and without `USE_LAYER1`).

### 2.3 New: runtime keywords are missing from `used.json`

Post-processing enables keywords **in code** (`Material.EnableKeyword`: fog `_FOGMODE_*` in bloom finalization, `_GRADING_*` in FXAA); material exports do not include them. Stripping through `used.json` would therefore have removed them (only `_FOGMODE_NONE` and `_GRADING_NONE` remained as “nearest”). Added `scripts/runtime_variants.json` (7 entries: 4 fog modes, 3 color-grading modes) and `material_variants.py --extra-used scripts/runtime_variants.json --exclude-shader FxSystem/Particle` (function `merge_used`, 2 tests). Other runtime keywords (depth of field, battle effects) are **not** covered; they depend on learning their call sites (gap 3).

## 3. Player, NPC, and Pokémon with generated shaders (lab)

Setup (`work/unity-shader-lab/Assets/Lab/EffectsRunner.cs`, lab only): real `FieldController` (repository sources, `XNU_GENERATED_SHADERS=1`, zone 422) plus `PlayerAvatar.Create(provider, new RemappedMaterials(fallback, model bundle catalog, variant table, bundle name), …)`: same class used in game, but with **material remapping from the model bundle** instead of replacement materials.

| Model | Bundle | Materials remapped / fallback | Shader (generated variants) | Image |
|---|---|---:|---|---|
| Player character | `Characters/persons/field/fc0001_00` | 13 / 8 | `Delphis/Character/Standard` (`…69ddfc07`, `…bf366d46` for hair) | **in color**: red cap, face, clothing with bundle textures; replacement shader was pale gray |
| NPC | `Characters/persons/field/fc2039_00` | 5 / 0 | same two variants | colored hair and clothing |
| Pokémon (field) | `Pokemon Database/pokemons/field/pm0387_00_00` | 7 / 0 | `Mitake/MitakeStandardBumpShader` (`…69ddfc07`, `…51727159`) | see failure below |

The player's 8 fallback materials belong to inactive parts in the same prefab (bicycle `bicycle`/`light`, fishing rods, watering can, mounts `mcl`/`mh`). Their materials come from neighboring bundles (`Characters/objects/…`), not the player bundle; the catalog searches only within its own bundle (gap 2). All player meshes have tangents, vertex colors, and skinning weights.

**Open Pokémon issue:** with real textures, Pokémon renders **black with cyan** (at noon, solid cyan (0, 255, 255); in house shadow, black with cyan spots). Lab isolation: setting `_Col0Tex` to white immediately removes cyan (22 → 0 pixels); also setting ambient, emission, and normal textures to white yields a plausibly lit gray model. Keywords, floats, and `_BaseColorAddEnable`/`_RimMaskEnable`/`_SpecularMaskEnable` change nothing. Color texture format is ASTC 6×6 (UNorm), same as correctly rendered character. *Suspected:* shader produces NaN/Inf with real texture values (cyan = (0, 1, 1) after clamp; same cyan spot appears over water in spherical sky image), like the 15 NaN pairs in `docs/shader-translator.md`; unproven. Next: harness comparison of `Mitake/MitakeStandardBumpShader` with texture `pm0387_00_00_Body_col` (translator, `shader_harness`).

NPC markers (capsules) remain field-code placeholders using replacement shader (`FieldNpcView`); NPC models (`Characters/persons/field/fcNNNN_00`) render with remapping (NPC row).

## 4. Sky (original)

From scene `Dpr/scenes/field` (`scripts/environment_export.py` → `work/masterdata/EnvironmentScene.json`, confirmed):

- **RenderSettings:** no skybox material (`m_SkyboxMaterial` empty), ambient mode “Skybox” with zero values (probe 0; sky/equator/ground stored only as three-color defaults), fog off, reflection “Skybox” (therefore black), `subtractiveShadowColor` (0.42 / 0.48 / 0.63). Our project used Unity's default skybox (ambient light ≠0); generated forward shaders do not read ambient light (image mean is same with/without scene values: (101.8 / 125 / 72.5)), so image does not change.
- **Cameras (6):** `Compositor` (clears nothing, culling mask 0, HDR, depth 4, has `MultipleCameraCompositor`, `PostProcessFilter`, `AfterImage`); **`Main Camera`** (**clears solid black, alpha 0**, HDR on, MSAA allowed, near 0.1, far 1500, culling mask 4,456,247, depth 0; `FieldCamera`, `FieldPanCamera`); `ReflectionCamera` (white, depth −10), `EncountEffectCamera`, `AnimaitonCamera`, `PokemonCamera` (off). Our field background color (0.45 / 0.62 / 0.85) was **invented**; original map edge appears black (alpha 0 in compositor).
- **Sky itself:** sphere meshes using `Delphis/Map/Sky` in bundles `Environments/bg/arenas/sky/s001 … s081`, `eventsky001`, and `Environments/fields/battle001` (22 bundles with 22 material entries); textures include gradient (`SkyGrad`), near/far clouds, scenery/depth (mountains), star field (`StarlightTex`). Time of day affects game globals (`_CloudParam`, `_EmissionThreshold`) and `SkyColorSettings` (class in dump; prefab/ScriptableObject values not evaluated).

Lab setup (sphere at camera position, camera pitch −8°, FOV 60°, generated `Delphis/Map/Sky` shader, one material per sphere, no fallback): `s008` 89.8% nonblack pixels (mean (7, 211, 204)); `s032` 99.8% ((43, 46, 49), stars); `s081` 100% ((68, 123, 152): gradient, cloud bands, stars, horizon). Sphere with terrain (“arena”) also renders. With field camera (pitch 40°–45°, FOV 17°–20°), sky is never visible. Open: which sphere belongs to which zone/hour (`SkyColorSettings`, weather), and daytime star intensity (`s081` is visibly too bright).

## 5. Post-processing

### 5.1 Original (confirmed from `Dpr/scenes/field` and decompiled `Bloom.Build`)

`PostProcessFilter` (on compositor) runs effects in order **`Bloom`, `DepthOfField`, `FXAA`** (ScriptableObjects, each with a material list) and builds a per-frame `CommandBuffer` (`GetTemporaryRT`, `Blit`, `SetGlobalVector/Texture`). Materials and shaders (all inventoried and generated):

| Effect | Material → shader | Material keywords |
|---|---|---|
| Bloom | `BloomSetup` → `Custom/Bloom Setup`; `Gaussian7x7` → `Custom/Gaussian7x7`; `BloomFinalize` → `Custom/Bloom Finalize` | `_SRGB_ON` |
| Depth of field | `CaptureFocus`, `Downsample2x2Focus`, `ExpandFocus`, `ResolveFocus`, `DepthOfField`, `Gaussian7x7` | `_GAMMA_ON`, `_BLUR_ON`, `_SRGB_ON` |
| FXAA | `FXAA` → `Custom/Fxaa` | `_GRADINGMODE_NONE`, `_GRADING_NONE` (runtime: color-grading LUT) |

**Bloom pipeline** (from `Bloom.Build`, 0x20A5050; values from pseudocode): 5 levels (`MaxLayerCount`), each level i has width/height `>> (i + 2)` (¼ down to 1/64), ARGBHalf format, one A/B buffer pair each. Level 0: source → A0 with **Bloom Setup** (threshold `_BloomThreshold`, global from `EnvironmentSettings`, 0.95 at noon). Level i >0: A(i−1) → A(i), simple downsample. Each level: `_BlurOffsetX` = (−2.2186; 2.2186; −0.6075; 0.6075) (bit patterns `0xC00DF8DF, 0x400DF8DF, 0xBF1B9852, 0x3F1B9852`, 7-tap Gaussian with bilinear samples), `_BlurOffsetY` = 0, A → B with **Gaussian7x7**, then X = 0, Y = offset, B → A. Finally source → target with **Bloom Finalize**, reading the five levels as global textures `_SubTex0..4` (weights embedded in shader) and drawing **distance fog** from `_GlobalDepthTexture` (`Bloom.SetFogParameters`: keyword `_FOGMODE_LINEAR/EXP/EXP2`, `_FogParam` = (end or start, 1/max(end − start, 0.1) [× density for Exp], 0, far plane), `_Color` = near color, `_FarColor` = far color from `EnvironmentSettings`). Zone 422 fog is “Exp” (on morning/evening/midnight, off daytime/nighttime).

### 5.2 Implementation

New `Scripts/Render/Runtime/PostChain.cs` (camera component, `OnRenderImage`, Built-in pipeline): bloom as above (17 blits per frame: 5 × (downsample/setup + 2 × Gaussian) + final pass), fog through generated shader variant `_FOGMODE_*` (values from `EnvironmentDriver.State.Current`), then FXAA (`_GRADING_NONE`). It attaches `DepthCaptureDriver` for `_GlobalDepthTexture` itself. Variants for each runtime keyword are resolved on demand through `ShaderVariantResolver` (hence `scripts/runtime_variants.json`, section 2.3).

### 5.3 Measurement (lab, zone 422, 921,600 pixels, reference = no `PostChain`)

| State | RGB mean | Changed pixels | Of those >8 levels | Largest change |
|---|---|---:|---:|---:|
| No chain | (94.2 / 116.8 / 67.2) | – | – | – |
| `PostChain` no effect (pass-through) | identical | 0 | 0 | 0 |
| FXAA only | (94.2 / 116.8 / 67.2) | 239,793 (26%) | 17,680 | 188 (edges) |
| Bloom only (noon, threshold 0.95) | (94.1 / 116.8 / 67.2) | 145,752 (15.8%) | 0 | 3 (subtle glow) |
| Bloom + FXAA | (94.1 / 116.8 / 67.2) | 308,488 | 17,752 | 188 |
| Morning (hour 6), no fog | (92.4 / 112.2 / 70.1) | – | – | – |
| Morning, **with fog** (Exp, start 15, end 65, density 0.45) | **(104.4 / 126.2 / 88.2)** | 921,600 (all) | – | 80 |

The chain causes no hang in lab (all images in this section took <0.2 s each including readback); a frame-rate comparison with and without the chain has not been done.

### 5.4 Not implemented / post-processing gaps

1. **Depth of field** (6 materials, 5 shaders, `DepthOfField.Build` 0x2DA77F0, 1,479 pseudocode lines under `work/decomp/effects/`): not rebuilt. `_FocalCoefficient` is already supplied (`DepthOfFieldMath`); missing `_FocusTex`, `g_BackgroundTexture`, `_AdditionalBlurry` from `EnvironmentSettings.Blurry`.
2. **Color grading:** `ColorGradingEnable` is on in zone settings (zone 422, all sections). Original calls `Fxaa.SetColorGrading(lut0, influence, lut1, weight)` and selects `_GRADING_SINGLE/MULTI` with LUT textures from `EnvironmentSettings` (`ColorGradingLookup`). LUTs are in bundles (reference unresolved); `PostChain` uses `_GRADING_NONE`. Original image is therefore slightly differently tinted (not measured).
3. **Feedback** (`FeedbackBlur`), `ColorFilter`, `ChromaticAberration`, `RadualBlur` (battle/events), `AfterImage`, and `g_BackgroundTexture` (particle distortion): not rebuilt.
4. **HDR:** original Main Camera uses HDR; lab field camera is LDR (`allowHDR` false), bloom buffers are ARGBHalf. Original values above 1 feed into bloom; not measured here, *suspected*: stronger glow.
5. No original comparison image (Ryujinx provides no images): bloom, fog, and FXAA are confirmed as **pipeline structure** (pseudocode, scene, shader properties), but image similarity is unmeasured.

## 6. Variant and shader gaps

1. **`MitakeStandardPetrify`** (statues): 2 variants cannot be translated (`hlsl: subgroup shuffle`); 2,583 statue-bundle materials fall back to replacement material. Translator change (subgroup shuffle) was **not** started (not essential for player/NPC/Pokémon).
2. **`FxSystem/Particle`:** 13,482 materials, **1,993 variants** not generated (generation not started: about 2 s per variant for translator, plus Unity compilation); 77 materials request a keyword with no variant (“nearest”). For Effects group, use `--exclude-shader FxSystem/Particle` until particles are needed.
3. **Runtime keywords** are covered only for bloom finalization and FXAA (section 2.3).
4. **Catalog searches only the current bundle** (`MaterialCatalog.Find(Bundle, Name, Keywords)`): prefab parts with materials from neighboring bundles (bicycle, fishing rods) fall back to replacement. Fix: search dependencies from catalog.
5. **Pokémon shader:** black/cyan (section 3).

## 7. Brightness bug after zone 54

Description in `docs/sichtpruefung-1.md`, section 4.2: after visiting zone 54, other zones are about 19% darker (zone 422: (82, 101, 59) instead of (101, 125, 72)).

**Lab reproduction** (real `FieldController`, hour 12): 422 (101, 124, 72) → reload 422 (101, 124, 72) → **54 (137, 123, 95) → 422 (82, 101, 59)**; 367 or 425 in between changes nothing. Ratio is **not uniform**: grass 0.785, roof 0.83, trees 0.89 (160 × 120 pixel tile grid: 0.79–0.92).

**Isolation** (lab; image mean after 54 → 422 is always (82, 101, 59)):

| Intervention after visiting 54 | Result |
|---|---|
| Toggle sun, `UnloadUnusedAssets`, reset `QualitySettings` to original, `DynamicGI.UpdateEnvironment`, new camera | Still dark |
| Destroy/recreate `FieldController` (new sun, driver, materials), `AssetBundle.UnloadAllAssetBundles(true)` | Still dark |
| State comparison (131 values: all lights, `RenderSettings`, quality, camera, 35 game globals, 13 texture globals, `unity_*`, keywords) | **Only difference besides time: `_ShadowMapTexture`** (before `UnityWhite` 4×4, after `null`) |
| All map material properties before/after (float, colors, texture names, keywords, queue) | Identical |
| Manually set `_ShadowMapTexture` to white | **(101, 124, 72)**, with shadows either on or off |

**Cause (confirmed):** Unity's screen-space shadow pass sets global `_ShadowMapTexture` only in frames where it creates a shadow map (at least one caster within shadow distance). This happens in zone 54 (shadow map `Shadowmap` 4096 × 4096). When switching to a zone **without** a caster in range (zone 422 at distance 20: focus point is 30 units in front of camera, section 8), the previous frame's value remains—a released reference (`null`) after zone unload. Generated forward shaders always read `_ShadowMapTexture` (`min(shadow, cloud term)`); null binds black = **everything is in shadow** (grass 21% darker: shadow color `_ShadowColor` replaces light). This explains why sun, globals, and toggling shadows changed nothing: bug is in screen-space shadow state, not globals. In fresh state value was `UnityWhite` (Unity default), so first zone was always bright.

**Fix (only `Scripts/Render`):** new `Render/Runtime/ShadowMapGuard.cs`: `Camera.onPreRender` sets `_ShadowMapTexture` to `Texture2D.whiteTexture` before **every** camera frame; if Unity creates a shadow map that frame, shadow pass overwrites it (confirmed: zone 54 still has shadow map, image unchanged at (137, 123, 95)). Installs through `SunLight.Ensure` and `EnvironmentDriver.OnEnable`; field code needs no change. After fix (sequence 422 → 54 → 422 → 54 → 367 → 422): zone 422 always **(101, 124, 72)**, zone 54 (137, 123, 95), zone 367 (99, 122, 65). Tests: `RenderShadowGuardTests` (reset, idempotent installation before camera frame, scene values, constants).

## 8. Shadow fidelity (zone 422)

**Original values:** original shadow distance does **not** come from quality settings (20); `EnvironmentController` overrides it each frame with scene values (`_ShadowDistance`, `_ShadowNearPlaneOffset`, `_ShadowNormalBias`). Read from scene bundles (`scripts/environment_export.py`):

| Scene | Distance | Near plane | Normal bias |
|---|---:|---:|---:|
| **`field`** | **45** | **15** | 0 |
| `battle`, `gms`, `contest`, `evolvedemo`, `sealpreview` | 20 | 3 | 0 |

Scene light (`EnvironmentController` object): directional, intensity 1.5, **soft shadows**, bias 0.05, normal bias 0.4 (`EnvironmentController` sets intensity, color, rotation, and normal bias each frame from zone values; zone 422: 1.15, (0.93, …), rotation (75, 345, 0)). Quality tier provides all shadows, high resolution, StableFit, **one cascade**.

**Measurement** (lab, `EnvironmentDriver` with `EnvironmentScene.json`, one cascade, StableFit, high, soft; frozen time, same camera; images `work/effects/shots/s45_on|off.png`, `s20_on|off.png`, difference `shadow_diff45.png`):

| Setting | Mean with shadows | Mean without | Pixels darker (>5) | Of those >20 | Largest decrease | Pixels brighter |
|---|---|---|---:|---:|---:|---:|
| **Distance 45, near plane 15** (scene value) | (94.2 / 116.8 / 67.2) | (101.8 / 125.0 / 72.5) | **203,302 (22.06%)** | 143,155 | 96 | 0 |
| Distance 20, near plane 3 (quality value) | (101.8 / 125.0 / 72.5) | (101.8 / 125.0 / 72.5) | **0** | 0 | 0 | 0 |

Image with shadows shows clear soft cast shadows: house (roof, wall) on ground/path down-right, mailbox, sign above, evergreens on right, neighbor's house on left; player casts none (replacement shader has no shadow pass). At distance 20, image has no shadows because focus point (cell 116, 886) is about 30 units from camera; image center is **outside** shadow distance. Zone 54, closer to camera, casts shadows even at distance 20—that triggered section 7 bug. Morning shadows (hour 6) are longer and bluer (`po_m_nofog.png`).

**Fidelity:** shape follows original method (Unity shadow map, one cascade, StableFit, soft, bias 0.05/0.4/0). Pixel comparison with Switch is impossible (no reference images). Remaining ambiguity: original light `shadowNormalBias` is 0 in controller or 0.4 in prefab; `EnvironmentDriver` sets 0, matching controller.

## 9. `EnvironmentController` scene values (additional result; closes gap 1 from `docs/shader-globals.md`)

`scripts/environment_export.py` now writes `work/masterdata/EnvironmentScene.json` from `Dpr/scenes/field`: `_ShadowDistance` 45, `_ShadowNearPlaneOffset` 15, `_ShadowNormalBias` 0, `_CloudSpeed` (0.5, 0.5), `_CloudTiling` (0.03, 0.03), `_CloudShadowBase` 0, `_CloudShadowScale` 1, `_EmissionScale` 1, `_Wetness` 1, `_WeatherMode` 0 (sunny), shadow color (0.41, 0.46, 0.53), snow shadow color (0.47, 0.52, 0.80); textures `_NoiseTex` = `noise_repeat`, `_SnowTex` = `snow`, `_SnowNormalTex` = `snowNormal`, `_EnvironmentMap` = `Reflection` (all in `Dpr/common_resources`), `_CloudShadowTex` **unresolved** (name “external”; reference points to a bundle outside dependency list, still open). C#: pure `EnvironmentSceneData.FromJson` (5 tests); `EnvironmentDriver` loads file itself (`AutoLoadScene`) and sets `State.Scene` and `RenderSettings` (`SceneRenderApply.Apply`). Cloud-shadow texture is largest remaining game-global gap: without it `_CloudShadowTex` is black, `_CloudShadowBase` is 1.

## 10. Field-code notes (not changed; belongs to `ap-vertical-slice`)

1. **Player with material remapping:** `FieldController.CreatePlayer` calls `PlayerAvatar.Create(_provider, _fallback, …)`. Pass `RemappedMaterials(_fallback, modelBundleCatalog, variantIndex, playerModelBundle)` instead of `_fallback` (catalog: `GeneratedShaderLibrary.MaterialFileFor(playerModelBundle)`; export at `<material-folder>/Characters__persons__field__fc0001_00.json`; material folder must contain files from `work/materials_all/`, e.g. `XNU_MATERIALS`). Same for NPC/Pokémon models. One remapping object per model; call `Destroy()` on teardown.
2. **Camera:** `SetupCamera` sets `_camera.backgroundColor = (0.45 / 0.62 / 0.85)`. Original: `SceneRenderApply.ApplyCamera(_camera, scene.Camera("Main Camera"), clipPlanes: false)` (solid black, alpha 0, HDR, MSAA allowed). `scene` = `EnvironmentDriver.SceneData`.
3. **Post-processing:** after `EnsureRenderEnvironment`, `var pc = _camera.gameObject.AddComponent<PostChain>(); pc.Driver = _envDriver;` (once).
4. **Scene export:** `masterdata` stage of `build_all.sh` should run `scripts/environment_export.py` (now also writes `EnvironmentScene.json`); without file, placeholders remain (distance 20, defaults).
5. **Stripping:** include `--extra-used scripts/runtime_variants.json` when building used variant set; `shader_wrap_all.py --used … --combine-shadow`.
6. **Map material catalog:** `FieldController.CreateMaterials` loads only map bundle export; characters need their own catalog as in item 1.

## 11. Reproduction

```
export PYTHONPATH=tools/pydeps
python3 scripts/environment_export.py                                    # + work/masterdata/EnvironmentScene.json
for g in Characters "Pokemon Database" Effects UIs Dpr Contest FureaiHiroba GMS UnderGround Union DigFossil StatuePlacementEdit; do
  python3 scripts/material_export.py --out work/materials_all --resolve-external --used "work/materials_all/used_$g.json" --dir "$g"; done
python3 scripts/material_variants.py --materials work/materials_all --extra-used scripts/runtime_variants.json \
    --exclude-shader FxSystem/Particle --used-out work/materials_all/used_game_nopart.json --report work/materials_all/variants_report.json
python3 scripts/shader_wrap_all.py --out work/shaders/combined_all --used <used set> --combine-shadow     # 119 of 120
# Lab: play mode via work/effects/run.cfg (steps=call:chars:…, snap:…, call:post:bf, call:sky:s081, shadows:off, call:dist:45 …),
#      start work/effects/run.sh; XNU_SHADERS=work/shaders/combined_all; run editor_stop before run_tests
```

Changed/new: `scripts/environment_export.py` (+`scene_document`, `read_scene`), `scripts/material_variants.py` (`--extra-used`, `--exclude-shader`, `merge_used`), `scripts/runtime_variants.json`, tests `scripts/tests/test_environment_export.py`, `test_material_variants.py`; Unity `Scripts/Render/EnvironmentScene.cs`, `Runtime/{ShadowMapGuard,SceneRenderApply,PostChain}.cs`, `Runtime/{EnvironmentDriver,SunLight}.cs` (modified), `Tests/EditMode/{RenderSceneTests,RenderShadowGuardTests}.cs`. `shader_translator/` and `scripts/shader_wrap*.py` unchanged.
