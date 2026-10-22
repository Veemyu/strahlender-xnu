# Differential test: generated C (c mode) versus real ARM64 semantics (`ap-recomp-diff`)

Status: 2026-10-19 (measurements from 13:45 to 15:10). Based on `docs/recomp-linux.md` (section 3, limits), `docs/architecture.md` (generator and lifter modes), and `research/LASRecomp` (MIT, user-approved; read-only and runtime-imported, nothing modified).

**Labels:** **measured** = generated using scripts under `scripts/recomp/diff/` (figures from reports under `work/recomp/diff/`, local, not in the repository); **derived** = conclusion from measurements; **not tested** = gap (section 9).

## 0. Summary

1. **The portable `c` mode is bit-exact to ARM64 semantics for everything the game executes—measured with the correct compiler flags and a clean host FPU state.** About **93.5 million cases per variant** (9,134 tests, 306 instructions, 10,240 cases per test) and **561 million cases** (61,440 per test) produced **0 mismatches** across five x86 variants for V0 (128 bits), X0, NZCV, memory, and base registers. In addition, **259.8 billion** cases were checked in exhaustive single-instruction tests (section 4).
2. **The float benchmark difference (`recomp-linux.md`, sections 6/8) was not a recompilation error or FMA fusion by the recompiled code:** the result is `NaN` (the loop reaches `inf - inf`); the native x86 reference produces the x86 default NaN **`0xFFF8…` (sign bit set)**, while ARM (and recompiled code and Unicorn) produce the ARM default NaN **`0x7FF8…`**. All finite runs agree (section 6).
3. **Found and fixed or guarded:** (a) recompiled code depended on **host MXCSR** (FTZ/DAZ or rounding other than nearest-even from drivers/audio libraries caused 1,560 or 386 of 9,126 tests to differ); `scripts/recomp/c_exact/fp_env.h` establishes the required state, after which there are 0 mismatches. (b) With `-ffp-contract=fast` and no `FENV_ACCESS` pragma, 45 tests differ (only when rounding mode ≠ RN); the runtime **already refuses to compile** with `-ffast-math`/`fast` (pragma error). (c) On an **arm64 host with `-O2`**, clang 23 generates incorrect code for `sqdmulh v.4h` (vectorizer; correct with `-fno-vectorize`, not seen on x86 or at `-O1`; game uses only `.4s`/scalar).
4. **Not modeled (documented remainder):** FPSR cumulative flags (IOC/DZC/OFC/UFC/IXC/IDC) and QC; game (`main`) never reads them (0 `mrs fpsr`), SDK reads them only in libm `fenv` functions. ARMv8.2 FP16 arithmetic and related instructions (1,632 instruction forms) are missing from lifter; none occur in game.
5. **Recommendation for Linux/Windows:** `clang -O1 -march=x86-64-v3 -ffp-contract=off -fno-fast-math` (not gcc/MSVC, no x87), call `rt_fp_guest_mode()` at each guest thread start and after foreign calls; run the differential test as a regression test for every compiler version (section 8).

## 1. Which FP/SIMD instructions does the game execute? (measured)

`scripts/recomp/diff/hist.py` disassembles every 32-bit word in the text segments of `main`, `sdk`, `subsdk0`, and `rtld` (local, `work/exefs`) using Capstone 5.0.7: **14,105,420 words** (`main` 11,786,892, `sdk` 1,455,692, `subsdk0` 861,276, `rtld` 1,560), of which 849 do not disassemble (data in text).

| Class | Words | Share | Instruction forms |
|---|---:|---:|---:|
| FP/SIMD data processing (bits 27:25 = 111) | 583,894 (`main` 557,608, `sdk` 20,359, `subsdk0` 5,927) | 4.14% | 576 |
| FP/SIMD loads/stores (`ldr q`, `ldp`, `ld1` …) | 302,393 | 2.14% | 254 |
| total | 886,287 | 6.28% | 830 |

Most common FP/SIMD instructions (data processing; “form” = mnemonic + register width/layout, excluding register numbers and constants):

| Instruction | Words | Share of data processing (cumulative) |
|---|---:|---:|
| `fmul` | 133,331 | 22.8% |
| `mov` (alias `orr`/`ins`) | 83,570 | 37.1% |
| `fadd` | 74,814 | 50.0% |
| `fmov` | 42,991 | 57.3% |
| `fsub` | 39,224 | 64.0% |
| `dup` | 27,769 | 68.8% |
| `fcmp` | 27,080 | 73.4% |
| `ext` 14,903, `movi` 9,027, `fdiv` 8,476, `fcsel` 8,232, `faddp` 7,806, `and` 7,567, `scvtf` 7,543 | | 84.3% |

The first 50 mnemonics cover 98.0% of data processing, including `eor`, `fneg` 5,129, `bsl`, `frecps` 4,343, `fcvtzs` 3,931, `fcmgt`, `ucvtf` 3,680, `fmin`, `frsqrts` 2,749, `fcvt` 2,700, `fmax`, `fabs`, `fsqrt` 1,733, `fmadd` 1,614, `fcvtzu` 1,565, `frsqrte` 1,328, `frecpe` 1,248.

Other families: **fused multiply-add** totals just 3,009 words (`fmadd` 1,614, `fmla` 934, `fmsub` 187, `fnmsub` 238, `fmls` 34, `fnmadd` 2; 0.02% of all words); conversions `fcvt{n,m,p,a,z}{s,u}` ≈5,800, `frint*` ≈670 (`frintm` 447, `frintp` 158, `frintz` 35, `frinta` 16, `frintx` 9, `frinti` 2); saturating/rounding NEON integer instructions ≈450 (`sqadd` 148, `sqrshrn` 141, `sqdmulh` 39, `uqadd` 21 …); crypto/CRC: `aese/aesd/aesmc/aesimc` 532, `sha1*/sha256*` 464, `pmull` 42, `crc32*` 18 (all in SDK).

**FPCR/FPSR in game code (measured):** `main`, `rtld`, `subsdk0`: **no** `mrs/msr fpcr/fpsr` at all. SDK: 5× `mrs fpcr`, 6× `mrs fpsr`, 3× `msr fpcr`, 4× `msr fpsr`; sites are libm `fenv` functions (`fegetround`/`fesetround`: read/set FPCR bits 22..23; `fetestexcept`/`feclearexcept`/`feraiseexcept`: FPSR bits 0..4; `fegetenv`/`fesetenv`: both; default environment = 0) and context save (`mrs x0, fpcr; mrs x1, fpsr`). **Thus the guest runs with default FPCR state 0** (round to nearest-even, FZ = 0, DN = 0) unless it calls `fesetround`. Default under Unicorn (`UC_CPU_ARM64_A57`) and Linux is also 0; as far as our sources show, Horizon does not set other bits for application threads (**not tested** on real hardware). Tests nevertheless cover 60% of cases using the other 15 combinations of RMode (RN/RP/RM/RZ) × FZ × DN so rare paths are covered too.

## 2. Test setup (`scripts/recomp/diff/`)

**Inputs** (`cases.c`, splitmix64, fixed seed per test, identical on Mac and Linux machine; no game bytes): per register by type (F16/F32/F64, I8..I64, bits)—22% special values (±0, ±Inf, qNaN/sNaN with payloads, largest/smallest denormal, smallest/largest normal, 2^24, 2^31, 2^63, 2^64 …), 18% random bits, 22% medium exponents, 10% neighbors (±3 ulp) of special values, 10% small exact values (rounding boundaries), 9% denormals/smallest normal, 5% near overflow, 4% exponents around 1; operands have a 14% chance to equal/be negated/be ±1 ulp from the previous operand (cancellation, equality), and in 8% of FMA cases `c = -(a*b)`. FPCR as above, random NZCV, GPR sources from integer/float special values.

**References** (`tmpl.S`, one loop, identical machine-code bytes everywhere):

- **Unicorn 2.1.4, Cortex-A57 model** (Switch core), one `emu_start` per test over all cases.
- **Native Apple M1 Pro** (`native.c`: JIT page, `MAP_JIT`; real instructions, constructed to be bit-exact with lifter `asm` mode).
- Result: **M1 and Unicorn-A57 agree exactly on all 9,134 tests × 10,240 cases, including FPSR** (0 mismatches). This validates Unicorn as the reference on the Linux machine (full comparison with M1 replaces spot checks against real ARM semantics). No differences between M1 and Cortex-A57 in NaN handling, FPCR behavior, rounding, or FPSR appeared (**only** details such as IDC under FZ could differ, but those cases did not occur).

**Test target:** lifter output in `c` mode (`Lifter(base, 'c').lift(...)`, then `simd_c.py`/`simd.h`/`simd_fp.h`), one guest function `void t_<id>(Cpu *)` per test (1–4 instructions), run in `ctest.c` with a fresh `Cpu` per case (V8..V31 = 0, as in reference). Memory instructions use a 192-byte buffer (guest address = host address).

**Test list** (`mktests.py`): Capstone iterates the full FP/SIMD encoding space (bits 27:25 = 111, plus loads/stores with V = 1), selecting 3–6 representatives per form (more for 576 game forms with constants/lane indices) → **9,134 tests: 6,016 data processing, 2,270 memory, 800 random chains (2–4 dependent FP instructions), 48 special cases** (FMUL+FADD/FSUB sequences for fusion checks, `fcmp #0.0`, `fccmpe`, `xzr` forms, CRC32). 306 distinct mnemonics. **Game coverage:** grid found 566 of 576 data-processing forms; the remaining 10 (`fcmp #0.0`, `xzr` sources) were added as special cases. Of 254 memory forms, 174 are covered and 80 missing (forms with `sp` base and register offset `[xN, xN]`; integer-side address calculation, **not tested**).

- **Unsupported in c mode:** 1,632 instruction forms (ARMv8.1+ `sqrdmlah`, dot product, `fcmla`, FP16 arithmetic, `fmlal`, `frint32/64`, …); **zero game occurrences**.

**Compiler variants (Linux machine, clang 22.1.8):** `-O1 -march=x86-64-v3` with default contraction (clang: `-ffp-contract=on`) and `-ffp-contract=off`; same at `-O2); also `-O1` for baseline x86-64 (no FMA hardware; `fma` via libm) with `off`. On Mac (arm64, clang 23): `-O1 -ffp-contract=off`, `-O2`.

## 3. Main run results (measured)

| Source (against reference) | Tests | Cases | Mismatches |
|---|---:|---:|---:|
| Unicorn-A57 against native M1 | 9,134 | 93,532,160 | **0** (including FPSR) |
| c, `-O1 -march=x86-64-v3`, contraction `on` (default) | 9,134 | 93,532,160 | **0** |
| c, `-O1 -march=x86-64-v3 -ffp-contract=off` | 9,134 | 93,532,160 | **0** |
| c, `-O2 -march=x86-64-v3 -ffp-contract=off` | 9,134 | 93,532,160 | **0** |
| c, `-O2 -march=x86-64-v3` (default) | 9,134 | 93,532,160 | **0** |
| c, `-O1 -ffp-contract=off` (baseline x86-64, no FMA) | 9,134 | 93,532,160 | **0** |
| c, `-O1 -march=x86-64-v3 -ffp-contract=off`, 61,440 cases/test | 9,126 | 560,701,440 | **0** |
| c, `-O2 -march=x86-64-v3` (default), 61,440 cases/test | 9,126 | 560,701,440 | **0** |
| c on arm64 host, `-O1 -ffp-contract=off`, against M1 | 9,134 | 93,532,160 | **0** |
| c on arm64 host, `-O2` (default), against M1 | 9,134 | 93,532,160 | **25,706** (only `sqdmulh v.4h`, section 6.1) |

FPSR: c mode always returns 0; reference sets cumulative flags in 18,725,436 cases (mostly IXC, bit 4). These cases are **not counted as mismatches** (section 9). Per-family excerpt; “occurrences” = FP/SIMD words in game, “cases” = test cases per variant; **all have 0 mismatches**:

| Instruction | Occurrences | Tests | Cases |
|---|---:|---:|---:|
| `fmul` | 133,331 | 108 | 1,105,920 |
| `ldr` (SIMD) | 114,925 | 77 | 788,480 |
| `mov` (SIMD) | 83,570 | 540 | 5,529,600 |
| `fadd` | 74,814 | 15 | 153,600 |
| `str` / `ldp` / `stp` (SIMD) | 74,038 / 43,217 / 33,185 | 71 / 66 / 66 | 727,040 / 675,840 / 675,840 |
| `fmov` | 42,991 | 38 | 389,120 |
| `fsub` / `fdiv` | 39,224 / 8,476 | 15 / 15 | 153,600 / 153,600 |
| `dup` | 27,769 | 78 | 798,720 |
| `fcmp` / `fcsel` | 27,080 / 8,232 | 6 / 96 | 61,440 / 983,040 |
| `ext` / `movi` / `faddp` | 14,903 / 9,027 / 7,806 | 12 / 84 / 11 | 122,880 / 860,160 / 112,640 |
| `scvtf` / `ucvtf` | 7,543 / 3,680 | 36 / 36 | 368,640 / 368,640 |
| `frecps` / `frsqrts` | 4,343 / 2,749 | 15 / 15 | 153,600 / 153,600 |
| `fcvtzs` / `fcvt` / `fmin` / `fmax` / `fabs` / `fsqrt` | 3,931 / 2,700 / 3,629 / 2,696 / 2,542 / 1,733 | 54 / 6 / 15 / 15 / 5 / 5 | 552,960 / 61,440 / 153,600 / 153,600 / 51,200 / 51,200 |
| `fmadd` / `fmla` / `frecpe` / `frsqrte` | 1,614 / 934 / 1,248 / 1,328 | in family and chain tests | — |
| Remaining 258 instructions/groups (including AES, SHA, PMULL, CRC32, conversions, saturating ops) | 34,225 | 7,089 | 72,591,360 |

The full table is produced by `report.py <report.json>`.

## 4. Exhaustive single-instruction test (measured)

`exh.c` (instruction list generated by `exh_gen.py`, run by `exh_run.sh`, compared by `exh_cmp.py`): 44 single instructions (`fsqrt`, `frecpe`, `frsqrte`, `frecpx`, `fcvt{zs,zu,ns,as,ps,mu}` to 32/64 bits, fixed-point-style `#8`, `fcvt` S↔D↔H, `frint{n,a,x,i,z,m,p}`, `fabs`, `fneg`, `scvtf`/`ucvtf` from 32/64 bits with and without fixed point, S and D forms) are run over **all 2^32 inputs** (complete 32-bit formats; for 64-bit formats, upper 32 bits exhaustive and lower bits from a mixer) and reduced to a hash: **native on M1** (inline assembly, real instructions, reference) versus **generated C** on the Linux machine (`-O1 -march=x86-64-v3 -ffp-contract=off`). FPCR = 0 exhaustively (4.29 billion inputs each), plus RP, RM, RZ, FZ, DN, and FZ+DN+RZ with every 16th value. **Result: 308 runs (44 instructions × 7 FPCR values), 259,845,521,408 cases, 0 differing runs.** (An initial run showed 13 mismatches for float-to-integer instructions; this was a test harness issue, not the recompiled code: inline-asm left D0 uninitialized while C had V0 = 0. Adding `fmov d0, xzr` before the instruction yielded 0 mismatches.) Runtime: M1 about 12 s per instruction and 4.29 billion cases; Linux machine with generated C (4 processes) about 13 minutes total.

## 5. Perturbation tests and negative controls (measured)

### 5.1 The test detects errors

Negative control (Linux machine): runtime **without** `#pragma STDC FENV_ACCESS ON` (copy under `work/`, original untouched) and `-ffp-contract=fast`: **45/9,134 tests differ** (51,901 cases), all **only when FPCR rounding mode ≠ RN** and only in `fnmul` (6), `ucvtf` (12), and random chains containing `fnmul` (27). With RN/FZ/DN alone: 0. Compiler likely folds `-(a*b)` or integer conversion in slow path without respecting current rounding mode (cause not investigated further). With unchanged original (pragma present), `-ffp-contract=fast` and `-ffast-math` **cannot compile at all** (`'#pragma STDC FENV_ACCESS ON' is illegal when precise is disabled`): built-in guard. **No x86 fusion effect in fast path:** `fmul`+`fadd` sequences and similar are not fused even with `fast`, because each operation checks its result for NaN (`FBAD`) and stores intermediate result in `Cpu`.

### 5.2 Host MXCSR (finding 1)

In fast path (FPCR = 0), recompiled code uses host FPU and assumes “round to nearest-even, denormals enabled” (documented in `simd.h`). If foreign code changes MXCSR in the same thread (common with audio/driver/graphics libraries; new threads inherit it), results differ:

| Host MXCSR during run | Tests differing (of 9,126) | Cases |
|---|---:|---:|
| `0x1F80` (default) | 0 | 0 |
| `0x9FC0` (FTZ + DAZ) | **1,560** | 737,630 |
| `0x7F80` (round toward zero) | **386** | 79,119 |

**Fix:** `scripts/recomp/c_exact/fp_env.h` (`rt_fp_guest_mode()`: set MXCSR to `0x1F80`, or FPCR to 0 on arm64 hosts), built into `ctest.c` with `-DCEXACT_GUARD`: with guard, **0 mismatches under both injected states**. **Runtime integration point** (not changed by me; `rt-bdsp` belongs to another agent): at every guest-thread start and after every foreign call (HLE services, Vulkan/audio callbacks); call costs one `stmxcsr` and a comparison.

## 6. Float benchmark (`recomp-linux.md`, sections 6/8): cause and resolution (measured)

`bench_fp.sh` builds the loop from `scripts/recomp/test/bench_guest.c` (`b = b*a + v*0.25; buf[...] = b - v`) in four variants (guest code and native reference, with default or `-ffp-contract=off`), generates C in c mode, and runs generated C (`REC`), native x86 (`NAT`), and **the same aarch64 bytes under Unicorn** (`UNI`, real ARM semantics). Results (D0 bits, buffer hash):

| Run | n | `REC` (recompiled) | `UNI` (Unicorn) | `NAT` (native x86) |
|---|---:|---|---|---|
| Default (both fused: guest `fmul`+`fmadd`, x86 `vfmadd`) | 1,000 | `411028b2b7d8b9f1` | `…b9f1` | `…b9f1` (**same**) |
| Default | 20,000 | `57432c81da143979` | same | same |
| Default | ≥200,000 | `7ff8000000000000` | `7ff8…` | **`fff8000000000000`** |
| All `-ffp-contract=off` | 1,000 | `…b9ee` | `…b9ee` | `…b9ee` (same) |
| All `-ffp-contract=off` | ≥200,000 | `7ff8…` | `7ff8…` | `fff8…` |
| Guest `off`, native default | 1,000 | `…b9ee` | `…b9ee` | `…b9f1` (**different fusion**) |
| Guest default, native `off` | 1,000 | `…b9f1` | `…b9f1` | `…b9ee` |

**Cause:** (1) After 100 million iterations, `b` overflows as `b` and `v` grow together; final expression is `inf - inf` → NaN. ARM produces default NaN **`0x7FF8000000000000`**, x86 “Real Indefinite” **`0xFFF8000000000000`**. Recompiled code (FPCR.DN path, `DNAN`) and Unicorn produce ARM value; native reference produces x86 value, hence “different.” Buffer hash is identical in every run. (2) The FMA-fusion hypothesis in `recomp-linux.md` was **not** the cause of the reported difference; however, fusion would cause differences for finite results **if native reference fused differently from guest compiler** (last two rows). Recompiled code never differs from Unicorn.

**Resolution:** no recompiled-code fix needed; use Unicorn/M1 as comparison reference, not native x86 compilation of the same source. The statement in `recomp-linux.md` was updated accordingly.

### 6.1 Compiler finding on arm64 (finding 3)

c mode on arm64 host with clang 23 and `-O2`: `sqdmulh v0.4h, …` (3 tests, 25,706 cases, always RN/no special values) produces incorrect lanes; `-O2 -ffp-contract=off` does not help, but **`-O2 -fno-vectorize -fno-slp-vectorize` fixes it** → vectorizer (lane function uses `__int128`). On x86 (clang 22, -O1/-O2) and arm64 at `-O1`: 0 mismatches. Game uses `sqdmulh` only as `.4s`/scalar (39 words), with 0 mismatches there. Therefore test each compiler version in build pipeline.

## 7. Cost of exact variants (measured, x86-64 CPU with 6 cores/12 threads, ns per generated guest function)

`perf_c.py` (`bench_c` in `ctest.c`, 5 million calls, best of 3; machine also loaded by `ap-recomp-vulkan`; function-pointer call included). FPCR = 0 (fast path) versus FZ/RZ (slow path):

| Instruction | `-O1 v3 off` RN | `-O1 v3` default RN | `-O2 v3 off` RN | `-O1` no FMA RN | FZ / RZ (`-O1 v3 off`) |
|---|---:|---:|---:|---:|---:|
| `fmul s` | 1.22 | 1.22 | 1.26 | 1.23 | 21.3 / 21.2 |
| `fadd s` | 1.34 | 1.91 | 1.75 | 1.92 | 21.5 / 21.4 |
| `fdiv s` | 1.91 | 1.92 | 1.75 | 1.92 | 21.3 / 21.1 |
| `fmul v.4s` | 1.91 | 1.92 | 1.74 | 1.91 | 89.3 / 88.9 |
| `fmla v.4s` | 2.58 | 2.62 | 2.55 | **8.44** | 91.2 / 91.3 |
| `fsqrt s` | 1.92 | 1.92 | 1.55 | 1.94 | 21.3 / 21.1 |
| `frecpe s` | 2.68 | 2.71 | 2.32 | 2.73 | 3.1 / 2.7 |
| `frecps s` | 1.91 | 1.94 | 1.94 | 3.11 | 21.7 / 21.5 |
| `fcvtzs w,s` | 1.92 | 1.96 | 1.73 | 2.88 | 2.1 / 1.9 |
| `scvtf s,w` | 1.92 | 1.96 | 1.73 | 1.72 | 1.8 / 20.8 |
| `faddp v.4s` | 1.92 | 1.95 | 1.76 | 1.93 | 90.6 / 91.4 |
| `mov v.16b` | 1.72 | 1.74 | 1.54 | 1.75 | 1.7 / 1.7 |
| `fmul`+`fadd` s (sequence) | 2.11 | 2.11 | 1.94 | 2.13 | 43.4 / 42.8 |
| `fmul`+`fadd` v.4s (sequence) | 1.92 | 1.92 | 1.94 | 2.13 | 179 / 179 |

**Derived conclusions:** (1) **`-ffp-contract=off` costs nothing** (differences are noise). (2) `-O2` brings no benefit over `-O1`. (3) Fast-path FP/SIMD instruction costs 1–3 ns (≈5–13 cycles). (4) **FPCR ≠ 0 (FZ, RP/RM/RZ) is 17× slower (scalar) to 47× slower (4 lanes)**; game does not use this unless it calls `fesetround`. (5) **Without FMA hardware (baseline `x86-64`), `fmla` is 3.3× slower** (correct software `fma`, but expensive)—x86-64-v3 (Haswell/Zen or newer) is required.

## 8. Recommendation for Linux/Windows x86-64 builds

**Compiler flags for generated C:** `clang -O1 -march=x86-64-v3 -ffp-contract=off -fno-fast-math -fno-strict-aliasing -fvisibility=hidden` (`-O2` equivalent; no `-Ofast`, `-ffast-math`, or `-ffp-contract=fast`; **clang only**—gcc lacks `__builtin_elementwise_*`, as does MSVC `cl`; Windows: clang-cl or MinGW clang, **not tested on Windows**). No x87 (x86-64 uses SSE; 32-bit hosts unsupported).

**Runtime:** call `rt_fp_guest_mode()` (`scripts/recomp/c_exact/fp_env.h`) at each guest-thread start and after calls into foreign code; guest FPCR remains in `Cpu` as before. Use `-march=x86-64-v3` (FMA!) rather than baseline profile.

**Regression test:** `scripts/recomp/diff/run_linux.sh base` (70 s for 93 million cases × 5 variants on 4 cores) after every lifter, `simd*.h`, or compiler-version change; expect 0 mismatches. Use `mktests.py --ncases 61440` for larger run (6 minutes). Use M1 as second reference with `difftest.py --src m1,uc,c:...`.

## 9. Limits and remaining gaps

- **FPSR cumulative flags (IOC, DZC, OFC, UFC, IXC, IDC) and QC are not set in c mode** (documented in `simd.h`). In game they are readable only via SDK libm `fenv` functions (`fetestexcept` …): `main`, `subsdk0`, `rtld` never read FPSR. Risk is calls from `main` into SDK `fetestexcept`/`feclearexcept` (not counted). Implementing them is medium effort (flag logic per operation in fast path, making it less “cheap”) and not recommended unless a game path reads them.
- **FPCR trap bits (IOE …), FP16 arithmetic, ARMv8.1+ instructions** are not modeled; Switch A57 core does not support them, and there are no game occurrences.
- **Not tested:** `sp`-relative and register-offset memory instructions (integer-side address calculation); exhaustive two-operand instructions (random + edge cases only, 10,240–61,440 cases per test); Windows/MSVC/clang-cl; gcc; real Switch hardware (reference is Unicorn-A57 and M1, which agree with each other); actual starting FPCR on Horizon threads (assumed 0 based on libm default environment and Linux).
- M1/Cortex-A57 differences in NaN/FPCR/FPSR behavior did **not** occur in tests; differences may exist only in unmeasured FPSR details.
- **Native x86 calculations are not a reference** (NaN sign `0xFFF8…`, different fusion); use only Unicorn/M1.

## 10. Implications for recompilation strategy

1. **Linux/Windows x86-64 (Vulkan) with c mode is feasible without float discrepancies in game arithmetic** (damage, RNG, animation, physics): 0 mismatches for every measured instruction across all flag variants, plus 259.8 billion exhaustive and 560 million random cases per variant. The concern from `recomp-linux.md` (“cannot bit-compare with true arm64 semantics”) is resolved: comparison uses Unicorn (A57) and M1, not native x86 compilation.
2. **Keep asm mode as default for macOS/iPadOS (bit-exact by construction, fastest);** c mode is an equally correct portable variant. Pipeline can compare them (`difftest.py --src m1,uc,c:...`).
3. **Cost of exactness is small:** 1–3 ns per instruction on fast path; only FPCR ≠ 0 is expensive (never seen in game). Additional safeguards are needed for host FPU state (`fp_env.h`), compiler flags, and compiler version (finding 3: test each version).
4. **Runtime risk list:** FPSR flags (above), host threads/drivers that change MXCSR, host math's default NaN (e.g. HLE functions computing `sinf` or similar on host may return x86 NaN sign; NaNs computed in guest are ARM-compatible)—use HLE math only where guest libm result is not required.

## 11. Files and reproduction

| File | Purpose |
|---|---|
| `scripts/recomp/diff/hist.py` | Histogram (mnemonics, forms, FPCR/FPSR accesses) over NSO text |
| `scripts/recomp/diff/mktests.py` | Test list (`tests.json`) and generated C (`lifted.c`) |
| `scripts/recomp/diff/cases.c`, `difftest.h`, `tmpl.S`, `native.c`, `ctest.c`, `common.py` | Inputs, reference loop, M1 run, C harness |
| `scripts/recomp/diff/difftest.py`, `report.py` | Driver (Unicorn/M1/C comparisons), report |
| `scripts/recomp/diff/build_c.sh`, `run_linux.sh` | Build libraries; Linux machine variant runs (`base`, `neg`) |
| `scripts/recomp/diff/exh.c`, `exh_gen.py`, `exh_run.sh`, `exh_cmp.py` | Exhaustive single-instruction test |
| `scripts/recomp/diff/bench_fp.c`, `bench_fp.sh`, `bench_fp_uc.py` | Float benchmark proof |
| `scripts/recomp/diff/perf_c.py` | Cost measurement |
| `scripts/recomp/c_exact/fp_env.h`, `NOTICE` | Host FPU guard, license notice |

```bash
python3 scripts/recomp/diff/hist.py                       # Mac, 3 min
python3 scripts/recomp/diff/mktests.py                    # Mac, 40 s
bash scripts/recomp/diff/build_c.sh base && bash scripts/recomp/diff/build_c.sh c mac_o1 -O1 -ffp-contract=off
python3 scripts/recomp/diff/difftest.py --src m1,uc,c:mac_o1=work/recomp/diff/lib_mac_o1.so --jobs 2 --out work/recomp/diff/rep_mac.json
bash scripts/recomp/diff/exh_run.sh m1                                        # Mac, native reference
# Linux machine (repo root; needs work/recomp/diff/tests.json and lifted.c from mktests.py in the working copy):
bash scripts/recomp/diff/run_linux.sh base                                    # variants; `neg`: negative control
bash scripts/recomp/diff/exh_run.sh c "-O1 -march=x86-64-v3 -ffp-contract=off" 4
```
