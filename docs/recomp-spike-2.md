# Recompilation Spike Phase 2 (`ap-recomp-spike-2`): Countercheck of the question “static recompilation as the primary path?”

Status: 2026-10-19 (final spike results; the interim report after Step 1 remains unchanged at the beginning). Basis: `docs/recomp-machbarkeit.md` (Phase 1), `docs/architektur-entscheidung.md` (Decision 2, reversible), `docs/referenz-las-shader.md`, `docs/ipad-messung-1.md`.
**Scope:** measurements and smallest prototypes only, with abort criteria. Not legal advice. **Nothing was copied** from `research/LASRecomp` (MIT, explicitly authorized by the user): the scripts under `scripts/recomp/` import the clone's lifter and generator at runtime (like `scripts/recomp_survey.py`) and extend them. No game bytes, generated code, or game addresses are in the repo; everything generated is under `work/recomp/` (gitignored).

**Labels:** **measured** = determined from the local dump with the scripts under `scripts/recomp/`. **documented** = read in the clone or a cited source. *inferred* = conclusion without a test. **not verified** = could not be checked.

## Interim results after Step 1 (exception test, disqualifying criterion)

**Result: passed. C++ exceptions are feasible in the LAS model (variant a), using the game's unmodified guest unwinder.** The disqualifying criterion in `docs/recomp-machbarkeit.md` (Section 5, “C++ exceptions”) is no longer a blocker. Production-readiness effort: **roughly 1 to 2 weeks** (Section 1.6); no longer a research question.

| Question | Result | Status |
|---|---|---|
| Does the SDK's actual unwinder (`_Unwind_RaiseException`, `unw_*`, `__gxx_personality_v0`, `__cxa_*`) run unchanged after recompilation? | **Yes.** It runs as generated C on the guest stack, reads guest frames through `.eh_frame`/`.eh_frame_hdr`, and calls the personality routine as recompiled guest code. | measured (tests T1 through T5) |
| Throw → catch across ≥ 2 recompiled frames with correct state | **Yes:** 3 guest frames in between (cleanup in 2 frames, catch in the 4th); callee-saved registers and destructor order are correct; rethrow (`catch (...)` + `throw;`) works; **200 frames** with landing pads work; throwing from **real SDK code** (`operator new` → `std::bad_alloc`) works. A countercheck under Unicorn (real ARM64 semantics) produces the same values. | measured |
| Additional mechanism required | Frame record + `_setjmp` for each guest function with a reentry point, reentry in the `rt_dispatch` failure path, and `ret` after `mov sp` as an indirect branch (3 places in the SDK: libunwind `jumpto`, `longjmp`). About 350 lines of Python (generator extension) and 30 lines of C (runtime) in total. | measured |
| Found and fixed | The standard generator splits functions at `adr` jump-table bases (610 places in the SDK); as a result, libunwind switch tables were not resolved and the unwinder crashed. After the fix, 515 tables resolve instead of 41. **Affects every function with a compact jump table, not just exceptions.** | measured |
| Cost | 44.8 µs per throw+catch across 4 frames (`-O1`, one thread, dispatch without cache) = about 22,000 throws/s; frame records only in the 3,447 functions with a reentry point (out of 270,299 generated functions). | measured |
| Evidence from real BDSP functions | Selected 180 real LSDA functions from `main` (60 each: cleanup only / typed catch / `catch (...)`; an initial run with 45 showed the same result): in **100** cases, execution reached a call with a landing pad, and in **all 100** the real guest unwinder selected exactly the landing pad predicted by an independent LSDA parser; cleanup code and `_Unwind_Resume` ran, and the exception reached the handler above (in 6 `catch (...)` functions, the function itself caught it). The other 80 failed because of the synthetic environment (25 reached no covered call; 55 crashed on null-pointer data or entered an infinite loop), not because of the unwinder; 0 mismatches. | measured (Section 1.5) |
| Verdict | **Feasible**, about 1 to 2 weeks of production work (Section 1.6). | |

### Interim results for the remaining steps (details in Sections 2 to 6)

| Step | Result | Verdict |
|---|---|---|
| 2 Stop-the-world GC / threads | `thread_suspend` + `thread_get_state` on own threads: 8 µs per thread with 1 to 4 threads (16 to 64 threads on a busy machine: 0.07 to 0.09 ms per thread). Boehm itself uses exactly these calls on Apple platforms. In recompiled guest code, asynchronous suspension found the object in `Cpu` memory alone in 19,293 of 19,293 critical windows (every guest memory access and call forces a writeback); Mach registers remain an additional safeguard. Alternative cooperative safepoints: up to 12% in the worst case, probably 1 to 4% in practice. | feasible, 2 to 4 days |
| 3 Memory model | `--rebase32` as a header switch (about 90 lines): the complete exception test with the real SDK runs with **all guest addresses below 4 GiB** and unchanged `g_base + (uint32_t)ea` access, passing (47.0 instead of 44.8 µs per throw). No pointer tags or 39-bit assumptions found in `main` code (only 4 masks with 48 bits, 1 with 40 bits; 0 suspicious tag instructions in 11.8 million words). | viable; about 1.5 to 3 weeks (instead of 3 to 6) |
| 4 Partial build | All four modules generated: 270,299 functions, 992 MB of C in 74 s; compiled in **15.6 minutes wall time** (3 parallel compilers, busy machine; 45 min total CPU time); library **224 MiB** (`__text` 210 MB); peak compiler memory 1.7 GB (not 3.3 GB); slowest file 214 s. | viable |
| 5 Smallest runnable piece | Load recompiled `main`+`sdk`+`subsdk0` (RSS 101 MiB), run `nn::init::Start`: `nnosInitialize` and all 115 SDK constructors complete, then **first hard blocker: IPC** (`sm:`, `lm`, CMIF Domain, then `apm`, `appletOE`, `aoc:u`, `ectx:aw`, `pctl*`). Up to that point: 8 distinct SVCs, 29 calls, 0 threads, 105 MiB RSS. | no CPU/exception/memory blocker; blocker = expected service layer |

**Additional performance result (Section 4a):** microbenchmarks of the same C code, recompiled versus native on the Mac: **factor of 1.4 to 4.3** (integer about 2, calls/FP 3 to 4).

**Provisional recommendation (Section 6):** hybrid. R moves from “deferred” to “parallel primary candidate with a decision point” (Phase 3, 4 to 6 weeks on the Mac); D continues unchanged, but no new large reconstruction blocks start before the decision point.

---

## 1. Exception test (disqualifying criterion)

### 1.1 Findings: what the game contains (measured, `scripts/recomp/eh_lsda.py survey|cfa`)

| | main | sdk | subsdk0 | rtld |
|---|---:|---:|---:|---:|
| FDEs (`.eh_frame`) | 216,168 | 29,434 | 9,844 | 26 |
| FDEs with LSDA (landing pads) | **2,917** | 508 | 0 | 0 |
| Call sites in LSDA tables | 26,631 | 2,802 | | |
| Landing pads (distinct addresses) | 14,887 | 1,601 | | |
| Landing pads per function (median / maximum) | 3 / 162 | 2 / 32 | | |
| Call sites without a handler / cleanup only | 9,257 / 3,866 | 937 / 1,087 | | |
| Action chains: typed catch / `catch (...)` / cleanup in chain | 11,851 / 1,658 / 11,844 | 0 / 761 / 0 | | |
| `setjmp` return points (reentry after `longjmp`) | 17 | 10 | 0 | 0 |

- **CFA instructions:** no module contains `DW_CFA_remember_state`/`restore_state`, expression instructions (`def_cfa_expression`, `expression`, `val_expression`), PAC instructions, or unknown opcodes. The Nintendo toolchain emits plain synchronous unwind tables. The SDK libunwind **rejects `remember_state`** (found during testing: an FDE with opcode `0x0a` causes FDE evaluation to fail). This affects only our test programs built with newer Clang (compiled with `-fno-asynchronous-unwind-tables`), not the game.
- Functions with landing pads average 720 bytes (180 instructions), for a total of 2.1 MB of code across the 2,917 functions in `main`.
- The personality routine is `__gxx_personality_v0` everywhere. The SDK libunwind is LLVM libunwind (`unw_*`, `_Unwind_RaiseException` using `unw_getcontext`, `unw_init_local`, `unw_step`). Reentry happens in `__libunwind_Registers_arm64_jumpto`: it loads all registers from the context, sets `sp`, and jumps with `ret` (x30 = landing pad) into the middle of a guest function.

### 1.2 Why the LAS model breaks (documented, lifter/generator inspected)

1. A guest `RET` becomes a host `return`; therefore, `ret` after `mov sp, xN` (`jumpto`) would return to the **host caller**, not to the landing pad. Likewise for `longjmp` (`br x30`).
2. `rt_dispatch` knows only function starts; a landing pad is in the middle of a function → “no function at …”.
3. The host stack still contains the frames of guest functions skipped between the throw site and the handler; those frames must be removed.

### 1.3 Design of the three variants

| Variant | Idea | Assessment |
|---|---|---|
| **(a) Unmodified guest unwinder + reentry through frame records (selected, prototyped)** | Each guest function with a reentry point (landing pad from the LSDA, or the instruction after `bl setjmp`) pushes an `EhRec {prev, lo, hi, sp, jmp_buf}` onto the host stack on entry, links it to `Cpu` (offset 336, previously unused padding), and calls `_setjmp`. Each exit (return, tail call, dispatch) unlinks it. The real unwinder (recompiled) operates on the **real guest frames**: guest stack frames are faithful because the recompiled prologues write `stp x29,x30` to the guest stack and the guest LR is set before every call. At the end, `jumpto` calls `rt_dispatch` with the landing-pad address via `br x30`; a miss there calls `rt_nle_enter`: find the innermost record whose range contains the address and whose entry SP is **above** the target SP (recursive calls to the same function are deeper), then `_longjmp` to it; the function dispatches via `switch (c->pc)` to the label. Guest registers are correct because they live only in `Cpu` and on the guest stack anyway (the unwinder restores x19 through x28, fp, sp from the frames; `_Unwind_SetGR` sets x0/x1). | works (1.4, 1.5); cost applies to only 3,447 of 270,299 functions |
| (b) Custom unwinder over `.eh_frame` with host `longjmp` | Implement `_Unwind_RaiseException`/`_Resume` as host functions (HLE): evaluate CFI directly (sufficient: only `def_cfa`, `offset`, `advance_loc`, `def_cfa_register/offset`, see 1.1); keep the personality routine as guest code. Advantage: faster, no need for SDK module info (`GetExceptionInfo`). Disadvantage: custom DWARF interpreter (about 300 to 400 lines of C), a second source of truth alongside the SDK unwinder. | possible as an optimization/fallback; not needed |
| (c) Error-return convention | Every function returns an exception state, and every call checks it. | **not viable:** 216,168 functions, including frames without LSDA, plus calls through function pointers and HLE; runtime and size costs everywhere |

### 1.4 The prototype (`scripts/recomp/`, all custom code; LAS generator imported only at runtime)

| Component | File | Contents |
|---|---|---|
| LSDA/CFA parser | `eh_lsda.py` | `.eh_frame_hdr`, FDE/CIE, LSDA call sites, action tables, type table; figures from 1.1 |
| Generator extension | `eh_gen.py` | `EhModule(gen.Module)`: reentry points, frame-record operations (`EH_ENTER/EH_POP/EH_SETJMP`), special `ret` cases, fix for jump-table function splitting (see below), partial build (`--only`), full generation (`generate`, a copy of the partition loop from `gen.main` with the fix) |
| Runtime header | `rt/cpu.h` | `EhRec`, macros, `#include_next` of the original `cpu.h` |
| Mini-linker | `mini_link.py` | ELF64 relocatable (aarch64) → NSO + image + `.eh_frame_hdr` (no aarch64 linker on Mac) |
| Image builder | `mkimg.py` | NSO → memory image with relocations, imports → module exports or HLE slots, weak imports → 0, `.mod` file |
| Tests | `test/eh_guest.cpp`, `test/eh_harness.c`, `test/run_eh_test.sh`, `test/uc_ref.py` | synthetic guest program (aarch64-Clang), host runtime, reference run under Unicorn |

**SDK unwinder constraints found** (discovered in testing; product requirements for the loader/runtime):

1. FDE lookup through `nn::ro::detail::GetExceptionInfo(info, pc)`. In the SDK this is implemented using **SVC `QueryMemory`** on the segment image (type 3 or 8 and permission 5 for code, then `MOD0` and `eh_frame_hdr`); replaced with a host function in the test. In the product: `QueryMemory` backed by the modules' segment table (already provided by the probe run in Step 5).
2. `nn::os` mutex for the FDE cache (thread object, arbitration): use a host mutex.
3. `__cxa_get_globals` (TLS through `nn::os`): host block in the test; in the product this runs through the real SDK startup (Step 5).
4. `malloc/free/calloc/aligned_alloc` are SDK imports supplied by the application (`nninitStartup`).
5. EH encodings: the Switch toolchain's libunwind uses `sdata4`; local Clang writes `sdata8` (the test converts it in assembly, `test/eh_sdata4.py`).

**Generator gap found (affects every function with a compact jump table):** `gen.py` treats every `adr` target in text as a function start. With Clang tables of the form `adr xA, T; ldrb w, [tab, idx]; add xA, xA, w, lsl #2; br xA`, `T` is the table base **inside** the function; the function was split, the table could not be resolved, and the branch landed in the middle of another “function.” Fix in `eh_gen.py` (`is_jumptable_base_adr`): 610 places in the SDK; resolved tables **41 → 515**, functions 44,718 → 38,342; `main`: 2,219 places, 2,277 tables resolved, 284 fallbacks to “all instructions are labels.” This is a general bug in the standard generator; without the fix, game code would also run incorrectly.

### 1.5 Measurements (`test/run_eh_test.sh`, `test/run_eh_real.sh`)

| Test | Contents | Result |
|---|---|---|
| T0 | `_Unwind_Backtrace` without a throw | 2 frames with LSDA/function start identified correctly |
| T1 | `leaf` throws `int` → cleanup in `mid` and `mid2` (landing pads) → caught in `test_basic`; check callee-saved values and log order | return 60/60, log 1234/1234 |
| T2 | no throw; frame chain is empty afterward | ok |
| T3 | `catch (...)` with `throw;` (rethrow), then catch by type farther up | ok |
| T4 | 200 frames with landing pads | ok |
| T5 | throw from real SDK code: `operator new(0x7fffffffffff)` → `std::bad_alloc` | ok (one real SDK frame in between) |
| T6 | 20,000 throws, 4 frames each | 44.8 µs per throw+catch (`-O1`) |
| Countercheck | same tests under Unicorn (real ARM64 semantics, same images and HLE semantics) | all passed |
| Real functions (`run_eh_real.sh`, `PER_KIND=60`) | 180 real LSDA functions from `main` (reproducible by seed; partial build uses direct calls as dispatch stubs; default is 45 functions). The first call with a landing pad **throws** an exception (real SDK `__cxa_allocate_exception`/`__cxa_throw`; return address = call site in the function); all imports of the function then go through real SDK code (PLT resolution). An independent parser (`eh_lsda.py`) predicts the landing pad. | **100 of 100** reached cases (cleanup only 40, typed catch 25, `catch (...)` 35): landing pad matches, cleanup runs, `_Unwind_Resume` continues unwinding, handler above receives exception (the `catch (...)` function itself caught it 6 times). 25 did not reach a covered call; 55 crashed/timed out because of the synthetic environment (arguments point to a page buffer filled with self-pointers). **0 mismatches, 0 runtime errors.** (Run with 45 functions: 25 of 25.) |

Limits: The throw test demonstrates landing-pad selection and unwinding in real functions, **not** game behavior (the function state is synthetic). For the 25 reached functions with a typed catch, the thrown type object did not match the catch clause (the exception continued to the wrapper); catching itself is demonstrated by T1/T3 (with test types). The timeouts/crashes for 55 of 180 are due to the environment, not the unwinder.

### 1.6 Verdict and effort

**Feasible.** Remaining production work (estimate, one developer): (1) `QueryMemory`/module segments in loader and a multi-threaded mutex for the FDE cache (1 to 2 days), (2) host HLE functions must not hold locks during unwinding; thread termination/`ExitThread` with open frames (2 days), (3) tests against more real functions and the `longjmp` variant (17 sites in `main`) (2 to 3 days), (4) performance: dispatch cache and `-O1` optimization (1 day). Total **1 to 2 weeks**. Risk: low to medium (no known open problems; Unity code is the larger test: managed exceptions come from IL2CPP through `__cxa_throw` with `Il2CppExceptionWrapper`).

---

## 2. GC / thread suspension

**Finding (documented):** `main` imports `nn::os::SuspendThread`, `ResumeThread`, `GetThreadContext`; a Boehm GC (13 warning strings, `GC_general_register_disappearing_link` in `main`, see Phase 1) suspends all threads and scans their stacks and registers. LAS does not implement SVC `0x32` (`SetThreadActivity`) or `0x33` (`GetThreadContext3`).

**Prototype** (`scripts/recomp/test/gc_suspend.c`, macOS, no entitlement):

| Measurement | Value |
|---|---|
| `thread_suspend` + `thread_get_state(ARM_THREAD_STATE64)` + `thread_resume`, 1 thread | 8.0 µs average |
| 4 threads | 34.5 µs (8.6 µs per thread) |
| 16 threads | 1.45 ms (machine busy with 14 other processes; worst case 25 ms) |
| 64 threads | 4.3 ms (67 µs per thread) |
| Guest value only in host register, **artificial case** (inline asm keeps it there) | in Mach register state 1 of 1, in `Cpu` memory 0: the API returns the register state |
| **Recompiled guest code** (`gc_guest.c` through `eh_gen.py`, `run_gc_proof.sh`): take pointer from slot, clear slot, do 60 arithmetic steps, put it back; 20,000 random suspension points | In critical window (slot empty, pointer only “in register”) 19,293 times: found with **`Cpu` + guest stack alone in 19,293 of 19,293 (100%)**; host registers/stack additionally needed: 0 |
| Cooperative safepoint (poll at function entry), worst case: 5 tiny functions per iteration | +12.1% (23.5 → 26.4 ns); real functions are larger, *inferred* 1 to 4% |

**Analysis:**

- **Why host state is still considered:** Generated C keeps guest registers in `Cpu` memory; LLVM may keep values in host registers inside a function, though, as long as no call or guest memory access occurs in between. The test above shows that this makes **no difference** in the “pointer only in register” pattern: every guest memory access is `may_alias` and forces the compiler to write `Cpu` back first; every call to `f_G(c)` does the same (`c` escapes). What remains are derived values computed in a stretch with no memory access (typically interior pointers that point to the same object); Boehm recognizes interior pointers, and stale `Cpu` values keep the object alive anyway. A case where **no** reference remains in `Cpu`, stack, or heap is not ruled out by the test, but was not produced.
- **Solution A (asynchronous, no runtime overhead, recommended):** `SetThreadActivity(pause)` → `thread_suspend`; `GetThreadContext3` returns the guest context from `Cpu` (x0 through x30, sp, pc, vector registers) and, as a safeguard, also mirrors the 29 host registers and the 512 bytes at the top of the host stack below the reported guest SP (Boehm scans down to that point; guest SP itself remains unchanged). Cost: microseconds per thread. **Remaining risk:** see above; this needs an allocation/GC stress test on the real game, which was not possible here.
- **Solution B (cooperative):** poll at function entry and on backward branches in generated C (`c->gc_pending`); threads in HLE/kernel waits count as safe. Deterministic, but incurs runtime overhead and requires a generator change for 218,195 functions.
- **iOS/iPadOS:** `thread_suspend` and `thread_get_state` on **own** threads are allowed (no entitlement); documented by Boehm source `darwin_stop_world.c` (public, accessed 2026-10-19: `thread_suspend`, `thread_get_state`, `task_threads(mach_task_self())`, ARM branches), which runs exactly this way on iOS (Unity Mono/IL2CPP Boehm on iOS). **Not measured on the iPad** itself.
- **Effort:** 2 to 4 days (SVC `0x32/0x33`, `nn::os::GetThreadContext`, test with two allocation threads), plus 2 to 3 days for stress testing. Verdict: **feasible**.

---

## 3. Memory model (32-bit guest addresses)

**Switch:** `scripts/recomp/rt32/cpu.h` and `rt32/simd.h` (about 90 lines total, `-DREBASE32 -I scripts/recomp/rt32` before `rt`): override `LD8..LD64/ST8..ST64`, `LD128/ST128`, and the exclusive/acquire helpers with `*(T*)(g_base + (uint32_t)ea)`. The generator remains **unchanged**; FP/SIMD must be generated in C mode (`--simd c`) because the inline asm blocks use guest addresses directly as host addresses.

**Test:** same exception test with the **real SDK module** (38,342 functions, `--simd c`) and **all guest addresses below 4 GiB** (SDK `0x1000000`, test module `0x2000000`, stack `0x3000000`, HLE `0x8000000`, heap `0x20000000`; windows via `mmap(NORESERVE)`): T0 through T5 **passed**, T6 47.0 µs per throw (asm mode without rebase: 44.8 µs, so +5%). The host (HLE) translates with `H()`/`GA()` (guest to host address and back); this is 20 lines in the 422-line harness (allocator, TLS, stack, `GetExceptionInfo`) in the test. SDK chunk object size is 35.8 MB instead of 30.3 MB (+18%, mostly C-SIMD instead of inline asm). **`main` in C-SIMD mode** (`--simd c`): 917 chunks, 781 MB C (inline-asm mode: 828 MB); generated C contains **not a single `(uintptr_t)`** outside the macros, so all memory accesses go through `LD*/ST*` and `ldx/stx`; 24 evenly selected `main` chunks (about 1.5 MB C each, 18 s with 3 jobs) compile cleanly with `-DREBASE32`.

**Sample scan for pointer tags and 39-bit assumptions** (`scripts/recomp/ptr_scan.py`, 11,786,892 words in `main`):

| Pattern | main | sdk | subsdk0 |
|---|---:|---:|---:|
| `AND` with mask 2^k−1, k = 39..63 (truncate pointer width) | 118 (106 with k = 62/63: sign/`fabs`; **4 with k = 48, 1 with k = 40**) | 134 | 11 |
| `AND` with 0xFFFFFFFF (truncate to 32 bits) | 4,681 | 9,311 | 120 |
| `ORR` with bit ≥ 40 set | 2,418 (most common: bit patterns `0xAAAA…`, `0xCCCC…`, `0xFFFFFFFF00000000`, floating-point constants) | 423 | 307 |
| `LSR/UBFX` from bit ≥ 40, `LSL` ≥ 40 | 1,605 / 23 | 859 / 36 | 428 / 6 |
| `MOVK/MOVZ/MOVN` with high halfwords | 7,424 | 7,565 | 2,477 |

Result: **no evidence of pointer tags in application code** (the 5 pointer-width masks are few enough to inspect individually); the clusters are bit patterns and floating-point constants. Not proof (data stored as 64-bit pointers with flags in high bits would not appear this way), but a favorable finding. In rebase mode, guest pointers are values below 4 GiB anyway; only stored pointers tagged in their upper 32 bits would be dangerous.

**Memory budget calculation for iPad** (measured limits: 5 GiB without, 8 GiB with Increased Memory Limit; warning thresholds 4.1 / 5.9 GiB; `docs/ipad-messung-1.md`):

| Item | MiB | Status |
|---|---:|---|
| Modules (text, ro, data, bss; image in guest) | 100 | measured (RSS 101 MiB after loading main+sdk+subsdk0) |
| Recompiled code (`__text` 210 MB, 224 MiB library), only touched pages resident (clean, evictable) | 50 to 200 | *inferred* |
| Guest heap (Switch application region; BDSP `SetHeapSize` not measured) | up to 3,328 | upper bound (LAS `HEAP_MAX` 3.25 GiB) |
| Guest stacks and TLS | 20 to 60 | *inferred* |
| Host side: texture copies (Tegra swizzle → Metal), buffers as no-copy wrappers around guest heap (LAS approach) | 300 to 1,000 | *inferred* |
| Metal/UIKit/runtime | 200 | measured (empty Unity scene: 180 MiB) |
| **Total** | **about 3.9 to 5.0 GiB** | |

Without the entitlement (5 GiB, warning at 4.1 GiB), this is **too tight**; with Increased Memory Limit (8 GiB, works with a free team) it **fits with 3 GiB to spare**. The 4-GiB window is reserved, not committed (`NORESERVE`); the iOS address-space limit (7.4 GiB usable according to Phase 1, **not verified on current iPadOS**) leaves 3.4 GiB for everything else; host thread stacks must be well below LAS's 256 MiB (guest stack 1 MiB; host stack should suffice at about 1 to 2 MiB: one host frame per guest call, about 50 to 200 bytes).

**Effort (estimate, revised from 3 to 6 weeks in Phase 1):** header switch is done; remaining: convert HLE/kernel/services to `H()`/`GA()` (Phase 1: about 456 `(uintptr_t)` conversions in HLE/services/NVN), `DC ZVA` (5 places in SDK, use `memset`), SIMD asm with rebase (289,000 accesses in `main`: either set base register to host address before instruction and convert back afterward, or accept C-SIMD), test with running game. **1.5 to 3 weeks.** Verdict: **viable.**

---

## 4. Partial build: generate and compile all four modules

**Generation** (`scripts/recomp/gen_all.sh`; output in `work/recomp/gen4`, gitignored; Python generator, single core):

| Module | Functions | Chunks | C size | Time | Generator peak RAM |
|---|---:|---:|---:|---:|---:|
| main | 218,195 | 1,046 | 828 MB | 62 s | 4.8 GB |
| sdk | 38,342 | 189 | 103 MB | 7.7 s | 0.7 GB |
| subsdk0 | 13,719 | 160 | 61 MB | 4.2 s | 0.4 GB |
| rtld | 43 | 1 | 0.1 MB | 0.2 s | |
| **Total** | **270,299** | **1,396** | **992 MB** | **74 s** | |

`main` has 2,929 functions with frame records, 14,887 landing-pad labels, 17 `setjmp` return points; 58 instructions are emitted as `rt_udf` (unsupported exclusive pairs).

**Compilation** (`scripts/recomp/build_all.sh 3`; `clang -O1 -fno-strict-aliasing -fvisibility=hidden`; individual functions over 1 MB C use `-O0`; 3 parallel compilers, machine was busy with other processes, load 8 to 14):

| Measurement | Result |
|---|---|
| Files | 1,400 (1,390 with `-O1`, 10 with `-O0`; 1,396 chunks plus 4 table files) |
| Total wall time | **937 s = 15.6 min** |
| Sum of individual times | 2,711 s (45 min CPU) |
| Median per file | 1 s |
| Files over 10 s / over 60 s | 21 / 4 |
| Slowest files | 214 s (729 MB), 187 s (727 MB), 87 s (**1,681 MB**, highest memory use), 72 s, 44 s |
| Peak memory | **1.7 GB** (870-KB single function; Phase 1 measured 3.3 GB in a sample, but that file was absent from the current chunking or was split differently) |
| Link (`clang -dynamiclib`) | 0.5 s |
| Object files | 266 MiB |
| `libgame.dylib` library | **224 MiB** (`__text` 209.6 MB, `__const` 12.2 MB, `__unwind_info` 0.4 MB) |

Outlier experiment (one single-function file each, `-O1` / `-O0`, peak memory): 134 KB C: 3.3 s / 0.08 s; 379 KB: 1.6 s / 0.11 s; 756 KB: 8.6 s (312 MB) / 0.24 s; 1.36 MB: **72 s** (604 MB) / 0.39 s; **8.0 MB** (largest function): **153 s** (867 MB) / 4.0 s (999 MB, 4.3 MB object). `-O0` eliminates the outliers completely (35 to 185 times faster), but costs runtime in those functions; there are 337 single-function files over 100 KB (284 between 100 and 300 KB, 32 up to 600 KB, 9 up to 1 MB, 8 up to 2 MB, 2 above), so 10 of 1,400 files take the special path. The three slowest files (214 s, 187 s, 87 s) are **single functions with 373 KB, 488 KB, and 870 KB of C**, below the 1-MB threshold; compilation time depends heavily on control flow, not just size (the 8-MB function takes 153 s; the 373-KB function takes 214 s). With a 300-KB threshold for `-O0`, all would have taken the special path.

**Assessment:** Full build is **within Phase 1 condition (c) (30 minutes)**: 15.6 min with 3 jobs on a busy machine; *inferred* 6 to 8 min with 8 free cores. Total resources: 1 GB C + 0.27 GB objects + 0.22 GB library, under 2 GB disk; generator needs 5 GB RAM for `main`. Verdict: **viable**. Remaining: iOS target (arm64, same library, embedded in app bundle; Xcode compilation instead of script), link behavior with LTO not measured.

---

## 4a. Performance: microbenchmarks recompiled versus native

`scripts/recomp/test/run_bench.sh`: the same C source (`bench_guest.c`) is compiled for aarch64-linux with `-O2` and run through the recompilation pipeline (`-O1` as in the full build, floating point as inline asm blocks, dispatch like LAS with a 4096-entry cache), and is compiled natively on the Mac (`-O2`) for comparison. Results match in all four cases.

| Benchmark | Recompiled | Native | Factor (`-O1`) | Factor (`-O2`) |
|---|---:|---:|---:|---:|
| Integer + memory (Xorshift, 32 KiB) | 0.41 s | 0.21 s | 1.9 | 2.0 |
| Calls + stack (`fib(35)`) | 0.12 s | 0.03 s | 4.3 | 3.2 |
| Floating point (FMA loop, inline asm) | 0.61 s | 0.15 s | 4.0 | 4.0 |
| Indirect calls (8-entry table, `rt_dispatch`) | 0.17 s | 0.11 s | 1.5 | 1.4 |

**Conclusion:** at the micro level, **1.4 to 4.3 times slower** than native code from the same source (integer code about 2×, call-heavy and FP-heavy code 3 to 4×). This supports the Phase 1 estimate of “2× to 5×” at the low end. Limits: small loops, one thread, no cache pressure; the Switch CPU (Cortex-A57, about 1 GHz) is estimated to be 6 to 10 times slower than an M1/M2 core, which would more than offset the factor (*inferred*); the game itself was not measured. The rebase switch costs +5% in the exception measurement.

---

## 5. Smallest runnable piece: `main` + `sdk` + `subsdk0` through `nnMain`

The condition “Steps 1 through 3 positive” is met. Setup (`scripts/recomp/test/boot_probe.c`, `run_boot_probe.sh`): load all three modules (from the 1,400 objects, not the test partial build) at their bases (`main` `0x70_0000_0000`, `sdk` `0x70_0600_0000`, `subsdk0` `0x70_0700_0000`; the `main` image is 84.3 MB, while the LAS slot is 64 MiB, so bases were changed), apply relocations and cross-references (`main` → `sdk`: 3,854; `subsdk0` → `main`/`sdk`: 6,551), set weak imports to 0, start `nn::init::Start(thread_handle, args, init_sdk, init_main, fini)` on the main thread (rtld replacement as in LAS: first callback = SDK module initialization after `nnosInitialize`, second = `main` before `nnMain`). Mini-kernel for this finding only: 25 SVCs with default responses, one thread, simple CMIF responses.

**Result (measured):**

| | |
|---|---|
| RSS after loading the three modules | **101 MiB** (all modules touched, 99 MB unpacked) |
| `nn::init::Start` → `nnosInitialize` | runs: `GetInfo` ×12, `QueryMemory` ×2, `GetThreadPriority`, `GetThreadId` (all values plausible) |
| SDK constructors (DT_INIT, **115 `init_array` entries**) | **complete**, without a crash or exception |
| First hard blocker | **IPC / service layer**: `ConnectToNamedPort("sm:")` → `SendSyncRequest` (HIPC type 6). With a mini-CMIF layer (responses, Domain, 120 lines), the test handles `sm:` Initialize, `lm` (control commands QueryPointerBufferSize and ConvertCurrentObjectToDomain, `OpenLogger` as a Domain object), and `MapPhysicalMemory`. **SDK query sequence afterward (`sm:` GetService):** `apm`, `appletOE`, `aoc:u`, **`ectx:aw`** (if missing, SDK calls `svcBreak`), then `pctl`, `pctl:s`, `pctl:a`, `pctl:r`. The SDK accepts error responses for `apm`/`appletOE`/`aoc:u`; if `pctl` and its variants are missing, it enters its abort handler (`nn::diag::detail::InvokeSdkAbortObserver`), which needs an `nn::am` object (from `appletOE`), and the test crashes with a null access (cause inferred from the function chain; not an error in generated code). Real services with valid objects are required. Required by this point: `ectx:aw` and one `pctl*` (otherwise abort), `appletOE` (for abort handling); `apm` and `aoc:u` tolerate the error; `lm` is implemented. |
| SVCs up to that point (run without `ectx:aw`) | 8 distinct (`0x06`, `0x0c`, `0x1f`, `0x21`, `0x25`, `0x26`, `0x29`, `0x2c`), 29 calls (`GetInfo` 13, `SendSyncRequest` 9); two `GetInfo` requests use IDs unknown to the mini-kernel |
| Threads, heap | 0 threads created; `SetHeapSize` not yet called (that happens in `nninitStartup` in `main`, after the constructors) |
| Peak RSS at abort | 105 MiB |
| Time to blocker | run itself < 1 s |

**What startup still needs (according to Phase 1 and this run):** (1) CMIF/Domain layer and the 47 services listed in NPDM (`sm:`, `lm`, `fsp-srv`, `appletOE`, `apm`, `hid`, `time:u`, `set:sys`, `acc:u0`, `pctl`, `aoc:u`, `audren:u`, `nvdrv` …; LAS includes 20 names, see Phase 1) — this is the next hard blocker and expected work, not a research risk; (2) thread and synchronization SVCs backed by real host threads (`CreateThread`, `StartThread`, `WaitSynchronization`, `ArbitrateLock`, `WaitProcessWideKey`, `WaitForAddress`; mini-kernel has placeholders only), SVC `0x32/0x33`, `0x20`, `0x23`, `0x28`, `0x2F`, `0x36`, `0x5F`; (3) `QueryMemory` segment types (reconstructed in the probe run); (4) `nninitStartup`/`SetHeapSize` (comes after constructors); (5) graphics and media layer (outside this run). The **number of Unity threads** remains unmeasured (strings: `UnityGfxDeviceWorker`, `Loading.*`, `Background Job`, `AK::IOThread`; probably 20 to 40).

**Extension (short additional run, `run_boot_probe_las.sh`):** LASRecomp's IPC/service layer (`ipc.c`, `services/am|misc|acc|hid_set|time.c`, linked, not copied) replaces the test's mini-CMIF layer, with a 40-line handle shim. Result: `sm:` → `lm` → `apm` → `appletOE` are handled; two `am` commands (`ICommonStateGetter` 900, `ISelfController` 91) are not handled by LAS; then the SDK calls `svcBreak` (reason 0), before `aoc:u`/`ectx:aw`/`pctl`. 9 distinct SVCs, 557 calls (`GetInfo` 14, `QueryMemory` 514 via the SDK EH unwinder path, `SendSyncRequest` 22), 0 threads, peak RSS 105 MiB. Finding unchanged: next blocker is missing or incomplete services (weeks of work according to the effort estimate), not an error in the recompiled modules.

**Stopped** as specified at the first hard blocker (missing service layer). The first Unity/IL2CPP startup log lines were **not** reached: RomFS (`fsp-srv`), threads, and graphics services are missing. CPU side: **no indication of errors** in the recompiled modules up to this point (SDK constructors, TLS, `nn::os`).

---

## 6. Decision memo

### 6.1 D versus R figures

| Criterion | D: Unity 6 rebuild with manually reconstructed logic | R: recompilation of the entire NSO (measured in Phases 1 and 2) |
|---|---|---|
| Status | 194 C# files (28,620 lines) plus 12,802 lines of tests, 645 tests passing; field, battle, event, UI slices; **about 39,100 game-logic methods** still to reconstruct in total | CPU side fully measured: 270,299 functions, 14.1 million words, **58 unsupported**, 1,400 files in 15.6 min, 224 MiB library; SDK initialization runs |
| Feature parity (logic, engine, UI, events) | only to the extent reconstructed; differences in randomness, timing, order, and Unity 6 versus 2019.4 remain | **1:1 automatically**, assuming CPU, kernel/services, and GPU match; save compatibility remains because the guest code writes unchanged |
| Fidelity check | against the original only through oracle/measurement (`scripts/battle_oracle*.py`) | the original **is** the code; D can be compared against it (reference) |
| GPU | Unity path with our Maxwell→MSL translator (99.8% of variants, fidelity measured) | NVN→Metal layer from LAS (9.5K lines, 495 of 524 NVN names, `docs/referenz-las-shader.md`) plus the same Maxwell→MSL translator (`shader_translator` stage): **GPU side mostly exists**; Unity-specific usage (MRT, instancing, compute skinning, 5 compute programs) unverified |
| Exceptions | n/a | **solved** (Section 1) |
| GC thread suspension | n/a (Unity IL2CPP) | **feasible**, 2 to 4 days (Section 2) |
| iPad address space/memory | normal Unity, 2.5 GB guideline / 4 GB limit (`ipad-messung-1.md`) | 32-bit window **works** (Section 3); total 3.9 to 5.0 GiB: safe **only with Increased Memory Limit** (8 GiB, measured with a free team); too tight without it |
| Performance | native Unity | game **not measured**; microbenchmarks (Section 4a): **1.4 to 4.3 times slower** than native code from same source (integer about 2×, calls/FP 3 to 4×), rebase +5%, safepoint polling up to 12% (worst case); target devices compute about 6 to 10 times as fast as Switch Cortex-A57 (*inferred*) |
| Build | Unity + Xcode as before | 15.6 min on Mac (3 jobs), generator 5 GB RAM, under 2 GB disk; 224 MiB library in app bundle |
| Still missing | everything outside the slices: estimated 90% of the logic | service layer (47 services), real threads, runtime memory conversion, media (8 of 23 `movie::` missing), audio (`hwopus`), input/touch, platform integration |
| Effort to feature parity (one developer with AI, **estimate**) | **40 to 80 weeks** (39,100 methods at 100 to 200 methods per workday with tools; rate is an assumption, not measured; current reference only: 645 tests, 28.6 kLOC); uncertainty ±50% | **Mac: 10 to 18 weeks; stable iPad: another 10 to 18 weeks** (breakdown below); uncertainty ±50%, biggest unknowns: Unity startup on guest, performance |
| Main risks | scope, silent differences, Unity 6 differences | performance (60 FPS on iPad), Unity multithreading/GC interaction with kernel reimplementation, iPad memory, legal status, maintenance (generator/runtime is a compiler project; according to its README, LAS source was almost entirely AI-generated) |
| Legal status (not legal advice) | rebuild from decompiler output; distribute repo without game content | **repo contains only recompiler + runtime** (`scripts/recomp`, clone code with MIT notice); generated C and binary are produced **locally** and not distributed (pattern: “repo + own dump”); binary is a mechanical translation of Nintendo code (more clearly a derivative work than D); app for personal use only; seek legal advice before public distribution |
| Resources | 16 GB Mac is enough (Unity Editor + tests) | 16 GB Mac is enough (generator 5 GB, compiler 1.7 GB each); iPad M2: 8 GB with entitlement, 5 GiB without, tight |

**R effort in weeks (estimate, one developer):**

| Package | Weeks |
|---|---:|
| Production exceptions, `QueryMemory`, loader, `longjmp` | 1 to 2 |
| GC thread suspension, thread/sync SVCs with host threads | 1.5 to 2.5 |
| CMIF/Domain, 47 services (stubs/real: `sm:`, `lm`, `fsp-srv`, `appletOE`, `apm`, `hid`, `time`, `set`, `acc`, `pctl`, `aoc`, `nvdrv`); LAS runtime as model | 3 to 5 |
| Memory model B in runtime/HLE (Section 3) | 1.5 to 3 |
| Graphics: port NVN→Metal and adapt to Unity, check Maxwell programs | 3 to 6 |
| Audio (`audren`, `hwopus`, Wwise), video (`movie::`) | 2 to 4 |
| Input/touch/iPad, paths/save, platform integration, Xcode bundle | 2 to 3 |
| Debugging and performance (60 FPS) | 4 to 10 |
| **Total** | **18 to 35.5** (Mac about half) |

### 6.2 Recommendation: **Hybrid; continue R as the priority with a decision point**

1. **Now (Phase 3, Mac only, no new Unity reconstruction), in two stages:**
   **Stage 1 (4 to 6 weeks):** build out CMIF/Domain and services through Unity/IL2CPP startup on the guest (use LAS runtime `ipc.c`/`kernel.c`/`services` as a model, without UI/Rando; next required according to Step 5: `ectx:aw`, `pctl*`, `appletOE`, then `fsp-srv`/RomFS), real host threads, SVC `0x32/0x33`, GC stress test; **measure `SetHeapSize`, guest RSS, thread and service counts, and the first Unity startup log lines**.
   **Stage 2 (another 4 to 6 weeks):** graphics (NVN→Metal, Maxwell→MSL) through title screen and into the field, **frame time** on Mac, and a probe build of the mini-scene on iPad.
2. **D continues as before** (shader/texture/save/data tools are shared by both paths), but starts **no new large logic blocks** before the decision point. Already reconstructed components (battle, EvScript) are checked **against R as an oracle** (same inputs, state comparison), which also reduces D risk.
3. **Decision points.** After Stage 1, continue only if (a) Unity startup on guest reaches a stable main loop (one-hour soak test with no exception or GC errors) and (c) guest RSS there is ≤ 4.5 GiB (below 5.9 GiB with entitlement). After Stage 2, R becomes the primary path (Mac **and** iPad) if, in addition, (b) frame time in the field is ≤ 16.7 ms on Mac and projection to iPad (factor from Mac M1 Pro versus iPad M2 using the probe build) meets the target, (e) full build takes ≤ 30 min on Mac, and (f) legal status for personal use is acceptable. **Otherwise** D remains primary, and R remains an oracle and comparison baseline (Decision 2 remains valid).
4. **Why not make R the sole primary path immediately:** Unity engine, services, audio, and guest graphics did not run in this spike; iPad performance and in-game memory are unmeasured; the work is estimated in weeks, but no Unity frame has been reached yet. **Why not use D alone:** the three main Phase 1 blockers (exceptions, GC, memory model) are gone; R provides feature parity and fidelity for one third to one half of D's effort if the open conditions (b), (c) hold.
5. **Hybrid abort criterion:** if a hard blocker appears in Phase 3 (Unity boot fails because of threads/GC/services, frame time is more than 3× the target, or memory exceeds 5.9 GiB), document the findings and make D the sole primary path again; cost is limited to 4 to 6 weeks (Stage 1) or 8 to 12 weeks (both stages).

---

## 7. Abort criteria and outcomes

| Step | Abort criterion | Result |
|---|---|---|
| 1 Exceptions | cannot throw → catch across ≥ 2 recompiled frames with correct state | **met** (tests T1 through T5, 100 of 100 reached real functions) |
| 2 GC | thread suspension impossible without entitlement | **did not occur** (Mach API; Boehm uses it) |
| 3 Memory | 32-bit offsets cannot be used without changing semantics | **did not occur** (header switch passes) |
| 4 Partial build | full build > 30 min or memory > 3.3 GB per compiler | **did not occur** (15.6 min, 1.7 GB) |
| 5 Smallest piece | first hard blocker | **occurred** after `nnosInitialize` and 115 SDK constructors: IPC (`sm:`/`lm`) |

## 8. Gaps and unverified items

- **Performance** of recompiled games (frame time, share of `Cpu` memory, dispatch): microbenchmarks only (Section 4a: factor 1.4 to 4.3 versus native, `fib`, FP, indirect calls, integer); there is no runnable game. The assumption “M core is 6 to 10 times faster than Cortex-A57” is not measured.
- **Unity startup on the guest** (IL2CPP initialization, threads, Wwise, video path): not reached.
- Actual `SetHeapSize` value, number of threads, and guest RSS in the field: unmeasured.
- **iPad**: neither 4-GiB reservation nor `thread_suspend` was measured on device; address-space limits on current iPadOS versions have not been verified.
- Throw test with real functions: only 100 of 180 reached the check (the rest failed due to the synthetic environment); typed catches with the **actually matching** type object were not tested on real functions; `longjmp` reentry (17 sites in `main`) uses the same mechanism but was not tested.
- GC suspension (Section 2): Mach measurements and a synthetic test on recompiled guest code, **no run with a real Boehm GC**; mirroring host state is a design, not a test result.
- Rebase32: tested only with the SDK test (exceptions, allocations), not with `main`; SIMD asm path with rebase is not implemented.
- Effort in weeks is estimated with ±50% uncertainty; the D range relies on an unmeasured assumption about methods per day.
- Compilation time: measured under external load; no LTO/release optimization measured; library startup time (page faults while loading the 224 MiB) not measured.

## 9. Reproduction

All local; outputs under `work/recomp/` (gitignored). Requirements: `work/exefs`, `research/LASRecomp`, `tools/pydeps` (capstone, unicorn, lz4), Homebrew LLVM.

```
python3 scripts/recomp/eh_lsda.py survey ; python3 scripts/recomp/eh_lsda.py cfa ; python3 scripts/recomp/eh_lsda.py sample
scripts/recomp/test/run_eh_test.sh               # Step 1: guest test with real SDK (generation, compilation, run)
python3 scripts/recomp/test/uc_ref.py            # countercheck under Unicorn
scripts/recomp/test/run_eh_real.sh               # 45 real LSDA functions from main (PER_KIND=60: 180)
clang -O1 -o work/recomp/spike2/gc_suspend scripts/recomp/test/gc_suspend.c && work/recomp/spike2/gc_suspend     # Step 2 (Mach latency, polling cost)
scripts/recomp/test/run_gc_proof.sh              # Step 2: asynchronous suspension in recompiled guest code
scripts/recomp/test/run_eh_rebase32.sh           # Step 3: 32-bit guest addresses
python3 scripts/recomp/ptr_scan.py               # Step 3: tag/39-bit sample
scripts/recomp/gen_all.sh ; scripts/recomp/build_all.sh 3     # Step 4
scripts/recomp/test/run_bench.sh -O1             # Section 4a: recompiled vs. native performance
scripts/recomp/test/run_boot_probe.sh            # Step 5
scripts/recomp/test/run_boot_probe_las.sh        # Step 5, extension using LAS IPC/service layer
```

Origin and license: `research/LASRecomp` (MIT, Copyright (c) 2026 Peiikai; excluding Nintendo property and `third_party/`) is imported only at runtime by the scripts; nothing was copied. If the generator is adopted later, follow the notices in `shader_translator/NOTICE.md` (license text unchanged, commit `09f8e5e`, identify changes); the original's `tools/patches.py` contains game addresses and cannot be adopted.
