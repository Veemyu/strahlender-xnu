# Reference: LASRecomp Shader Pipeline and Adaptation Plan (as of 2026-10-18)

Independent analysis of the local clone `research/LASRecomp` (gitignored, read-only; commit `09f8e5e`, its only commit, author “Peiikai”). All statements are in our own words; references are limited to file and function names with line numbers. Nothing from `research/` was copied into the repository or committed.
Labels: **verified** = read in code/documentation or measured; *inferred* = conclusion without a test.

**Permission status:** The user explicitly approved adapting LASRecomp code (MIT). This document therefore also describes an adaptation plan (sections 8–11). The main agent handles copying and committing.

---

## 1. How Guest Shaders Reach the Runtime (verified)

LASRecomp is not an emulator; it statically recompiles the game. Game code calls NVN functions implemented by the runtime. Shaders are not read from files: they are taken from the game's memory when the game passes them to NVN.

| Step | Evidence | Finding |
|---|---|---|
| Bind program | `runtime/nvn/objects.c:565-599` (`set_shaders`, `nvnProgramSetShaders`, `…Ext`) | One entry per stage: 64-bit code address and pointer to the control section. 16-byte stride (24 for Ext, which includes a debug hash). |
| Determine stage | `objects.c:578-588` | Bits 10–13 of the first word in the program header (SPH, at code + 0x30): 1 Vertex, 5 Fragment, 4 Geometry, 2 Tess-Control, 3 Tess-Eval. If the code does not start with magic word `0x12345678`, it is treated as Compute. |
| Container | `translate.c:1927-1940`, `shader.h:97` | Blob = NVN header (0x30 bytes, starts with `0x12345678`), SPH (0x50 bytes for graphics), then Maxwell code from offset 0x80. Compute has no SPH and code starts at the beginning of the blob. Code is grouped in fours of 64-bit words: one scheduling word and three instructions. |
| Control section | `objects.c:591-592`, `nvn.h:60-69`, `renderer.m:1346` | Contains the offset and size of “compiler constants” (`+0x700`, `+0x6FC`) and, for Compute, workgroup size (`+0x748`). Compiler constants follow the code in the same blob and also bound the instruction scan. |
| Output registers | `translate.c:1933-1936` | Only output masks are read from SPH (color targets at `+0x48`, depth at bit 1 of `+0x4C`). SPH interpolation and input masks are **not** read; they are derived from instructions (IPA) and the vertex shader's `vs_out_mask`. |
| Constant buffers | `renderer.m:610`, `renderer.m:1274-1313` (`bind_cbufs`) | Hardware cbuf 0 = driver constants (storage-buffer table, workgroup count); cbuf 1 = compiler constants after the code; cbuf `k >= 3` = NVN uniform binding `k - 3` (`cbuf_base = 3`, configurable by environment variable). Buffers are copied into a ring per draw (snapshot). Maximum 18 cbufs (`shader.h:62-63`). |
| Textures | `translate.c:451-480` (`tex_slot`), `renderer.m:1098-1103`, `1176-1180` | TEX instruction carries a 13-bit index into the handle table; byte offset `index*4`, slot = `(offset - 0x20) / 8`. A 64-bit handle contains a 20-bit texture index (TIC) and 12-bit sampler (TSC), looked up in the game's texture pool. Up to 31 textures per shader. Type (1D/2D/3D/Cube/Array/Shadow) comes from the instruction's target bits; for size queries alone, it is inferred later from the sample (“weak”). |
| Attributes | `renderer.m:654-727`, `1613-1620`, `1830-1870` | Only each vertex attribute's type (Float/Int/UInt, `attr_kind`) goes into the key; the vertex format itself is in the Metal vertex descriptor. Fragment inputs come from the active vertex shader's `vs_out_mask`. |
| State | `renderer.m:1613-1620` | `ShaderKey` = attribute types, render-target types, `depth_minus_one`, `flip_y`, `flip_x`, `vs_out_mask`, `glsl`. A program is translated once per (code addresses, key) pair. |

**Implication (verified):** The `translate.c` interface is narrow: input = blob pointer + upper bound + stage + `ShaderKey`; output = `ShaderInfo` with source and metadata. It is independent of the rest of the runtime (see section 8).

## 2. Translator: `runtime/nvn/maxwell/translate.c` (2,165 lines, 126 KB) and `shader.h` (103 lines)

### 2.1 Structure (verified)

- **Decoder:** A long `if/else` chain, `emit_insn` (`translate.c:824-1624`), matches each 64-bit instruction word using `OPM(value, mask)` patterns. Half-precision instructions are handled separately in `emit_half` (`:332`); texture instructions in `emit_tex`/`emit_texs` (`:753`, `:672`). There is no intermediate representation (no SSA or control-flow graph analysis).
- **Register mapping:** All 255 registers are represented as `uint rN`; predicates P0–P6 as `bool pN`; `PT` = true; RZ = `0u`. Floating point uses `as_type<float>` (MSL) or `as_f/as_u` (GLSL). Carry/zero/sign flags use `cc/ccz/ccs` (only when needed).
- **Predicates:** Every guarded instruction is wrapped in `if (pN) { … }` (`:824-840`).
- **Control flow:** Without branches, code is linear inside `do { } while(false)`. With branches, it becomes a `switch (pc)` state machine inside a loop (100,000-iteration guard), with explicit 16-entry stacks for SSY, PBK, and PCNT. Supported: BRA, SSY, PBK, PCNT, SYNC, BRK, CONT, BRX (jump table, then each word is a target), EXIT, KIL. This is robust but unstructured, producing long target code that compiles slowly.
- **Interpolation:** IPA modes pass/multiply/constant (`:874-900`). Constant → `flat`. “pass” returns attr/w; “multiply” multiplies by a register (`attr_load`, `:224-276`). `noperspective_mask` is declared but **never set** in the code (only read at `:69`, `:1849`, `:2038`), so `noperspective` is never emitted. IPA centroid/sample flags are not evaluated. This is *probably* harmless for Unity without MSAA (`render-treue.md`).
- **Outputs:** Vertex: `out.pos`, `out.v<i>`, point size. Fragment: color targets from SPH (`omap_target`), each Float/Int/UInt, and optional `depth`. Vertex-shader epilogue: `flip_y`, `flip_x`, `depth_minus_one` (z = (z+w)/2, NVN depth −1..1 → Metal 0..1) (MSL `:2113-2115`, GLSL `:1886-1888`).
- **Target languages:** Two. MSL (Metal) is the primary output. GLSL 460 for Vulkan is derived from the same MSL-like text by token-based rewriting (`glsl_rewrite`, `:1640`, prelude `:1724`) plus separate paths for textures, memory, and entry points; the GLSL interface (bindings, locations) is at the top of `shader.h:1-27`. SPIR-V is generated at runtime by shaderc in `runtime/nvn/vulkan/shaders.c` (**not** by the translator). There is no HLSL output.
- **Game-specific runtime additions (verified):** “Tint” epilogue for color target 0 (`:1817`, `:2070`, for marked pots in the game), `flip_x` (mirror mode), resolution scaling `rscale` (buffer 18, affects fragment coordinates and texel fetches), `maxwell_dbg_*` hooks, `getenv("BDSP_NO_DISCARD")`, and `BDSP_SAVE_MSL` (`:847`, `:1984`). An IPA special case for fog in one game level appears in the comment at `:258-262`; the code itself is general.

### 2.2 Coverage

**Supported (verified from comments/patterns in `emit_insn`, `emit_half`):**

| Group | Instructions |
|---|---|
| Floating point | FADD, FADD32I, FMUL, FMUL32I (with scaling), FFMA, FFMA32I, FMNMX, FSET, FSETP, FCMP, MUFU (COS, SIN, EX2, LG2, RCP, RSQ, SQRT), RRO (no-op), F2F, F2I, I2F, FSWZADD |
| Half (SM53) | HADD2, HMUL2, HFMA2, HSET2, HSETP2 (register forms for SET/SETP; all forms for ADD/MUL/FMA), merge/swizzle modes |
| Integer | IADD (+CC/X), IADD32I, IADD3 (+CC/X), ISCADD, ISCADD32I, ISET, ISETP, ICMP, IMNMX, SHL, SHR, SHF, LOP, LOP32I, LOP3, BFE, BFI, XMAD (all four forms), IMUL, IMUL32I, FLO, POPC, I2I, PRMT, SEL, MOV, MOV32I |
| Predicates/flags | PSETP, PSET, R2P, P2R (including CC), CSETP (Z/S only) |
| Memory | LD c[…] (LDC, including register index), LDL/STL (local, 1 KB), LDG/STG (global, via guest-heap buffer), IPA, LD/ST attribute (constant address only) |
| Texture | TEX (1D/2D/3D/Cube, Array, Shadow, LOD modes, offset), TEXS, TLDS (subset of info values), TXQ (dimension/mip count only) |
| Other | S2R (Y direction, thread/block ID), SHFL, BAR, KIL, DEPBAR/NOP/MEMBAR (ignored) |

**Not supported (verified from `fail(...)` sites and missing patterns):**

| Gap | Evidence | Relevant to BDSP? |
|---|---|---|
| TLD (full form), TLD4/TLD4S (gather), TXD (explicit derivatives), TMML | no pattern in `emit_insn`; result is “unknown instruction” (`:1624`) | *inferred*: may occur occasionally (gather/fetch in post-effects); measure |
| Image access SULD/SUST, atomics ATOM/RED/ATOMS, shared-memory LDS/STS | no pattern | low (only 5 Compute programs in Ryujinx cache) |
| TEX.B (bindless) | `:760` “bindless tex” | *inferred*: no (Unity binds textures conventionally) |
| TXQ types other than dimension | `:954` | possible |
| MUFU RCP64H/RSQ64H and other functions | `:967` | low |
| Indexed IPA, LD a[] with register index | `:878`, `:892`, `:226` | low outside Geometry/Tessellation |
| BFE.BREV, PRMT special modes, R2P.CC, CSET | `:1246`, `:1377`, `:1566`, `:1618` | PRMT modes are *inferred* to be rare; measure |
| TLDS/TEXS: unlisted info values | `:645`, `:665`, `:726`, `:746` | possible |
| Other Maxwell instructions without a pattern (e.g. LEA, CS2R, PIXLD, VOTE, FCHK, DADD/DMUL/DFMA, VMAD, ISBERD) | inferred only from absence | *inferred*: some are rare; measure |
| Geometry/Tessellation stages | Stage constants exist (`shader.h:33`); `attr_load`/`attr_store` return zeros/comments there (`:277-282`) | **No** in Ryujinx cache (Vertex + Fragment + 5 Compute only, `shader-audio-machbarkeit.md:44`) |
| Memory-safety risk | `cbuf_ref` writes `cbuf_size[idx]` and `cbuf_need[idx]` without bounds checks (`:126`, `:909`); arrays have 18 entries | harden if inputs are untrusted |

**Known differences and quirks (verified or *inferred*):**
- Metal fast math is not disabled in runtime options (`renderer.m:862`, `:834`: only `preserveInvariance` for the vertex shader; fragment options are empty). For 1:1 fidelity, we **must** check `fastMathEnabled=NO` or equivalent modes (*inferred*, untested).
- FTZ and instruction rounding flags are not evaluated; Maxwell behavior for denormals may differ (*inferred*).
- RRO is a no-op and MUFU.SIN/COS use radians; whether that matches glslc shader code (factor 1/2π in the shader) needs **a test case** (*inferred* to be correct because the game runs).
- Half merging had to be rewritten because Metal compiler mistranslated one mask form on M1 (comment `:2014-2017`); GLSL deliberately computes half values with bitwise operations (comment `:1758-1762`). Compiler quirks are real and must be caught with differential tests.
- “Unknown instruction” handling is limited: the translator stops at the **first** error (`fail`, `:84-91`); a histogram requires collecting all unknowns (see section 11).

### 2.3 Tests and Validation (verified)

| Tool | What it checks | What it does **not** check |
|---|---|---|
| `tools/test_translate.c`/`.sh` | Fuzzing: synthesize programs from every pattern in `translate.c`; (1) MSL must be byte-identical to a translator reference revision (regression), (2) GLSL must compile with shaderc and validate with SPIRV-Tools. | No numeric comparison against hardware or Ryujinx. |
| `tools/test_shaders.c`/`.m` | Split dumped shaders (`BDSP_DUMP_SHADERS`), translate, compile with `xcrun metal` or `newLibraryWithSource`. | Compileability only. |
| `tools/test_vk_pipelines.c`/`.sh` | Fuzzed programs → GLSL → real Vulkan pipelines under the validation layer. | Windows/Vulkan-specific; no image checks. |
| `runtime/ui/shader_tour.mm` (70 lines) | Not a test: a “shader tour.” Warps through all game warp points so each shader is translated and compiled once during play, populating Metal's disk cache. | — |
| `tools/test_lift.py`, `test_simd.py` | Differential tests of the **CPU** lifter against Unicorn, not shaders. | — |

LASRecomp therefore checks fidelity by playing and taking screenshots (`tools/shot.sh`, `tools/frames.sh`, debug hook `BDSP_DBG_FS`, which displays a register at a program location as grayscale). I **did not find** a comparison against a reference result (Ryujinx or hardware) in the clone.

### 2.4 Caching and Runtime Cost (verified)

- A program is translated on its first draw (`renderer.m:878-950`), and MSL is saved under `cache/shaders/` (`:814-826`). At startup, all sources there are compiled in the background (`shader_cache_warm`, `:827-856`) to populate Metal's own disk cache.
- Compilation is asynchronous; draws using a program that is not ready yet are skipped (`:951-960`). A source comment estimates about 40 ms for first compilation (`:807`, `:951`), then about 0.1 ms. This is a project estimate, not my measurement.
- This runtime compilation is **not an option for us**: although `newLibraryWithSource` is available on iPadOS (the Metal compiler is in the OS), our design calls for translation at build time (core requirement: no game code in the app, reproducible builds). We also run inside Unity, which compiles its own shaders (see section 9).

## 3. Metal Renderer (`renderer.m`, 2,701 lines/148 KB; `metal.m`, 1,191 lines/67 KB)

| Topic | Finding (verified) | Relevance to us |
|---|---|---|
| Pipeline state | Per draw, hash program, target formats, blend, vertex formats/streams, channel mask, alpha-to-coverage (`renderer.m:1582-1605`, `:1767`), then asynchronously create `MTLRenderPipelineState` (`:1784-1815`). | Low: Unity handles this. |
| Blend/depth/stencil | NVN → Metal tables: `blend_factor` (`:729`), `blend_op`, `compare_fn` (`:768`), `stencil_op` (`:781`). States come from NVN commands, not ShaderLab. | Useful when mapping render states parsed from bundles (Unity enum → Metal); otherwise low. |
| cbuf binding | See section 1 (cbuf 0/1/≥3, ring-buffer snapshot). | cbuf numbers connect to Unity constant buffers (see section 9). |
| Samplers | `sampler_for` (`:959-1020`): filter, mip filter, wrap modes including Border/MirrorClamp, LOD limits, anisotropy, comparison samplers. Switch sampler LOD bias is **not** preserved. | Reference for sampler fidelity. |
| Clip space/Y flip | `flip_y` for a bottom-left window origin, `depth_minus_one` for NVN depth mode −1..1; front-face winding flips with `flip_y` (`renderer.m:1613-1616`, culling at `:1868`). Vulkan uses a negative-height viewport (`shader.h:21-23`). | Unity manages projection itself; Unity shaders must preserve **original matrix** conventions (see section 10). |
| Gamma/sRGB | sRGB formats are mapped (`metal.m:78-140`). Screen output samples sRGB targets through a non-sRGB view, “showing what the game wrote” (`metal.m:650-661`). Copies can be raw (`BDSP_COPY_RAW_SRGB`, `renderer.m:2223`). | Matches our Gamma requirement: the game computes in Gamma without intermediate linearization. Force Gamma color space and no sRGB targets in Unity 6.3. |
| SMAA | SMAA 1x (MIT, `third_party/smaa`, 1.2 MB) via SMAA port macros, compiled for each new image size (`metal.m:700-815`). | **Not relevant**: the original has no anti-aliasing (no MSAA, `render-treue.md`). |
| MetalFX | Spatial scaler, “Perceptual” mode (`metal.m:663-698`). Dynamic resolution in `output_scale.c` (93 lines). | **Not relevant** to 1:1 fidelity; could be an optional quality setting later. |
| Feedback | If a texture is read while also used as a target, a copy is made (`resolve_feedback`, `:1113`). | Note: original shaders may read their depth buffer; *inferred* Unity solution is GrabPass/copy. |
| Game-specific | Widescreen changes, mirror mode, pot tint, texture patches (`texpatch.c`, 1,043 lines), button prompts. | Do not port. |

## 4. Link's Awakening vs. BDSP

| Aspect | LAS (verified from clone/README) | BDSP (verified from our docs/measurements) |
|---|---|---|
| Engine | Grezzo's custom engine (secondary source, `docs/recomp-referenzen.md`) | Unity 2019.4.27f1, IL2CPP (`docs/extraktion.md`) |
| Shader source | Finished NVN programs (glslc binaries) are in the game itself; game code calls `nvnProgramSetShaders`. | Unity compiles ShaderLab into NVN programs at build time and stores them in bundle shader objects (platform 19). No source code is present there at runtime (`shader-audio-machbarkeit.md:21-28`). |
| Constant buffers | Game-specific layouts (reverse engineered) | Unity layouts (`UnityPerDraw`, `UnityPerCamera`, …) are named in parsed shader data (*inferred* from uniform names found there, such as `unity_MatrixVP`, `_MainTex_ST`, `shader-audio-machbarkeit.md:27`). |
| Variants | Few, selected by the game | Keyword variants: `work/shaders/mapping.json` (our `scripts/shader_map.py`): 13,710 programs (6,878 Vertex, 6,832 Fragment), 8,332 distinct code hashes, 0–17 keywords per program, blob size 2,516–12,300 bytes, median 6,316 bytes. |
| NVN runtime in game | Game links the system NVN driver; runtime replaces it | `sdk`, `subsdk0` are in ExeFS (`docs/extraktion.md:17`). **Open:** whether they contain a runtime shader compiler (e.g. glslc library) has **not been investigated**. *Inferred*: no, because Unity supplies offline-compiled shader binaries and binds them only with `nvnProgramSetShaders`; `sdk` is *probably* Nintendo's SDK library without a shader compiler. Check strings/symbols in `sdk`/`subsdk0` (record names only). |
| letsgo-recomp | Based on LASRecomp (README: “built on the runtime and recompiler of LAS Recomp”); NVN on **Vulkan**, Maxwell → SPIR-V at runtime, SMAA, on-disk shader cache (SPIR-V and pipeline cache). README says Windows-only. | Our earlier `recomp-referenzen.md` described Let's Go as non-Unity; web research supports a Game Freak custom engine with YEBIS 3 middleware (secondary source, not checked directly). Both target games are therefore non-Unity; **BDSP would be the first Unity case**. |

**Key difference (verified):** We know our container format. `scripts/shader_map.py` shows that each bundle program starts with magic `0x0C07513C`, followed by a version, keyword list (count at `+0x18`), a control header with magic `0x98761234` (at `header+0x14`), then the GLSLC data section with `0x12345678` marking the program start; SPH = magic position + 0x30 (`scripts/shader_map.py:parse_nvn`). This is exactly the input format for `maxwell_translate` (blob from `0x12345678`, SPH at `+0x30`, code at `+0x80`). Of the 1,388 guest entries in the Ryujinx cache (401 Vertex, 982 Fragment, 5 Compute), 1,288 match bundle programs byte-for-byte (`mapping.json`: `guestMatchedFull`). This is the bridge for fidelity tests. No separate `docs/shader-inventar.md` existed at the time (checked).

## 5. Portability (answers to questions 5a–5d)

**(a) Maxwell → MSL/SPIR-V as a build step:** *Technically plausible* because the input format and stages match (Vertex/Fragment, no Geometry/Tessellation). Coverage remains open; see section 11. The translator produces register-machine code, not readable ShaderLab source (see section 9 for implications).

**(b) What we would need to write:** container parser (already exists as a Python script, to be reimplemented in C/CLI); map cbuf offsets and texture slots to Unity names from parsed data; ShaderLab/HLSL wrapper; keyword selection; missing instructions; differential-test integration; removal of game-specific behavior.

**(c) MIT license (not legal advice):** The license permits use, modification, and redistribution **provided the “Copyright (c) 2026 Peiikai” notice and license text remain in all copies or substantial portions**. The `LICENSE` explicitly excludes Nintendo property and third-party components in `third_party/`. Neutral notes on quality/provenance: the README says the code was written “almost entirely” with AI (Claude via Claude Code), under human direction, testing, and review (`README.md:4-8`); the clone has only one commit, so there is no development history. Translator comments cite Ryujinx (HADD2/HMUL2/HFMA2/XMAD/LDC field layouts, `translate.c:355`, `386`, `900`, `1265`) and the README mentions envytools; the README does **not** list Ryujinx as a source (search returned no matches). The clone does not establish whether, or which, structures or tables draw on third-party works (Ryujinx, envytools); future notices should mention Ryujinx and envytools. This is a risk assessment, not a judgment.

**(d) 1:1 fidelity check:** Reference = Ryujinx SPIR-V (and guest code for the same programs). See section 10.

## 6. Recommendation (eight points, options A, B, C)

1. **Option B (use the LASRecomp translator as a base, MIT, with changes)** is the fastest route to a build step that does not need the Ryujinx cache, now that permission has been granted, because the input formats match exactly (section 4).
2. **Option A (write our own translator)** would be cleaner (SSA, structured control flow, direct HLSL), but would take months and require deriving the same opcode details again; consider it only if B fails on fidelity or runtime.
3. **Option C (use a local Ryujinx reference and port shaders by hand)** remains essential for fidelity checks, but cannot be the only route because users will not all have the cache and 13,710 programs cannot be ported manually.
4. Recommended: **B as the core, C as the test oracle**, and A for targeted parts (e.g. structured control flow) only if needed.
5. **Measure coverage first** (section 11), before adapting code; that determines whether B is viable at all.
6. Isolate the translator as a standalone C tool with a clear interface, remove all LAS-specific behavior, and retain license/notices (section 8).
7. First generate MSL for the test harness, then build an HLSL/ShaderLab wrapper for Unity; whether Unity's Metal compiler translates the generated structure faithfully is a risk (section 9).
8. Texture-slot and cbuf mapping to Unity names and differential tests against the Ryujinx SPIR-V reference remain decisive; without them there is no 1:1 evidence.

---

## 7. Repository-rule Note (verified)

`.gitignore` excludes the `tools/`, `research/`, `work/`, `Ryujinx/`, and `nsp/` directories. A destination at `tools/shader_translator/` would therefore **not be versioned**. Either place the translator outside `tools/` (suggestion: `shader_translator/` at the repository root) or selectively override the ignore rule (`!tools/shader_translator/`). The main agent decides.

## 8. Adaptation Plan: What Is Suitable as a Base

Sizes measured in bytes with `wc -c`/`du`.

### 8.1 Suitable

| File | Size | Use |
|---|---|---|
| `runtime/nvn/maxwell/translate.c` | 126,050 B / 2,165 lines | Core. libc only (`math.h`, `stdio.h`, `stdlib.h`, `string.h`, `stdarg.h`; `malloc.h` on Windows only), **no** runtime dependency (verified from `#include` list at `:15-23`). |
| `runtime/nvn/maxwell/shader.h` | 6,765 B / 103 lines | Public interface (`ShaderKey`, `ShaderInfo`, `maxwell_translate`, `maxwell_free`). |
| `tools/test_translate.c` + `.sh` | 15,157 B + 1,941 B | Fuzz/regression test; reads patterns from `translate.c`. The script needs a reference revision (`git show $REF:…`) and shaderc/SPIRV-Tools; adapt it to our repository. |
| `tools/test_shaders.c` / `.m` | 1,230 B / 2,032 B | Compile dumps → MSL → Metal; use as a template for our coverage/compile test (adapt input format). |
| `tools/test_vk_pipelines.*` | 16,514 B + 891 B | Only needed for Vulkan output; *inferred* not to be needed on macOS. |
| `runtime/nvn/vulkan/shaders.c` | 24,622 B | Ideas for GLSL → SPIR-V and reflection if we need SPIR-V output; read only, do not port. |
| Ideas from `renderer.m`/`metal.m` | 147,860 B / 66,506 B | **Do not copy.** Read as reference for blend/compare/stencil/sampler tables, cbuf convention (`cbuf_base = 3`), texture-handle lookup, and compile options. |

### 8.2 Do Not Port

| Area | Size | Reason |
|---|---|---|
| `third_party/LAS-Randomizer` | 864 KB | LAS randomizer, separate license(s), closely tied to game content |
| `third_party/imgui` | 7.2 MB | UI library, not needed |
| `third_party/fonts`, `fonts/` | 660 KB / 4 KB | Fonts, game-related |
| `third_party/smaa` + `runtime/nvn/smaa_data.c` | 1.2 MB | SMAA is not in the original |
| `runtime/ui/` | 392 KB | Menus, cheats, randomizer, shader tour |
| `runtime/hle/`, `runtime/services/` | 356 KB / 120 KB | Switch OS replacement and game patches |
| `runtime/*.c` (kernel, loader, dispatch, …) | 2.1 MB for all of `runtime/` | Recompilation runtime |
| `tools/gen.py`, `lifter.py`, `passes.py`, `patches.py`, … | `tools/` 1.5 MB | ARM64 → C recompiler, not relevant here (BDSP path is a Unity rebuild, `architektur-entscheidung.md`) |
| `runtime/nvn/{astc,texpatch,tegra,objects,cmdbuf,formats}.c` | 147,412 B total | NVN object model, texture decoding (not needed for Unity, which decodes textures itself), game patches |
| `docs/`, `docs/icon` | 1.6 MB | LAS-specific |

## 9. Target Structure and Decoupling

Proposal (location: see section 7):

```
shader_translator/
  LICENSE-LASRecomp          (license text unchanged, including Copyright (c) 2026 Peiikai)
  THIRD_PARTY_NOTICES.md     (LASRecomp MIT; note Ryujinx/envytools as sources for field layouts/documentation)
  README.md                  (origin, changes from upstream, original AI disclosure)
  include/maxwell.h          (cleaned-up equivalent of shader.h)
  src/translate.c           (from translate.c)
  src/container.c           (Unity NVN container: magic 0x0C07513C / 0x98761234 / 0x12345678)
  src/main.c                (CLI)
  tests/…                   (fuzz, coverage, differential tests)
Makefile                    (clang, macOS)
```

**Interface:**
- Input: bundle program blob (or an already-extracted Maxwell blob starting at `0x12345678`), stage (from control header `header+4`, called “stage” in `shader_map.py`), optional cbuf info and `ShaderKey`.
- Output: source (MSL; HLSL/GLSL optional) plus metadata (cbufs used and their sizes, texture slots with type/shadow, attribute/varying masks, output mask, flags).
- CLI example: `shader_translator --stage vs --target msl --in prog.bin --out prog.metal --info prog.json`. A library call uses the same flow through `maxwell_translate`.

**Decoupling tasks (concrete):**
1. `translate.c` already has no runtime headers (see section 8.1). Remove: tint epilogue (`:1817`, `:2070`) and `uses_tint`, `flip_x`, `rscale` paths (`uses_rscale`, `RSC2`, `rsc()`), `maxwell_dbg_*` variables/hooks, `getenv` calls (`:847`, `:1984`), and global `maxwell_gmem_base/size` (make parameters or remove them; Vertex/Fragment shaders should not need global memory).
2. Make global static buffers (`RSC2` with `static char bufs[4][1024]`, `:526`) and `alloca` macros thread-safe for parallel translation of 13,710 programs.
3. Validate inputs: bounds for cbuf index (`cbuf_ref`), `reg_used` (register > 255), and blob size.
4. Port the container parser from `scripts/shader_map.py` to C and return stage/keywords/constant offset. **Check:** whether `Control+0x700/0x6FC` (compiler-constant offset/size) have the same positions in Unity's container; otherwise bound the scan by “end of code” (`:1964-1971`).
5. Output backends: MSL exists. Add **HLSL** for Unity, analogous to `glsl_rewrite` (token rewriting), but using `asuint/asfloat`, `mad`, `rsqrt`, and `[loop]` controls. **Risk (*inferred*):** implicit derivatives (`Sample`) inside the `switch(pc)` state machine; HLSL/Metal compilers may reject them as non-uniform control flow or handle them incorrectly. First structure control flow (dominators, if/else, loops), or move LOD calculation out.
6. Reproducibility: the build step reads only local bundles (core goal step 4, “replace shaders with our own”) and writes output under `work/` (never into the repository).

**Unity-specific output question (decision required):** (i) Embed translated programs as ShaderLab `HLSLPROGRAM`, letting Unity compile them for Metal (fast math, operation ordering, and `precise` determine fidelity); or (ii) use MSL directly through a native Metal plugin, for maximum fidelity but bypassing Unity lighting, shadows, and pipeline. I recommend (i) first to test feasibility and (ii) only as a test harness.

## 10. BDSP Follow-up Tasks (Roughly Prioritized)

| Priority | Task | Rationale / evidence |
|---|---|---|
| 1 | **Measure coverage** (see section 11) and collect all unknown opcodes instead of stopping at the first. | `fail` stops at the first error (`:89-95`). |
| 2 | C container parser, extract all 13,710 programs, parallelize. | Known from `shader_map.py`. |
| 3 | Add missing instructions by frequency, starting with Fragment shaders (TLD, TLD4, TXD, more TEXS/TLDS info values, PRMT modes, MUFU variants). | See section 2.2. |
| 4 | **Fidelity test against Ryujinx SPIR-V** in existing harness `scripts/shader_harness`: feed identical inputs (vertex data, cbuf, textures) to the reference (SPIR-V → MSL) and our translator, compare pixel/value outputs. 1,288 programs have a matching counterpart (section 4). | Reference described in `render-treue.md`. |
| 5 | Numerics: disable fast math; test FTZ/denormals, MUFU accuracy (RCP, RSQ, SIN, COS), F2I/F2F rounding, and half precision; one microtest per instruction against the reference. | See section 2.2 (differences). |
| 6 | **Unity constant buffers:** map cbuf number and offset to names (`UnityPerDraw`, `UnityPerCamera`, material properties) from parsed shader data (`scripts/shader_inventory.py` reads parameter layouts). Map texture slots to property names. Check whether `cbuf_base = 3` also applies to Unity glslc (*inferred* because it is the same compiler). | Main effort according to `render-treue.md` (“Open”). |
| 7 | **Keyword variants:** each program carries its keywords (up to 17). Map variants to Unity material keywords; handle 8,332 unique codes instead of 13,710 programs (deduplicate by hash). | `mapping.json`. |
| 8 | Structured control flow instead of `switch(pc)` (translation time, derivative fidelity, HLSL compatibility). | See section 9. |
| 9 | Check Compute (5 programs, *inferred* to be skinning/effects); check Geometry/Tessellation only if measurements find any (none in the cache). | `shader-audio-machbarkeit.md:44`. |
| 10 | Hardening: fuzz for crashes, validate input bounds, add tests in a CI-like script. | Section 2.2 “Memory-safety risk.” |

## 11. Measuring Instruction Coverage for BDSP

**Goal:** For each of the 13,710 bundle programs (8,332 unique codes), identify which Maxwell instructions occur and which are unsupported by `translate.c`.

Method (all local; write only counts/names under `work/`, no binary data in the repository):
1. **Extract:** use the known container structure (section 4) to slice each Maxwell blob starting at `0x12345678` (`scripts/shader_map.py` supplies program ID, stage, keyword list, and `codeHash`). Deduplicate by `codeHash`.
2. **Histogram A (instructions):** for each instruction (each word whose index is not divisible by 4), identify its opcode class from the `OPM(value, mask)` patterns in `translate.c` (read patterns from source as in `test_translate.c:load_patterns`). Count by stage: words per opcode, programs per opcode, and share of programs **fully** covered by known opcodes.
3. **Histogram B (unknowns):** group unmatched words by top 12 bits (and opcode family), with sample program ID and location; identify them against a Maxwell opcode table (envytools/Ryujinx documentation). Extend translator `fail` to collect errors instead of stopping.
4. **Histogram C (partially supported forms):** count `fail` messages (e.g. “mufu 6”, “prmt mode”, “texs info N”) by message; they identify opcodes that are recognized but only partly supported.
5. **Compileability:** use Metal runtime compiler (`newLibraryWithSource`) to check every translatable program (template: `tools/test_shaders.m`); measure time and source size per program.
6. **Weighting:** also group results by shader name (`perShader` in `mapping.json`) and whether the variant occurs in Ryujinx cache (prioritize played paths).
7. **Second corpus:** use the 1,388 Ryujinx guest programs (1,288 have bundle counterparts) to cross-check whether bundle measurements yield the same results.

**Metrics (acceptance criteria):** (a) share of programs with zero unknown opcodes, (b) missing opcodes ranked by program count, (c) share of compilable MSL outputs, (d) image comparison against Ryujinx SPIR-V reference for the 1,288 matched programs, with tolerance to be defined.

**Open questions:** layout and offset of compiler constants in the Unity container; meaning of some control-header fields; whether `sdk`/`subsdk0` contain a shader compiler; whether Unity Metal faithfully translates generated HLSL; coverage measurements (none yet).
