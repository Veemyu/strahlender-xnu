# Visual inspection 1: first zone 422 image with generated shaders (task `ap-effects-fidelity`, part 3)

Historical Unity-rebuild report; that rebuild is deprecated.

Date: 2026-10-19, Unity 6000.3.26f1 (main Editor, `unity/` project), macOS (M1 Pro), Built-in RP, Gamma, Metal. `FieldTest2` in Play mode with `XNU_GENERATED_SHADERS=1`: remapping reports 61/61 shaders and 124 material entries; game values from `EnvironmentSettings` (hour 12); **only** our generated shaders and character fallback shader, no original shader loaded, **no sound**.

Images are stored only under ignored `work/visual/`; descriptions are recorded here instead. Captures use `Camera.Render` into a `RenderTexture` (1280 × 720, alpha 255, Gamma), because `ScreenCapture` can return cyan (`Field/Editor/FieldShot.cs`).

## 1. Image observations

**Zone 422 (Twinleaf Town, hour 12, camera yaw 180, pitch 45.0°, FOV 17.5°).** Recognizable and coherent: the player's house has a green shingle roof, chimneys, logs, a door, and three windows; an orange mailbox stands outside. The neighboring house (roof, windows) is on the left; conifers with alpha-tested foliage on the right; grass with flowers, a light-brown path, and a sign at the top. Image mean **(101, 125, 72)**.

No black or magenta map areas, mirrored/inverted geometry, or background leaking through foliage. Shingles, windows, and wood look correct; winding/culling show no obvious issue. Textures and tiling are correctly assigned. Grass is medium green with a slight yellow tint, ground ochre, roof dark green: plausible in Gamma, not overexposed. The blue-violet `_ShadowColor` is barely visible at wall edges.

**Time of day (same position, `EnvironmentDriver`, hour set through `XNU_ENV_HOUR`):**

| Hour | Image mean | Observation |
|---|---|---|
| 7 | (99, 120, 75) | Slightly warmer/greener than noon |
| 12 | (101, 125, 72) | Daylight |
| 18.5 | (103, 121, 67) | Warmer evening |
| 22 | (57, 75, 49) | Dark; **windows glow** yellow-orange (emission through `_EmissionThreshold`), as expected at night |

**Zone 425 (player's house, hour 12, interior settings).** Complete living room: wood floor, striped wallpaper, kitchen counter with sink and stove, refrigerator, television (black screen), rug, table and chairs, stairs, two potted plants, and doormat at the bottom door. The isolated room sits against the uniform blue camera clear color; no indoor sky. Mean (128, 144, 166), 85 renderers.

**Zone 54 (town with Pokémon Center, pitch 40°, FOV 18°).** Herringbone paving, red-roofed Pokémon Center with Poké Ball sign, neighboring house with yellow roof and blue door, fence on the left, lattice roof at bottom right. Mean (139, 126, 98).

**Zone 367 (Route 209, gate to Hearthome City).** Visible after the section 3 fix: gatehouse with blue corrugated roof, windows, brick foundation, fence, sign, tall grass at top right, and deciduous trees. Mean (99, 122, 65).

**Player character.** Orientation is correct (facing the camera when leaving the house), standing at the front door. Image height ≈ 1.35 cells (target 1.4). The character is **whitish/gray without proper texture colors** (fallback shader; see open issues). **NPC markers:** Blue capsules with a white spot (left in zone 54, on the rug in zone 425), intentional placeholders. An irregular blue-brown shape below the player in zone 422 belongs to the map (puddle/decal), not the character; not investigated further.

**Sky/background.** No sky: the camera clears to a solid (0.45 / 0.62 / 0.85). Outdoor maps fill the frame; this color would appear at map edges.

**Camera.** Pitch 45°, FOV 17.5° (zone 422), 20° (425, 367), or 18° at pitch 40° (54) come from `CameraTable` and produce BDSP-like weak perspective. The cell grid aligns with the map: house five cells wide, blocked cells under it, door at (116, 885).

## 2. Measurements (Editor Play mode, `get_performance_stats`, three samples, 1493 × 840 Game view)

| Zone | Renderers in map hierarchy | Blocks | Draw calls | SetPass | Triangles | Vertices |
|---|---|---|---|---|---|---|
| 422 | 1,484 (5 of 12 containers) | 4 | 155 | 51 | 53,793 | 38,692 |
| 425 | 85 | – | 197 | 88 | 26,511 | 23,518 |
| 54 | 1,737 (cumulatively built) | 6 | 291 | 153 | 224,673 | 251,916 |
| 367 | 1,910 (cumulatively built) | 4 | 323 | 56 | 205,121 | 249,192 |

Zone 422 frame time: CPU frame 33.5 ms (30 fps, `targetFrameRate` 30, project VSync setting), main thread 1.3 ms, GPU 25–27 ms in the Editor Game view (includes Editor rendering; one sample 48 ms). Unity memory ≈ 620 MB, 1.09 GB reserved. Capture itself (render + readback, 1280 × 720): 44–84 ms. Zone changes: 422 → 425 in 375 ms; 425 → 54 in 908 ms (including map reload and fade).

Zone 54 `FieldMemoryLog`: Unity 569 MB, graphics 270 MB, textures 91 MB. Editor figures are not Player measurements; see `docs/player-build-1.md`.

## 3. Issues found and fixed

1. **Outdoor camera yaw (visual error, fixed).** Yaw 0 (earlier assumption) looked toward +Z: the door (code 105 at (116, 885), on the house's +Z side) was *behind* the house, and the player was hidden behind the roof (image mean (83, 104, 63)); the windowless gable faced the camera. Yaw **180** gives the correct image: grid x right/y down, front door and windows visible, player leaving toward the camera. Locator facing z = 0 also means “away from the door.” Added `FieldController.fieldCameraYaw`, default 180 (previously fixed 0; indoor yaw unchanged at 180). The decompilation finding in `docs/feld-szene-1.md` (yaw 0 except system flag `0x305`) remains recorded, but is disproved for the starting zone; `0x305` is unresolved.
2. **Zone 367 showed only the background (fixed, tested).** Streaming assigned each container (`R209`, `T05`, etc.) only to its **origin** block (`round(−x/32)`, `round(z/32)`). Route containers span multiple blocks and may not align to the 32-cell grid (`T04` at x = −540, `C07` at −678/574). `R209` originates at z = 672 (row 21), but meshes reach row 24; start (512, 726) is in row 22. No block there; the nearest was 23 cells away (load distance 20), giving zero renderers. `FieldAreaStreamer` now computes each container's world rectangle from mesh bounds (`BlockStreamingMath.BlocksCovering`, at most 16 blocks per axis) and assigns all intersecting blocks. Shared containers build once and unload only with the final block (reference count). Zone 422 now loads four blocks rather than one, with five containers.
3. **Initial player height in zone 367 (fixed, tested).** Ground is y = 2; the ground ray began at 0 + 1.2 and missed (height 0, player below ground). `RaycastGround.SpawnSearch` searches from above when placing/teleporting only; ordinary steps are unchanged.
4. **Magenta player/NPC markers after zone changes (fixed, tested).** `RemappedMaterials.Destroy` destroyed the *shared* fallback store used by the character. It now releases only map-created fallback materials (`FallbackMaterials.Release`).
5. **Character height from incorrect bounds (fixed).** Height 5.07 included every prefab renderer, even disabled ones (mounts, bicycle, alternate models), giving scale 0.28. Only active, enabled renderers now count: height 1.41, scale 1.0. Image size stayed ≈ 1.35 cells; animation apparently sets size itself. The 1.4 assumption is no longer necessary, but remains a target.
6. **Game values instead of placeholders; lighting (task 2).** `FieldController.EnsureRenderEnvironment` uses `SunLight.Ensure(transform, Soft)` instead of custom construction and adds an `EnvironmentDriver` to the sun. Zone settings come from `work/masterdata/EnvironmentSettings.json` and `MapRenderSettings.json` (default `<GameData>/masterdata`); hour comes from `XNU_ENV_HOUR`, otherwise `environmentHour`, otherwise local time (`useGameEnvironment`, `environmentHour`). Zones without settings (2 of 658) or a catalog retain placeholders and white sunlight. Zone 422: intensity 1.15, color (0.93, 0.93, 0.93), rotation (75, 345, 0), shadow distance 20. Mean (101, 125, 72), versus placeholder (37, 49, 28), matches `docs/shader-globals.md` section 10a.

Tests: Unity EditMode **645/645 passed** (previously 638; seven new `FieldStreamerContainerTests` for block coverage, limits, zone 367 assignment, shared containers, top-down ground search, and fallback release); Python `scripts/tests`: 268 passed; translator `make test` passed. `shader_translator/` and `scripts/shader_wrap.py` were unchanged.

## 4. Open issues and gaps

1. **Player and NPC markers use the fallback shader.** Character materials were not exported (`work/materials` contains no `Characters__…`), so the character is whitish-gray without texture colors or lighting; character shader variants were not generated. Next: export `Characters/persons/field/fc0001_00` with `material_export.py` and generate its variants.
2. **Other zones become ≈ 19% darker after visiting zone 54.** Zone 422 becomes (82, 101, 59) instead of (101, 125, 72); zone 367 becomes (86, 105, 57) instead of (99, 122, 65). Zones 54 and 422 share `FieldRenderSettings`. Ruled out: sun values, all 36 game globals (identical before/after), shadows on/off, hour, visits to 367 or 425. Reproducible: 54 → 422. Cause unresolved; suspected state outside globals, e.g. zones with `ReflectionCamera`.
3. **Roofs hide the character.** Zone 367 starts in the gatehouse door (`P_C_001_BarrierGate`, roof y = 6), with the roof between camera and player, hiding the player. Original roof-hiding behavior was not investigated.
4. **No sky/background except clear color.** Cloud shadows and field water/reflection (`ReflectionCameraDriver`, `DepthCaptureDriver`) are not connected. `EnvironmentController` scene values and post-processing (bloom, depth of field) remain missing (`docs/shader-globals.md`, section 10).
5. **No reference image.** `Ryujinx/` contains configuration, logs, saves, and shader caches, but no screenshots; pixel comparison with the original is impossible. Assessment is descriptive and based on familiarity with the game, not measured against a reference.
6. Outdoor yaw 180 is inferred from the image and locator data (door/facing), not original code; system-flag `0x305` camera behavior is unresolved.
7. Measurements cover only the Editor (Game view, Gamma RT capture 1280 × 720); Player and iPad results are pending.

## 4a. Follow-up (part 4, `docs/sichtpruefung-2.md`)

Updates to the issues above: (1) Model-bundle material remapping now gives player/NPCs generated shaders and color, but field-code integration remains pending. (2) **The 19% brightness error was traced and fixed:** `_ShadowMapTexture` remained a released reference after a zone with a shadow map (black meant everything shadowed); `ShadowMapGuard`. (4) The original has no skybox material: camera clear is black with alpha 0; sky is a sphere using `Delphis/Map/Sky`. Bloom/fog/FXAA were reconstructed (`PostChain`); depth of field and color correction remain open. Zone 422 shadows were missing because original scene values specify shadow distance 45 and near plane 15, not quality-setting distance 20.

## 5. Reproduction

```
# Editor: open FieldTest2 outside Play mode, then use unity command … eval:
#   Xnu.Field.Editor.FieldShot.Prepare(12f);   // XNU_GAMEDATA=<Repo>/work, XNU_GENERATED_SHADERS=1, XNU_ENV_HOUR=12
# editor_play, wait about 20 seconds (zone 422), then:
#   Xnu.Field.Editor.FieldShot.Status();       // zone status as text
#   Xnu.Field.Editor.FieldShot.Capture("…/work/visual/z422.png", 1280, 720);   // image mean, PNG
# Change zone: var f = FieldShot.Find(); f.StartCoroutine(f.SwitchZone(367));
# Always editor_stop before run_tests
```

Changed files: `Field/Runtime/{FieldController,FieldAreaStreamer,PlayerAvatar,FallbackMaterials,RemappedMaterials}.cs`, `Field/Logic/BlockStreaming.cs`; new: `Field/Editor/FieldShot.cs`, `Tests/EditMode/FieldStreamerContainerTests.cs`.
