# Feasibility spike `ap-recomp-feasibility`: LAS-style recompilation of BDSP NSO (as of 2026-10-18)

**Task:** measure and analyze only; make no decision. In our own words, not legal advice. Nothing was copied from `research/LASRecomp` (MIT; read-only); this document records only file paths, line numbers, numbers, and names. No binaries, generated code, or disassembly.

**Update 2026-10-19:** Phase 2 of the spike from section 7 was completed: `docs/recomp-spike-2.md`. The “core blocker” of C++ exceptions is resolved (variant A, tested with real SDK unwinder and 180 real functions); thread suspension and 32-bit memory model have been prototyped; full build measured (15.6 min, 224 MiB). Statements below that describe these as open or “weeks to months” are superseded.

**Labels:** **measured** = obtained with `scripts/recomp_survey.py` or commands on local files. **Verified** = read in clone, cited source, or our docs. *Suspected* = inference without test. **Unverified** = secondary-source number/claim or not testable.

**Reproduction** (all local; outputs under gitignored `work/recomp/`):

```
pip install --target tools/pydeps capstone unicorn            # lz4 was already installed
python3 scripts/recomp_survey.py nso | hist | imports | svc | npdm | eh
python3 scripts/recomp_survey.py lifter    --lifter-dir scripts/recomp/upstream/generator --module main --simd asm
python3 scripts/recomp_survey.py gensample --lifter-dir scripts/recomp/upstream/generator --module main --functions 0
```

`lifter` and `gensample` import lifter and generator from clone at runtime only (do not write `.pyc` files there and omit LAS-specific patch tables) and produce numbers only. The target binary is never modified.

## Summary (key figures)

| Question | Result | Status |
|---|---|---|
| LAS lifter CPU coverage for BDSP | 14,105,420 words across four modules. **58 words** rejected (`LDXP/STXP/LDAXP/STLXP`, all in `main`), 4 of 332 distinct mnemonics. No LSE, PAC, or crypto/CRC in `main`. | measured |
| Generated C size (ARM64 mode, inline asm) | **1.01 GB** (`main` 846 MB, `sdk` 105 MB, `subsdk0` 63 MB), 71.8 bytes/instruction, about 1.25 C lines/instruction | measured (full generation without writing files) |
| Functions | `main` 217,858; `sdk` 37,267; `subsdk0` 13,343 (boundaries from eh_frame, symbols, relocations, BL targets) | measured |
| Compile time | Normal chunk (1.5 MB C) 1–4 s; **long outliers**: individual functions with 1.1–1.4 MB C take 13–200 s and up to 3.3 GB RAM; largest (8.0 MB C) not compiled | measured (sample) |
| Interface | `main` imports 1,040 symbols: 1,013 from `sdk`, 23 from `subsdk0` (movie), 4 unresolved. NVN only through `nvnBootstrapLoader`. | measured |
| LAS SVC gap | BDSP mask has 50 SVCs, LAS implements 43; **8 missing**, including `SetThreadActivity`/`GetThreadContext3` (thread suspension) | measured/verified |
| Services (IPC) | NPDM allows 47 services; LAS includes 12 of them (20 service names total) | measured/verified |
| **Core blocker** | BDSP uses C++ exceptions (IL2CPP): 2,917 functions with landing pads. LAS has no mechanism for them. | measured/verified |
| Memory/iPadOS | Fixed 12.5 GiB window at `0x70_0000_0000` is **not** compatible with iOS without entitlement; free team does not have the relevant entitlement (section 4a). | verified (XNU source, Apple docs) |

## 1. CPU recompilation architecture in LASRecomp

### 1.1 Pipeline (verified)

| Stage | File (lines) | Task |
|---|---|---|
| Read NSO | `tools/nso.py` (98) | Decompress LZ4 segments, MOD0, Dynamic, Dynsym, relocations |
| Function boundaries | `tools/analyze.py` (105), `tools/gen.py:boundaries/main` | Find starts from `.eh_frame_hdr`, function symbols, `R_AARCH64_RELATIVE` pointers to text, BL targets, ADR/ADRP pairs; fixed-point iteration until every branch target outside a function is itself a function start |
| Jump tables | `tools/gen.py` (630) | `br xN` through bounds-checked tables: **Unicorn** executes address pattern for each index; on failure, fallback labels every instruction in function (`switch(c->pc)`) |
| Lifter | `tools/lifter.py` (728) | Integer, memory, branches, system instructions to C; FP/SIMD depends on mode |
| FP/SIMD | `tools/lifter.py:emit_asm_batch`, `tools/simd_c.py` (1,156), `runtime/simd.h` (818), `simd_fp.h` (340) | Mode `asm` (arm64 host): original encodings packed as `.inst` in inline asm blocks (up to 24); V registers loaded from `Cpu` before each block and written back afterward, bit-exact by construction. Mode `c`: portable C emulation (x86 hosts). |
| Output | `gen.py` | Per-function `void f_<address>(Cpu *c)`, chunks up to 1,500 functions or 1.5 MB; functions over 100 KB get own file; plus `*_table.c` with sorted address/function-pointer table |
| Build | `Makefile` | `clang -O1 -fno-strict-aliasing -fvisibility=hidden` per chunk; result is **one separate library** (`lasgame.dylib`) loaded by runtime via `dlopen` (`runtime/gamelib.c`) |

Important for us: guest registers live in in-memory `Cpu` structure (`runtime/cpu.h`: `x[32]`, `sp`, `nzcv`, `tpidr`, `excl_addr`, `v[32]`). Every instruction reads/writes `c->x[n]`; flags are packed word (inline functions such as `adds64`, `COND_EQ`). Simple and correct, but loses register allocation across function boundaries (*suspected*: significantly slower than native ARM64; **not measured**, neither working BDSP nor LAS available here).

### 1.2 Memory accesses (verified)

- **Guest address = host address.** `LD8..LD64`/`ST8..ST64` are direct pointer dereferences (`runtime/cpu.h:62-72`, unaligned-safe, `may_alias`). No translation or range check; out-of-range access SIGSEGVs.
- **Fixed window:** `runtime/rt.h:14-30`. `GUEST_LO=0x70_0000_0000`, `GUEST_HI=0x73_2000_0000` = **12.5 GiB**. Comment's rationale (`rt.h:14-15`): macOS occupies `0x2_0000_0000-0x70_0000_0000`; guest addresses must fit 39 bits. Layout: main at `0x70_0000_0000`, SDK at `0x70_0400_0000` (only 64 MiB gap), HLE stubs `0x70_8000_0000`, TLS `0x70_9000_0000` (1 MiB), HLE heap 224 MiB, 4 GiB alias region from `0x71_0000_0000`, 1 GiB stack window from `0x72_0000_0000` (`runtime/kernel.h:7-8`), heap from `0x72_4000_0000`, **up to 3.25 GiB** (`HEAP_MAX`).
- **macOS:** `plat_reserve_guest` uses `mach_vm_allocate(..., VM_FLAGS_FIXED)` over whole window, read/write; pages allocated on first access (`runtime/platform/macos.c:24-37`). `plat_commit` is a no-op. Page size is 16 KiB (`platform.h:32`); guest operates in 4 KiB increments because permissions are never changed: `SetMemoryPermission`/`SetMemoryAttribute` simply return OK (`kernel.c:579`). Thus no guest guard pages or write protection.
- **Linux:** same principle with `MAP_NORESERVE | MAP_FIXED_NOREPLACE` (`platform/linux.c:29-44`). **Windows:** `VirtualAlloc(MEM_RESERVE)` for window, commit per region (`plat_commit`) and lazily through exception handler in 64 KiB chunks (`platform/windows.c:14-27`).
- **Collision:** if macOS has already mapped something at requested address, process restarts itself up to 20 times (`main.c:37-52`, `plat_exec`/`execv`).
- **Exclusive accesses** (`LDXR/STXR`): emulated through `excl_addr`/`excl_val` and compare-and-swap (`cpu.h:74-95`). Not hardware-identical (ABA cases); sufficient for usual spinlocks/counters. `CLREX` resets monitor. `LDAR/STLR` use real acquire/release accesses. Barriers use `__atomic_thread_fence`.

### 1.3 Indirect calls, vtables, function pointers (verified)

- Direct `BL`/`B` between functions become direct C calls or tail calls (`musttail`). Guest `RET` becomes host `return`: **host stack mirrors guest call stack**; guest LR (`x30`) is set but not used to return.
- `BLR`/`BR` with register target: `c->pc = target; rt_dispatch(c)` (`runtime/dispatch.c:157-164`): 4,096-entry direct-mapped cache per thread (index from `pc>>2`); on miss, **binary search** sorted address table, then HLE stubs (addresses from `HLE_BASE`) and overrides. Unknown target: `FATAL "no function at …"`.
- There are **two** tables (main, SDK; `dispatch.c:12, 116, 187`) and `g_modules[4]` (`rt.h:40`). BDSP has three code modules (`main`, `sdk`, `subsdk0`); third table required.
- Every guest function that may be reached through pointer must be separate C function: generator uses code pointers from relocations, `ADR/ADRP+ADD` and BL targets as function starts. `main` has about **554,000 relocations** (`.rela.dyn` size / 24). IL2CPP method tables and vtables are there (*suspected*; share targeting text not counted individually).
- **No guest C++ exceptions or `setjmp/longjmp`.** No `_Unwind`, `__cxa_throw`, or Personality found in clone (`grep` over `runtime/` and `tools/`). Runtime uses `longjmp` only to unwind guest threads during shutdown/restart (`kernel.c:184-192, 611`). Consequence for BDSP: section 5.

### 1.4 Threads, TLS, atomics, exclusives (verified)

- Each guest thread is host `pthread` with **256 MiB** host stack (`kernel.c:226`, comment: “guest recursion runs on the host stack”) plus its own guest stack (from guest memory): two stacks per thread. Guest threads run in parallel; priorities recorded, core masks ignored (`SetThreadCoreMask` = OK).
- TLS: `MRS TPIDR_EL0/EL0RO` return `c->tpidr`/`c->tpidrro` (`lifter.py:system`); each thread has a 0x200-byte region in TLS window (`kernel.c:209-214`). Counter registers (`CNTVCT`, `CNTFRQ`=19.2 MHz) use `rt_ticks()`.
- Synchronization (`ArbitrateLock`, `WaitProcessWideKey`, `WaitForAddress` …) implemented in `kernel.c` with one global mutex and condition variables.
- **Thread suspend/context read** (`SetThreadActivity`, `GetThreadContext3`): not implemented (section 3.3).
- README (`README.md` around line 183): contribution #107 by hjqcan: “Windows game thread stacks reserved instead of committed, about 9 GB less memory committed.” Related code commit cannot be isolated in clone (commits `9f26e4c` and `ece84d7` change README only). Clone still reserves 256 MiB in `kernel.c:226`. Lesson (reserve stacks without committing) is plausible; where LAS implements it is **unverified**.

### 1.5 SVC and IPC implementation

**SVCs (verified, `runtime/kernel.c:569-780`):** 43 numbers: `0x01-0x1F` (heap, memory, threads, events, shared/transfer memory, `CloseHandle`, `WaitSynchronization`, arbitrate lock/unlock, ProcessWideKey, `GetSystemTick`, `ConnectToNamedPort`), `0x21` SendSyncRequest, `0x22` with user buffer, `0x24-0x27`, `0x29` GetInfo, `0x2C/0x2D` MapPhysicalMemory, `0x34/0x35` WaitForAddress/SignalToAddress, `0x45` CreateEvent. Others are `FATAL "unimplemented svc"`. `MapMemory` is implemented as copy (source supposedly inaccessible, per comment).

**IPC (verified, `runtime/ipc.c` 246 lines, `ipc.h`):** HIPC/CMIF with domains, X/A/B/C buffers; services are host functions registered with `SERVICE("name", handler)`. **20 names** implemented: `sm:`, `acc:u0`, `aoc:u`, `apm`, `appletOE`, `audout:u`, `audren:u`, `fsp-srv`, `hid`, `hid:sys`, `lm`, `pctl` (+ `:a :r :s`), `set`, `set:sys`, `time:u/:a/:s`. Also **68 `HLE_FUNC` overrides** for individual guest symbols (including `nvnBootstrapLoader`, `nn::vi`, `nv::`, `nn::pl`, `nn::swkbd`, `movie::`).

### 1.6 Size and timing in LASRecomp and Let's Go

- **Let's Go: 123,612 functions, ~550 MB C: unverified.** Neither these figures nor “letsgo” appear in clone (`grep -ri` over clone found none). Therefore no “C lines per instruction” ratio for Let's Go can be derived from notes. Instead, ratio was measured directly on BDSP (section 2.4). As an arithmetic example only: 550 MB / 123,612 = 4.4 KB/function; BDSP `main` is 3.9 KB (measured).
- LAS compile time: only note is “a few minutes” (`runtime/ui/launcher.mm:282`, builds game library on first launch). No measurement in clone.

### 1.7 Runtime size (measured, `wc -l`, clone at 77 commits)

| Directory | Lines | Notes |
|---|---:|---|
| `runtime/*.c, *.h` (core) | 5,351 | Kernel 868, IPC 246, Dispatch 289, Loader 185, main 188, `cpu.h` 197, `simd.h` 818, `simd_fp.h` 340, Gamebuild/Settings/Paths, etc. |
| `runtime/hle/` | 6,462 | Only about 2,000 generally reusable (Input 515, Movie 796, Heaps 163, Bindings 228, `pl`, `vi`, `swkbd`, `nvn_boot`, `framepace`); rest (~4,400) Zelda/randomizer-specific (Warp, Digs, Miniboss, Pets, …) |
| `runtime/services/` | 2,452 | Audio 1,251, FS 618, AM 236, Time 139, HID/Set 103, ACC 57, Misc 48 |
| `runtime/nvn/` (Metal path: `*.c`, `*.m`, `maxwell/`) | 9,534 | `renderer.m` 2,701, `translate.c` 2,165, `metal.m` 1,191, `texpatch.c` 1,043 (LAS-specific), `objects.c` 806, `astc.c` 524, `cmdbuf.c` 451 |
| `runtime/nvn/vulkan/` | 6,019 | Not needed for us |
| `runtime/platform/` | 943 | macOS 167 |
| `runtime/ui/` | 6,479 | Randomizer/start UI, do not reuse |
| `tools/*.py` | 4,659 | Lifter 728, `simd_c.py` 1,156, generator 630, `patches.py` 687 (LAS addresses), tests |

Without UI, Vulkan, and game-specific code, **roughly 18,000–20,000 lines are reusable** (kernel, IPC, dispatch, loader, SIMD, general services, Maxwell translator, Metal renderer) plus 3,000 lines of generator. *Estimate* based on counts above.

## 2. Measurements on BDSP NSO

### 2.1 Modules and segments (measured, `recomp_survey.py nso`)

| Module | File | text | ro | data | bss | Image | Instructions (4 B) | Dynsym: imports / exports |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| rtld | 7,187 | 6,240 | 3,384 | 600 | 3,496 | 16,384 | 1,560 | 19 / 0 |
| main | 37,895,896 | 47,147,568 | 27,143,648 | 5,735,456 | 4,258,784 | 84,287,488 | 11,786,892 | 1,040 / 49 |
| sdk | 5,755,393 | 5,822,768 | 6,840,808 | 416,248 | 759,304 | 13,844,480 | 1,455,692 | 13 / 26,570 |
| subsdk0 | 3,409,290 | 3,445,104 | 2,161,836 | 197,496 | 1,162,376 | 6,971,392 | 861,276 | 657 / 10,895 |
| **Total** | 47,067,766 | 56,421,680 | 36,149,676 | 6,349,800 | 6,183,960 | **105,119,744** | **14,105,420** | |

`main` text (`0x2cf6a30` = 47.1 MB) matches Ghidra's “.text through `0x2df6a30`” with image base `0x100000`. The `.plt` section in nx2elf conversion (22 MB) is actually IL2CPP game code.

**Correction to `docs/extraktion.md`:** “6630 .dynsym entries” is section *hex size* (`0x6630` bytes = 26,160 B = **1,090 entries**; confirmed by `llvm-readelf --dyn-syms`).

### 2.2 Instruction-class histogram (measured, `hist`, Capstone 5.0.7, linear scan over text)

Classes based on word encoding plus mnemonic. Aliases such as `mov`, `cmp` counted under “Integer.” Percentages are share of module words.

| Class | main | % | sdk | % | subsdk0 | % | All 4 modules |
|---|---:|---:|---:|---:|---:|---:|---:|
| Integer ALU/Move/Bitfield | 3,673,845 | 31.2 | 600,116 | 41.2 | 360,125 | 41.8 | 4,634,626 |
| Integer Mul/Div | 50,825 | 0.4 | 13,278 | 0.9 | 11,713 | 1.4 | 75,843 |
| Conditional integer (CSEL/CCMP) | 64,582 | 0.6 | 17,596 | 1.2 | 12,681 | 1.5 | 94,869 |
| ADR/ADRP | 436,790 | 3.7 | 36,143 | 2.5 | 17,829 | 2.1 | 490,837 |
| Single GPR Load/Store | 3,062,698 | 26.0 | 307,226 | 21.1 | 215,134 | 25.0 | 3,585,423 |
| GPR pair Load/Store | 916,290 | 7.8 | 130,006 | 8.9 | 52,715 | 6.1 | 1,099,152 |
| LDAR/STLR (Acquire/Release) | 2,028 | 0.02 | 2,067 | 0.14 | 64 | 0.01 | 4,159 |
| Prefetch | 1,313 | 0.01 | 109 | 0 | 77 | 0 | 1,499 |
| **Exclusive** (LDXR/STXR/LDAXR/STLXR, CLREX) | 8,768 | 0.07 | 1,521 | 0.10 | 22 | 0 | 10,315 |
| **Atomics/LSE** (CAS, SWP, LDADD …) | **0** | 0 | **0** | 0 | **0** | 0 | **0** |
| FP/NEON/SIMD arithmetic | 557,608 | 4.7 | 19,321 | 1.3 | 5,927 | 0.7 | 582,856 |
| FP/NEON/SIMD Load/Store | 288,804 | 2.5 | 11,957 | 0.8 | 1,624 | 0.2 | 302,393 |
| **Crypto** (AES/SHA/PMULL) | 0 | 0 | 1,038 | 0.07 | 0 | 0 | 1,038 |
| CRC32 | 0 | 0 | 18 | 0 | 0 | 0 | 18 |
| System: MRS/MSR | 0 | 0 | 120 | 0.01 | 0 | 0 | 120 |
| System: barriers (DMB/DSB/ISB) | 858 | 0.01 | 133 | 0.01 | 51 | 0.01 | 1,042 |
| System: DC/IC/SYS/TLBI | 0 | 0 | 5 | 0 | 0 | 0 | 5 |
| System: SVC | **0** | 0 | 77 | 0.01 | 0 | 0 | 81 (including 4 in rtld) |
| System: UDF/BRK (trap filler words) | 99,955 | 0.85 | 19,197 | 1.3 | 5,303 | 0.6 | 124,504 |
| System: NOP/Hints | 160,556 | 1.4 | 138 | 0.01 | 61 | 0.01 | 160,758 |
| **PAC/BTI** | **0** | 0 | 2 (only `AUTIA1716/AUTIB1716`) | 0 | 0 | 0 | 2 |
| Direct branch | 2,204,659 | 18.7 | 241,547 | 16.6 | 159,495 | 18.5 | 2,605,987 |
| Indirect branch (`BR`/`BLR`) | 99,451 (`BLR` 83,726, `BR` 15,725) | 0.84 | 22,950 | 1.6 | 8,285 | 1.0 | 130,697 |
| `RET` | 157,607 | 1.3 | 30,848 | 2.1 | 9,856 | 1.1 | 198,347 |
| Not decodable | 255 | 0 | 279 | 0.02 | 314 | 0.04 | 849 |
| **Total words** | **11,786,892** | | 1,455,692 | | 861,276 | | 14,105,420 |

Observations (measured): memory accesses (GPR, pairs, acquire/release, exclusive, FP) account for **36.3%** of `main` instructions, i.e. 4.28 million sites needing address rebasing if every access is rebased (section 4c). FP/NEON is only 7.2% in `main`. No ARMv8.1 atomic extension or pointer authentication: code is pure ARMv8.0 (Cortex-A57). All 77 SVC call sites are in `sdk` (plus 4 in `rtld`); **`main` never calls kernel directly**.

### 2.3 Lifter coverage (measured, `lifter`; every word checked, not just mnemonic list)

A static mnemonic list cannot be cleanly derived from `lifter.py`/`simd_c.py` because lifter decodes bit patterns, not names. Therefore every word of `rtld`, `main`, `sdk`, and `subsdk0` was passed through lifter and rejections (`Unsupported`) counted in both FP modes.

| Module / mode | Words | Rejected | Reason | Mnemonics |
|---|---:|---:|---|---|
| main, `asm` | 11,786,892 | **58** | “exclusive pair / CAS” | `ldxp` 20, `stxp` 23, `ldaxp` 9, `stlxp` 6 |
| main, `c` | 11,786,892 | 58 | same | same |
| sdk, subsdk0 (both modes) | 2,316,968 | 0 | | |
| rtld, `c` | 1,560 | 1 | one undecodable FP word (data word) | |

- **Not covered: 58 words = 29 exclusive pairs in `main`**, 0.0005% of instructions; 4 of 332 distinct mnemonics. These are 128-bit lock-free operations (typically Boehm GC/allocator or Unity atomics). Addition is small (paired load/store with 128-bit CAS) but mandatory, otherwise execution ends in `rt_udf`.
- “Covered” here means lifter emits C. **Correctness was not measured.** LAS includes `tools/test_lift.py` (244) and `test_simd.py` (460), which were not run.
- 100,211 words in `main` lift as `trap` (UDF filler and data words in text). They must never execute.

### 2.4 Generated C size (measured, `gensample --functions 0`: real generator over all functions, count only)

| Module | Functions | Instructions | C bytes (`asm`) | B/instr. | B/function | Functions >100 KB (share of C) | Largest function |
|---|---:|---:|---:|---:|---:|---|---:|
| main | 217,858 | 11,786,892 | 846,020,435 | 71.8 | 3,883 | 336 (84.4 MB = 10%) | 8.0 MB |
| sdk | 37,267 | 1,455,692 | 104,737,617 | 72.0 | 2,810 | 76 | 0.61 MB |
| subsdk0 | 13,343 | 861,276 | 62,834,635 | 73.0 | 4,709 | 74 | 0.58 MB |
| rtld | 42 | 1,553 | 109,798 | 70.7 | | 0 | |
| **Total** | **268,510** | **14,105,420** | **1,013,702,485 ≈ 1.01 GB** | | | | |

- `c` mode (portable SIMD): `main` 797,415,923 bytes, 67.7 B/instruction.
- Lines: 198,987 lines for 12.3 MB sample (3,000 functions) = **1.25 C lines per instruction** (including declarations); inline-asm blocks combine FP sequences into one line.
- Limits: function count is number of starts before fixed point (generator “boundaries” step); final count is slightly higher. Ghidra reports 166,095 functions (different counting: only recognized functions, no eh_frame splits). `main` has 216,168 FDEs.
- **Range without extrapolating from Let's Go:** at 60–90 B/instruction (around measured value) and 14.1 million instructions, result is 0.85–1.27 GB. Measured 1.01 GB is in the middle. Earlier estimate “0.7–1 GB” (`docs/recomp-referenzen.md`) was slightly low.
- Object code size (sample, 8 chunks, 12.3 MB C): 3.8 MB object file, factor **0.31**. Extrapolated to 1.01 GB C: roughly **300–330 MB machine code** in library (about 5–6× the 56 MB guest text). *Estimate*, not linked.

### 2.5 Compile time (measured on samples, Apple clang 17, `-O1` as Makefile, M1 Pro)

| Sample | C size | Time | Peak RAM |
|---|---:|---:|---:|
| 8 chunks with 1.3–1.7 MB each, 3,000 random functions (7 of 8) | about 1.5 MB each | 1–4 s per chunk | about 200 MB (2 measurements: 227 and 203 MB) |
| Same set, one chunk containing a large function | 1.5 MB | **89 s** | |
| 9 of 10 largest single-function files (1.1–2.8 MB each) | 1.1–2.8 MB each | 13 / 39 / 49 / 1.4 / 1.0 / 1.1 / 75 / **200** / 3.2 s | up to **3.3 GB** (one case with 1.2 MB) |
| Largest function (8.0 MB) | 8.0 MB | **not compiled** (measurement RAM limit 3 GB) | unknown |

- Normal throughput about 0.7–0.8 MB C/s per core. For 1.01 GB this gives about **25 CPU minutes**; add long tail: 9 measured outliers alone cost about 6.5 CPU minutes, and 8 MB function is missing. *Suspected:* 30–60 CPU minutes, **10–20 minutes wall time** on 6 M1 Pro performance cores, if memory per outlier job (up to 3.3 GB) limits parallelism. Not an iPad issue (build on Mac), but a build-pipeline issue.
- Cause of outliers (*suspected*): functions with huge `switch`/many labels (264 functions in `main` fell back to “every instruction is a label”). Possible remedies: less optimization for these functions, splitting them, better jump-table resolution.
- Link step for ~300 MB library was not measured. Direct ARM64 `BL` reaches only ±128 MB; ld64 inserts thunks itself (*suspected*, not checked).

## 3. Switch system interface

### 3.1 Imports from `main` (measured, `imports`; NSO Dynsym)

`main` has 1,090 Dynsym entries, including **1,040 imports** (1,026 functions, 10 objects, 4 weak markers) and 49 exports. Providers (resolved by name against other module exports): **sdk 1,013**, **subsdk0 23** (all in `movie` namespace), 4 unresolved (`__rel_*`).

| Namespace | Imports | Notes |
|---|---:|---|
| `nn::*` (C++, `_ZN2nn`) | **733** | namespace breakdown below |
| libc/libm (`memcpy`, `malloc`, `printf` …) | 125 | from `sdk` (includes nnmusl) |
| C++ ABI/unwind/libc++ (`__cxa_*`, `_Unwind_Resume`, `std::`) | 80 | includes `__cxa_throw`, `__gxx_personality_v0` |
| `nnos*`/`nnsocket*`/`nnssl*`/`nnResult*` (C API) | 20 / 21 / 21 / 4 | |
| `movie::*` (Nintendo multimedia) | 23 | from `subsdk0` |
| `nv::` (graphics-driver init) | 3 | `InitializeGraphics`, `SetGraphicsAllocator`, `…DevtoolsAllocator` |
| `nvn*` | **1** | only `nvnBootstrapLoader`; Unity obtains all other NVN functions from loader by name |
| pthread family | 5 | |
| AK/Wwise, Unity native symbols | **0** | both statically linked into `main` (strings only, e.g. `AK::…`, `UnityGfxDeviceWorker`) |

`nn::*` by subnamespace (second level): `hid` 102, `os` 91, `friends` 75, `socket` 60, `audio` 50, `swkbd` 43, `fs` 40, `account` 36, `ldn` 26, `irsensor` 24, `oe` 22, `bcat` 22, `ec` 21, `err` 20, `crypto` 17, `nifm` 12, `time` 10, `mem` 10, `web` 8, `ngc` 7, `prepo` 6, `util` 5, `vi` 5, `ssl` 4, `aoc` 4, `diag` 3, `pl` 3, `settings` 3, `cstd` 2, `nsd` 1, `codec` 1. Online/network share (`friends`, `socket`, `ldn`, `bcat`, `ec`, `nifm`, `ssl`, `web`, `prepo`, `ngc`, `nsd`) is **242 of 733** `nn::` imports, plus 42 C API imports (`nnsocket*`, `nnssl*`).

### 3.2 What `sdk` and `subsdk0` contain (measured where export names make it clear)

| Module | Size (text/image) | Contents (from export names) | Purpose |
|---|---|---|---|
| `rtld` | 6 KB / 16 KB | 19 imports, 4 SVCs (`QueryMemory`, `Break`, `OutputDebugString`, `ReturnFromException`) | Runtime linker; LAS replaces it with `module_init` in `main.c` (initialization order) |
| `sdk` | 5.8 MB / 13.8 MB | 26,570 exports: 16,900 `nn::*`, 4,220 C++ ABI, 1,807 libc, 148 `nv*`, 102 pthread; contains **NVN driver library** (exports `nvnBootstrapLoader`, `nvnBootstrapLoaderInternal`, `nvnDevtoolsBootstrap`) | Nintendo SDK (`nnSdk`): OS layer, IPC clients, libc (nnmusl), libc++, libunwind, libpng (`nndetailImagePng…`), and NVN drivers |
| `subsdk0` | 3.4 MB / 7.0 MB | 10,895 exports: `android` 5,249, `movie` 825, `mkvparser` 360, `mkvmuxer` 225, `mm_internal` 61, `nnAudioSink` 32 | Nintendo multimedia library (per `NEEDED` entry in `main`; filename only used for name comparison): WebM/Matroska parser and decoder wrapper for video player (VP8 WebM videos; `docs/daten-inventar.md`) |

- **glslc:** `sdk` contains only five allocator hooks `glslc_Alloc`, `…Realloc`, `…AllocAlign`, `…Free`, `…GetAllocator`; `main` imports no glslc functions. Runtime shader compiler therefore **unlikely**, but call-graph proof is missing. This provisionally answers open question in `docs/referenz-las-shader.md` (section 4): *probably not*.
- NVN names: `main` contains 524 `nvn…` name strings (string scan). LAS implements 495 `NVN(...)` functions; **495 of BDSP's 524 names** have a counterpart, 29 do not (7 checkpoint/debug functions, plus e.g. `ClearBuffer`, `DispatchCompute(Indirect)`, `Draw*Indirect`, `ReportCounter`, `SetSampleMask`, `Wait/SignalEvent/Sync`). Whether BDSP actually *calls* them is open; strings are not calls. `docs/shader-audio-machbarkeit.md` reports 5 compute programs.

### 3.3 Required HLE scope compared with LAS

| Area | BDSP needs | LAS provides | Gap |
|---|---|---|---|
| SVC | 50 per NPDM mask (46 called in `sdk` text) | 43 | Missing **0x20, 0x23, 0x28, 0x2F, 0x32, 0x33, 0x36, 0x5F**. `SetThreadActivity`/`GetThreadContext3` (0x32/0x33) underpin `nn::os::SuspendThread/ResumeThread/GetThreadContext`; `main` imports all three, and stop-the-world GC typically uses them (*suspected*, not shown in code) |
| IPC services | 47 per NPDM | 20 names (12 of 47) | 35 missing: `audin:u`, `bcat:u`, `bsd:u`, `bsdcfg`, `caps:u/su`, `csrng`, `friend:u`, `hwopus`, `irs`, `ldn:u`, `ldr:ro`, `mii:u`, `mm:u`, `nfc:*`, `nfp:user`, `nifm:u`, `nim:eca`, `notif:a`, `nsd:u`, `ntc`, `nvdrv`, `pcm`, `pl:u`, `prepo:u`, `sfdnsres`, `ssl`, `vi:u`, `htc*`, `banana`, `ectx:aw`, `ngct:u`. LAS covers three differently: `vi`/`nv` (HLE symbol overrides, `hle/vi.c`), `pl` (`hle/pl.c`), `nvdrv` (NVN HLE). Rest are network/online/sensors: *can be stubbed* (error return) if SDK initialization does not hang (untested). **Actually needed:** `hwopus` (Opus decode, probably used by Wwise; *suspected*), `csrng`, `mm:u`/`nvdrv` (video decoder), `ssl`/`bsd` as error stubs only |
| Graphics | NVN via loader, 524 names, Unity Maxwell shaders (13,710 programs) | NVN Metal backend (9.5 kLOC), Maxwell→MSL (`translate.c`, 2,165 lines) | Shader-opcode coverage unmeasured (`docs/referenz-las-shader.md` §11); Unity-specific usage (instancing, MRT, compute skinning) untested |
| Video | 23 `movie::` imports | `hle/movie.c` (796 lines, FFmpeg): 15 of 23 names present | 8 missing (e.g. `Extractor::SetDataSource/GetTrackCount/GetTrackConfiguration`, `MediaData::FindRect/FindInt64`, `SetCoreMask`); test VP8 through FFmpeg |
| Audio | Wwise via `audren` (renderer) and `hwopus` | `audren` (1,251 lines) | Opus service missing; Wwise usage patterns untested |
| Filesystem | 40 `nn::fs` imports, RomFS mount, save, AddOn content | `fsp-srv` (618 lines) | Check save mount (`MountSaveData`, `EnsureSaveData`) and AddOn Content (`MountAddOnContent`) with Unity data layout |
| HID | 102 `nn::hid` imports (Npad, touch, gyro, vibration, IR sensor 24) | `hid` + `hle/input.c` (SDL) | Touch/gyro/IR (only partly required) |
| Account/online | 36 `account`, 75 `friends`, 60 `socket`, … | `acc:u0` | Stub |

Overall *suspected*: **8,000–12,000 lines of new or heavily adapted HLE/services** on top of reused core (LAS: HLE 6,462 + services 2,452 + IPC 246 = 9.2 kLOC, about half game-specific). Main effort is not line count but testing against Unity game.

## 4. Memory model

### Historical continuation: original phase-one findings (as of 2026-10-18)

The following sections preserve the full phase-one feasibility report. Phase two later resolved or superseded several findings; see the update at the top of this document and `docs/recomp-spike-2.md`.

### 4.1 `main.npdm` (measured with `npdm`, without keys; layout based on <https://switchbrew.org/wiki/NPDM>)

| Field | Value | Note |
|---|---|---|
| Magic / size | `META`, 1,620 bytes | |
| Flags0 | `0x37`: 64-bit instructions, **AddressSpace64Bit (39 bits)**, OptimizeMemoryAllocation, DisableDeviceAddressSpaceMerge | Bit 5 was not shown by the script; value read from the raw byte |
| Main thread | Priority 44, core 0 | Kernel capability `ThreadInfo`: priorities 28–59, cores 0–2 |
| **Main-thread stack** | **1 MiB** (`0x100000`) | LAS reads this field (`main.c:141-148`) |
| **SystemResourceSize** | **16 MiB** (`0x1000000`) | Kernel reserves it for page tables; required for `MapPhysicalMemory` |
| Version | 0 | |
| Process category | **No dedicated field** in the NPDM header; `MiscParams.ProgramType = 1` (Application), ACID flags: MemoryRegion **0 = Application**, Production, UnqualifiedApproval | |
| Kernel capabilities | KernelVersion 9.1, HandleTableSize **512**, MiscFlags `EnableDebug` | |
| SVC mask | **50 SVCs** (ACI0 and ACID match), list in `work/recomp/npdm.json` | |
| Services (SAC) | **47** access names, no host services | |
| Heap limit | **Not in NPDM.** The heap comes from the Application region and the game requests it with `SetHeapSize` or `nn::os::SetMemoryHeapSize`. | |

The Application region on retail Switch is roughly 3.2–3.3 GiB (*unverified*, based on a secondary Switchbrew source); LAS uses `HEAP_MAX` = 3.25 GiB (`rt.h:29`). BDSP's actual request is **unmeasured** (not run).

### 4.2 BDSP guest address-space requirements (estimate from measurements)

| Component | Size | Status |
|---|---|---|
| Modules (text+ro+data, decompressed, rounded to 16 KiB) | main 80.0 MB, sdk 13.1 MB, subsdk0 5.8 MB, rtld 0.01 MB = **98.9 MB** (94.3 MiB) | measured |
| bss | 6.2 MB (main 4.3, sdk 0.8, subsdk0 1.2) | measured |
| `main` image vs. LAS slot | **84.3 MB > 64 MiB** (`SDK_BASE - MAIN_BASE`, `rt.h:18-19`) | measured: layout must change |
| Heap | up to about 3.25 GiB (Switch limit) | upper bound |
| Main stack | 1 MiB; the game allocates other guest stacks in the heap | verified |
| TLS | 0x200 B per thread (LAS window 1 MiB) | verified |
| Runtime HLE heap | LAS 224 MiB | verified (`rt.h:25`) |
| NVN pools, alias/mapped memory | within the heap or alias region; size unknown | unmeasured |
| Additional host-side memory | Metal textures/buffers (copies from Tegra-swizzled data), host stacks | *inferred*, unmeasured |

A **compact** guest address space would need roughly 3.6–4.0 GiB with the heap fully used, which barely fits in 4 GiB. The 12.5-GiB window is therefore more than three times the actual requirement; the excess comes from the 4-GiB alias region, the 1-GiB stack window, and gaps between regions.

### 4a. Virtual memory: fixed window, iPadOS, and “no high virtual memory requirements for iOS compatibility”

**What is resident at startup, and what is only reserved?** (inferred from code; neither LAS nor BDSP could be run, so **not measured**)

| Item | Reserved | Resident at startup |
|---|---|---|
| Guest window | 12.5 GiB (`mach_vm_allocate` FIXED, `macos.c:24-28`) | Only pages that are touched. On macOS, the rest remains zero-filled-on-demand (no commit or overcommit). |
| Modules | Within the window | **Everything the loader describes**: LZ4 decompresses text, ro, and data into the window (`loader.c:57-75`) → about **99 MB** for BDSP (bss untouched), plus the NSO file temporarily read (about 47 MB, then released) |
| HLE heap | 224 MiB | Only allocated portions (`hle_alloc` zeroes the requested length) |
| Host thread stacks | **256 MiB per guest thread** | Only touched pages; BDSP thread count unmeasured (*inferred*: dozens—Unity workers, Wwise, loader, GfxDevice, video); 30 threads would reserve 7.5 GiB for host stacks alone |
| Heap (`SetHeapSize`) | Up to 3.25 GiB | Only memory the game touches; Unity/IL2CPP grows its heap incrementally |

On Windows, the “commit everything up front” pattern was identified as a problem (README credit #107: about 9 GB less committed memory). On Apple systems, this is not an issue for **memory consumption** (Jetsam counts touched, “dirty” memory), but it is an issue for the **address space**.

**What does not work on iOS/iPadOS without an entitlement?** (sources below)

| LAS component | iOS/iPadOS problem | Evidence |
|---|---|---|
| Fixed address `0x70_0000_0000` (448 GiB) | The highest valid user address on arm64 outside macOS in public XNU headers is `0xFC0000000` (about 63 GiB). A 47-bit variant appears there only behind kernel-private `EXTENDED_USER_VA_SUPPORT`. `0x70_0000_0000` exceeds the public limit, so `VM_FLAGS_FIXED` fails without an entitlement. With *Extended Virtual Addressing*, XNU code reportedly enables “jumbo” = 64 GB (blog); whether iPadOS kernels enable the 47-bit window is **unverified**. | XNU `osfmk/mach/arm/vm_param.h` (lines 135–153), `osfmk/arm/pmap.c` as discussed in the blog |
| 12.5-GiB window size | An ordinary iOS process reportedly has **15.375 GiB of address space on devices with more than 3 GiB RAM, of which 7.375 GiB is usable** (subtract 4 GiB `__PAGEZERO` and 4 GiB Shared Region). A 12.5-GiB window cannot fit alongside the binary, frameworks, Metal, and heap. The analysis covers iOS 12–15; whether it still applies to current iPadOS versions and M-series chips is **unverified**. | <https://alwaysprocessing.blog/2022/02/20/size-matters> (analysis of XNU source) |
| 256-MiB host stack per thread | Counts toward address space; 20 threads = 5 GiB | `kernel.c:226` and limit above |
| Re-exec on address collision | `execv` may be unavailable on iOS (*inferred*, not checked); iOS also lacks a macOS-style collision | `main.c:37-52` |
| Guest address = host address; constants embedded in code | Requires a *fixed* build-time base (immediates from `ADRP/ADR`, jump tables, address table); a runtime-selected base would not work this way | `lifter.py` (`hx(val)`), `gen.py` |
| `dlopen` of game library | A signed library embedded in the app bundle is allowed; creating/compiling one on-device is not (the “prepackaged” path) | Architecture requirement, not checked |
| No JIT required | Guest code is AOT-compiled; FP/NEON uses `.inst` inline assembly and should be unproblematic (*inferred*) | |

**Entitlements (Apple documentation, checked 2026-10-18):**

- *Extended Virtual Addressing* (`com.apple.developer.kernel.extended-virtual-addressing`, iOS/iPadOS 14.0 and later): provides a “larger addressable space,” intended in part for games with mapped assets: <https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.extended-virtual-addressing>. It **changes the address space, not the memory limit**.
- *Increased Memory Limit* (`com.apple.developer.kernel.increased-memory-limit`, 15.0 and later): permits exceeding the standard limit “on supported devices”; the app must also work without the extra memory, and available memory can be queried with `os_proc_available_memory`: <https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.increased-memory-limit>. A field report (iPhone 17 Pro, 8 GB) says it raises the resident-memory limit and makes no difference on 4-GB devices: <https://zenn.dev/mtfum/articles/ios_memory_entitlements>. Apple does not publish Jetsam limits by iPad model; forum figures (for example, “about 6 GB on 8 GB devices, about 12 GB on 16 GB devices”) are **unverified**. Measure `os_proc_available_memory` on the target device.
- **Free Personal Team:** Apple's “Supported capabilities (iOS)” table lists *Extended Virtual Addressing* only for ADP and ADEP (paid), **not** for “Apple Developer” (free accounts): <https://developer.apple.com/help/account/reference/supported-capabilities-ios> (HTML table checked). The same applies to “Increased Debugging Memory Limit.” *Increased Memory Limit* is **not listed** in this table; whether Xcode allows it with a Personal Team is **unverified** (*inferred*: no; check first with an empty test project).

**Does a fixed 12.5-GiB window conflict with the “no high virtual memory requirements for iOS compatibility” requirement (`goal.md`)?** Yes, in three ways (verified from the sources above): (1) the window exceeds the standard address space; (2) its fixed address is outside the public limit and would require both an entitlement and a compatible kernel; (3) Extended Virtual Addressing is unavailable to a free team. The “guest = host address, fixed base” model is **unsuitable for iPadOS**, even if it works on macOS. Resident memory (Jetsam) is not the primary issue; address space is.

### 4b. Alternative: pointer rebasing / 32-bit offsets in generated C

| Variant | Idea | Estimated effort | Risk |
|---|---|---|---|
| **A: Runtime base** | Keep guest addresses as 64-bit values, but rewrite every embedded constant (`ADRP/ADR`, literal loads, jump-table `case`, address tables) as `g_base + off` | Lifter and generator: about 437,000 ADR/ADRP sites in `main`, plus tables; runtime unchanged (guest = host, only the base moves) | The window still has to be placed at a system-selected address and all guest pointers (such as stored vtable pointers and relocations) must be fixed up at runtime; 12.5 GiB remains too large, so the window must shrink to ≤ 4 GiB. Medium |
| **B: 32-bit offsets** | Guest pointers are values < 4 GiB. Each access becomes `*(T*)(g_base + (uint32_t)ea)`; constant guest addresses stay unchanged (build-time base 0). Runtime gives the guest only addresses < 4 GiB (heap, stacks, TLS, and manually placed modules). | Lifter: memory emission at about 11 locations in `lifter.py` (`LD*/ST*`, pairs, exclusives, `DC ZVA`, literal), plus inline-assembly path for FP/NEON (289,000 accesses in `main`: set base register to host address before instruction, reverse the adjustment after write-back) or use FP in `c` mode. Runtime: **about 456 `(uintptr_t)` conversions and 209 typed pointer casts** in HLE/Services/NVN/Kernel (introduce `g2h()`), plus `G()` macro in `nvn.h`. Roughly **3–6 weeks** for generator and runtime changes, followed by lengthy debugging. | Silent truncation errors (guest may store tagged pointers or assume 39-bit addresses; LAS itself documents the 39-bit limit, `rt.h:14`); Boehm GC and Unity may pack pointers; an extra addition per memory access (ARM64 has `ldr x, [base, w, uxtw]`, so *inferred* overhead is small); harder debugging (crash instead of an access at the wrong address) |
| **C: Smaller window at a fixed low address** | Use a build-time base below, for example, 7 GiB | Low effort (constants in `rt.h`) | Not guaranteed to be free on iOS (ASLR, frameworks); can only be tested on-device |

Assessment: **B is the robust route for iPadOS**, because it limits address space to ≤ 4 GiB, does not depend on the platform's chosen base, and requires no entitlement. It turns the lifter into a different product (no longer a 1:1 port of LAS) and gives up the simplicity of “guest = host.” On **macOS**, the fixed window is sufficient.

## 5. Unity-specific risks and effort estimate

| Area | Finding | Replacement / effort | Status |
|---|---|---|---|
| **C++ exceptions (IL2CPP)** | `main` imports `__cxa_throw`, `__cxa_allocate_exception`, `__cxa_begin/end_catch`, `__cxa_rethrow`, `_Unwind_Resume`, `__gxx_personality_v0`; `sdk` contains libunwind (`_Unwind_RaiseException`); **2,917 functions with LSDA** (landing pads) among 216,168 FDEs; `setjmp`/`longjmp` also occur in `main` | Landing pads sit inside functions, and `rt_dispatch` cannot jump to them (it only knows function starts); `RET` returns to the host caller, not the guest caller. **The “host stack = guest stack” model breaks for every caught managed exception.** Options: emit landing pads as entry points and replace stack unwinding (host `setjmp` per function with LSDA, custom unwinder over `.eh_frame`, or an error-return convention). Requires research and generator work. | measured/verified; effort *inferred* high (weeks to months) |
| **Boehm GC (libil2cpp)** | 13 `GC Warning …` strings and `GC_general_register_disappearing_link` in `main`: Boehm. It conservatively scans stacks, registers, and data segments, and suspends threads (`SuspendThread`/`GetThreadContext` are imported). | Guest registers live in `Cpu` (good: scannable), but an arbitrarily suspended host thread may hold guest values in host registers. Needed: cooperative safepoints (poll at function entry and loop back-edges, with overhead) or `thread_suspend` + `thread_get_state` (Mach; *inferred* to be allowed for the app's own threads on iOS, not checked). SVC 0x32/0x33 are missing in LAS. | verified/inferred |
| Engine threads | Strings: `UnityGfxDeviceWorker`, `Loading.PreloadManager`, `Loading.AsyncRead`, `Background Job`, `AK::IOThread` | Run as host threads as in LAS; count and stack demand unmeasured; choose smaller host stacks (256 MiB is too large for iOS) | verified/open |
| Job system / workers | Unity jobs use `nn::os` threads, core masks, and events | Threads and `WaitForAddress` are present | inferred |
| Wwise | Statically linked in `main` (AK:: strings), output via `audren`, decoding probably `hwopus`; streaming I/O thread | Port `audren` (1,251 lines), implement `hwopus` (libopus), run Wwise soundbanks unchanged (1:1) | inferred |
| VideoPlayer | 23 `movie::` imports from `subsdk0` | Extend `hle/movie.c` (15/23); check VP8 decoding with FFmpeg/VideoToolbox; VP8 on iOS untested (`docs/kernziel.md`) | verified |
| `nn::fs` | 40 imports, RomFS mount (from our `work/romfs` or package), SaveData, AddOn | Expand `fsp-srv`; save layout is known from `docs/save-format.md` (user requirement: preserve save compatibility because guest code writes the save unchanged) | verified |
| `nn::hid` | 102 imports, Npad, touch, gyro, vibration | Use `hle/input.c` (SDL) as a pattern; add native touch/gyro support for iPad | verified |
| `nn::audio` | 50 imports | `audren`/`audout` present, `audin` missing (microphone, *inferred* unused) | verified |
| `nn::account` | 36 imports (user selection, UID for SaveData) | `acc:u0` present; must support Unity calls | inferred |
| Online/Pia/NEX | `friends`, `ldn`, `bcat`, `ec`, `nifm`, `ssl`, `socket`: 242 `nn::` imports plus 42 C API imports | Stubs with error codes; game logic should run offline (`docs/spielcode-inventar.md`: online features can be stubbed) | inferred |
| Graphics | Unity NVN paths, 13,710 shader programs | Maxwell → MSL from LAS (see `docs/referenz-las-shader.md`); Unity uses more features than LAS (MRT, instancing; no compute or tessellation) | open |

**Compared with LAS (custom engine):** LAS does not involve a managed runtime layer (GC, exceptions, reflection metadata, many threads); the game calls into nn/NVN relatively directly. BDSP brings the full Unity engine and IL2CPP runtime, Wwise, and video path along, all of which must be carried with the guest code. In BDSP's favor, recompilation brings everything over at once (1:1, including engine behavior and game logic), and instruction coverage is unusually high (58 of 14.1 million words). Against it are exceptions, GC thread suspension, the 3.3-GB compiler outlier, the iPadOS address-space issue, and the size (1 GB of C, roughly 300 MB of machine code).

## 6. Options compared

**(D)** Unity 6 rebuild with hand-reconstructed logic (about 39,100 gameplay methods so far, `docs/spielcode-inventar.md`) versus **(R)** LAS-style recompilation of the entire NSO, including the Unity engine.

| Criterion | (D) Unity 6 rebuild | (R) Recompile the entire NSO |
|---|---|---|
| 1:1 fidelity | Only as good as the reconstruction: hand-written logic (39,100 methods), engine behavior (Unity 6 instead of 2019.4), shaders replaced/translated. Differences in randomness, timing, and ordering are possible and must be checked against the original. | **Logic and engine behavior match automatically**, provided the CPU lifter, kernel/IPC emulation, and GPU path are correct. Differences come from emulation (time, threads, GC timing, floating-point details), not hand reconstruction. |
| Effort | Very high and grows with game scope (battle 12,575 methods, UI 7,723, field/entities 6,613, …); parallelizable and incremental | High initial effort (port core, generator for 3 modules, exceptions, GC suspension, ~35 services, memory model B), then *inferred* smaller remainder; hard to predict because one defect affects everything. Time required: **cannot estimate without a phase-two spike** |
| Main risks | Scope; silent discrepancies; Unity 6 differences from 2019 in physics, animation, Timeline, shaders | IL2CPP C++ exceptions (core blocker), Boehm GC/thread suspension, iPadOS memory model, build size/time, Maxwell shader coverage, performance (registers in memory) |
| Core requirement (repository without derived code) | Met: original code, data comes from the dump | **Can be met, but requires a pipeline:** repository contains only the recompiler and runtime; generated C (1 GB) and library are produced locally during the build (`work/`, gitignored) and remain only in the local binary, which is not distributed. The build must run on the development machine (Xcode compiles the C). The generator must not check in addresses/game bytes into source files (LAS's game-specific `patches.py` therefore cannot be reused). |
| iPad memory/performance | Known order of magnitude for Unity 6 on iPad; memory can be controlled | Address space requires variant B (≤ 4 GiB); guest heap up to about 3.25 GiB plus host GPU-data copies could be tight on 8-GB devices without Increased Memory Limit (unmeasured); performance *inferred* at 2×–5× slower than native due to `Cpu` structure and dispatch (**not measured**); binary 300 MB+ |
| Maintainability | Normal C#/Unity code, readable and testable | Generator and runtime form a custom compiler project; LAS README says the source was “almost entirely” AI-generated (quality unknown); game updates require a new lift and address adjustments; debugging uses only host backtraces `f_<address>` |
| Legal position (not legal advice) | Reconstruct logic in original words/code; whether implementing from decompiler output is too close to the original remains an open question | Generated artifact is a mechanical translation of Nintendo code. It is not distributed, but remains a derivative work of the user; the “repository + own dump” arrangement is the same. LASRecomp is MIT with a game-file exclusion; some contributions are AI-generated. Seek legal advice before public distribution. |

## 7. Conditional recommendation (no decision)

**Option 1: Stay with (D).** Makes sense if phase two below hits a blocker or the recompilation schedule is too tight. No new dependencies.

**Option 2: Phase-two spike for (R) (“smallest runnable piece”)**, in this order, with a stop criterion for each:

1. **Exception test (go/no-go criterion).** Minimal example: `rtld`+`main`+`sdk` through the first caught managed-exception path; design the solution (landing-pad entry plus stack unwinding) in a one-day spike and test it on 3 real functions with LSDA. If it fails, (R) is not viable for BDSP.
2. **Lifter additions:** `LDXP/STXP/LDAXP/STLXP` (58 words), a third dispatch table for `subsdk0`, module layout with a larger `main` slot; SVC 0x32/0x33/0x36/0x28/0x2F/0x23/0x20/0x5F.
3. **Run only `rtld`+`sdk`+`subsdk0`+`main` through `nnMain` on Mac:** target “first log line from Unity startup” (no graphics). Measure resident versus reserved startup RAM, thread count, `SetHeapSize` value, and number of required services.
4. **Compile times:** full generation to disk (1 GB), build with `-O1`; isolate outliers (functions > 1 MB with `-O0`/`optnone`).
5. **Memory model B:** first test a small subset with generator switch `--rebase32`, before changing the runtime. On an iPad, test a 4-GiB reservation with no entitlement (Personal Team) and report `os_proc_available_memory`.
6. **Graphics last:** Unity Maxwell programs against `translate.c` (instruction coverage, `docs/referenz-las-shader.md` §11).

**Conditions for (R) to remain viable:** (a) exceptions and GC thread suspension are solvable; (b) 32-bit offsets work with BDSP (no pointer tags); (c) full build under about 30 minutes on Mac; (d) iPad (M-series) performance reaches 60 FPS (measure in the spike); (e) the legal position is acceptable for personal use.

**Hybrid approach (*inferred* to be useful):** use (R) as a **reference implementation** for fidelity checks against (D) (same inputs, compare state), even if (R) is not shipped on iPad.

## 8. Open and unverified points

- Let's Go figures (123,612 functions, 550 MB C): **unverified** (not in the clone).
- No runtime measurements: resident memory, thread count, performance, BDSP heap size.
- Lifter correctness and matching floating-point/NEON semantics have not been checked; only coverage was measured.
- Function counts before/after fixed-point iteration and code-pointer relocations are only partially measured.
- Jetsam limits by iPad model and address space on current iPadOS versions are unverified; Xcode support for *Increased Memory Limit* with a Personal Team is also unverified.
- The 8-MB function (largest, 8,010,651 bytes of C) was not compiled; link time and behavior of the 300-MB library are unmeasured.
- Earlier statements in `docs/recomp-referenzen.md` (“game code is compiled on the user's machine, which is impossible on iPadOS”) apply to LAS's initial setup, not the prepackaged path; “0.7–1 GB C” is now measured (1.01 GB).
