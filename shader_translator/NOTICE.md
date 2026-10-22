# NOTICE: adapted code (LASRecomp)

This directory contains code adapted from another project and modified by us.

| | |
|---|---|
| Project | LASRecomp |
| Repository | https://github.com/peiikai/LASRecomp |
| Revision used | Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5` (short `09f8e5e`, the clone's only commit) |
| Author | Peiikai |
| License | MIT, “Copyright (c) 2026 Peiikai.” License text is unchanged in [`LICENSE-LASRecomp`](LICENSE-LASRecomp). |
| Adapted files | `runtime/nvn/maxwell/translate.c` → `translate.c`, `runtime/nvn/maxwell/shader.h` → `shader.h` |
| Not included | Everything else from upstream (runtime, NVN renderer, `third_party/`, UI, fonts, recompiler, tests) |

The upstream license explicitly excludes Nintendo property and third-party components in its `third_party/` directory. None of those are included here. The repository user explicitly approved this adaptation.

The two adapted files had no individual copyright notices upstream. We added a source comment at the beginning of each file that identifies its origin and refers to the license and commit.

## Upstream statement about how it was created

The upstream README describes the project as created “almost exclusively” with an AI (Anthropic Claude through Claude Code) and directed, tested, and reviewed by a human. The clone has only one commit and no development history. The code is provided without warranty; we check it with our own tests and, in part 2, numerical comparisons against the Ryujinx reference.

Comments in `translate.c` identify Ryujinx decoders as sources for individual field layouts (HADD2/HMUL2/HFMA2, XMAD, LDC). The upstream README does not list Ryujinx as a source. It is not possible to determine which parts of the structure or tables derive from other works (Ryujinx, envytools); both are therefore listed in `../THIRD_PARTY_NOTICES.md`.

## Our changes

All changes to adapted files are marked with `XNU:` comments.

### `translate.c`

1. **Coverage mode (`--survey`).** Added `maxwell_translate_ex()` with optional `Survey` pointer. When set, `fail()` no longer stops at the first problem; it records the issue (name, example word, count) in the survey and translation continues. Unknown opcodes are grouped by their upper 12 bits (`op<hex>`). Additionally, `approx()` reports cases where translator silently emits a placeholder (unknown attribute address) in survey mode. `maxwell_translate()` retains its signature and behavior.
2. **End of code.** Translator recognized padding after final EXIT (unconditional branch to itself) only with offset −8. Unity compiler targets the preceding scheduling word (−16), so compiler constants after code were read as instructions. Now accepts unconditional BRA whose normalized target is its own position.
3. **Input validation.** Too-small blobs now return an error rather than reading past the buffer.
4. **Removed because LAS-specific:** debug hooks `maxwell_dbg_*` (register output to color target, position dump buffer 29), `getenv("LARECOMP_NO_DISCARD")`, tint epilogue for color target 0 and buffer 19, and `uses_tint`.
5. **`LARECOMP_SAVE_MSL` → `ShaderKey.annotate`.** Instruction annotations (PC and word) now come from the key instead of an environment variable.
6. **`ShaderKey.no_rscale`.** This switch prevents the translator from reading resolution-scale table (buffer 18): window coordinates, texel fetches (TLD/TLDS), and size queries (TXQ) remain unscaled. `maxwell2msl` sets it by default; `--rscale` restores upstream behavior.

Part 2 (2026-10-18):

7. **TEX.B (bindless texture).** Upstream aborted on this instruction with “bindless tex.” Now `prov_track()` tracks, for each register, whether its value was built from constant-buffer words (MOV c[][], LOP.OR with c[][], LDC, MOV Rb; any other write resets tracking, based on generated text). `emit_tex()` uses this to read TEX.B handle register; texture is determined by word pair (sampler word | texture word) and assigned a slot (`bindless_slot()`, first-use order). Registers following handle supply LOD, offset, and depth comparison. If provenance is missing, instruction remains an error (“bindless handle not from cbuf words”). Added `bindless_has_sampler` and `bindless_sampler_offset` to `ShaderTexture`.
8. **HSETP2 with constant-buffer and immediate operands** (0x7e80/0x7f80 and 0x7e00/0x7f00). Register form existed upstream and was generalized: compare field bits 49..52 instead of 35..38, HAND bit 53 instead of 49, operand B is one f32 (cbuf) or two half values (immediate).
9. **Resource-map metadata:** statically addressed region per constant buffer (`cbuf_min_off`/`cbuf_end_off`, set in `cbuf_ref()`), input/output component masks (`in_comp`/`out_comp`), `flat_mask`/`noperspective_mask`, beginning of compiler constants in blob (`cbuf1_blob_offset`: code end rounded up to 0x100).
10. **Exact arithmetic.** MSL now starts with `#pragma METAL fp math_mode(safe)` and `#pragma METAL fp contract(off)` (key `fast_math` disables these). Upstream left Metal fast math and FMA fusion enabled.
11. **`ShaderKey.half_compat`** (test oracle only): keeps an unrounded `float2` shadow for registers written by half instructions, as Ryujinx does when removing pack/unpack pairs. Default behavior rounds to fp16, as hardware does.

### `shader.h`

Added `Survey`/`SurveyItem` and `maxwell_translate_ex()`; added `ShaderKey.no_rscale`, `ShaderKey.annotate`; removed `uses_tint`, `maxwell_dbg_*` declarations, and tint from interface comment; added provenance comment. Part 2: `ShaderKey.fast_math`, `ShaderKey.half_compat`; `ShaderTexture.bindless_has_sampler`/`bindless_sampler_offset`; `ShaderInfo.cbuf_min_off`, `cbuf_end_off`, `cbuf1_blob_offset`, `in_comp`, `out_comp`, `flat_mask`, `noperspective_mask`.

Part 3 (2026-10-19): added `ShaderKey.hlsl` and “HLSL contract” interface comment (structures, constant-buffer/texture names, limits).

### `translate.c`, part 3: HLSL output for Unity (`ShaderKey.hlsl`, tool option `--lang hlsl`)

All changes are marked with `XNU:` or in the file's header comment. MSL and GLSL output remain byte-identical (checked against previous version on 500 random blobs with three option sets each).

12. **New `hlsl_rewrite()`/`hlsl_prelude`/`hlsl_finish()` branch** following GLSL branch pattern: instruction body is still emitted in MSL syntax, then rewritten token by token (`as_type<float/uint/int>` → `asfloat/asuint/asint`, `fmin/fmax` → `min/max`, `rint` → `round`, `fma` → `mx_fma` (= `mad`), `isnan` → `mx_isnan` (bit test, because FXC folds away `isnan`), `popcount` → `countbits`, `char()/short()` → `sx8/sx16`, `in`/`out` → `i_`/`o_`, `cb<k>` → `mx_cb<k>`; unsupported names such as `ulong`, `half`, `gmem`, `simd_shuffle*` abort with an “hlsl:” message). Helpers (bitfields, `mulhi`, `clz`, `prmt`, `hx`/`hpack` via `f16tof32`/`f32tof16`, 32-bit carry `mx_adc3`, funnel shifts `mx_shf_*`, `fswzadd` with lane from pixel position) are in prelude, which has an include guard (vertex and fragment share a program).
13. **Regenerated per dialect:** texture fetches (`hlsl_sample()`: `Sample/SampleLevel/SampleBias/SampleCmp(LevelZero)`; register offsets become coordinate shifts because HLSL accepts only literal offsets), `TLDS` as `Load`, `TXQ` via `tsize<i>()`/`tlevels<i>()` (`GetDimensions`), 16-bit packing for `TEXS.F16`/`F2F`/`F2I`/`I2F`, `IADD32I`/`IADD3` with carry and `SHF` without 64-bit integers, `KIL` → `discard`, declarations and entry points (`mx_vs`, `mx_fs`, structures without semantics; wrapper supplies semantics).
14. **Control-flow state machine:** HLSL (FXC) supports neither `continue` inside `switch` nor assignments to `switch` variable inside loop (“l-value expected”). Therefore `switch (pc)` is emitted as an `if (pc == N) { … pc = next; }` chain (fallthrough sets `pc`; branch sets `pc = X; continue;`).
15. **`ShaderKey.hlsl`** excludes GLSL; compute, `half_compat`, global memory, resolution scaling, point coordinates, and subgroup instructions are rejected with a message.
16. **`main.c`** (our own code): `--lang msl|glsl|hlsl`, `--hlsl`, `language` key in resource map. Tests: 16 new C checks (`test_hlsl_backend`) and one CLI test.

Part 4 (2026-10-19, instancing and storage buffers):

17. **Register-indexed constant-buffer reads** now appear in HLSL as `mx_cbr<k>(Offset)` rather than `cbr(mx_cb<k>, Offset)`. `hlsl_finish()` emits a replaceable default definition per buffer (`#ifndef mx_cbr<k>`); wrapper replaces it for instanced fields (`cbuf_ref()`, `hlsl_finish()`). MSL and GLSL unchanged.
18. **Global memory (LDG) in HLSL.** Replaced “hlsl: global memory” error with a dedicated path: 32-, 64-, 128-bit and subword reads via `ByteAddressBuffer mx_gmem` (address is byte offset because wrapper leaves buffer address in driver cbuf 0 as zero; a nonzero high address word reads 0). STG and multiple storage buffers remain rejected (“hlsl: global memory store”). An `insn_done:` branch target at end of `emit_insn()` lets HLSL path run shared postprocessing (predicate).
19. **`main.c`:** `--gmem-base`/`--gmem-size` for MSL/GLSL output (harness test bank; default remains 0/0). Tests: five new C checks (LDG, STG rejection).

### Deliberately unchanged (for now)

Global variables `maxwell_gmem_base/size`, `flip_x`, GLSL branch (TEX.B and `half_compat` are MSL-only; GLSL branch untested), static buffers in `RSC2` (not thread-safe; translation runs in one thread), and `sprintf` without length check. See the open items in `docs/shaders.md`.

## Our own code in this directory (not third-party)

`main.c` (tool `maxwell2msl`; part 2: resource map via `--info`, `--cbuf1`, `--fast-math`, `--half-compat`; part 3: `--lang`), `container.c`/`container.h` (Unity shader-program reader), `Makefile`, `survey_report.py`, `tests/`. Outside this directory: `scripts/shader_fidelity.py` (fidelity test), `scripts/tests/test_shader_fidelity.py`; part 3: `scripts/shader_wrap.py` (ShaderLab wrapper generator), `scripts/tests/test_shader_wrap.py`, `docs/shader-unity-integration.md`.
