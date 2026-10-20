# Shader Inventory, Ryujinx Cache Mapping, and Interfaces (as of 2026-10-18)

Part 1 of `ap-shaders`: read-only inspection and measurement. Nothing was rendered or played; no dumped shader was run in Unity.
This file contains only names, numbers, and render states. Binary data (shader code, textures) is not in the repository.
Labels: **verified** = measured directly; *inferred* = conclusion without a cross-check; **open** = unresolved.
Related context: `render-treue.md` (1:1 fidelity requirement), `shader-audio-machbarkeit.md` (cache format, 5,937 SPIR-V modules).

## Tools and Outputs

| Script (repository) | Task | Output (local, `work/shaders/`, not in repository) |
|---|---|---|
| `scripts/shader_inventory.py` | Read shader objects via UnityPy TypeTree: properties, SubShaders, passes, render states, programs, blob sizes | `inventory.json` |
| `scripts/shader_map.py` | Parse NVN blobs, compare Maxwell code with `guest.data`, resolve `shared.toc` | `mapping.json` |
| `scripts/shader_reflect.py` | Analyze SPIR-V for mapped cache entries with `spirv-cross --reflect` and `--msl` | `reflect.json` |
| `scripts/shader_report.py` | Generate tables and metrics for this document | `tables.md` |

Run from the repository root, for example: `PYTHONPATH=tools/pydeps python3 scripts/shader_inventory.py`. Peak memory use is about 600 MB RAM; each script takes under two minutes.

## 1. Inventory

### Sources

- **Verified:** The 64 shaders in scope: 63 in `AssetAssistant/Dpr/shaders` and 1 in `AssetAssistant/Effects/fxparticle` (`FxSystem/Particle`). All use platform ID 19 (= `kShaderCompPlatformSwitch` in the UnityPy enumeration), Unity 2019.4.27f1, program type `ConsoleVS`/`ConsoleFS`, hardware tier 3.
- **Verified (additional):** A pass over all 14,056 files under `AssetAssistant` (counting object types only) found more shader objects: 26 from 8 additional sources. These include `Data/resources.assets` (9, including `Hidden/ModelViewReflection`, `TextMeshPro/Sprite`, duplicates of `UI/Custom`, `Custom/Fxaa`, Bloom, and TMP), `Dpr/tmpshader` (11 TextMeshPro variants), one each in `FureaiHiroba/poffin/prefabs`, `Environments/prefab_map/c10r0101`, `Environments/underground/ugspace03`, and `Environments/bg/arenas/ground/g070` (all four are Unity `Standard`), `Dpr/scenes/digfossil` (`Skybox/Procedural`), and `Dpr/fieldui/gymseq` (`Hidden/encseqpanelshader`). The catalog (`work/dpr_catalog.json`) lists only the two bundles. Additional shaders are in `inventory.json` under `extraShaders` and are included in mapping (section 3); the tables below cover only the 64 in scope.
- `fxparticle` also contains 400 `ShaderVariantCollection` objects with 2,000 variants total (keyword text and pass type). The shader itself has 3,988 Vertex/Fragment pairs. 1,994 of the 2,000 keyword sets exist in the shader.
- The `shaders` file also contains 1 `Material` (not analyzed).
- Structural note: the shader object's `m_Name` field is empty. Its name is in `m_ParsedForm.m_Name`.

### Metrics for the 64 Shaders

- Total programs: 6,878 Vertex, 6,832 Fragment, **0** Geometry, **0** Hull, **0** Domain, 0 Raytracing. The bundles contain **no tessellation, geometry shaders, or compute**.
- Passes per shader: 1 pass in 45 shaders, 2 in 16, 3 in 2, and 4 in 1 (`UI/Blur`). All 64 have exactly one SubShader with LOD 0. In total: 74 regular passes, 9 GrabPass, and 4 UsePass (all `Legacy Shaders/VertexLit/SHADOWCASTER`).
- Keywords: 155 distinct names. Local keywords (`shader_feature_local`/`multi_compile_local`) occur in only 5 shaders (`UI/Custom`, `UI/UI-SoundWave`, `UI/UI-Multiply`, `Custom/Contest/ColorAdditve`, `Delphis/Dig/DigColorGain`).
- Instancing: 4 shaders have an instancing variant (`Delphis/Map/Standard`, `Custom/StencilMask`, `UI/UI-Multiply`, `FxSystem/Particle`). Only `FxSystem/Particle` also has a procedural instancing variant (`PROCEDURAL_INSTANCING_ON`).
- Render states across 87 passes (including GrabPass and UsePass, whose state is unspecified): Blend `One Zero` (= off) 56, `SrcAlpha OneMinusSrcAlpha` 13, controlled by material properties (`_SrcBlend`/`_DstBlend` or `_SrcColor`/`_DestColor`) 11, `SrcAlpha One` 2, `One One` 2, `One OneMinusSrcAlpha` 2, `DstColor OneMinusSrcAlpha` 1. Stencil is active in 12 passes. ZWrite is property-controlled (`_ZWrite`) in 12; ZTest (`_ZTest`, `unity_GUIZTestMode`) in 20; Cull (`_Cull`, `_CullMode`) in 15.
- Queue tags: Transparent 23 (+1 `Transparent-1`), Overlay 2, Background 1, Geometry±n 6; the remaining 31 shaders have no queue. The original contains the typo `RenderType=Opeque` five times (`Dpr/PostEffect/*`). It does not affect behavior, but preserve it as an original quirk if shader replacement searches by RenderType.
- Properties: 964 total: 394 Float, 262 Range, 145 Texture (143 2D, 2 Cube), 116 Color, 47 Vector. Property attributes: `PowerSlider` 94, `Header` 63, `Enum` 45, `Toggle` 44, `KeywordEnum` 40, `Space` 19, `MaterialToggle` 13, `ValueOffset` 3. Flags: `HideInInspector` 56, `NoScaleOffset` 29, `PerRendererData` 10, `HDR` 2.
- Default textures: `white` 88, `black` 37, `bump` 16, `gray` 3, `green` 1. Most common texture name: `_MainTex` (47 shaders).
- Custom editor classes (names from game code, not included in bundles): `TMPro.EditorUtilities.TMP_SDFShaderGUI` (2), `DelphisMapStandardShaderGUI`, `DelphisCharacterStandardShaderGUI` (2), `PokeDefaultGUI` (2), `FireCoreShaderGUI`, `FireMaskShaderGUI`, `SmokeMaskShaderGUI`, `InspectorFxParticle`. Fallbacks are set for `TextMeshPro/Distance Field` (to the mobile variant) and `Custom/StencilMask` (`Diffuse`).
- Program blobs: 11,974,198 B compressed, 84,758,224 B decompressed (all 64). 62 shaders have one segment; `Delphis/Map/Standard` and `FxSystem/Particle` have three each (about 16 MB each).
- Vertex inputs (Unity channel → shader input): the most common layout uses channels 0–5 (position, normal, tangent, color, UV0, UV1) in 2,560 programs, all in `Delphis/Map/Standard`. Next are channels 0, 3, 4 (position, color, UV0) in 1,808 programs across 16 shaders (UI, Blend/Additive/Water, post-processing). Then channels 0, 3, 4, 5, 6, 7 (plus UV1–UV3) in 1,670 programs, all in `FxSystem/Particle`.

### Families (grouped by shader name; classification is ours)

Character/Pokémon models 8, environment 18, UI/text/video 10, particles/effects 13, post-processing 15; 64 total.
Table A columns: passes; Vertex/Fragment programs; keyword combinations (sum across passes: distinct keyword sets among programs); number of distinct keywords; total properties/texture properties; instancing variant; cache entries (number of Ryujinx programs mapped to this shader in section 3).
“Combos” equal to “V/F” means each keyword set has its own program for each stage. `Mitake/*` and `UI/Custom` have different numbers of Vertex and Fragment programs (some keywords apply to only one stage).

#### Character / Pokémon Models

| Shader | Passes | V/F | Combos | Kw | Props/Tex | Instancing | Cache |
|---|---|---|---|---|---|---|---|
| `Delphis/Character/DepthOnly` | 2 | 6/6 | 6 | 3 | 39/4 | no | 6 |
| `Delphis/Character/Standard` | 2 | 28/28 | 28 | 8 | 45/4 | no | 28 |
| `Delphis/Poffin` | 2 | 28/28 | 28 | 8 | 49/7 | no | 28 |
| `Mitake/MitakeDepthOnlyShader` | 1 | 1/1 | 1 | 0 | 0/0 | no | 1 |
| `Mitake/MitakeStandardBumpShader` | 2 | 32/16 | 32 | 6 | 59/6 | no | 4 |
| `Mitake/MitakeStandardPetrify` | 2 | 32/16 | 32 | 6 | 63/9 | no | 4 |
| `Mitake/MitakeStandardPetrifyFire` | 1 | 1/1 | 1 | 0 | 35/7 | no | 1 |
| `Mitake/MitakeStandardShader1st` | 3 | 42/26 | 42 | 10 | 56/4 | no | 14 |

#### Environment

| Shader | Passes | V/F | Combos | Kw | Props/Tex | Instancing | Cache |
|---|---|---|---|---|---|---|---|
| `Custom/StencilMask` | 2 | 11/9 | 11 | 8 | 0/0 | yes | 9 |
| `Custom/WaterInteration/DynamicNormalMap` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Custom/WaterInteration/WaterSimulation` | 1 | 1/1 | 1 | 0 | 4/1 | no | 1 |
| `Delphis/Map/Blend` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Delphis/Map/FlowMap` | 2 | 1/1 | 1 | 0 | 5/2 | no | 1 |
| `Delphis/Map/FlowmapBumpWater` | 1 | 1/1 | 1 | 0 | 27/4 | no | 1 |
| `Delphis/Map/FlowmapWater` | 1 | 1/1 | 1 | 0 | 20/3 | no | 1 |
| `Delphis/Map/Fog` | 2 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Delphis/Map/LineUVScroll` | 1 | 1/1 | 1 | 0 | 11/1 | no | 1 |
| `Delphis/Map/Mask` | 1 | 1/1 | 1 | 0 | 1/0 | no | 1 |
| `Delphis/Map/PhotoFrame` | 1 | 1/1 | 1 | 0 | 8/1 | no | 1 |
| `Delphis/Map/Sky` | 2 | 4/4 | 4 | 4 | 14/6 | no | 3 |
| `Delphis/Map/Standard` | 2 | 2570/2570 | 2570 | 18 | 71/9 | yes | 2570 |
| `Delphis/Map/Water` | 2 | 1/1 | 1 | 0 | 15/3 | no | 1 |
| `Delphis/Map/Wave` | 2 | 1/1 | 1 | 0 | 6/2 | no | 1 |
| `Delphis/Snowfield/Snowfield` | 2 | 4/4 | 4 | 4 | 4/4 | no | 4 |
| `Delphis/WaterSimulation/WaterSurface` | 2 | 1/1 | 1 | 0 | 11/3 | no | 1 |
| `Dpr/Objects/ShadowCast` | 1 | 2/2 | 2 | 1 | 1/1 | no | 2 |

#### UI / Text / Video

| Shader | Passes | V/F | Combos | Kw | Props/Tex | Instancing | Cache |
|---|---|---|---|---|---|---|---|
| `Delphis/UI/FrostedGlass` | 1 | 1/1 | 1 | 0 | 12/3 | no | 1 |
| `MovieTexture` | 1 | 1/1 | 1 | 0 | 2/2 | no | 2 |
| `TextMeshPro/Distance Field` | 1 | 8/8 | 8 | 3 | 65/5 | no | 8 |
| `TextMeshPro/Mobile/Distance Field` | 1 | 8/8 | 8 | 3 | 35/1 | no | 8 |
| `UI/Blur` | 4 | 2/2 | 2 | 0 | 7/1 | no | 2 |
| `UI/Custom` | 1 | 4/16 | 16 | 4 | 19/1 | no | 16 |
| `UI/UI-Gray` | 1 | 2/2 | 2 | 1 | 10/1 | no | 2 |
| `UI/UI-Multiply` | 1 | 4/4 | 4 | 2 | 7/2 | yes | 4 |
| `UI/UI-SolidColor` | 1 | 2/2 | 2 | 1 | 6/1 | no | 2 |
| `UI/UI-SoundWave` | 1 | 4/4 | 4 | 2 | 9/1 | no | 1 |

#### Particles / Effects

| Shader | Passes | V/F | Combos | Kw | Props/Tex | Instancing | Cache |
|---|---|---|---|---|---|---|---|
| `Custom/AfterImage` | 1 | 1/1 | 1 | 0 | 5/2 | no | 1 |
| `Custom/Contest/ColorAdditve` | 1 | 4/4 | 4 | 2 | 1/1 | no | 1 |
| `Custom/ProceduralPlane/Footprint` | 1 | 1/1 | 1 | 0 | 9/1 | no | 1 |
| `Custom/ProceduralPlane/FrameFade` | 1 | 1/1 | 1 | 0 | 2/1 | no | 1 |
| `Delphis/Battle/Encount01` | 2 | 1/1 | 1 | 0 | 2/1 | no | 1 |
| `Delphis/Battle/Encount02` | 2 | 1/1 | 1 | 0 | 2/1 | no | 1 |
| `Delphis/Dig/DigColorGain` | 1 | 4/4 | 4 | 2 | 1/1 | no | 1 |
| `Delphis/Map/Additive` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `FxSystem/Particle` | 1 | 3988/3988 | 3988 | 102 | 77/3 | yes | 138 |
| `Mitake/FireCore1st` | 1 | 1/1 | 1 | 0 | 21/3 | no | 1 |
| `Mitake/FireMask1st` | 1 | 18/18 | 18 | 8 | 18/2 | no | 6 |
| `Mitake/MitakeGroundEffectShader1st` | 3 | 21/13 | 21 | 9 | 46/4 | no | 7 |
| `Mitake/SmokeMask_MT` | 1 | 3/3 | 3 | 3 | 10/2 | no | 1 |

#### Post-Processing

| Shader | Passes | V/F | Combos | Kw | Props/Tex | Instancing | Cache |
|---|---|---|---|---|---|---|---|
| `Custom/Bloom Finalize` | 1 | 4/4 | 4 | 4 | 6/2 | no | 4 |
| `Custom/Bloom Setup` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Custom/CaptureFocus` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Custom/DepthOfField` | 1 | 1/1 | 1 | 0 | 4/4 | no | 1 |
| `Custom/Downsample2x2Focus` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Custom/EffectCopyTexture` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Custom/ExpandFocus` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Custom/Fxaa` | 1 | 3/3 | 3 | 3 | 6/3 | no | 3 |
| `Custom/Gaussian7x7` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Custom/ResolveFocus` | 1 | 1/1 | 1 | 0 | 1/1 | no | 1 |
| `Dpr/PostEffect/BtlvPfxShader` | 1 | 4/4 | 4 | 2 | 11/1 | no | 4 |
| `Dpr/PostEffect/ChromaticAberration` | 1 | 1/1 | 1 | 0 | 2/1 | no | 1 |
| `Dpr/PostEffect/ColorFiler` | 1 | 1/1 | 1 | 0 | 2/1 | no | 1 |
| `Dpr/PostEffect/FeedbackBlur` | 1 | 1/1 | 1 | 0 | 8/0 | no | 1 |
| `Dpr/PostEffect/RadualBlur` | 1 | 1/1 | 1 | 0 | 4/1 | no | 1 |

Required textures and properties per shader are fully listed in `inventory.json` (`properties`: name, display name, type, default value, texture dimension, default texture; `stages.*.textures`: texture unit, name, dimension). The most-used textures are material properties (`_MainTex`, `_BumpTex`, `_Col0Tex`, `_EmissionMaskTex`, `_ComplexTex`, `_FlowMap`, `_NoiseTex`, …). Shaders also read **global textures** that are not listed as properties and must be set by the game:

| Global texture | Shaders (count) | Examples |
|---|---|---|
| `_ShadowMapTexture` | 8 | Character/Standard, Map/Standard, Poffin |
| `_CloudShadowTex` | 7 | Character/Standard, Map/Standard, Poffin |
| `_BackgroundTexture` (GrabPass) | 5 + `g_BackgroundTexture` in Particle | Encount01/02, Map/Water |
| `_CameraDepthTexture` | 5 | Map/Additive, Map/Blend, Map/Fog |
| `_OpaqueDepthTexture` | 5 | FlowmapWater, FlowmapBumpWater, Map/Standard |
| `_EnvironmentMap` | 5 | Character/Standard, Map/Standard |
| `_GlobalDepthTexture` | 2 | Bloom Finalize, CaptureFocus |
| `_ReflectionTex` | 2 | Map/FlowMap, Map/Standard |
| `_LightTexture0`, `_LightTextureB0` | 2 each | Mitake Standard/GroundEffect (light cookie, attenuation) |
| `_SnowTex`, `_SnowNormalTex`, `_FocusTex`, `_SubTex0`–`4`, `_DelayFrameTexture`, `_GrabTexture` | 1 each | Map/Standard, Downsample2x2Focus, Bloom Finalize, FeedbackBlur, UI/Blur |

### Render State per Pass (from `m_State`, Table B)

`[_Name]` means the value comes from a material property. GrabPass and UsePass state fields are unspecified (placeholders `ZTest Disabled`, `Cull Off`, `ZWrite Off`); those values have no meaning there. Stencil rows list only Ref, comparison, and pass operation (read/write masks and Fail/ZFail are in `inventory.json`). Tags: `Lightmode` is the pass tag; `QUEUE`/`RenderType` come from the SubShader.

#### Character / Pokémon Models

| Shader | Pass | Tags | State |
|---|---|---|---|
| `Delphis/Character/DepthOnly` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest LEqual; Cull Back; ColorMask 0; Stencil Ref 0 Comp GEqual Pass Keep |
| `Delphis/Character/DepthOnly` | #1 | Lightmode=SHADOWCASTER, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back; ColorMask 0 |
| `Delphis/Character/Standard` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest LEqual; Cull Back; Stencil Ref 0 Comp GEqual Pass Keep |
| `Delphis/Character/Standard` | #1 | Lightmode=SHADOWCASTER, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull [_Cull] |
| `Delphis/Poffin` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest LEqual; Cull Back; Stencil Ref 0 Comp GEqual Pass Keep |
| `Delphis/Poffin` | #1 | Lightmode=SHADOWCASTER, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull [_Cull] |
| `Mitake/MitakeDepthOnlyShader` | #0 | Lightmode=FORWARDBASE | ZWrite On; ZTest LEqual; Cull Back; ColorMask 0 |
| `Mitake/MitakeStandardBumpShader` | #0 | Lightmode=FORWARDBASE | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeStandardBumpShader` | UsePass `Legacy Shaders/VertexLit/SHADOWCASTER` | – | (unspecified) |
| `Mitake/MitakeStandardPetrify` | #0 | Lightmode=FORWARDBASE | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeStandardPetrify` | UsePass `Legacy Shaders/VertexLit/SHADOWCASTER` | – | (unspecified) |
| `Mitake/MitakeStandardPetrifyFire` | #0 | QUEUE=Geometry+2, RenderType=Opaque | ZWrite On; ZTest [_ZTest]; Cull Back; Stencil Ref 0 Comp Equal Pass Keep |
| `Mitake/MitakeStandardShader1st` | #0 | Lightmode=FORWARDBASE | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeStandardShader1st` | #1 | Lightmode=FORWARDADD | Blend One One; ZWrite Off; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeStandardShader1st` | UsePass `Legacy Shaders/VertexLit/SHADOWCASTER` | – | (unspecified) |

#### Environment

| Shader | Pass | Tags | State |
|---|---|---|---|
| `Custom/StencilMask` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Back; ColorMask 14; Stencil Ref 1 Comp Always Pass Replace |
| `Custom/StencilMask` | #1 | Lightmode=FORWARDADD, RenderType=Opaque | Blend SrcAlpha One; ZWrite Off; ZTest LEqual; Cull Back; ColorMask 14; Stencil Ref 1 Comp Always Pass Replace |
| `Custom/WaterInteration/DynamicNormalMap` | #0 | – | ZWrite Off; ZTest LEqual; Cull Off |
| `Custom/WaterInteration/WaterSimulation` | #0 | – | ZWrite Off; ZTest LEqual; Cull Off |
| `Delphis/Map/Blend` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Off |
| `Delphis/Map/FlowMap` | #0 Grab | QUEUE=Transparent | (unspecified) |
| `Delphis/Map/FlowMap` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Map/FlowmapBumpWater` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Map/FlowmapWater` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Map/Fog` | #0 Grab | QUEUE=Transparent | (unspecified) |
| `Delphis/Map/Fog` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Off |
| `Delphis/Map/LineUVScroll` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Opaque | Blend SrcAlpha OneMinusSrcAlpha; ZWrite On; ZTest LEqual; Cull Back |
| `Delphis/Map/Mask` | #0 | QUEUE=Geometry-1, RenderType=Opaque | ZWrite Off; ZTest LEqual; Cull Back; ColorMask 0; Stencil Ref 0 Comp Always Pass Replace |
| `Delphis/Map/PhotoFrame` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back |
| `Delphis/Map/Sky` | #0 | Lightmode=FORWARDBASE, QUEUE=Geometry, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back |
| `Delphis/Map/Sky` | #1 | Lightmode=SHADOWCASTER, QUEUE=Geometry, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back |
| `Delphis/Map/Standard` | #0 | Lightmode=FORWARDBASE, RenderType=Opaque | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest LEqual; Cull [_Cull]; ColorMask [_ColorMask] |
| `Delphis/Map/Standard` | #1 | Lightmode=SHADOWCASTER, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull [_Cull] |
| `Delphis/Map/Water` | #0 Grab | QUEUE=Transparent | (unspecified) |
| `Delphis/Map/Water` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Opaque | ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Map/Wave` | #0 Grab | QUEUE=Transparent | (unspecified) |
| `Delphis/Map/Wave` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Opaque | ZWrite Off; ZTest LEqual; Cull Back |
| `Delphis/Snowfield/Snowfield` | #0 | Lightmode=FORWARDBASE, QUEUE=Background, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Back; Stencil Ref 1 Comp Always Pass Replace |
| `Delphis/Snowfield/Snowfield` | #1 | Lightmode=SHADOWCASTER, QUEUE=Background, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull [_Cull] |
| `Delphis/WaterSimulation/WaterSurface` | #0 Grab | QUEUE=Transparent | (unspecified) |
| `Delphis/WaterSimulation/WaterSurface` | #1 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Opaque | ZWrite Off; ZTest LEqual; Cull Back; Stencil Ref 2 Comp NotEqual Pass Keep |
| `Dpr/Objects/ShadowCast` | #0 | Lightmode=SHADOWCASTER, QUEUE=Transparent-1 | ZWrite On; ZTest LEqual; Cull Back |

#### UI / Text / Video

| Shader | Pass | Tags | State |
|---|---|---|---|
| `Delphis/UI/FrostedGlass` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |
| `MovieTexture` | #0 | – | ZWrite On; ZTest LEqual; Cull Back |
| `TextMeshPro/Distance Field` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend One OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull [_CullMode]; ColorMask [_ColorMask] |
| `TextMeshPro/Mobile/Distance Field` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend One OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull [_CullMode]; ColorMask [_ColorMask] |
| `UI/Blur` | #0 Grab, #2 Grab | QUEUE=Transparent, RenderType=Opaque | (unspecified) |
| `UI/Blur` | #1, #3 | QUEUE=Transparent, RenderType=Opaque | ZWrite On; ZTest LEqual; Cull Off |
| `UI/Custom` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend [_SrcColor] [_DestColor]; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |
| `UI/UI-Gray` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |
| `UI/UI-Multiply` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend DstColor OneMinusSrcAlpha; ZWrite Off; ZTest LEqual; Cull Off |
| `UI/UI-SolidColor` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |
| `UI/UI-SoundWave` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off; ColorMask [_ColorMask] |

#### Particles / Effects

| Shader | Pass | Tags | State |
|---|---|---|---|
| `Custom/AfterImage` | #0 | RenderType=Opaque | ZWrite Off; ZTest Always; Cull Off |
| `Custom/Contest/ColorAdditve` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off |
| `Custom/ProceduralPlane/Footprint` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend [_SrcBlend] [_DstBlend]; ZWrite Off; ZTest LEqual; Cull Off |
| `Custom/ProceduralPlane/FrameFade` | #0 | – | ZWrite Off; ZTest LEqual; Cull Off |
| `Delphis/Battle/Encount01`, `Encount02` | #0 Grab | QUEUE=Overlay | (unspecified) |
| `Delphis/Battle/Encount01`, `Encount02` | #1 | QUEUE=Overlay | ZWrite Off; ZTest Always; Cull Off |
| `Delphis/Dig/DigColorGain` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha OneMinusSrcAlpha; ZWrite Off; ZTest [unity_GUIZTestMode]; Cull Off |
| `Delphis/Map/Additive` | #0 | Lightmode=FORWARDBASE, QUEUE=Transparent, RenderType=Transparent | Blend SrcAlpha One; ZWrite Off; ZTest LEqual; Cull Off |
| `FxSystem/Particle` | #0 | QUEUE=Transparent, RenderType=Transparent | Blend [_SrcColor] [_DestColor]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_Cull] |
| `Mitake/FireCore1st` | #0 | QUEUE=Geometry+2, RenderType=Opaque | ZWrite [_ZWrite]; ZTest [_ZTest]; Cull Back; Stencil Ref 0 Comp Equal Pass Keep |
| `Mitake/FireMask1st` | #0 | QUEUE=Geometry+1, RenderType=Opaque | ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode]; ColorMask 0; Stencil Ref 0 Comp NotEqual Pass Replace |
| `Mitake/MitakeGroundEffectShader1st` | #0 | Lightmode=FORWARDBASE | Blend [_SrcBlend] [_DstBlend]; ZWrite [_ZWrite]; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeGroundEffectShader1st` | #1 | Lightmode=FORWARDADD | Blend One One; ZWrite Off; ZTest [_ZTest]; Cull [_CullMode] |
| `Mitake/MitakeGroundEffectShader1st` | UsePass `Legacy Shaders/VertexLit/SHADOWCASTER` | – | (unspecified) |
| `Mitake/SmokeMask_MT` | #0 | QUEUE=Geometry+1, RenderType=Opaque | ZWrite [_ZWrite]; ZTest [_ZTest]; Cull Off; ColorMask 0; Stencil Ref 0 Comp NotEqual Pass Replace |

#### Post-Processing

All passes use `ZWrite Off; ZTest Always; Cull Off` (full-screen triangles) with blending disabled, except:
`Dpr/PostEffect/FeedbackBlur`, which uses `Blend SrcAlpha OneMinusSrcAlpha`. This applies to `Custom/Bloom Finalize`, `Bloom Setup`, `CaptureFocus`, `DepthOfField`, `Downsample2x2Focus`, `EffectCopyTexture`, `ExpandFocus`, `Fxaa`, `Gaussian7x7`, `ResolveFocus`, and `Dpr/PostEffect/BtlvPfxShader`, `ChromaticAberration`, `ColorFiler`, `FeedbackBlur`, `RadualBlur` (one pass each).

### Notable Details (Summary)

- **No tessellation, geometry shaders, or compute** in the bundles. The cache contains 5 Compute programs that do not match a bundled shader (see section 3).
- **Lighting:** environment/character shaders are Unity forward shaders with `FORWARDBASE`, `SHADOWCASTER` (and `FORWARDADD` for `Mitake/*`). Keywords mostly show one directional light (`DIRECTIONAL`) with shadows (`SHADOWS_SCREEN`, `SHADOWS_DEPTH`, `SHADOWS_CUBE`). Only `Mitake/*` supports point and spot lights (`POINT`, `SPOT`, `*_COOKIE`, `VERTEXLIGHT_ON`, `LIGHTPROBE_SH`). None of the 155 shaders uses lightmap keywords.
- `Delphis/Map/Standard` is the largest shader: 18 keywords, 2,570 variants, 71 properties, instancing (`INSTANCING_ON`). It has 2,562 variants in the FORWARDBASE pass and 8 in SHADOWCASTER.
- `FxSystem/Particle`: 102 keywords, 3,988 variants, one pass, instancing and procedural instancing. Its keywords describe a combiner system (`_COLORTEXTUREEXPRESSION_*`, `_ALPHAEXPRESSION_*`, `_MULTITEXTUREMODE_*`).
- The 9 GrabPass entries use `_BackgroundTexture` (7 passes) or the default Grab texture (`UI/Blur`).
- Stencil appears in `Custom/StencilMask`, `Snowfield`, `WaterSurface`, `Map/Mask`, `Mitake/Fire*`/`SmokeMask`, and `Delphis/Character/*` (GEqual). Stencil masks matter visually and are specified in pass data.
- Unity shader source is not present in the bundles. Inventory columns contain program metadata.

## 2. ShaderLab Skeleton from ParsedForm

Result: **A complete ShaderLab skeleton can be reconstructed from `m_ParsedForm`, except for the program code.** This is an analysis of the available data. No reconstruction was attempted in the Unity Editor, and no script was written to generate `.shader` text. *Inferred:* a Python generator based on `inventory.json` is a manageable task. AssetRipper already emits placeholder files for 9 shaders (`//DummyShaderTextExporter`, name and properties only); that is less than ParsedForm provides.

| Part | Present in ParsedForm? | Note |
|---|---|---|
| Shader name, `CustomEditor`, `Fallback`, dependencies | yes | Name is only in `m_ParsedForm.m_Name` |
| Properties: name, display name, type, default value, range limits, default texture, texture dimension | yes | Range stored as [value, min, max] |
| Property attributes (`[Toggle]`, `[KeywordEnum(...)]`, `[Enum(...)]`, `[PowerSlider(n)]`, `[Header]`, `[Space]` …) and flags (`HideInInspector`, `NoScaleOffset`, `PerRendererData`, `HDR`) | yes | Attributes are stored as text per property (e.g. 94 `PowerSlider`, 44 `Toggle`) |
| SubShader: tags, LOD | yes | LOD is always 0 |
| Pass: type (normal, UsePass, GrabPass), name, tags (`LightMode` …), GrabPass texture name | yes | |
| Render state: Blend (including alpha, Op, MRT blend), ZWrite, ZTest, Cull, ColorMask, Offset, AlphaToMask, Stencil (Ref, masks, Comp/Pass/Fail/ZFail, Front/Back), fog state | yes | Values can reference material properties (`[_SrcBlend]`); the property name is stored |
| Keywords per program (global and local) and which combinations were compiled | yes | **Not** recoverable: whether `multi_compile` or `shader_feature`, and grouping (which keywords belong to one selection group). Combination lists can be derived, but not the original `#pragma` lines |
| Instancing flag per pass, procedural instancing | yes | The pragmas (`multi_compile_instancing`, `instancing_options`) are missing |
| Parameter layout per program: constant-buffer names, sizes, members with offsets and components, textures (unit, dimension), input channels | yes | This is the program interface (section 4) |
| Requirements (`m_ShaderRequirements`), hardware tier | yes | Only as a bitmask |
| **HLSL/CG program code** | **no** | Only NVN binary code (Maxwell). Code can be recovered only from SPIR-V/Maxwell, not from ParsedForm |
| `#include`/helper functions, struct names, variable names, comments | no | |
| Custom `UsePass` targets | name only | `Legacy Shaders/VertexLit/SHADOWCASTER` requires Unity's built-in legacy shader |

Implication: the skeleton (properties, tags, states, keyword list) can be generated mechanically. Each shader's program body must come from cache SPIR-V (or directly from Maxwell). That is the real work required for 1:1 fidelity (`render-treue.md`).

## 3. Mapping Bundle Programs ↔ Ryujinx Cache

### Bundle Blob Contents (verified)

For each program (12-byte blob-table entry: offset, length, segment), all values are little-endian:

| Offset | Contents | Observation |
|---|---|---|
| 0x00 | Magic `0x0C07513C` | present in all 14,342 blobs; the sequence does not occur in the 80 MB `main.elf`, so NVN shaders are only in the data files |
| 0x04 | Version word 26 (`0x1A`) | present in every blob; matches program type 26 (`ConsoleVS`) in ParsedForm; its meaning is *inferred* |
| 0x18 | Number of global keywords, then for each keyword `[length][text, padded to 4 bytes]`, followed by the number and list of local keywords | keyword lists match ParsedForm in **14,342 of 14,342** programs (checked using sorted names) |
| next | Header: total size, stage (0 Vertex, 1 Fragment), 0, data-section offset (always `0x880`, relative to header), data-section size, magic `0x98761234` | “GLSLC” header section, followed by words 1, 0x10, 0x120, 0x0B, 0x878 (identical in every blob) |
| header + 0x8C4 | **SPH**: 0x50-byte Maxwell GPU shader-program header | Word 0: Vertex `0x02060461`/`0x04060461`/`0x00060461`/`0x06060461`, Fragment `0x00065462`/`0x0006D462`/`0x0406D462`. First 5 bits = type (1 VTG, 2 Pixel), bits 5–9 = version 3 |
| next | Maxwell machine code, in 32-byte units: one scheduling word plus 3 instructions, ending in `EXIT` and loop padding | code starts at header + 0x914 |
| end of data section | Constant pool (floating-point constants, e.g. gray values in `UI/UI-Gray`) | *Inferred:* bound at runtime as constant buffer 1 (section 4) |
| after data section | Reflection table: block names (`VGlobals`, `PGlobals`), size, members (name, type, offset) | content matches the parameters in ParsedForm |

Blob segmentation: `Delphis/Map/Standard` and `FxSystem/Particle` each span 3 LZ4 segments (table in segment 0, programs in segments 0–2); all others fit in one segment.
**Open:** exact meanings of the header words other than size, stage, and data offset; constant-pool offset; and scaling of scratch/local-memory fields in SPH.

### Ryujinx Cache Contents (verified)

- `guest.toc` has 1,388 entries: 401 Vertex, 982 Fragment, and 5 Compute code blocks. Graphics entries each contain **SPH (0x50 B) + code** (Compute has code only); Cb1 size is 0 throughout.
- `shared.toc` has 2,971 entries. Mask `0x22` (Vertex + Fragment) for 2,966; mask 0 (Compute) for 5. Bit 1 = Vertex, bit 5 = Fragment (Ryujinx stage numbering, with Compute = 0). Each entry gives the index in `guest.toc` for each stage.

### Method (verified)

1. For each bundle program, locate the SPH (header + 0x8C4, verified by type/version bits). SPH and code follow it.
2. For each guest entry, use the 32 code bytes immediately after SPH as a key and build a lookup from key to guest indices.
3. A match requires the entire guest entry (SPH + code, length from cache) to match **byte-for-byte** the beginning of the blob code at SPH. The guest entry is a prefix of the blob code (*inferred*: Ryujinx stores only the reachable code length and omits trailing loop padding).
4. For guest entries with no match, also search for a 48-byte substring starting at the 17th code byte in raw blobs of all shaders. This found 4 candidates. They were not investigated further and were not counted as mappings.
5. Map cache entry (shared) → guest Vertex/Fragment indices → bundle programs → common (shader, SubShader, pass). A variant is considered identified when exactly one keyword set has matching keywords for its Vertex and Fragment programs.

**No relocations** are needed: every match is bit-identical, including SPH. Comparing code without SPH found no additional matches.

### Results (verified; figures from `mapping.json`)

| Measurement | Value |
|---|---|
| Bundle programs (Vertex + Fragment) in the 64 shaders | 13,710 (6,878 + 6,832); 8,361 have distinct code |
| … plus 26 additional shaders (resources.assets, tmpshader, scene bundles) | +632, 14,342 total |
| Guest code blocks in cache | 1,388 (1,383 graphics, 5 Compute) |
| **Guest blocks matching a bundled program from the 64 shaders** | **1,302 of 1,383** graphics blocks (94.1%) |
| … including additional shaders | **1,316 of 1,383** (95.2%); +14 (TextMeshPro Mobile, `Standard`, `Hidden/ModelViewReflection`, `TextMeshPro/Sprite`) |
| **Cache entries (shared) fully mapped** (Vertex and Fragment) to one of the 64 shaders | **2,901 of 2,966** graphics entries (97.8%) |
| … including additional shaders | **2,915 of 2,966** (98.3%); 3 have only one stage, 48 have no stage; 5 Compute entries have no bundle counterpart |
| **Bundle programs found in cache** (64 shaders) | **8,613 of 13,710** (62.8%); 5,221 have distinct code |
| … all bundle programs (including additional shaders) | 8,797 of 14,342; 5,241 distinct code blobs |

Distribution of the 2,915 fully mapped entries:
- 2,900 map to exactly one shader name (the remaining 15 map to several, e.g. `TextMeshPro/Distance Field` and `… Overlay`, which share code).
- 2,899 map to exactly one pass.
- **2,815 map to exactly one keyword variant** (shader + pass + keyword set, when Vertex and Fragment keywords match). Fourteen entries (12 from `UI/Custom`, 2 from `Custom/StencilMask`) have no pair with matching keyword sets because the stages have different program counts. The remaining cases are genuinely ambiguous because multiple keyword sets produce identical machine code.
- Only 43 entries are unique at the program level (exactly one Vertex and one Fragment program).

Keyword variant coverage (sets present in both the Vertex and Fragment lists of the same pass): 3,181 of 6,820 across the 64 shaders.

Per shader (excerpt; full data in `mapping.json` under `stats.perShader`):

| Shader | Bundle programs | Found in cache | Cache entries |
|---|---|---|---|
| `Delphis/Map/Standard` | 5140 | **5140 (all)** | 2570 |
| `FxSystem/Particle` | 7976 | 2879 | 138 |
| all other 62 shaders | 594 | **all** | 1–28 each |

- The cache is complete for 63 of the 64 shaders: every bundle variant was compiled once (*inferred*: startup warm-up through variant collections). **Only `FxSystem/Particle` is incomplete:** of its 3,988 keyword sets, 343 occur in cache with an identical set; 304 of those are among the 2,000 `ShaderVariantCollection` variants. These are the variants actually played by the user. The remaining particle variants exist only as binary code in the bundle, without SPIR-V.
- For reconstruction, this means every variant of the other 63 shaders has an SPIR-V module (including duplicates); only the played subset is available for particles.

### Unmapped Entries (open)

- **72 guest blocks** (37 Vertex, 30 Fragment, 5 Compute) match no bundle program. They belong to 48 cache entries without a stage and 3 with only one stage. Their code shares 0–48 initial bytes (SPH only), so they are not closely related to a bundle program.
- Their SPIR-V interfaces resemble Unity shaders (blocks `VGlobals`/`PGlobals`, 0–3 textures). *Inferred:* Unity built-in shaders (`Hidden/…`, internal blit or screen shaders) absent from the searched files, or a different game version in the cache (cache dated 2023-07-07; dump version not compared).
- Comparing against the ELF (`work/elf/main.elf`) found none of the 72 blocks.
- The 5 Compute programs have no counterpart in shader bundles.

## 4. Interface: Constants, Buffers, Textures

Sources: parameter layouts from ParsedForm (`m_ConstantBuffers`) and SPIR-V reflection of the mapped cache modules (`spirv-cross --reflect`, 5,830 modules, no errors; `--msl` to inspect accesses). `spirv-dis` is not installed.

### Constant Buffer Layout (verified)

- All 64 Switch shaders use **two shared blocks**: `VGlobals` (in all 6,878 Vertex programs) and `PGlobals` (in 6,678 of 6,832 Fragment programs). With instancing, `UnityInstancing_PerDraw0` (1,289 Vertex programs), `UnityInstancing_PerDraw2` (2), and `UnityInstancing_PerDrawSprite` (2) also occur. The classic Unity blocks `UnityPerDraw`, `UnityPerCamera`, and `UnityLighting` are **absent**; their contents appear as ordinary members in `VGlobals`/`PGlobals`.
- **Binding:** Unity binding index n corresponds to hardware constant buffer n + 3 in SPIR-V. Examples: `VGlobals` binding 1 → `vp_c4` (2,874 modules), `PGlobals` binding 0 → `fp_c3` (2,874), `VGlobals` binding 0 → `vp_c3` (41), `UnityInstancing_PerDraw0` binding 2 → `vp_c5` (1,282). This rule held across all 5,830 analyzed modules; the only additional buffers were **c1** (see below) and **c2** in 47 Fragment modules.
- The buffers appear in SPIR-V as `float4[4096]` (65,536 B), a Ryujinx-specific representation. Their actual sizes are those in ParsedForm (for example, `VGlobals` is 416 B for `TextMeshPro/Mobile/Distance Field`). The Ryujinx block `support_buffer` (1,344 B, binding 0) appears in all 5,830 modules and has no Unity name. *Inferred:* it belongs to the emulator (extra data for alpha testing, viewport, etc.) and is irrelevant to reconstruction.
- **Instancing:** `vp_c5` (instance data, 1,286 modules) is dynamically indexed. *Inferred:* this corresponds to Unity's instance arrays (`UNITY_INSTANCING_BUFFER`).
- **c1 (constant pool):** 2,705 Fragment and 1,330 Vertex modules read from buffer 1. Example `UI/UI-Gray`: the Fragment shader reads `c1[0].xyz` and multiplies color channels by it; the blob data section contains floating-point values there (0.59 and 0.11). **Inferred:** c1 is the shader compiler's constant pool, whose contents are stored in the blob. The cache does not store it (Cb1 size is 0 throughout). A faithful reconstruction must read it from the blob. The exact offset is **open**.
- **Textures:** Fragment textures are at set 2, binding 128 + texture unit in SPIR-V; the unit matches `m_TextureParams.m_Index` in ParsedForm (consistent for 59 of 61 shaders; the exceptions, `Snowfield` and `MitakeStandardPetrify`, read textures in the Vertex shader at different bindings). Across the 64 shaders there are 31,483 2D and 4 Cube parameters. The mapped modules' SPIR-V contains `sampler2D` (180 bindings across all shaders) and `samplerCube` (3). At most 13 textures occur in one program (`Delphis/Map/Standard`, bindings 128 to 140).
- **Vertex inputs:** inputs are attributes 0 through 7 (each a vec4). The Unity channel → input mapping is in `inputChannels` (see section 1 for the most common layouts).

### Unity Built-in Constants Expected by Shaders (verified)

The names listed occur in `VGlobals`/`PGlobals`/`UnityInstancing_*`. The number after each name is the number of shader names in which it occurs (77 distinct names across the bundles and additional sources); “used” means that SPIR-V access analysis shows it is actually read by the machine code.

- **Matrices:** `unity_ObjectToWorld` (76; used in 63 shaders), `unity_MatrixVP` (76; 64), `unity_WorldToObject` (25; 18), `unity_MatrixV` (13; 11), `glstate_matrix_projection` (10; 4), `unity_MatrixInvV` (1), `unity_CameraInvProjection` (1).
- **Camera/screen:** `_WorldSpaceCameraPos` (26; 21), `_ProjectionParams` (19; 17), `_ScreenParams` (12; 5), `_ZBufferParams` (12; 11), `_Time` (15; 12), `unity_WorldTransformParams` (10; 8).
- **Lighting:** `_WorldSpaceLightPos0` (22; 17), `_LightColor0` (11; 7), `unity_LightShadowBias` (10; 4), `unity_WorldToLight` (5; 3), `_LightShadowData`, `unity_ShadowFadeCenterAndType`, `unity_WorldToShadow`, `_LightPositionRange`, `_LightProjectionParams` (1 each), four point lights (`unity_4LightPosX0`/`Y0`/`Z0`, `unity_4LightAtten0`, `unity_LightColor`; 4; used in 1).
- **Spherical harmonics (light probes):** `unity_SHAr/g/b`, `unity_SHBr/g/b`, `unity_SHC` (6 each; used in 3).
- **Probe volumes, reflection probes:** `unity_ProbeVolume*` (3), `unity_OcclusionMaskSelector` (3), `unity_SpecCube0_*`, `unity_SpecCube1_*` (1: this is `Standard`, not the game's shader).
- **Instancing/particles:** `unity_BaseInstanceID` (7; 5), `unity_ParticleUseMeshColors`, `unity_ParticleUVShiftData` (1).
- **Derived constants** (`_ST`, `_TexelSize`, `_HDR`, `_ProjS` associated with a property): 41 names. Unity sets `_ST`/`_TexelSize` itself; `_ProjS` is custom material handling (see next item).
- **Global values the game must set** (neither material-property names nor Unity names), 40 names: `_CloudParam`, `_CloudShadowBase`, `_CloudShadowScale`, `_ShadowColor` (7 shaders each), `_ReflectorColor` (5), `_GlobalLightPower`, `_PokeLightColor`, `_PokeReflectorColor`, `_EnvMatrix`, `_ClipRect` (4 each), `_ReflectionVP` (3), `_CharacterLightColor`, `_CharacterReflectorColor`, `_FocalCoefficient`, `_RcpGridSize` (2 each), plus other individual values (including `_BloomThreshold`, `_BlurOffsetX/Y`). Of the 40 names, 32 occur as strings in game code (`work/il2cpp/stringliteral.json`), which is where their values originate. The remaining 8 are automatically set by Unity/TMP (`_TextureSampleAdd`, `_UIMaskSoftnessX/Y`, `*_TexelSize`).

### Values That Must Be Supplied for Unity 6

First, values supplied by the Built-in pipeline itself (only if we use the same settings as the original: Forward, Gamma, one directional light, and shadow cascades as described in `render-treue.md`):

1. **Matrices and camera** (`unity_ObjectToWorld`, `unity_WorldToObject`, `unity_MatrixVP`, `unity_MatrixV`, `_WorldSpaceCameraPos`, `_ProjectionParams`, `_ScreenParams`, `_ZBufferParams`, `_Time`, `unity_WorldTransformParams`): supplied by Unity 6 Built-in. The names must remain the same in the new HLSL shaders; the buffer layout does not matter (Unity maps `UnityPerDraw`/`UnityPerCamera` itself).
2. **Lighting** (`_WorldSpaceLightPos0`, `_LightColor0`, `unity_LightShadowBias`, `unity_WorldToLight`, point-light fields, `unity_SH*`): supplied by Unity during FORWARDBASE/FORWARDADD passes when `LightMode` tags and pragmas (`multi_compile_fwdbase`, `multi_compile_fwdadd_fullshadows`) are set correctly. The keyword lists in section 1 are the reference. **Open:** whether `unity_SH*` and vertex lights have the same values in Unity 6 as in 2019.4 (Gamma/Linear path, probe data).
3. **Shadows:** `_ShadowMapTexture` (screen-space shadows) and `SHADOWS_DEPTH`/`SHADOWS_CUBE`: generated by Unity in the Forward path. Configure `Shadows` in the quality settings and cascades as in the original (distance 20, level 2).
4. **Instancing:** `UnityInstancing_PerDraw0` corresponds to Unity's `UNITY_INSTANCING_BUFFER`; the instancing path must be re-enabled with a pragma.
5. **GrabPass:** `_BackgroundTexture` (GrabPass in `Delphis/Map/*`) is still available in Unity 6 Built-in.

Then the values that **the game (our reconstruction) must set**:

6. **Global values** from the list above (cloud parameters, light/reflector colors such as `_PokeLightColor`, `_EnvMatrix`, `_ReflectionVP`, `_FocalCoefficient`). Strings in the game code show where the original sets them; values come from game state.
7. **Global textures:** `_CloudShadowTex`, `_EnvironmentMap`, `_OpaqueDepthTexture`, `_GlobalDepthTexture`, `_CameraDepthTexture`, `_ReflectionTex`, `_BackgroundTexture` (table in section 1). The depth textures (`_OpaqueDepthTexture`, `_GlobalDepthTexture`) are internal render targets generated by the game itself.
8. **Constant pool (c1):** not supplied by Unity. Either embed constants from the blob as literals in the new shader, or regenerate shaders from SPIR-V (where c1 appears as a uniform block).
9. **Material properties:** the inventory lists 964 properties across 64 shaders; material values themselves are in the Material objects in the scene bundles (outside this analysis).

### Open Questions

- **c1 constant pool:** location in the blob, layout, and whether it is identical across all programs to the buffer bound at runtime.
- Meaning of NVN blob header words beyond the named fields.
- Whether the 72 unmapped guest blocks (67 graphics, 5 Compute) come from other shaders or another game version.
- Which variants found only in the bundle (without SPIR-V; about 3,700 particle keyword sets) the game actually uses.
- Whether mapping variants that share identical code (e.g. 3 keyword sets → 1 program) matters visually (machine code is identical; only the keyword name differs).
- Unity Built-in values in Unity 6 vs. 2019.4 (Gamma path, `unity_SH*`, shadow cascades).
- Dump and cache game versions were not compared (cache dated 2023-07-07).
- Reconstruction of `#pragma` lines (`multi_compile` vs. `shader_feature`).

## Files

- `scripts/shader_inventory.py`, `shader_map.py`, `shader_reflect.py`, `shader_report.py` (Repo).
- Local: `work/shaders/inventory.json` (all shaders including additional sources, properties, passes, program lists, parameter layouts), `mapping.json` (programs, guest matches, cache entries with candidates, statistics), `reflect.json` (SPIR-V interface per mapped entry, per-shader summary), `tables.md` (tables).
