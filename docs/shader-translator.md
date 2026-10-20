# Maxwell-to-MSL Shader Translator (status 2026-10-18; Part 1: Adoption and Coverage Measurement; Part 2: TEX.B, HSETP2, Resource Map, Exact Arithmetic, Fidelity Test)

The LASRecomp translator (MIT; provenance and changes in `shader_translator/NOTICE.md`, notes in `THIRD_PARTY_NOTICES.md`) is included in the repository as a standalone command-line tool, `maxwell2msl`. Part 1 (sections 1–6) asked how many Switch shaders from bundles it can translate and what is missing. Part 2 (section 8 onward) closes the gaps and checks translation numerically against the Ryujinx reference. **Part 2 summary:** 100% of blobs are recognized (4,276 of 4,276, vertex and fragment), all 8,552 generated MSL files compile with Metal, and in a fidelity test with 500 program pairs, 85.8% of informative pairs (332 of 387) are within 1/255 per channel; 155 are bit-identical. Almost all remaining differences come from the reference's fp16 approximation (section 11); excluding those gives 95.1% (368 of 387). The analysis and adoption plan are in `docs/referenz-las-shader.md`. Core goal, Gamma/Built-in pipeline, and difference tests: `docs/kernziel.md`, `docs/render-treue.md`, `docs/shader-harness.md`.

Notation: **confirmed** = measured or read in code; *suspected* = inference without a test.

**Scope:** The repository contains only code and documentation. Shader binaries are generated locally under ignored `work/shaders/` from the user's own bundles.

## 1. Structure

| File (`shader_translator/`) | Origin | Contents |
|---|---|---|
| `translate.c`, `shader.h` | LASRecomp, modified by us | Maxwell machine code → MSL translator (and GLSL, unused). |
| `container.c`, `container.h` | original | Reader for Unity shader programs (magic `0x0C07513C`, control `0x98761234`, blob starts at `0x12345678`). |
| `main.c` | original | `maxwell2msl` tool. |
| `survey_report.py` | original | Aggregates survey runs into a histogram. |
| `Makefile`, `tests/` | original | Build (clang, `-O2`, warnings), `make test`, `make asan`. |
| `LICENSE-LASRecomp`, `NOTICE.md` | original / original | License text unchanged; provenance and change list. |

Outside the directory: `scripts/shader_extract_blobs.py` (extracts bundle shaders to `work/shaders/blobs/`), `scripts/tests/test_shader_extract.py`; from Part 2, `scripts/shader_fidelity.py` (fidelity test) with `scripts/tests/test_shader_fidelity.py` (24 synthetic tests).

Data flow: bundles (Unity, platform 19) → `shader_extract_blobs.py` → `work/shaders/blobs/<hash>.bin` + `index.json` → `maxwell2msl --survey --batch` → `survey.jsonl` → `survey_report.py` → histogram.

## 2. Usage

```sh
make -C shader_translator            # builds build/maxwell2msl
make -C shader_translator test       # 72 C checks, 14 CLI tests, 6 report tests (synthetic)
make -C shader_translator asan       # same CLI with AddressSanitizer/UBSan

# Translate one file (Unity program: stage comes from container; raw blobs need --stage)
shader_translator/build/maxwell2msl prog.bin -o prog.metal --info prog.json
shader_translator/build/maxwell2msl --stage fs blob.bin

# Coverage: one shader as JSON, or many using a list file ('vs|fs|cs <path>' per line), one JSON line per shader
shader_translator/build/maxwell2msl --survey --stage fs blob.bin
shader_translator/build/maxwell2msl --survey --batch list.txt -o survey.jsonl
```

Options: `--stage vs|fs|cs`, `-o`, `--info` (resource map, section 9), `--cbuf1 <file>` (compiler constants, section 9), `--survey`, `--batch`, `--attr-kind N=f|i|u`, `--rt-kind N=f|i|u`, `--vs-out-mask`, `--flip-y`, `--depth-minus-one`, `--rscale`, `--glsl`, `--annotate`, `--fast-math` (disable pragmas, section 10), `--half-compat` (test oracle, section 11). Key values (`ShaderKey`) match the original.

Exit codes: 0 = success (survey: no issues), 1 = translation failed (survey: issues found), 2 = invalid usage, 3 = input/output error (file, unknown container).

Input format: Maxwell blob (NVN header `0x12345678`, 0x30 bytes; SPH, 0x50 bytes; code from 0x80 in groups of four: one scheduling word and three instructions; compute: code starts at file beginning) or a complete Unity program. Constant buffers are not read as input; constant-buffer information is part of output (`--info`). Translator does not read compiler constants after code; `--cbuf1` writes them out (section 9).

Per-shader survey JSON: `file`, `stage`, `bytes`, `insts`, `translatable`, `us`, `unknownOpcodes[]` (`name` = `op<upper 12 bits>`, `bits`, `count`, `example`), `unsupportedForms[]` (`name`, `count`, `example`), optional `error`/`inputError`/`overflow`.

Extraction:

```sh
PYTHONPATH=tools/pydeps python3 scripts/shader_extract_blobs.py            # work/shaders/blobs (Dpr/shaders + Effects/fxparticle)
PYTHONPATH=tools/pydeps python3 scripts/shader_extract_blobs.py --extra --out work/shaders/blobs_extra   # plus resources.assets, tmpshader
python3 shader_translator/survey_report.py work/shaders/blobs/index.json work/shaders/blobs/survey.jsonl --json work/shaders/blobs/report.json
```

## 3. Differences from upstream (summary; details in `NOTICE.md`)

1. **Survey mode** (`maxwell_translate_ex`): collects every unknown opcode and unsupported form instead of stopping at the first error; also reports silent placeholders (`approx:`). Normal mode is unchanged.
2. **Fixed code-end handling:** Padding after EXIT in Unity shaders jumps to the preceding scheduling word (offset −16). Upstream knew only −8, then read compiler constants as instructions (first measurement showed 67 false “unknown opcodes”; `op000` and `opbf1` were floating-point constants).
3. **Input validation** for minimum size.
4. **Removed LAS-specific behavior:** debug hooks `maxwell_dbg_*`, `getenv` switch, tint epilogue (buffer 19).
5. **`no_rscale`:** no resolution scaling (buffer 18); default in this tool.
6. **Still unchanged:** GLSL path (TEX.B and `half_compat` are MSL-only, GLSL untested), `flip_x`, global-memory globals, non-thread-safe static buffers, unbounded `sprintf` (tasks below).
7. **Part 2 (sections 8–11):** TEX.B, HSETP2 (cbuf/imm), resource map, pragmas against fast-math and FMA contraction, `half_compat`. Each change is marked `XNU:` in source and listed in `NOTICE.md`.

## 4. Measurement (Part 1, before TEX.B and HSETP2; updated numbers in section 8)

Measured 2026-10-18, M1 Pro, `clang` 23 (Homebrew), `-O2`. All numbers come from `work/shaders/blobs/report.txt`.

### 4.1 Corpus

| Quantity | Value |
|---|---|
| Programs in `Dpr/shaders` + `Effects/fxparticle` | **13,710** (vertex 6,878, fragment 6,832); all containers parse |
| Of which `shaders` / `fxparticle` | 5,734 / 7,976 |
| Unique Maxwell blobs (whole blob from NVN header to program end) | **4,276** (vertex 683, fragment 3,593) |
| Unique code bodies (SPH + code, without constants or trailing data) | **2,859** |
| Blob size | median 1,604 bytes, max 9,352 bytes |
| With `--extra` (plus `resources.assets`, `tmpshader`) | 13,918 programs, 4,336 blobs, 2,919 code bodies (`work/shaders/blobs_extra`, nearly identical results) |

**Difference from the previously reported 8,332 “unique code bodies” (confirmed; cause *suspected*):** That number came from the hash in `scripts/shader_map.py`, which truncates code at absolute position `dataOffset + dataSize`. Truncating the same blobs this way produces 8,454 rather than 4,276 distinct values. The reference point probably shifts with keyword-list length, giving identical code different hashes. Also, this truncation leaves fewer than one instruction group in 254 blobs even though code continues afterward. Therefore `shader_extract_blobs.py` does not truncate; it exports to program end and the translator detects code end itself. `shader_map.py` was not changed (owned by another agent). Ryujinx mapping by prefix comparison is unaffected; only its “unique code bodies” count is too high.

### 4.2 Coverage (“translatable” = no unknown opcode, unsupported form, or silent placeholder)

| Stage | Blobs | Translatable | Code bodies | Translatable | Programs | Translatable |
|---|---:|---:|---:|---:|---:|---:|
| All | 4,276 | **684 (16.0%)** | 2,859 | 670 (23.4%) | 13,710 | 6,876 (50.2%) |
| Vertex | 683 | 675 (98.8%) | 675 | 667 (98.8%) | 6,878 | 6,842 (99.5%) |
| Fragment | 3,593 | **9 (0.3%)** | 2,184 | 3 (0.1%) | 6,832 | 34 (0.5%) |

By bundle (blobs): `shaders` 1,154, 322 translatable (vertex 315/323, fragment 7/831); `fxparticle` 3,122, 362 translatable (vertex 360/360, fragment 2/2,762). The 50% program coverage is misleading: it comes almost entirely from vertex shaders. **Fragment shaders are practically untranslatable at this point.**

### 4.3 Missing instructions (counted per blob; only these three groups)

| Issue | Blobs | Code bodies | Programs | Occurrences | Stage |
|---|---:|---:|---:|---:|---|
| `TEX.B` (bindless texture, reported as “bindless tex”) | 3,592 (84.0%) | 2,189 | 6,834 | 13,613 | 3,584 fragment, 8 vertex |
| Opcode group `0x7e8` = **HSETP2**, constant-buffer form | 437 | 437 | 1,589 | 813 | fragment |
| Opcode group `0x7e0` = **HSETP2**, immediate form | 179 | 179 | 566 | 181 | fragment |

I looked up the names of the two groups in a public emulator decoder table (`maxwell.inc` in citron-neo/emulator; GPL, read only, nothing copied). *Suspected* pending a test: translator supports HSETP2 only in register form.

Greedy priority by benefit: `TEX.B` alone makes 3,152 blobs translatable (89.7% of blobs, 88.4% of programs), then HSETP2-cbuf adds 261 (95.8%), and HSETP2-imm adds 179 (100%). **After these three items, no unknown instruction remains in the corpus.** This means “recognized,” not “correct” (section 4.6).

Not found (unlike concerns in `referenz-las-shader.md`): TLD4/TXD/TMML, image accesses, atomics, indexed IPA/LD, `mufu` variants, PRMT modes, BFE.BREV, R2P.CC, CSET, TXQ types. Either they do not appear in these bundles, or another pattern misclassifies them (section 4.6). No silent placeholders (`approx:`) occurred.

### 4.4 Runtime

Processing all 4,276 blobs takes **0.5 s** in one process (1.3 s cold), 639,844 instructions; mean 88 µs per shader, median 48 µs, P95 237 µs, max 398 µs. Translator is negligible as a build step. Same run with `make asan` produces identical results and no sanitizer report.

### 4.5 Output compilation

All 684 translatable blobs were converted to MSL with `maxwell2msl` and checked with Metal runtime compiler (`scripts/shader_msl_check.swift`, language version 2.3, Apple M1 Pro): **684/684 compile** (13 s). This verifies syntax only.

### 4.6 Measurement limits

- **“Recognized” does not mean “correct.”** Decoder is a chain of mask patterns with no independent cross-check. A loose pattern could silently translate another instruction incorrectly, so it would never appear as unknown. Part 2's numerical comparison provides the cross-check.
- Instruction mix (frequency of each instruction) was not analyzed.
- Whether control flow using `switch (pc)` occurs, or its effect on Metal compile time and derivatives, was not measured.
- The 684 compiling shaders are almost all vertex shaders.
- Cross-check against Ryujinx cache as a second corpus (`referenz-las-shader.md`, section 11, item 7) remains open.

## 5. Findings for Part 2 (from Part 1; resolved in section 8)

- **TEX.B is the main blocker.** Translator had fields for bindless textures (`ShaderTexture.bindless`, `bindless_cbuf`, `bindless_offset`) but no implementation. This disproves the assumption in `referenz-las-shader.md` (“bindless probably irrelevant”): almost all Unity NVN shaders sample through handles.
- **Handle origin** (confirmed for 13,544 of 13,601 TEX.B instructions in fragment shaders): the handle register is set immediately beforehand by an instruction in class `0x4c4x` (*suspected*: logical operation, cbuf form) from **cbuf 2**. Offsets use 8-byte increments from `0x568` to `0x5c8` (13 values; `0x568` occurs 3,822 times, `0x570` 3,408, declining to `0x5c8` 12 times). *Suspected:* cbuf 2 is the driver's handle table, texture k at `0x568 + 8k`. Unity shader parameter layout maps these to texture names. **Part 2 refines this:** before the `0x4c4x` instruction (LOP.OR) is a MOV from the same buffer; handle is bitwise OR of two words (section 8).
- **Vertex shaders are nearly complete** (98.8%); eight exceptions are vertex texture accesses (TEX.B).
- Fragment blobs usually contain 2–4 TEX.B instructions (up to 20).

## 6. Part 2 task list and status

| # | Task | Status after Part 2 |
|---:|---|---|
| 1 | TEX.B | **done** (section 8) |
| 2 | HSETP2 cbuf/imm | **done** (section 8); HSET2 in these forms is absent from corpus |
| 3 | Numerical fidelity tests | **done for full shaders** (section 11); instruction microtests and decoder cross-check remain (Part 3) |
| 4 | Disable fast math | **done** (section 10); FTZ/denormals remain |
| 5 | `noperspective`/interpolation | **open**: none of the 500 tested references contain `flat`, `noperspective`, or `centroid`, so this case was not tested |
| 6 | Map Unity constant buffers | **partial**: resource map provides sizes and ranges (section 9); names from parameter layout remain (Part 3) |
| 7 | Compiler constants (cbuf 1) | **done**: location after code found, `--cbuf1` (section 9); embedding as `constant` array remains |
| 8 | Keyword variants | **open** (Part 3); program → blob mapping is local at `work/shaders/prog_blob.json` |
| 9 | Hardening | **open**; running all 8,552 translations with AddressSanitizer/UBSan produced no report |
| 10 | Control flow | **open** |
| 11 | Output format for Unity | **open** (Part 3) |
| 12 | Remaining LAS-specific behavior | **open** |
| 13 | Expanded measurement | **partial**: second corpus (Ryujinx) is now fidelity test; instruction mix and control-flow statistics remain open |

Original task wording is in Git history of this file.

## 8. Part 2: TEX.B, HSETP2, and coverage

### 8.1 TEX.B (bindless texture)

**How the handle is built (confirmed for all 13,613 TEX.B instructions in corpus).** Unity compiler builds handle register from two words in constant buffer 2: first `MOV Rh, c[2][s]`, then `LOP.OR Rh, Rh, c[2][t]`. An NVN handle stores texture ID in lower 20 bits and sampler ID in upper 12 bits; word `t` is in range starting at `0x568`, word `s` starts at `0x168`, both on 8-byte boundaries. Texture is therefore known at translation time; MSL needs no runtime handle. Translator tracks for each register whether its value is built from constant-buffer words (`prov_track()`; MOV c[][], LOP.OR, LDC, register MOV; any other write resets, as does a predicated write). Unresolvable handles still produce an error.

TEX.B field layout (like `TEX`, differently arranged): destination bits 0..7, coordinates from `Ra` (bits 8..15), handle register `Rb` (bits 20..27), dimension bits 28..30 (array, target), write mask bits 31..34, offset flag bit 36, LOD mode bits 37..39, depth compare bit 50. Registers following handle provide LOD, offset, and depth comparison value in order. All forms supported by `TEX` (1D/2D/3D/Cube, array, shadow, LOD modes, offset) are therefore available for TEX.B without extra code; corpus uses 2D and Cube with LOD modes “implicit,” `LL`, and `LZ` (Cube only 4 times; shadow, array, offset never).

**Measurement over all 4,276 blobs (from resource map):** 3,592 blobs use textures, with 13,134 distinct texture slots total (up to 13 per blob), all from cbuf 2, all with sampler word. 13,130 are 2D, 4 Cube. Slots are assigned in first-use order; slots are equivalent when word pair, type, shadow, and array flags match. Texture-word minus sampler-word distance is exactly `0x400` in 8,043 cases (61%), otherwise `0x3f8` (3,646), `0x408` (409), `0x410` (146), and other values: sampler and texture combine independently, so sampler has its own table index. **Cross-check:** Ryujinx bindless texture name encodes same word pair (`fp_tex_cb196610_1056805A` = texture word `0x568`, sampler word `0x168`). Across all 970 stage pairs in fidelity test (vertex and fragment for 500 pairs), set of (texture, sampler) keys matches between our translation and reference.

### 8.2 HSETP2 with cbuf and immediate operands

Register form already existed. The other forms (groups `0x7e80`/`0x7f80` and `0x7e00`/`0x7f00`) have same fields in different locations because bits 20..38 carry operand: comparison bits 49..52 (register form: 35..38), HAND bit 53 (49), for cbuf form negate bit 56 and absolute bit 54, operand as one f32 (cbuf) or two half values with separate signs (immediate; same encoding as HADD2). I inferred locations from HADD2/HMUL2 forms in same instruction family and cross-checked against corpus words (source words: `0x7e85038c0457ff07`, `0x7e0883bc0f071207`). Numerical test is decisive: 128 cbuf-form pairs and 73 immediate-form pairs were in fidelity test; per section 11, 117 and 71 pass. HSET2 in these forms (group `0x7c..`) does not occur in corpus and is not implemented.

### 8.3 Coverage after Part 2

Re-measured with `--survey` over all blobs; figures from `survey_report.py`:

| Stage | Blobs | Recognized | Code bodies | Recognized | Programs | Recognized |
|---|---:|---:|---:|---:|---:|---:|
| All | 4,276 | **4,276 (100%)** | 2,859 | 2,859 (100%) | 13,710 | 13,710 (100%) |
| Vertex | 683 | 683 (100%) | 675 | 675 | 6,878 | 6,878 |
| Fragment | 3,593 | 3,593 (100%) | 2,184 | 2,184 | 6,832 | 6,832 |

Extra corpus (`--extra`, plus `resources.assets`, `tmpshader`) gives 4,336/4,336 blobs and 13,918/13,918 programs. No unknown opcodes or unsupported forms remain; further instructions (TLD.B, TLDS, TXQ.B) did not appear after TEX.B. Run takes 0.5 s. **All 4,276 blobs translate (`maxwell2msl` without survey), and all 8,552 generated MSL files (standard mode and `--half-compat`) compile with Metal runtime compiler** (`scripts/shader_msl_check.swift`, 98 s, M1 Pro). Same run with AddressSanitizer/UBSan produced no report.

“Recognized” still means only “no unknown instruction.” Section 11 tests whether translation is correct.

## 9. Resource map (`--info`)

`maxwell2msl --info <file.json>` writes a machine-readable map for a driver (harness, later Unity) to bind resources correctly. New in Part 2: `metal`, `compilerConstants`, `constantBuffers`, expanded `textures`, plus `inputs` and `outputs`; older keys (`cbufMask`, `cbufSize`, `attrMask`, `outMask`, etc.) remain. Example for a synthetic fragment shader with one bindless texture (no game content, shortened):

```json
{
  "stage": "fs", "instructions": 4,
  "metal": {"entry": "main0", "constantBufferSlot": "cbuf k -> [[buffer(k)]], constant uint4*",
            "textureSlot": "texture i -> [[texture(i)]] and [[sampler(i)]]",
            "vertexAttribute": "location i -> [[attribute(i)]], float4",
            "stageInterface": "vertex out / fragment in: [[user(locn i)]], float4", "rscaleBuffer": null, "globalMemoryBuffer": null},
  "compilerConstants": {"cbuf": 1, "blobOffset": 256, "bytesAvailable": 16},
  "constantBuffers": [{"index": 2, "metalBuffer": 2, "size": 1536, "dynamic": false, "staticMinOffset": 360, "staticEndOffset": 1388}],
  "textures": [{"slot": 0, "metalTexture": 0, "metalSampler": 0, "type": 1, "typeName": "2d", "shadow": false, "array": false,
                "bindless": true, "handleCbuf": 2, "textureWordOffset": 1384, "textureTableIndex": 0,
                "hasSamplerWord": true, "samplerWordOffset": 360, "samplerTableIndex": 0}],
  "inputs": [], "outputs": []
}
```

Meaning:

- **`constantBuffers`:** for each buffer read, index (= Metal buffer slot), size (rounded up to 256 bytes; with register-index access `dynamic: true`, bind entire buffer, up to 64 KB), and range of statically addressed bytes (`staticMinOffset` to `staticEndOffset`, exclusive). This shows which portions of a Unity block the shader actually reads.
- **`textures`:** `slot` is both Metal texture and sampler index. `textureWordOffset`/`samplerWordOffset` are byte offsets of handle words in cbuf `handleCbuf` (always 2). Driver-table index is `(textureWordOffset − 0x568) / 8` or `(samplerWordOffset − 0x168) / 8` (`textureTableIndex`/`samplerTableIndex`; base offsets are assumptions derived from shaders, −1 if mismatch). Driver must bind that table entry's texture to `texture(slot)` and sampler to `sampler(slot)`. Type (`typeName`, `shadow`, `array`) determines MSL declaration (`texture2d<float>`, `texturecube<float>`, `depth…`).
- **`inputs`/`outputs`:** Vertex: input locations and read components (`[[attribute(i)]]`, all declared `float4`), outputs and written components (`[[user(locn i)]]`). Fragment: inputs and interpolation (`flat`/`perspective`), outputs as color targets with components.
- **`compilerConstants` and `--cbuf1 <file>`:** constant buffer 1 contains compiler-generated constants. They are in blob after code, rounded up to 0x100 (`blobOffset`). Confirmed for all 934 shaders with static cbuf 1 reads: nonzero data is present there, and read byte count matches floating-point constants in checked cases (e.g. `1.0, 0.8, 0.05, 0.1, 0.5` for 20 bytes). `--cbuf1` writes at most 64 KB from that location (remainder is reflection data and padding never read by shader). Constant-buffer size is not stored in blob; required size comes from `constantBuffers`.
- **Buffer roles** (assumption, not emitted by `maxwell2msl`): cbuf 0 driver, 1 compiler constants, 2 handle tables, 3+ Unity blocks. Buffers read across 4,276 blobs: cbuf 0 in 180, 1 in 934, 2 in 3,592, 3 in 3,615, 4 in 614, 5 in 118. Register-index (dynamic) reads occur in cbuf 5 in 118 blobs and cbuf 4 in 7 blobs (instancing data).

Note: MSL still reads handle words in cbuf 2 (compiler MOV/LOP instructions remain in output); values are never used, but buffer must be bound unless Metal compiler removes dead access. In 500-pair fidelity test, our translation therefore reads one more buffer than reference in 473 of 970 stages.

## 10. Exact arithmetic (fast math disabled)

**Metal defaults:** fast math (reordering, relaxed NaN/Inf handling, fast functions) and contraction of `a*b+c` into FMA. Switch GPU rounds each FMUL and FADD separately. Both can change low bits and become visible at thresholds and feedback loops.

**What macOS 26 (Xcode 26.0.1, M1 Pro) accepts (measured):**

- `MTLCompileOptions.mathMode = .safe` and `mathFloatingPointFunctions = .precise` are accepted with language version 2.3; before macOS 15 use `fastMathEnabled = false`.
- Pragmas `#pragma METAL fp math_mode(safe)` and `#pragma METAL fp contract(off)` compile with language version 2.3.
- **`mathMode = .safe` alone does not prevent FMA contraction:** test `a*b+c` (buffer operands chosen so separately rounded result is 0, fused result is `2^-26`) produced fused result in both modes; only `contract(off)` yielded separately rounded value.
- Options have effect: deliberately chaotic test shader (sin, exp2, division, log2, multiplied and amplified with `fract`) differs between `safe` and `fast` by up to 253 levels (PSNR 16.7 dB).

**Implementation:** `maxwell2msl` writes both pragmas at start of every MSL file (`--fast-math` omits them). Harness (`scripts/shader_harness`, `Render.swift`/`main.swift`, commented) compiles with `mathMode = .safe` and precise functions by default; it prepends `#pragma METAL fp contract(off)` to sources without an `fp contract` pragma (spirv-cross reference), so reference and translation receive same treatment. `--fast-math` disables this. Output reports mode (`math=safe`).

**Open:** instruction FTZ and rounding flags are not evaluated; denormal behavior unmeasured. How Unity's own shader pipeline receives these pragmas/options belongs to Part 3.

## 11. Numerical fidelity test (`scripts/shader_fidelity.py`)

### 11.1 Method

`work/shaders/mapping.json` provides 2,901 cache entries (2,900 unique blob pairs) with vertex and fragment stages in both sources: bundle blob and Ryujinx SPIR-V. `prog_blob.json` (program → blob hash, `shader_fidelity.py index`) connects them. The sample alternates across shaders deterministically so `Delphis/Map/Standard` with 2,570 entries does not dominate.

For each pair:

1. **Reference:** SPIR-V → MSL using `spirv-cross` (MSL 2.3, no extra flags), then parse MSL header for interface: vertex attributes, buffers (`vp_c<k>`/`fp_c<k>` = hardware cbuf k), textures and samplers with slots. Ryujinx name of bindless texture gives (texture, sampler) key.
2. **Our output:** run `maxwell2msl` on vertex and fragment (fragment with vertex shader's `--vs-out-mask`), read interface from resource map, compiler constants (cbuf 1) from `--cbuf1`.
3. **Same inputs:** 12×12 grid (169 vertices, 288 triangles), all attributes from union of both sides as `float4` (lowest location = position in ±0.9, others vary in [0, 1]); constant buffers are 64 KB files from one of 42 deterministic profiles (`identity`: identity matrices on 64-byte grid, possibly shifted by 1–3 vectors, and may differ per buffer; `dense`, `hash`, `signed`, `small`, `half`). Textures are 64×64 with mipmaps (checkerboard with alternating alpha or gradient, colors from texture-word hash); sampler linear/linear/mip-linear/repeat. First profile where reference image is informative (at least 2% pixels covered, at least two colors) wins. cbuf 1 is blob constant data, not synthetic.
4. **State:** 128×128, `rgba8Unorm`, no depth, blending, culling, one draw, no MSAA. Both sides output guest clip position unchanged (`flip_y`/`depth_minus_one` off for ours, `--flip-vert-y`/`--fixup-clipspace` off for reference); inspected reference modules show Ryujinx writes position unchanged, and 332 pairs match within one level without coordinate correction, so state is equivalent.
5. **Comparison:** `scripts/shader_compare.py` (RGBA, max/mean difference, pixels above threshold, PSNR). On mismatch, two mixed runs (reference VS + our FS; our VS + reference FS) attribute error to stage.

**Thresholds:** *pass* = maximum difference ≤1 level per channel (1/255). Rationale: `rgba8Unorm` rounds; two floats differing only in low bits can differ by exactly one level at rounding boundary. More than one level indicates real arithmetic difference. *Near* = ≤3 levels (e.g. different function approximations), *fail* above. Also record pixel count over 1 level, mean difference, and PSNR.

Pairs are **uninformative** if reference image remains almost empty (discarded/outside) or monochrome with all 42 profiles; excluded from totals. **Unsupported:** Cube textures (harness supports only 2D) or memory buffers (`vp_s0`, instancing data for `FxSystem/Particle`).

### 11.2 Results (500 pairs, 62 shaders, Apple M1 Pro, Metal safe math, `shader_fidelity.py run --count 500`)

| Result | Pairs |
|---|---:|
| Pass (≤1 level) | **332** (155 bit-identical, 177 within one level) |
| Near (≤3) | 11 |
| Fail | 44 |
| Uninformative | 98 (64 monochrome, 34 almost empty; 47 are `Delphis/Map/Standard`, remainder alpha-test, mask, DepthOnly, similar shaders) |
| Unsupported | 15 (11 memory buffer, 4 Cube texture) |
| **Informative** | **387** |

**Rate among informative pairs: 85.8% pass in standard mode** (332/387; 88.6% including “near”). Removing differences caused by Ryujinx fp16 approximation (next section): **95.1%** (368/387). Informative pairs come from 55 of 62 shaders. Mean difference across all channel values for passing pairs is 0.008 levels on average (maximum 0.21). Subsets (standard / compatibility mode): pairs with TEX.B 331/386 and 367; HSETP2 cbuf 89/128 and 117; HSETP2 imm 50/73 and 71; TEX.B in LOD `LL` 76/103 and 93. Pairs without packed-half results pass at 100% (159/159).

Example images (reference, translation, difference ×8) are under `work/shaders/out/fidelity/` and must stay out of repository. All figures are in local `work/shaders/fidelity_report.json`.

### 11.3 Causes of differences

**1. Ryujinx does not round fp16 (55 pairs; 52 fragment-only).** Unity shaders use `half` variables on Switch; hardware runs HADD2/HMUL2/HFMA2 in fp16 and rounds every result to half precision. Ryujinx translator removes pack/unpack pair between half instructions, so reference computes in fp32 without rounding. Evidence:

- Pair 2801 (`UI/Blur`, simple, one texture): reference has `fma(_54, -9.0, _48)` in fp32 where our translation rounds to fp16. Rounding these ten values in a copy of reference (`float(half(x))`) reduces max difference from 16 to 1 level.
- `--half-compat` imitates Ryujinx behavior (unrounded `float2` shadow per register written by half instructions, `translate.c` `hstore()`). 36 of 55 pairs then pass, including bit-identical pairs.
- All 55 differing pairs use packed-result half instructions in vertex or fragment; all 159 pairs without them pass.

**Which side is “correct”?** *Suspected:* ours (hardware rounds), but this test has no hardware reference. Ryujinx is an approximation; `--half-compat` also only approximates it (Ryujinx does round in some places; reference occasionally contains `half2(`). Standard behavior is for 1:1 fidelity; this test cannot prove it. Hardware image or emulator reference with fp16 rounding remains open (Part 3).

**2. Remainders after `--half-compat` (19 pairs, 4.9%).**

- 3 pairs (`Mitake/MitakeStandardBumpShader` 73 and 74, `Delphis/Character/Standard` 106): 5–6 of 16,384 pixels (0.04%) flip between 0 and 255 (chaotic path, edge pixels); rest of image ≤1 level.
- 15 `Delphis/Map/Standard` pairs: 61 or 99 pixels (0.4–0.6%) are 0 in ours and colored in reference. **By bisection** (stop shader after instruction k and output “any register is NaN” flag), for pair 362 the 61 mismatching pixels are exactly those where our translation has NaN somewhere; first NaN occurs in half-instruction chain (`rsqrt` of fp16 sum, then `inf * 0`). Consistent with fp16 overflow at extreme synthetic values, absent in fp32 reference. Not proven for every instance of this group.
- Pair 2452 (`Map/Standard`): max difference 6, 43 pixels; unanalyzed.

**3. Not the cause:** binding, register allocation, interpolation, clip space. Texture keys match in 970/970 stages, mixed variants show no interface errors, and all 332 + 36 passing pairs use same bindings. `noperspective`/`flat`/`centroid` do not occur in 500 references, so they remain untested.

### 11.4 Test limits

- Synthetic inputs: extremes (NaN, Inf, overflow) occur more often than in game. A passing result confirms equality with reference for those inputs, not bug-free behavior.
- Reference is Ryujinx (SPIR-V → spirv-cross → Metal), not hardware. Where Ryujinx differs (fp16), it cannot serve as ground truth.
- 98/500 pairs are uninformative. `Delphis/Map/Standard` (2,570 of 2,901 entries) has 180 sampled pairs, 133 informative; distribution of its variants was not analyzed. Running all 2,901 with profile search takes hours; stopped after about 290 pairs (at that point 160 of 186 informative `Map/Standard` pairs passed).
- One draw, 2D textures, `rgba8Unorm`, fixed samplers (no comparison sampler, no border), no depth/stencil/blend, no Cube/array/shadow textures, no memory buffers.
- Input profiles are guesses (test does not know which cbuf range contains a matrix).

## 12. Open items

1. **Check fp16 rounding against hardware** (11.3): device reference image or emulator that rounds fp16; retain standard behavior until then.
2. **Resolve section 11.3 item 2 remainder** at instruction level (bisect other pairs, microtest HFMA2/HMUL2 overflow).
3. **Add Cube, array, shadow textures, and memory buffers** to harness (4 Cube pairs in test; `FxSystem/Particle` needs `vp_s0`).
4. **Verify `noperspective`, `flat`, `centroid`** against reference (`noperspective_mask` remains unset in translator).
5. **Instruction microtests** (MUFU variants, F2I rounding, SHF/BFE/PRMT/XMAD, FTZ/denormals) and **decoder cross-check**: full shader tests cover only corpus instructions whose result affects image.
6. **Hardening** (task 9 above), **GLSL path** (TEX.B/`half_compat` are MSL only).
7. **Harness:** vertex shader without `[[stage_in]]` crashes renderer (`vertexAttributes!` is nil); pre-existing, unchanged.
8. **Dead handle-word accesses** (section 9) should be removed from MSL.

## 13. Reproduction (Part 2)

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
make -C shader_translator test                                   # 72 + 14 + 6 checks
swift build -c release --package-path scripts/shader_harness --scratch-path work/shaders/build
python3 -m unittest scripts/tests/test_shader_fidelity.py       # 24 synthetic tests
PYTHONPATH=tools/pydeps python3 scripts/shader_fidelity.py index # once: work/shaders/prog_blob.json
python3 scripts/shader_cache_extract.py                          # all SPIR-V modules to work/shaders/spirv (203 MB)
python3 scripts/shader_fidelity.py run --count 500 --jobs 4      # about 10 minutes, report work/shaders/fidelity_report.json
python3 scripts/shader_fidelity.py run --only 2801 103           # individual cache indices
```

For each pair, run creates specifications, MSL, and chosen-profile inputs under `work/shaders/fidelity/<index>/` (about 150 MB total for 500 pairs), and images under `work/shaders/out/fidelity/` (about 6 MB).

## 14. Part 3 (proposal)

**Status of Part 4 (2026-10-19):** HLSL path implemented (`docs/shader-unity-integration.md`); HLSL backend now reads global memory through `ByteAddressBuffer mx_gmem` (180 particle blobs; 4,272/4,276 blobs translatable, 4 fragment blobs with subgroup shuffle remain) and makes register-indexed cbuf accesses replaceable as `mx_cbr<k>` (instancing). Maxwell texture-table index corresponds to inventory field `sampler`, not `index` (section 4.1 there). MSL options `--gmem-base`/`--gmem-size` are available for harness.

**Unity integration**

- Choose output format (`referenz-las-shader.md`, section 9): HLSL backend for ShaderLab, or MSL as native plugin. Resource map supports both.
- Name constant buffers: map cbuf 3+ against parsed shader parameter layout (`UnityPerDraw`, `UnityPerCamera`, material, instancing); offsets in `staticMinOffset`/`staticEndOffset` show what is read. Embed compiler constants (cbuf 1) as `constant` array.
- Texture binding: map driver-table entry `(textureWordOffset − 0x568) / 8` to material texture property; use sampler state from Unity (filter, wrap, anisotropy) instead of fixed test samplers.
- Adapt Y and depth conventions (`flip_y`, `depth_minus_one`) to Unity; enforce pragmas or compile options from section 10 in Unity Metal pipeline (or verify their effect).

**Variants and keywords**

- Move program → blob hash mapping (local `prog_blob.json`) into build stage; select by Unity keyword set; 13,710 programs → 4,276 blobs → 2,859 code bodies, deduplicated at build. Test covers one variant per cache entry; distribution inside `Delphis/Map/Standard` and `FxSystem/Particle` is open.

**Effects**

- Particles (`FxSystem/Particle`: instance data in memory buffer), Cube textures (reflection), post effects, and GrabPass need harness extensions and fixed capture points for image comparison.
- Extend fidelity test to time sequences and multiple draws (multipass, depth testing, blending from parsed pass state).

**Verification**

- Open items 1–8 from section 12.

## 15. Reproduction (Part 1)

```sh
make -C shader_translator test
PYTHONPATH=tools/pydeps python3 scripts/shader_extract_blobs.py
python3 - <<'EOF'   # list file (paths relative to repository root)
import json
d = "work/shaders/blobs"
with open(f"{d}/list.txt", "w") as f:
    for e in json.load(open(f"{d}/index.json"))["blobs"]:
        f.write(f"{e['stage']} {d}/{e['hash']}.bin\n")
EOF
shader_translator/build/maxwell2msl --survey --batch work/shaders/blobs/list.txt -o work/shaders/blobs/survey.jsonl
python3 shader_translator/survey_report.py work/shaders/blobs/index.json work/shaders/blobs/survey.jsonl
```

Test files: `shader_translator/tests/test_translate.c` (core and container, survey collection, code end), `tests/test_cli.py` (exit codes, JSON, batch, key options), `tests/test_report.py` (histogram), `scripts/tests/test_shader_extract.py` (container parser, code end, deduplication). All use synthetic inputs and no game data.
