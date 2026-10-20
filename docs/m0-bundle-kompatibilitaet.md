# M0 – Bundle Compatibility: BDSP Dump in Unity 6.3 LTS

Status: 2026-10-18. Tested whether AssetBundles from the user's BDSP dump (UnityFS v7, built with Unity 2019.4.27f1, LZ4HC, Switch) can be loaded in Editor 6000.3.26f1 (macOS arm64, Metal, StandaloneOSX build target) via `AssetBundle.LoadFromFile`. All bundles were loaded by absolute path (not copied into Assets) and then unloaded with `Unload(true)`. This document contains names, numbers, and types only—no game content.

## Summary

- All bundles can be loaded: a pass over the entire `AssetAssistant` directory yielded 14,052 of 14,052 bundles `ok`, 0 failures. Only `Dpr.bin` (not a bundle) and macOS `.DS_Store` files could not be loaded.
- There were **no** messages of the form “was built with an incompatible …”. Bundles contain TypeTrees; Unity 6 reads them.
- Textures, meshes, sprites, AnimationClips, TimelineAssets, TMP fonts, and prefabs are accessible as objects.
- ScriptableObjects/MonoBehaviours (master data) cannot be instantiated without the game scripts (expected).
- **Shaders from the dump must never be rendered:** a `Graphics.Blit` using a material based on a dump shader crashed the Editor (see below).

## Results by Bundle

Paths are relative to `work/romfs/Data/StreamingAssets/AssetAssistant/`.

| Bundle | Size | Type | Loads | Assets (`GetAllAssetNames`) | Objects / types | Console |
|---|---:|---|---|---|---|---|
| `Dpr/masterdatas` | 449 KB | master data | yes | 1118 (`.asset`) | `LoadAllAssets` = 0 objects, `LoadAsset` (including ScriptableObject/MonoBehaviour type) = null, `LoadAssetWithSubAssets` = 0 | none |
| `UIs/textures/box` | 110 KB | textures/UI | yes | 62 (1 `.spriteatlas`, 61 `.png`) | 61 Sprite, 1 SpriteAtlas | none |
| `UIs/shareduiassets/sharedui` | 970 KB | UI | yes | 298 (297 `.png`, 1 `.spriteatlas`) | 322 Sprite, 1 SpriteAtlas | none |
| `Pokemon Database/pokemons/common/pm0002_00` | 944 KB | mesh/texture/animation | yes | 27 (14 `.anim`, 3 `.mesh`, 6 `.tga`, 4 `.png`) | 14 AnimationClip, 3 Mesh, 10 Texture2D | none |
| `Characters/objects/ob1015_01` | 11.7 KB | prefab/mesh | yes | 3 | GameObject, Mesh, Material | none |
| `Pokemon Database/pokemons/battle/pm0001_00_00` | 19 KB | prefab | yes | 1 (`.prefab`) | 1 GameObject | none |
| `Pokemon Database/pokemons/battle/animations/pm0292_00` | 6.6 KB | animation | yes | 1 (`.anim`) | 1 AnimationClip | none |
| `FureaiHiroba/demo/timeline/evolve` | 508 KB | Timeline | yes | 2 (`.playable`, `.prefab`) | 1 TimelineAsset, 1 GameObject, 20 AnimationClip | none |
| `Dpr/common_resources` | 9 MB | textures/font | yes | 8 | 7 Texture2D, 1 TMP_FontAsset, 2 Material | none |
| `Dpr/shaders` | 6.7 MB | shaders | yes | 64 (63 `.shader`, 1 `.mat`) | 63 Shader, 1 Material (loading about 0.7 s) | none on load; crash on render, see below |

Additional samples also load: `Dpr/ev_script`, `Dpr/Dpr`, `Pml/personal_masterdatas`, `Battle/battle_masterdatas`, `FureaiHiroba/fureai/prefabs` (1 prefab), and `UIs/textures_mass/pokemon_dp/*` (1 Sprite + 1 Texture2D each).

### Asset Types Across the Full Run (Filename extensions, number of bundles)

`.prefab` 7050, `.png` 2836, `.asset` 1898, `.anim` 1882, `.tga` 1632, `.mesh` 945, `.mat` 414, `.spriteatlas` 60, `.controller` 6, `.playable` 5, `.shader` 3, `.fbx` 2, `.jpg` 1, `.shadervariants` 1. There are no audio extensions (`.wav`, `.ogg`, etc.); audio is therefore not in these Unity bundles, so access to AudioClips could not be tested.

## Access to Textures, Meshes, and Animations

| Source | Finding |
|---|---|
| `box` (Sprite Atlas) | 1 atlas texture, ASTC_6x6, 1024×1024, 1 mip, unreadable. `Sprite.texture` is `null` for all 61/61 sprites; texture is accessible only through SpriteAtlas (`SpriteAtlas.GetSprite` returns sprites). |
| `sharedui` | 2 atlas textures, ASTC_6x6, each 2048×2048, 1 mip; `Sprite.texture` is also `null` for 322/322. |
| `pm0002_00` | 10 textures: DXT1 512×512 (3), DXT1 256×512, DXT1 32×32 (2), ASTC_6x6 512×512 (2), ASTC_6x6 256×512, ASTC_6x6 256×128; 6–10 mips. |
| `pm0002_00` meshes | 2309 / 1111 / 896 vertices, 1–4 submeshes, readable. |
| `ob1015_01` | Mesh with 50 vertices, unreadable; Material shows `Hidden/InternalErrorShader` because the shader is in another bundle. |
| `common_resources` | DXT1 512² and 256², BC5 512², BC4 256² / 1024² / 256², Alpha8 4096² (readable). |
| `textures_mass/pokemon_dp/…` | RGBA32 88×88, 1 mip, Sprite references the texture correctly. |
| Animation | `pm0292_00`: length 0.67 s, 30 fps, not Legacy; `evolve`: clips of 10 s, 14.4 s, and 11.8 s at 30 fps, some with events. `AnimationUtility.GetCurveBindings` returned 0 bindings; curve evaluation was not investigated further. |

ASTC loads as `Texture2D` without issue on Apple Silicon. DXT/BC formats also load; Unity decompresses them as needed on Mac.

## Type Tree / Version Compatibility

No “The AssetBundle … was built with an incompatible …” message, read errors, or null result from a real bundle. The only console messages during the entire run were:

- `Failed to read data for the AssetBundle '.DS_Store'.` (3×)
- `Failed to read data for the AssetBundle 'Dpr.bin'.`
- `The AssetBundle 'sharedui' can't be loaded because another AssetBundle with the same files is already loaded.` — caused by an aborted test script that had not unloaded the bundle, not a bundle defect.

TypeTrees are therefore present and readable by Unity 6. ScriptableObject/MonoBehaviour objects (e.g. `masterdatas`) lack their script classes, so the objects are not instantiated. Their data must be read outside Unity (TypeTree parser such as UnityPy/AssetRipper) or the script classes must be recreated.

## Shaders and the Editor Crash

`Dpr/shaders` loads completely: 63 Shader objects, `isSupported` is `true` for all, names and properties (e.g. 35–65 properties for TextMeshPro shaders) are readable, and the console stays empty. This says nothing about whether they are usable.

Crash: an Eval script created materials from all 63 shaders and drew them to a RenderTexture with `Graphics.Blit`. The Editor crashed on 2026-10-18 at 21:25:30 with `SIGSEGV` (segmentation fault 11). Immediately before it, Editor.log contained:

`GpuProgram creation error: shader program type is unrecognised. You might have a precompiled shader asset from an old Unity version.`

The managed stack trace ends at `UnityEngine.Graphics:Blit` → `Graphics:Internal_BlitMaterial5`. Likely cause (inferred from the message): dump shaders contain only precompiled programs for Switch; Metal cannot generate a GPU program from them, and the render call does not handle this. `isSupported == true` is not a reliable test.

Rule for all further work: never render dump shaders (no blit/draw, no materials using them in scenes). Loading, listing, and inspecting are safe. The Editor was restarted afterward; the crash was deliberately not reproduced.

## Conclusion for Option A (New Unity Project)

The data path is feasible with Option A: all bundles open in Unity 6.3; geometry, textures (ASTC/DXT/BC), sprites/atlases, animations, timelines, fonts, and prefab hierarchies are available as objects. There is no version break due to missing TypeTrees.

Limitations:
1. **Shaders must be rewritten** (URP/HDRP or custom Metal shaders); dump shaders serve only as references for names and properties. Materials must be reassigned to new shaders or they show `Hidden/InternalErrorShader`.
2. **Master data (ScriptableObjects) needs custom script classes** or an external parser, because Unity does not load the objects without scripts.
3. Sprite atlases return `Sprite.texture == null`; textures must be resolved through the atlas or via export.
4. Audio is not in these bundles.
5. The “load bundles directly at runtime” path must strictly exclude materials/shaders from rendering; recommended approach is an import step that converts meshes, textures, animations, and prefabs to custom assets.

Not tested: rendering dump materials with new shaders, Animator Controller behavior, skinning/rigs in Play mode, audio, or player build behavior.
