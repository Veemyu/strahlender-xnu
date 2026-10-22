# Original water rendering: findings for recompilation

Updated: 2026-10-19, 16:58. The “water in the Unity rebuild” task was **withdrawn**: the intended target is the recompiled BDSP app (`dev.local.xnubdsp`, tracks `ap-recomp-qa`/`ap-recomp-ios`), not the Unity project. **Nothing was changed** in Unity. This document records only material-analysis and reference-image findings useful to recompilation. No new Unity measurements or iPad startup investigation were performed.

Labels: **verified** means measured from our exports or the reference image; *inferred* means a conclusion not tested.

## 1. Reference (Ryujinx, original game)

`work/visual/ref/ryujinx/views/free_wasser_a.png` and `free_wasser_b.png` (local only, not in Git), two seconds apart, save SHA prefix 0396a4a62735, Canalave City (zone 24), pool right of the Pokémon Center, in-game hour ≈ 14.4 (file time 14:49:59 UTC minus offset 1388 s, assumption [A]).

Appearance: deep saturated blue with bright, sharp **caustics** (white net-like light lines and highlights at different positions in images a and b); faint **reflection/refraction** of the bridge and planks along the upper pool edge, and dark cast shadows in the water; orange bank edges (wood/copper) on both sides and pale stone walls.

Measurements (water region x 790–1180, y 170–650 in the 1280×720 image, **verified**):

| Metric | Image a | Image b |
|---|---|---|
| Mean RGB | 87.2 / 126.7 / 209.6 | 88.1 / 127.5 / 210.6 |
| RGB standard deviation | 25.8 / 17.1 / 24.7 | 26.2 / 17.8 / 25.1 |
| 99th brightness percentile | 191 | 195 |
| Very bright pixels (all channels > 200) | 0.27% | 0.33% |

Animation: mean difference between a and b in the region is **8.7** (5% of pixels differ by > 24). The mean stays stable while the caustic pattern moves. The original report treats animation through `_Time` and a stable overall color as **verified**. A recompiled frame should therefore have mean ≈ (87 / 127 / 210) ± 10%, and two frames should have regional MAD ≈ 9.

## 2. Zone 24 shader and material

Zone 24 water is in bundle `Environments/fields/area010` (area C02), material **`M_C_001_SeaWater_03`** (from `work/materials/Environments__fields__area010.json`, **verified**; Pokémon Center prefabs `c02r*` contain no water material):

| Property | Value |
|---|---|
| Shader | `Delphis/Map/FlowmapWater` (one pass, `Lightmode=FORWARDBASE`) |
| State | `QUEUE=Transparent`, `Blend SrcAlpha OneMinusSrcAlpha`, `ZWrite Off`, `ZTest LEqual`, `Cull Back` (inventory); material `renderQueue` −1 (shader default) |
| Keywords | `_ALPHABLEND_ON`, `_CASCADE_SINGLE`, `_ENVIRONMENTMAPENABLE_SPECULAR` |
| Instancing | No |
| Grab pass | **None** (only `Map/Water`, `Wave`, `Fog`, `WaterSurface`, `Encount01/02` have `_BackgroundTexture`) |
| Textures (bound by property name) | `_CausticsTex` “Caustics” 256×256 (format 10 = DXT1/BC1), tiling 4×4; `_FlowMap` “Flow” 256×256 (format 27 = RGBA/BC7 class according to export table), 1×1; `_TimeOffsetMap` “TimeOffset” 256×256 (format 1 = Alpha8), tiling 5×5, offset 0.3 |
| Colors | `_WaterColor` (0.012 / 0.205 / 0.620, alpha 0.698), `_Color` (0 / 0.626 / 1), `_SkyColor` (0.099 / 0.718 / 1), `_SpecularColor` (0.35 / 1 / 0.751), `_WaveColor` (0.344 / 1 / 1, alpha 0.25), `_Reflectivity` (1,1,1) |
| Scalars | `_CausticsIntensity` 6, `_CausticsExponential` 3, `_FlowSpeed` 0.1 (vector (1, 0, 1, 0)), `_FlowStrength` 0.015, `_TimeScale` 0.5, `_BumpScale` 0.67, `_FresnelPower` 3, `_RefractionScale` 3, `_ReflectionBias` 5, `_ReflectionOffsetScale` 1, `_DensityExponential` 2, `_MaxDensity` 1, `_TransDistance` 0.6, `_SpecularIntensity` 0.5, `_SpecularCosinePower` 18, `_Cull` 0 (material), `_SrcBlend` 1, `_DstBlend` 0 |

The image is consistent with this: `_WaterColor` in Gamma space produces deep blue; `_CausticsIntensity` 6 and exponent 3 produce sparse bright lines (0.3% of pixels above 200). *Inference:* The caustics texture uses two oppositely shifted UV sets (time × `_TimeScale`, offset from `_TimeOffsetMap`), explaining the moving net; this was not checked against shader code.

## 3. Inputs recompilation must provide

From the inventory (`docs/shader-inventar.md`, Globals section) and `docs/shader-globals.md`:

1. **`_OpaqueDepthTexture`** (`FlowmapWater`, `FlowmapBumpWater`): Depth after the opaque pass (`CameraEvent.AfterForwardOpaque`, `MultipleCameraCompositor`). Without it the shader uses depth 0/1 and draws a uniform brown surface in Unity (`sichtpruefung-3` in the git history, **verified** in the Unity rebuild). Water must not write to this depth texture (`ZWrite Off`).
2. **`_ReflectionTex` and `_ReflectionVP`**: Reflection camera (`ReflectionCameraFollower`), mirrored across y = 0, position (x, −y, z), Euler rotation (−x, y, −z), FOV = main-camera FOV × `_fovScale`, screen-sized texture with mips. **Inventory inconsistency:** The table lists `_ReflectionTex` only for `Map/FlowMap` and `Map/Standard`, while section 7 of `docs/shader-globals.md` also lists it for `FlowmapWater`. Whether zone 24 reads it is unresolved. The bridge reflection suggests it does (*inferred*).
3. **`_Time`** from game time (animation, section 1), plus environment globals (`_SkyColor`-like values come from the material; light and `_ShadowColor` from `EnvironmentController`).
4. Pass **blend state** (`SrcAlpha OneMinusSrcAlpha`, `ZWrite Off`) and **transparent draw order (queue 3000)** after all opaque surfaces; Cull Back. The mesh has no normals (only position, color, UV0 as Float16×2, `sichtpruefung-3` in the git history): missing normals are zero; water normals come from bump calculations.
5. Original **texture binding** uses material property names (`_CausticsTex`, `_FlowMap`, `_TimeOffsetMap`). Recompilation receives bindless handles in `cbuf 2` (from 0x568, stride 8, `docs/render-treue.md`); incorrect handles or unloaded textures produce a uniform surface.

## 4. Grab pass (other water shaders)

`Delphis/Map/Water`, `Wave`, `Fog`, and `WaterSurface` have a `_BackgroundTexture` grab pass before the main pass. The game creates **no** dedicated buffer; this is Unity's `GrabPass`, copying the image rendered so far. In recompilation, copy the current color target to a texture between opaque and transparent passes. Zone 24 does not need it (`FlowmapWater` has no grab pass). Unity-lab measurements: with the grab pass, the background shows through water (red (209, 95, 96), blue (65, 115, 245)); without it, the color stays constant (`docs/shader-globals.md`, section 7).

## 5. Recompilation checks

- Use the region and measurements in section 1: mean (87 / 127 / 210) ± 10%, standard deviation ≈ (26 / 17 / 25), very bright pixels ≈ 0.3%.
- Capture two frames two seconds apart: regional MAD ≈ 9, mean unchanged. No movement suggests missing `_Time` or time constants; movement without the caustic net suggests missing `_CausticsTex`.
- Compare with `scripts/visual_compare.py ref compare` (heatmap, image mean). A `free_wasser_a`/`b` view still needs adding to `scripts/visual/ref_map.json` (not done; manual comparison suffices for the figures above).

## 6. Unresolved

- Whether zone 24 `FlowmapWater` actually reads `_ReflectionTex` (section 3, item 2).
- Texture format code 27 was taken from the export table, not independently checked.
- iPad startup (two or three attempts before starting) was not investigated; this belongs to `ap-recomp-ios`.
