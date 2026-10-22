# Game Shader Globals, Shadows, Water, and Neighbor-Bundle Textures (Todo `ap-effects-fidelity`, Part 1)

> **Historical (as of 2026-10-20):** The Unity path has been discontinued. Removed from `main` (retained only on branch `unity`): `scripts/environment_export.py`, `scripts/material_export.py`, and their tests. The commands below no longer run on `main`.

As of 2026-10-19. Questions: Which code sets the 35 game globals used by the original shaders (`_ShadowColor`, `_CloudParam`, `_PokeLightColor`, …), and where do their values come from? How does the original render shadows, and do our shaders work with that path? What does the original do for water (GrabPass)? How do we resolve texture references into neighboring bundles?

Labels: **verified** = read in decompiled game code or measured in Unity; *inferred* = conclusion without a test. Sources: `work/il2cpp/dump.cs` and `script.json` (Il2CppDumper), Ghidra project `work/ghidra/bdsp` (headless, `-readOnly`; scripts `scripts/ghidra/`: `StringXrefs.java`, `CallersOf.java`, `ExportDecompiled.java`; launcher `run_headless.sh` uses lock file `work/ghidra.lock`), and pseudocode under `work/decomp/effects*` (not in the repository). Addresses below are Il2CppDumper RVAs (Ghidra = RVA + 0x100000). The repository contains only code, formulas, and numbers, not game data.

## 1. Results at a Glance

| Question | Result |
|---|---|
| Globals with a confirmed setter | **35 of 35** (table in section 2); Ghidra cross-references through the string slots found, for every name, the class that uses it with `PropertyToID` (`work/ghidra/globals_xrefs.txt`) |
| Sourced from data (asset or scene object) | 18: 10 from `EnvironmentSettings`, 8 from scene objects; plus 3 from game state/constants, 4 from camera rigs (reflection, depth), 6 from post-processing (CommandBuffer), 3 per object (`MaterialPropertyBlock`), and 1 from the TextMeshPro package (35 total) |
| Implemented in code (`EnvironmentState`, `DepthOfFieldMath`, `Runtime/*`) | **26 of 35**; 9 remain: `_UVOffset`, `_Corner`, `_RcpGridSize` (per object), `_EnvMatrix` (package), `_FocusTex`, `_BlurOffsetX/Y`, `_DelayFrameTexture`, `g_BackgroundTexture` (post-processing, part 2) |
| In-game lighting data | **175** `EnvironmentSettings` assets (bundle `Dpr/scriptableobjects/gamesettings`, 5 time-of-day periods each); **656 of 658** zones reference them (`MapInfo.ZoneData[].RenderSettings`); 97 distinct assets are used, and 556 zones have `FixedTime` |
| Shadows with our shaders | **Working** (lab, Unity 6.3, Built-in, Gamma, Metal): the caster pass in the generated shader casts visible shadows, and the receiver pass gets Unity's screen-space shadow; no changes to `shader_translator/` were needed (section 6) |
| Combined shaders (Forward + shadow caster in the same `.shader`) | `shader_wrap_all.py --combine-shadow`: 61 used variants, 48 with a shadow pass; **61 of 61 compile** (37 s); the zone test needed 0 separate shadow materials |
| Water/GrabPass | `GrabPass { "_BackgroundTexture" }` is now preserved (7 named shaders + 2 unnamed in `UI/Blur`); lab measurements show background colors through water with GrabPass, and a constant tint without it (section 7) |
| Textures in neighboring bundles | **52 of 52** resolved, all in `Dpr/common_resources` (5 bundles, 0 unresolved) |
| Tests | 18 new C# tests (`RenderEnvironmentTests`) + 1 Unity test + 9 Python tests (`test_environment_export` 2, `test_material_export_external` 2, `test_shader_wrap` +5, no game data); lab 37 of 37, `dotnet test` 29 of 29, Python 247 passed, translator `make test` still green |

## 2. Table: Global → Setter Class/Method → Data Source

Setter abbreviations: **EC.OU** = `EnvironmentController.OnUpdate` (RVA 0x1F0EB60, runs every frame; section 3); **EC.SL** = `EnvironmentController.SetLight` (0x1F0FA10). Property IDs are stored as `static readonly int` fields in `EnvironmentController` and created with `Shader.PropertyToID` in its `.cctor` (0x1F109C0).

| Global | Type | Setter | Data source | Implemented |
|---|---|---|---|---|
| `_ShadowColor` | Vector | EC.OU | `Parameters.ShadowColor` for the time-of-day period (copied by EC.SL), **× 0.5** (including alpha); in snowy weather, use scene object's `_SnowShadowColor` × 0.5 instead | yes |
| `_CloudParam` | Vector | EC.OU | (time in hours · 60 · `_CloudSpeed.x`, likewise y, `_CloudTiling.x`, `.y`); when tiling ≠ 0, x/y are first reduced with `fmodf` by 1/tiling | yes |
| `_CloudShadowBase` | Float | EC.OU | **1 − `_CloudShadowBase`** (scene object) | yes |
| `_CloudShadowScale` | Float | EC.OU (value from EC.SL) | `Parameters.CloudShadowScale` | yes |
| `_CloudShadowTex` | Texture | EC.OU | Scene object's `_CloudShadowTex` when cloud shadows are enabled (`EnvironmentSettings.CloudShadowEnable`); otherwise `Texture2D.blackTexture` | yes |
| `_GlobalLightPower` | Float | EC.OU | **static `globalLightPower` − 1** (default 1, so **0**); 0 when `_throughGlobal` is set | yes |
| `_GlobalBumpScale` | Float | EC.OU | static `globalBumpScale` (default 1) | yes |
| `_EmissionScale` | Float | EC.OU | scene object's `_EmissionScale` | yes |
| `_EmissionThreshold` | Float | EC.SL and `SceneConnector.OnUpdate` | **(period + progress) · 0.2**, where period 0 is morning … 4 is midnight; EC.OU only forwards the value | yes |
| `_VertexColorScale` | Float | EC.OU | `Parameters.VertexColorScale` | yes |
| `_ReflectorColor` | Vector | EC.OU | `Parameters.ReflectorColor` | yes |
| `_CharacterLightColor` | Vector | EC.OU | `Parameters.CharacterLightColor` · (I, I, I, 1), I = `CharacterLightIntensity` + `AddCharacterLightIntensity` | yes |
| `_CharacterReflectorColor` | Vector | EC.OU | `Parameters.CharacterReflectorColor` | yes |
| `_PokeLightColor` | Vector | EC.OU | `Parameters.PokeLightColor` · (I, I, I, 1), I = `PokeLightIntensity` + `AddPokeLightIntensity` | yes |
| `_PokeReflectorColor` | Vector | EC.OU | `Parameters.PokeReflectorColor`; `SetPokemonLight` (0x1F10520) overrides the three Pokémon lighting values for other contexts (battle, Pokémon viewer) | yes |
| `_AdditionalBlurry` | Float | EC.OU | `Parameters.Blurry` (EC.OU also sets static `DepthOfField.blurry`) | yes |
| `_BloomThreshold` | Float | EC.OU | `Parameters.BloomThreshold` | yes |
| `_EnvironmentMap` | Texture | EC.OU | scene object's `_EnvironmentMap`; otherwise white | yes |
| `_SnowTex`, `_SnowNormalTex` | Texture | EC.OU | Scene object's `_SnowTex`, `_SnowNormalTex`; otherwise `Texture2D.normalTexture` for normals | yes |
| `_NoiseTex` | Texture | EC.OU | scene object's `_NoiseTex`; otherwise gray | yes |
| `_ReflectionTex`, `_ReflectionVP` | Texture, matrix | `ReflectionCameraFollower.OnEnable` (0x19A5C10) / `.LateUpdate` (0x19A5F30) | Section 4.1 | yes (`ReflectionCameraDriver`) |
| `_OpaqueDepthTexture`, `_GlobalDepthTexture` | Texture | `MultipleCameraCompositor.OnReset` (0x1F7D4C0, CommandBuffer) | Section 4.2 | yes (`DepthCaptureDriver`, simplified) |
| `_FocalCoefficient` | Vector | `SmartPoint.Rendering.DepthOfField.Update` (0x2CA8EA0) | (d, f, 1/f, 1/max(d + f, 0.001)), where d = camera-to-focus distance and f = depth of field (section 5) | yes (`DepthOfFieldMath`) |
| `_FocusTex`, `_BlurOffsetX/Y` | Texture, vector | `DepthOfField.Build` (0x2CA77F0), `Bloom.Build` (0x20A5050): per-pass CommandBuffer `SetGlobal*` | Blur kernel and focus map; part 2 | no |
| `_DelayFrameTexture` | Texture | `Dpr.Rendering.FeedbackBlur.Build` (0x1BCFDB0) | Feedback reference; part 2 | no |
| `g_BackgroundTexture` | Texture | `Effect.EffectManager.SetupBackgroundTexture` (0x1F00310) | `DepthOfField.renderTexture` (downsampled scene image), updated each frame after `UpdateDistortionCamera` | no |
| `_UVOffset` | Vector | `FieldCharacterEntity.OnUpdate` (0x17885E0) | Set per renderer through a `MaterialPropertyBlock` (eye and mouth patterns, blink curve); not a global | no |
| `_Corner` | Vector | `Snowfield.OnUpdate` (0x2CAAE70) | Set per footprint through a `MaterialPropertyBlock` | no |
| `_RcpGridSize` | Float | only `ProceduralPlane.cctor` (property ID); no `SetFloat` in code | Footprint material property (*inferred*) | no |
| `_EnvMatrix` | Matrix | TextMeshPro package (`TMPro.ShaderUtilities.GetShaderPropertyIDs`) | TMP shader material property (environment-map rotation); identity matrix by default | no |

Other properties also set by `EC.OU` (not in our list of 35 because no bundled shader needs them): `_Wetness` (scene object's `_Wetness`) and `_MipTex` (debug texture).

Implications for the defaults: `GameGlobals.SetDefaults` used to set `_GlobalLightPower` to 1; the original idle value is **0** (static value 1 − 1). This has been corrected, including the existing test. Also, the placeholder `_CloudShadowBase` = 0 makes **everything shadowed** in the original shader (section 6.3); its original value is `1 − scene value`, so a scene value of 0 yields 1 (the placeholder was corrected as well).

## 3. Call Flow

```
GameManager.OnUpdate            nowTime = DateTime.Now (system clock) each frame, unless paused/loading
SceneConnector.OnUpdate         (field scene, 0x19A7720)
  ├─ (period, progress, weight) = GameManager.currentPeriodOfDayEx       (section 3.1)
  ├─ Settings = MapInfo.ZoneData[PlayerWork.zoneID].RenderSettings        (exceptions: move cut-in, fog)
  ├─ zone with FixedTime: SetLight(Settings, day, 0, 0); _EmissionThreshold = (progress + period) · 0.2
  └─ otherwise:           SetLight(Settings, period, progress, weight)
EnvironmentController.SetLight  (active controller only; Parameters = Settings.GetTransition(period, weight))
EnvironmentController.OnUpdate  (per-frame tick callback) → all SetGlobal* from section 2, Light, QualitySettings
```

There are 24 other callers of `SetLight` (battle sequence `SpecialSetTimeZone`, contests, demos, GMS, fossil minigame, UI model viewers, timeline `TimeLineBinder`, seal preview, …); each chooses its own settings and period. `OnUpdate` also sets `Light.intensity` = `Parameters.LightIntensity` + `AddLightIntensity`, `Light.color`, `Light.transform.eulerAngles` = (`PitchYaw.x`, `PitchYaw.y`, 0) (settings provide pitch and yaw), `Light.shadowNormalBias` = `_ShadowNormalBias`, `QualitySettings.shadowDistance` = `_ShadowDistance`, and `shadowNearPlaneOffset` = `_ShadowNearPlaneOffset` (both from the scene object).

### 3.1 Time of Day (`GameManager`, **verified**)

`elapsedTimeOfDay` (0x2CD0A50) = `((tickOffset + timeScale · (nowTime.Ticks mod day)) mod day) / day · 24` in hours (day = 864 · 10⁹ ticks; `nowTime` is system time, and `tickOffset`/`timeScale` are static fields for debugging and time acceleration, with no direct callers).

| Hour | Period | Duration (minutes) |
|---|---|---|
| 4–10 | 0 Morning | 360 |
| 10–17 | 1 Day | 420 |
| 17–20 | 2 Evening | 180 |
| 20–2 | 3 Night | 360 |
| 2–4 | 4 Midnight | 120 |

`currentPeriodOfDayEx` also returns progress p (0..1 within the period) and weight **max((p · duration − (duration − 10)) · 0.1; 0)**: the transition weight to the next period (morning → day → evening → night → midnight → morning) rises from 0 to 1 **only during the final 10 minutes**. `EnvironmentSettings.GetTransition(period, weight)`: weight < 0.0001 → current period values; > 0.9999 → next period values; otherwise interpolate colors with `Color.Lerp`, intensities with `Mathf.Lerp`, light angles along the shortest path (d − round(d / 360) · 360), fog (fade via the alpha channel of the fog colors, otherwise linear), and color correction (influence) accordingly. Implemented and tested in `TimeOfDay` and `EnvironmentSettingsData`.

## 4. Camera Rigs

### 4.1 Reflection (`ReflectionCameraFollower`, **verified**)

A second camera on the same object; `targetTexture` = `RenderTexture(screen width, −height, depth 24)` with mipmaps and automatic mip generation (recreated when the size changes, otherwise `SetCustomResolution`). Each frame (`LateUpdate)): position (x, **−y**, z), rotation `Euler(−x, y, −z)` of the main camera, **field of view = main camera · `_fovScale`**; `_ReflectionVP` = `GL.GetGPUProjectionMatrix(projectionMatrix, false)` · `worldToCameraMatrix`; `_ReflectionTex` = target texture. Reflection is across the y = 0 plane, so the original water level is 0.

### 4.2 Depth (`MultipleCameraCompositor`, **verified**)

All layer cameras (main and layer cameras) render to **one shared color texture and one shared depth texture** (`SetTargetBuffers`); two `CommandBuffer` instances:

- `CameraEvent.BeforeForwardOpaque` (10) on the compositor camera: `_GlobalDepthTexture` = shared depth texture; blit the color texture to the screen.
- `CameraEvent.AfterForwardOpaque` (11) on the main camera: `_OpaqueDepthTexture` = `BuiltinRenderTextureType.Depth`.

Our `DepthCaptureDriver` sets both textures on the same events using `_CameraDepthTexture` (equivalent for **one** camera; the shared target texture across multiple layer cameras has not been reproduced, gap 3).

## 5. Post-Processing (only as it relates to globals)

`DepthOfField.Update`: `distance d` = |target + `targetOffset` − camera position|; without a physical camera, focal length comes from field of view and sensor height `sensorScale · 24 mm`, with `k = 0.024`; otherwise `k = sensor height · 0.001`. **Depth of field f = (sensorScale · k · d · 0.5) / (focal length · 0.001)²**; `_FocalCoefficient` = (d, f, 1/f, 1/max(d + f, 0.001)). The blur offsets `_BlurOffsetX/Y` are fixed Gaussian-pass kernel constants (four floats in `get_blurOffset`, 0x2CA7790), set per pass with `CommandBuffer.SetGlobalVector`. The focus map, blur, bloom, FXAA/color correction, and feedback are **CommandBuffer chains** on the main camera (`GetTemporaryRT`, `Blit`, `SetGlobalTexture`); they belong to part 2 (effects), and their structure can be carried over unchanged in Built-in.

## 6. Shadows

### 6.1 The Original (**verified**)

- **QualitySettings** (`globalgamemanagers`, “Ultra” level, the only level): shadows *All* (2), resolution High (2), StableFit projection (1), **one cascade**, distance 20, near-plane offset 3, no MSAA, 4 pixel lights. The last level in our `ProjectSettings` matches (`RenderSettingsTests`); `OriginalQuality.Apply()` also sets it at runtime. Each frame, `EnvironmentController` overrides the distance and near-plane offset with scene values.
- **Lighting**: one directional light per scene, controlled by `EnvironmentController` (color, intensity, rotation, and `shadowNormalBias` from the scene value); shadow type and strength are in the scene/prefab asset and cannot be read from code.
- **Shaders**: the code has no custom screen-space shadow collector. Map shaders are forward shaders with `LightMode=ForwardBase` and the `SHADOWS_SCREEN` variant (they sample `_ShadowMapTexture`, generated by Unity's built-in `Internal-ScreenSpaceShadows` pass), and, where present, a **custom `ShadowCaster` pass** (7 shaders: `Delphis/Map/Standard`, `Map/Sky`, `Character/Standard`, `Character/DepthOnly`, `Poffin`, `Snowfield`, `Dpr/Objects/ShadowCast`). The four `Mitake/…` shaders (`BumpShader`, `Petrify`, `Shader1st`, `GroundEffect1st`) use `UsePass "Legacy Shaders/VertexLit/SHADOWCASTER"` (Unity's built-in shadow caster).

### 6.2 Our Implementation (**measured in the lab**)

Unity selects shadow casting from the material's **shader**; each material has one shader. Therefore, `scripts/shader_wrap.py` now generates shaders with multiple passes:

| Option | Effect |
|---|---|
| (default) | Preserve **GrabPass** immediately before and **UsePass** immediately after the main pass, in the original order from the inventory (`--no-aux` disables this) |
| `--also PASS[:KW,KW]` | Add another regular pass (typically the `SHADOWCASTER` pass with `SHADOWS_DEPTH`) to the same SubShader; properties appear once in the header, and each pass gets its own `HLSLPROGRAM` |
| `shader_wrap_all.py --combine-shadow` | Select the matching shadow caster for each forward variant (same rule as `ShaderVariantResolver`: material keywords intersected with caster-pass keywords plus `SHADOWS_DEPTH`; otherwise omit `INSTANCING_ON`); add `shadow` (pass, keywords) and `aux` to `variants.json`; if the caster cannot be translated, emit the variant without it (`shadowError`) |

C#: `VariantEntry.EmbeddedShadowKeywords` reads `shadow`; `MaterialRemapper` then **does not** create a separate `ShadowCaster` material (`RemapResult.ShadowEmbedded`).

Test setup (`work/unity-shader-lab/Assets/Editor/ShadowTest.cs`, not in the repository): a plane (receiver) and cube (caster), both using `Delphis/Map/Standard` (forward `DIRECTIONAL SHADOWS_SCREEN _CASCADE_SINGLE` + caster `SHADOWS_DEPTH`), directional light Euler (50, 40, 0), soft shadows, original QualitySettings (one cascade, StableFit, distance 20), forward camera.

| Case | Result |
|---|---|
| Hand-written control shader (`multi_compile_fwdbase`, `SHADOW_ATTENUATION`) | Shadows visible; Unity's screen-space shadows work in this lab |
| Our caster pass (cube) + control receiver | **Shadows visible**: Unity finds the generated `SHADOWCASTER` pass tagged `LIGHTMODE=SHADOWCASTER` (uppercase as in the inventory) |
| Our receiver + caster, placeholder `_CloudShadowBase` = 0 | Plane **completely shadowed** (mean (100, 100, 100)); no cube shadow visible. Cause is the placeholder, not the shadow path: the shader takes `min(shadow texture, cloud term)`, and with `_CloudShadowBase` = 0 the cloud term is always 0 |
| Our receiver + caster, `_CloudShadowBase` = 1 | **Cube shadow visible** (shadowed area/open area = 181 / 198, cube top 203); the image is pixel-identical with and without `#pragma multi_compile_fwdbase`, so the pragma is unnecessary: Unity supplies screen-space shadows even to a shader without keyword variants |
| Caster via `UsePass` (Mitake) | Shadows visible (cube using `MitakeStandardBumpShader`, variant `DIRECTIONAL LIGHTPROBE_SHADOWS_SCREEN`) |
| One cascade instead of four | Same image |
| Zone 422, `--combine-shadow` variants | All 34 of 34 materials complete, **0** separate shadow materials, plausible image (section 6.4) |

**Fidelity:** There is no reference image from the Switch. We verified that the **passes and Unity paths behave as in the original** (caster, screen-space shadow, cascade 1, distance 20) and that the shadow appears in the right place. Pixel equality with the Switch cannot be measured. Shadow shape depends on Unity's shadow rendering; the Built-in path is structured the same way in Unity 2019.4 (original) and 6.3 (here), but **bit-for-bit equivalence** has not been established.

### 6.3 Finding: Placeholder Globals Distort Shadows

The forward shader combines screen-space shadows, cloud shadows (`_CloudShadowTex`, `_CloudShadowScale`, `_CloudShadowBase`, `_CloudParam`), `_ShadowColor`, and lighting (`_GlobalLightPower`; read from the generated HLSL: shadow sample, cloud term, `_ShadowColor`, light). With the old placeholders (base 0, color 0), the whole map looked shadowed (mean (29, 38, 22) in zone 422). The derived values (section 6.4) change the image substantially.

### 6.4 Zone 422 with Derived Globals (Lab, `MatRender`, 960 × 540)

`EnvironmentDriver` with the zone's actual data (`FieldRenderSettings`, no `FixedTime`), combined variants (`--combine-shadow`), and controller scene fields left at their defaults (gap 1):

| State | Mean image RGB | Note |
|---|---|---|
| Placeholder (`SetDefaults`, previous state) | (26, 34, 20) | Map appears “shadowed” |
| Hour 12 (day) | (83, 104, 62) | House, forest, and meadow are visibly brighter; image at `work/matremap/shots/ap_env12.png` |
| Hour 22 (night) | (65, 79, 43) | Darker, cooler lighting |

The image shows that the data chain (zone → settings → period → globals → shader) works; pixel comparison with the Switch remains impossible because no reference images are available.

## 7. Water and GrabPass

**Original (verified):** The water shaders use Unity's own `GrabPass`: inventory passes of type *Grab* with texture `_BackgroundTexture` occur in `Delphis/Map/Water`, `Wave`, `Fog`, `FlowMap`, `WaterSurface`, `Delphis/Battle/Encount01/02`, and one unnamed shader in `UI/Blur` (twice, with default texture `_GrabTexture`). The game itself does **not** create a custom CommandBuffer for the background (the code does not reference `_BackgroundTexture`; it only knows `g_BackgroundTexture`, the depth-of-field texture used for particles). `FlowmapWater`/`FlowmapBumpWater` have **no** GrabPass: they read `_OpaqueDepthTexture`, `_ReflectionTex`, and `_ReflectionVP` (section 4).

**Built-in equivalent:** `GrabPass { "_BackgroundTexture" }` is the same mechanism. The wrapper previously emitted only regular passes; now the GrabPass precedes the generated shader's pass (`aux_blocks`). Test (`GrabTest.cs` in the lab): two surfaces (red/blue) beneath a water surface using `Delphis/Map/Water`, with the camera set to `DepthTextureMode.Depth`:

| Shader | `_BackgroundTexture` after rendering | Water over red / blue background |
|---|---|---|
| With GrabPass | 256 × 256 texture bound | (209, 95, 96) / (65, 115, 245) |
| Without (`--no-aux`) | none | (136, 168, 169) / (139, 171, 172) |

The background shows through the water as intended by GrabPass; `isSupported` is true for both shaders. Still open: comparison with a Switch image (not possible) and flow rendering with the actual `_FlowMap`/`_NormalMap` textures from the bundles (part 2).

## 8. Textures from Neighboring Bundles

`scripts/material_export.py --resolve-external` resolves texture references with `FileID ≠ 0`: it reads the CAB name from the bundle's external file list, checks candidate dependencies from the catalog (`work/dpr_catalog.json`, field `deps`; names have no directory, so any `AssetAssistant` directory may qualify—the CAB name in the bundle is decisive), then reads the matched bundle's texture table (name, dimensions, format). The entry receives `texName`, `width`, `height`, `format`, and `extBundle`.

| Measurement | Value |
|---|---|
| Texture references in all materials (640 `Environments/` bundles) | 30,609 |
| In neighboring bundles | **52** across 5 bundles (`prefab_map/d29r0101`, `d29r0102`, `d05r0104`, `d05r0105`, `fields/area009`) |
| Resolved / unresolved | **52 / 0**, all in `Dpr/common_resources` |

C#: `MaterialTextureRef.ExternalBundle` carries the bundle name; `LoadedTextureIndex` finds the texture by name and dimensions as before, **provided `Dpr/common_resources` is loaded** (it is a catalog dependency, so `BundleProvider` loads it anyway). Same-name textures with identical dimensions remain a theoretical risk (0 wrong matches so far).

## 9. C# Implementation

| File | Contents |
|---|---|
| `Scripts/Render/TimeOfDay.cs` | `PeriodOfDay`, time from ticks, period, (period, progress, weight) |
| `Scripts/Render/EnvironmentData.cs` | `Rgba`, `EnvironmentParameters`, `EnvironmentSettingsData` (`GetTransition`), `EnvironmentSettingsCatalog` (reads `EnvironmentSettings.json` and `MapRenderSettings.json` from `scripts/environment_export.py`) |
| `Scripts/Render/EnvironmentState.cs` | Port of `SetLight`, `SetPokemonLight`, `OnUpdate` (`Apply` sets 21 globals through `GameGlobals`), `FieldLighting` (SceneConnector), `DepthOfFieldMath`, `DefaultTextures` |
| `Scripts/Render/GameGlobalSources.cs` | Section 2 table represented as data (`GameGlobalSources.All`, one entry per `GameGlobals.Specs`) |
| `Scripts/Render/Runtime/EnvironmentDriver.cs` | `EnvironmentDriver` (sets lighting, quality, globals each frame), `OriginalQuality` |
| `Scripts/Render/Runtime/CameraRigs.cs` | `ReflectionCameraDriver`, `DepthCaptureDriver` |
| `Scripts/Render/Runtime/UnityGlobalSink.cs` | Texture placeholders `black`/`white`/`gray`/`bump` → Unity built-in textures |
| `Scripts/Render/RenderChecks.cs`, `Runtime/SunLight.cs` | Checks for a black image (no light, light with no intensity, unset globals, multiple lights), `SunLight.Ensure/FindActive/Collect`, `RenderHealthWatch` (section 10a) |
| `scripts/environment_export.py` | exports settings and zone mappings to `work/masterdata/` |

Constants (factor 0.5, 1 − base, −1, 0.2, 60, 0.0001/0.9999, 10 minutes, `k` = 0.024) are fixed in tests (`RenderEnvironmentTests`, 18 tests: period boundaries, weight, ticks, transitions including angles and fog, every `Apply` formula, snow, cloud shadows, FixedTime, catalog, and source table). The constructor defaults for scene fields (cloud speed, tiling, shadow colors) are **not** in the repository; serialized values override them anyway.

## 10. Gaps (Current Status)

1. **`EnvironmentController` scene values** (`_CloudSpeed`, `_CloudTiling`, `_EmissionScale`, `_CloudShadowBase`, textures, shadow distance/offset/bias, `_WeatherMode`, `_SnowShadowColor`) live on the map's scene object (prefab), not in the tables. The exporter does not read them yet; `EnvironmentSceneParams` has the fields, but its source (prefab component in the bundle) is not connected. Zone 422 therefore used defaults for these fields.
2. **Weather:** `MapInfo.Weather` (`SYS_WEATHER`) and the calendar (`CalenderEncTable.weather`) control rain/snow and `SkyColorSettings`; their connection to `_WeatherMode` has not been traced.
3. **Multiple layer cameras** (compositor with shared color/depth texture) have only been reproduced for one camera.
4. **Post-processing** (blur kernel, focus map, bloom, color correction, feedback, `g_BackgroundTexture`) and the three per-object properties (`_UVOffset`, `_Corner`, `_RcpGridSize`) are missing (part 2).
5. **`GameManager.nowTime`** is system time; whether the game sets it differently when needed (debugging, events) has not been traced.
6. **Shadow fidelity** has only been checked structurally (no reference image); in-game lighting (shadow strength and resolution per scene) is in the prefab.
7. **`UsePass "Legacy Shaders/VertexLit/SHADOWCASTER"`** assumes Unity includes its built-in shader in the player (the `Always Included Shaders` build step has not been checked).
8. **`multi_compile_fwdbase`** is not needed (measured). All lab results use Unity 6000.3.26f1 on an Apple M1 Pro; other GPUs have not been checked.

### 10a. Update 2026-10-19 (`ap-effects-fidelity`, Part 2): Globals, Lighting, Black Frames, and “Hangs”

Details, method, and log evidence: `docs/material-remap.md`, section 10b. Implications for globals (lab, zone 422, 34 materials, Gamma, mean RGB from `RenderTexture`; actual `FieldController`: “rebuild (61/61 shaders, 124 material entries)”):

| State | Mean image value | Takeaway |
|---|---|---|
| No directional light; globals irrelevant (placeholders or null) | **(0, 0, 0)** | Forward shaders multiply by `_LightColor0`; without light, everything is black even if all 35 globals are set. `SunLight.Ensure` (Render/Runtime) guarantees a light, then `EnvironmentDriver` sets its color/intensity/rotation from game values. |
| Directional light, all globals null | (31, 39, 23) | Not black: without globals the image is merely darker (`_ShadowColor`, `_GlobalLightPower`, cloud term 0). |
| Directional light, placeholders (`SetDefaults`) | (37, 49, 28) | Compared with “all null,” placeholders make only a small difference (+6, +10, +5). |
| Directional light, zone 422 game values, hour 12 | (83, 104, 63) | As in section 6.4; the mean is unchanged with soft shadows (4 cascades, distance 20). |

Conclusions: (1) “Globals unset” never explains a black image, only a dark one; in this chain a **black** image always means “no light / dark light” (rules in `Render/RenderChecks.cs`, covered by `RenderChecksTests`). (2) Placeholders are only rough enough for visual smoke tests; measure images with `EnvironmentDriver` and zone values (hour selectable). (3) Globals cost: one `Tick` is just calculations plus 21 `Shader.SetGlobal*` calls; no compilation or variant selection. The editor hang in the main session was unrelated to globals and shaders (cause: `run_tests` in play mode).
Gaps (unchanged): `EnvironmentController` scene values, post-processing globals (9 unresolved), Switch reference image.

### 10b. Update 2026-10-19 (`ap-effects-fidelity`, Part 4): Scene Values, `_ShadowMapTexture`, Post-Processing

Details: `sichtpruefung-2` (git history; sections 5, 7, 8, 9).

| Topic | Result |
|---|---|
| `EnvironmentController` scene values (gap 1 from section 10) | **Read** from `Dpr/scenes/field` (`scripts/environment_export.py` → `EnvironmentScene.json`): shadow distance **45**, near plane **15**, normal bias 0, cloud `_CloudSpeed` (0.5, 0.5), `_CloudTiling` (0.03, 0.03), `_CloudShadowBase` 0, `_EmissionScale` 1, `_WeatherMode` 0, shadow color (0.41, 0.46, 0.53); other scenes (`battle`, `gms`, …) use 20 and 3. Textures `_NoiseTex`, `_SnowTex`, `_SnowNormalTex`, `_EnvironmentMap` are named; `_CloudShadowTex` is unresolved. `EnvironmentDriver` loads the file itself (`EnvironmentSceneData`). |
| Shadow distance | The original overrides the quality setting (20) each frame with the scene value 45; shadows then appear in zone 422 (22.06% of pixels darker, mean RGB (101.8 / 125.0 / 72.5) → (94.2 / 116.8 / 67.2)). At distance 20 the image center is outside the shadow area (0 pixels differ). |
| `_ShadowMapTexture` (new, 36th global) | Set only in frames with a shadow map; without one, a released reference remains and binds black (“everything shadowed”). This caused the “19% darker after zone 54” result. `ShadowMapGuard` sets it to white before every camera frame; zone 422 returns to (101, 124, 72) after zone 54. |
| Remaining post-processing globals (part 1 had 9 unresolved) | `_BlurOffsetX/Y` **verified** (vector (−2.2186, 2.2186, −0.6075, 0.6075), X or Y per pass; bit patterns `0xC00DF8DF, 0x400DF8DF, 0xBF1B9852, 0x3F1B9852`) and set in bloom (`PostChain`); `_SubTex0..4` (bloom levels) too. Still unresolved: `_FocusTex`, `_DelayFrameTexture`, `g_BackgroundTexture` (depth of field, feedback, particles), `_UVOffset`, `_Corner`, `_RcpGridSize`, `_EnvMatrix`. |

## 11. Reproduction

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
PYTHONPATH=tools/pydeps python3 scripts/environment_export.py                              # work/masterdata/EnvironmentSettings.json, MapRenderSettings.json
PYTHONPATH=tools/pydeps python3 scripts/material_export.py --out work/materials --resolve-external --dir Environments
python3 scripts/shader_wrap_all.py --out work/shaders/combined --used work/materials/used_variants.json --combine-shadow
python3 scripts/shader_wrap.py 'Delphis/Map/Standard' --pass 0 --keywords DIRECTIONAL SHADOWS_SCREEN _CASCADE_SINGLE --also 1:SHADOWS_DEPTH --out work/unity-shader-lab/Assets/XnuGen/x.shader
python3 scripts/shader_wrap.py 'Delphis/Map/Water' --pass 1 --out work/unity-shader-lab/Assets/XnuGen/water.shader   # with GrabPass
# Ghidra (one instance at a time; lock file work/ghidra.lock, waits up to 20 minutes)
scripts/ghidra/run_headless.sh <name> work/ghidra/x.log -postScript StringXrefs.java work/ghidra/out.txt _ShadowColor=0x4CAB640
scripts/ghidra/run_headless.sh <name> work/ghidra/x.log -postScript ExportDecompiled.java '^EnvironmentController\$\$' work/decomp/effects
scripts/ghidra/run_headless.sh <name> work/ghidra/x.log -postScript CallersOf.java work/ghidra/callers.txt 'EnvironmentController\$\$SetLight'
python3 -m unittest discover -s scripts/tests
```
