# Shader and audio feasibility for a Mac/iPad rebuild (as of 2026-10-18)

This is our own analysis based on our dump and locally generated data. Only counts, sizes, and formats are recorded here; no game content is checked into the repository.
Outputs are under `work/shader-test/`, `work/audio-test/`, and `tools/vgmstream/` (all gitignored).
Helper scripts: `scripts/shader_bundle_scan.py`, `scripts/shader_cache_scan.py`, `scripts/shader_msl_check.swift`.
Labels: **verified** = measured directly or read from source; *suspected* = inference without a test.

## Summary

- Shaders: the Ryujinx Vulkan cache contains 5,937 compiled SPIR-V modules. `spirv-cross` translates all 5,932 graphics modules to MSL without errors. A sample of 401 modules (6 plus every 15th of 5,932 = 395) compiles with the Metal runtime compiler (Apple M1 Pro). Path B is technically feasible.
- The main effort is not translation, but bindings, render state, and mapping Unity shaders to materials.
- Audio: all 3,241 `.wem` files use Wwise Vorbis. `vgmstream` cleanly decodes the files tested. The banks are version 135 (Wwise 2019.2), matching the Wwise version in opendpr.
- Recommendation: pursue Path A (a new Unity project using the opendpr scaffold), using the cache only as a reference for shader rewrites. Keep Path B as a later research project.

## 1. Shaders

### 1a. Shader bundles in RomFS

| File | Size | UnityFS | Contents (UnityPy) |
|---|---|---|---|
| `AssetAssistant/Dpr/shaders` | 6,744,100 B | Format 7, Unity `2019.4.27f1`, flags `0x43` | 63 `Shader`, 1 `Material`, 1 `AssetBundle` |
| `AssetAssistant/Effects/fxparticle` | 3,857,759 B | Format 7, Unity `2019.4.27f1`, flags `0x43` | 400 `ShaderVariantCollection`, 1 `Shader`, 1 `AssetBundle` |

- **Verified:** Flags `0x43` indicate compression type 3 (LZ4HC) for the block index, with the directory and block index stored together (bit `0x40`).
- **Verified:** Both bundles have a single platform ID: `19`. *Suspected:* this is Unity's Switch platform (NVN binary code), so the bundles do not contain Windows, Metal, or Vulkan code.
- **Verified:** The 63 Shader objects in `shaders` total 7,909,771 B compressed (LZ4) and 42,487,172 B uncompressed. The largest is `Delphis/Map/Standard` (about 10.7 MB as an object). Name groups: Delphis 22, Custom 17, Mitake 9, UI 6, Dpr 6, TextMeshPro 2, MovieTexture 1.
- **Verified:** Subprograms contain binary data and uniform names (for example, `unity_MatrixVP`, `_MainTex_ST`), not readable source code.
- **Verified:** The AssetRipper dump export (`work/ripper/out/ExportedProject/Assets/Shader`) contains 9 `.shader` files (11,593 B total), all with the line `//DummyShaderTextExporter`. They are placeholders with a name, properties, and a default surface shader, not the original logic. There are 9 of roughly 64 shaders; they contain neither source nor binary code.

### 1b. Ryujinx shader cache

The format is documented in the public Ryujinx source (`Ryujinx.Graphics.Gpu/Shader/DiskCache`). The original `Ryujinx/Ryujinx` and `Ryubing/Ryujinx` repositories return 404 on GitHub. I read the `NextendoNetwork/Ryujinx-Nextendo` fork. The layout was independently reimplemented; no code was copied.

Basic layout, all little-endian, with 32 B headers:

| File | Magic | Entry | Contents |
|---|---|---|---|
| `guest.toc/.data` | `TOCG` | 16 B: offset, code size, CB1 size, hash | Console Maxwell shader code (hardware-independent) |
| `shared.toc/.data` | `TOCS` | 8 B: offset | Per program: stage mask, guest indices, specialization state |
| `vulkan_apple.toc/.data` | `TOCH` | 16 B: offset, uncompressed size, compressed size | Per-program package with SPIR-V per stage (`[count][stage, length, bytes]`), followed by stage information |

Data blocks begin with one byte identifying the compression algorithm (0 none, 1 Deflate, 2 Brotli).

**Verified (counted directly):**

| File | TOC version | Entries | Data size |
|---|---|---:|---:|
| `guest.toc` | 1.1 | 1,388 | 2,256,780 B |
| `shared.toc` | 1.2, codegen 5311 | 2,971 | 623,941 B |
| `vulkan_apple.toc` | 1.2 | 2,971 | 58,521,808 B |

- Timestamps in `shared`/`vulkan_apple`: 2023-07-07. Codegen version 5311 predates the current source version (7355). Current Ryujinx builds would discard the host cache. That does not affect us because we read it ourselves.
- All 2,971 host entries are Deflate-compressed and decompressed without errors (199,915,580 B total uncompressed, 5,528 to 99,864 B per entry).
- **SPIR-V is present:** 5,937 modules (magic `0x07230203`): 2,966 vertex, 2,966 fragment, and 5 compute. That is 2,966 vertex/fragment pairs plus 5 compute programs. There are no geometry or tessellation shaders, which suits Metal.
- This is only the selection needed during the recorded gameplay; it is incomplete. Names and material mappings are also missing.

### 1c. spirv-cross to MSL

Command: `spirv-cross --msl --msl-version 20300 <module>.spv`. All 5,932 vertex and fragment modules were extracted (202 MB under `work/shader-test/all`).

- **Verified:** All 5,932 exit with code 0 (no errors).
- **Verified:** The 3 sample programs (vertex plus fragment, 6 modules total) produced 102 to 247 lines of MSL. Another 395 modules were translated (every 15th module).
- **Verified:** The Metal runtime compiler (`MTLDevice.makeLibrary`, MSL 2.3, Apple M1 Pro) compiled all 401 MSL files without errors. The `metal` command-line tool is unavailable because the Metal toolchain is not installed; I did not download it.
- Quality: syntactically correct, but machine-generated. Variable names such as `_42`, each component handled separately, constant buffers represented as `float4[4096]` (64 KB, Ryujinx layout), and inputs as `user(locn0)`. Readable enough for analysis, not for maintenance.
- *Suspected:* Only compilation was checked, not image equivalence. Bindings (buffer/texture indices), y-flip/clip space (`--flip-vert-y`, `--fixup-clipspace`), and specialization state (blending, vertex format) remain untested.

### 1d. Assessment

**Path A: create a Unity project and rewrite shaders in ShaderLab.**

- Pros: fits opendpr (Unity 2019.4.27f1, scripts, Wwise). It runs on Mac with the editor under Rosetta and can be built for iPad. There are roughly 64 shaders, of which about 9 standard shaders (TMP, UI, Bloom, FXAA) are commonplace.
- Cons: each shader requires manual work (Delphis/Map/Standard, Character, Poffin, Mitake). MSL outputs, bundle uniform names, and reference SPIR-V serve as guides. The result will not be 1:1, only “visually similar.” The main blocker remains B1 from `opendpr-machbarkeit.md`: the Switch shader bundles are unusable on Mac.

**Path B: custom runtime, SPIR-V to MSL.**

- Pros: 100% of shaders present in the cache can be translated automatically; no per-shader manual work.
- Cons: this requires a complete custom engine (scenes, materials, state, game logic). That is the largest effort and only loosely related to shaders. The mapping from cache programs to materials and the state from `shared` are also missing. Cache coverage is incomplete (only variants used during gameplay). *Suspected:* cache programs could be matched to Switch binaries in the bundles through their guest code to recover names. This has not been tested.

**Scaffold (opendpr scripts, Unity project):** this is the basis for Path A. It does not replace shaders.

**Recommendation:** Path A. Cache translation (`spirv-cross` → MSL) is a useful reference for checking rewrites and may later support rendering individual effects directly with Metal. A custom runtime under Path B is worthwhile only if Path A fails.

## 2. Audio

Path: `work/romfs/Data/StreamingAssets/Audio/GeneratedSoundBanks/Switch` (427 MB).

**Verified:**

| Measurement | Value |
|---|---|
| `.bnk` | 696, all with `BKHD` version 135 (Wwise 2019.2.x) |
| `.wem` | 3,241, 379,052,108 B total (529 B to 9,163,998 B, 7,379 B median) |
| Other files | `Wwise_IDs.h` (1.7 MB), `PluginInfo.xml` |
| Bank chunks | `BKHD`, `HIRC`: 696 each; `DIDX`/`DATA`: 695 each (embedded media: 2,344 entries, 56,496,146 B); one each of `INIT`, `STMG`, `ENVS`, `PLAT` |
| Largest bank | `Delphis_Main.bnk`, 24,561,004 B |
| Codec | RIFF format tag `0xFFFF`: Wwise Vorbis (not Opus) |
| Sample rates | 32 kHz: 2,337; 48 kHz: 371; 36 kHz: 344; 24 kHz: 162; other: 27 |
| Events in `Wwise_IDs.h` | 24,278 named IDs in namespace `EVENTS` |

- Version check: opendpr includes Wwise 2019.2.4 with Mac plugins (see `opendpr-machbarkeit.md`). Bank version 135 matches. *Suspected:* the Switch banks will work if their folder is renamed to `Windows`, as opendpr instructs; this is untested.
- **vgmstream:** release `r2117`. The Mac release `vgmstream-mac.zip` hardcodes paths to Homebrew libraries (`libvorbis`, `libogg`, FFmpeg version 62) that are missing or too new here. I therefore built vgmstream r2117 with libogg 1.3.5 and libvorbis 1.3.7 under `tools/vgmstream/` (without ffmpeg/mpg123/speex/celt). The build is at `tools/vgmstream/b-vgm/cli/vgmstream-cli`. Homebrew was not changed.
- Decode tests to `work/audio-test/*.wav` (all succeeded, encoding “Custom Vorbis”):

| File | Source size | Format | Duration |
|---|---:|---|---:|
| `284133277.wem` | 1,661 B | 32 kHz, mono | 0.22 s |
| `1000209917.wem` | 10,663 B | 32 kHz, mono | 1.32 s |
| `382403544.wem` | 563 B | 6 kHz, 2 channels | 5.00 s |

- All 3,241 `.wem` files were also checked by metadata only (`-m`); vgmstream recognized each as Custom Vorbis without an error. Only the 3 files above were fully decoded.
- **wwiser (bnnm/wwiser; README only):** reads complete `.bnk` files, including `HIRC` (event, action, and container structure); can use names from `Wwise_IDs.h` and `SoundbanksInfo.xml); and produces XML/TXT dumps and `.txtp` files that vgmstream can play. *Suspected:* this is the tool to resolve event → action → `.wem`. It only partially simulates Wwise features and does not modify banks.

### Audio assessment

- Under Path A, Wwise 2019.2.4 runs natively on Mac through the opendpr scaffold (plugins are in the repository). To our knowledge, opendpr lacks iOS plugins (*suspected*, not checked). The SDK is proprietary (Audiokinetic account/license required).
- Alternative without the Wwise runtime: convert `.wem` to WAV/OGG with vgmstream and map events from wwiser dumps into a custom mixer. This requires substantially more work (RTPCs, switches, states, container logic).

## 3. Recommendation and next steps

1. Continue with Path A. Prioritize a small shader list (TMP/UI/Bloom/FXAA first, then Delphis Map/Character).
2. Match cache programs with bundle shaders (guest code ↔ Switch binaries) to recover names and variants. This is the only unknown step remaining for Path B.
3. Audio: run wwiser on `Delphis_Main.bnk`, inspect the event list, then test the Wwise banks in the Unity project on Mac.
4. Open risks: the game version in the dump has not been compared with the 2023 Ryujinx cache; MSL was compiled but not rendered; iPad Wwise plugins are unverified.
