# Native Linux build host

> **Status:** The remote Linux machine and the SSH/rsync workflow of the measurements below no longer exist. Linux builds now run only locally from the repository root, with the scripts in `scripts/recomp/linux/local/` (see [BUILD.md](BUILD.md), section 6). The figures in the historical report are reference numbers from 2026-10-19.

The native ARM64 recompilation builds an x86-64-v3 runtime with Vulkan and a
Qt 6 frontend. The Unity rebuild is deprecated and unrelated to this target.

The maintained commands and package list are in [BUILD.md](BUILD.md), section 6.
The local Linux build scripts are under `scripts/recomp/linux/local/`. Local
artifacts are under `work/recomp/` (gitignored); the scripts write their
statistics and timing logs to `logs/` in the repository root. Game data, keys,
and generated code are not committed.

Install Qt6 Widgets, SDL3, Vulkan headers/loader, shaderc, VMA, and FFmpeg
development packages through the Linux distribution. Build scripts use pkg-config
and do not copy Homebrew headers, download VMA, vendor Qt, or install packages.
The existing MIT-licensed recompilation runtime is not replaced by these changes.

The in-process Qt frontend owns its Vulkan surface and supports native Wayland
and X11. The older separate-process host remains an X11 fallback. Compile with
`scripts/recomp/linux/local/vk_build.sh --qt`; launch using
`scripts/recomp/linux/local/vk_qt.sh`.
System packages and a valid desktop-session environment are required. See
[BUILD.md](BUILD.md), section 6, for the local user workflow.

Both Qt paths were previously built and briefly exercised with the old header
setup. The package-only build needs a fresh native build after missing devel
packages are installed. Unit/preflight tests are not a substitute for that check.
Linux audio, extended gameplay/rendering validation, and Windows remain incomplete.

Historical measurements: see the report below. German version: [recomp-linux.de.md](recomp-linux.de.md).

## Historical investigation report

The following report records measurements from an earlier workflow that used a remote Linux machine, which no longer exists, so the figures are historical reference values. For builds, use [BUILD.md](BUILD.md), section 6, and the local scripts in section 2.1.

### Linux as build and test machine for the recompilation

Measured 2026-10-19, from 10:48 to 12:20; the generator revision for each run is given in sections 4 and 5. Based on `docs/recomp-spike-2.md` (phase 2, Mac figures), `docs/recomp-gate1.md` (work state `ap-recomp-3`), and `research/LASRecomp` (MIT, read-only/runtime-imported).

**Labels:** **measured** = obtained with the scripts under `scripts/recomp/linux/` on the Linux machine (raw figures in the `*.stats` and `*.times` logs). *Suspected* = inference without a test. **No game content** is in the repository: generated C, objects, libraries, and NSOs are kept only under gitignored `work/`; only abbreviated hashes and sizes are recorded here.

## 1. Summary of results

| | Mac (Spike 2) | Linux machine (this measurement) |
|---|---|---|
| Machine | Shared M1 Pro, load 8–14 | x86-64 CPU, 6 cores / 12 threads, 30 GB RAM, dedicated |
| SIMD/FP mode of generated C | `asm` (inline assembly, arm64) | `c` (portable C, `-march=x86-64-v3`) |
| Generate, 4 modules, one core | 74 s | **51 s** (c) / 57 s (asm, comparison only) |
| Compile all (Spike threshold: per-function file >1 MB → `-O0`) | **937 s** with 3 jobs | **986 s** with 3 jobs (same job count: effectively equal), **692 s** with 10 jobs |
| Compile with `-O0` for per-function files ≥300 KB | not measured | **310 s** (12 jobs), 384 s (6 jobs), 388 s (10 jobs) |
| Total compiler CPU time (3 jobs) | 2,711 s | 2,868 s user (+6%); with 10 jobs, 4,584 s (SMT: 10 jobs on 6 cores) |
| Target library | 224 MiB (`libgame.dylib`) | 327 MiB (`libgame.so`), 341 MiB with 300 KB threshold |
| Largest compiler peak | 1.7 GB | 1.6 GB (single function, 790 KB C) |
| Boot probe (SDK constructors through `svcBreak`) | see Spike 2, section 5 | **identical**: same SVC counts and service sequence |

**Assessment:** Per core, the Linux machine is **not faster** than the M1 Pro (986 s versus 937 s at 3 jobs, with the same compiler work per file; the Mac was loaded). Its advantage comes from **parallelism and exclusive use**: 6 cores / 12 threads, 30 GB RAM, no competing process, plus the `-O0` rule for outliers ≥300 KB. This cuts the full build from 15.6 minutes to **5–6.5 minutes** and an incremental build to about a minute (section 9). The Linux machine is **not a replacement** for the Mac build: SIMD/float bit accuracy and the final macOS/iPad build (asm mode, Xcode) remain on the Mac.

## 2. Setup

### 2.1 Scripts (`scripts/recomp/linux/local/`)

Run the scripts from the repository root. `common.sh` is sourced by the others and is not run directly.

| File | Purpose |
|---|---|
| `setup.sh` | Checks tools and Python packages (`lz4`, `capstone`, `unicorn`), compares the inputs with `work/exefs.sha256` if that file exists, and installs nothing |
| `gen.sh [c\|asm] [modul ...]` | Generates the C of the four modules (`rtld`, `main`, `sdk`, `subsdk0`) with the LAS lifter (`eh_gen.py`) and measures time, RAM, and size; `c` is the default, `asm` is for comparison only on x86 |
| `compile.sh [c] [--neu]` | Compiles the generated C in parallel (`JOBS`, default 10) with `-O1`; single-function files above `THRESH_O0` (default 300 KB) get `-O0`; links `libgame.so` |
| `build_all.sh [--neu] [--nur-gen] [--nur-compile]` | Runs `gen.sh c` and `compile.sh c` with total time; also accepts `--tag=`, `--jobs=`, and `--schwelle=` (the `-O0` threshold in bytes) |
| `las_runtime.sh` | Compile check of the Linux path of the LAS runtime without graphics; reports ok or error per source file |
| `probe.sh <test>` | Linux counterparts of the spike probes: `eh`, `eh-real` (after `eh`), `rebase32`, `gc`, `bench`, `boot`, `boot-las` (after `boot`), and `bdsp` (Gate-1 runtime, section 7); `alle` runs all except `bdsp` |
| `incr_test.sh` | Measures incremental rebuilds on a copy of a finished build (scenarios A, B, C) |
| `vk_build.sh [--qt]` | Builds rt-bdsp with the Vulkan backend (after `build_all.sh`); `--qt` also builds the in-process Qt frontend |
| `vk_run.sh` | Starts the Vulkan build `work/recomp/bdsp_boot_vk` headless by default; needs `work/romfs` |
| `vk_qt_build.sh` | Builds the separate-process Qt host (CMake) into `work/recomp/qt-host` |
| `vk_qt.sh` | Starts the Qt frontend with the Vulkan game: the in-process build if `vk_build.sh --qt` was run, otherwise the separate-process host (`BDSP_QT_PROCESS=1` selects it) |

Further files: `gc_prove_linux.c` is the Linux version of the GC proof (signals instead of Mach) and is used by `probe.sh gc`. `compat/mach/*.h` is a Mach compatibility layer (time, thread suspension by signal, `task_info`, `mach_vm_*`) so that `rt-bdsp` compiles unchanged on Linux (section 7).

The working copy changed during the measurements: `ap-recomp-3` was editing `eh_gen.py` and `rt/cpu.h` in parallel (section 8).

## 3. Setup (measured)

Linux machine: Fedora 44, Linux 7.2, clang 22.1.8, gcc 16.2.1, GNU make 4.4.1, Python 3.14.7 (same as Mac `tools/pydeps`, cpython-314), x86_64 with AVX2/FMA/BMI2, 174 GB free under `/home`. Clang recognizes target `aarch64-linux-gnu` (for synthetic guest programs in probes). `pip install --user lz4==4.4.5 capstone==5.0.9 unicorn==2.1.4`; versions match the Mac and imports were checked. The measurements used no sudo, audio, graphics, or disk scan.

Inputs (verified with `sha256sum -c` against the list made on the Mac; all four **OK**; short hash = first 16 hex digits):

| File | Size (bytes) | SHA-256 (short) |
|---|---:|---|
| `rtld` | 7,187 | `bc175ad9865adb48` |
| `main` | 37,895,896 | `9c6b1d847d8fb3a1` |
| `sdk` | 5,755,393 | `1c9f198a91c0bcfe` |
| `subsdk0` | 3,409,290 | `67a38fcf89cd13e0` |

Not included in the measurements: `main.npdm`, keys, NCA/XCI/NSP, RomFS, saves, LASRecomp `third_party`. Storage required on the Linux machine: about 4 GB (1 GB generated C each for `c` and `asm`, 0.8 GB of objects per mode, 0.35 GB library).

## 4. Generator (measured)

`eh_gen.py gen` (LAS lifter plus phase 2 extensions), one core, four modules sequentially (`gen.sh`). Generator revision as in Spike (repository state around 10:48, size-based chunk selection).

| Module | Functions | C files | C size | C time | C peak RAM | asm files | asm size | asm time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| main | 218,195 | 918 | 817.3 MB | 41.3 s | 4.3 GB | 1,047 | 865.6 MB | 47.5 s |
| sdk | 38,342 | 180 | 105.0 MB | 5.6 s | 0.6 GB | 190 | 107.6 MB | 5.8 s |
| subsdk0 | 13,719 | 158 | 63.2 MB | 3.2 s | 0.35 GB | 161 | 63.9 MB | 3.2 s |
| rtld | 43 | 2 | 0.11 MB | 0.1 s | — | 2 | 0.11 MB | 0.07 s |
| **Total** | **270,299** | **1,258** | **985.6 MB** | **50.6 s** | — | **1,400** | **1,037.2 MB** | **56.9 s** |

- Function count is the same in both modes (the lifter does not choose function boundaries based on SIMD mode). The `c` mode emits about 5% less C text (float/SIMD as short calls into `simd.h` rather than long inline-asm blocks), but more machine code (section 5).
- **The generator is platform-independent and deterministic:** the Linux machine's `asm` run produced **byte-for-byte the same 1,400 files** as Mac `work/recomp/gen4` (all chunk file hashes compared; total 1,037,185,555 bytes). The `asm` mode can be generated on x86 but not compiled (arm64 inline assembly). Generation on the Linux machine is therefore a full replacement for Mac generation; only the compile mode differs.
- Python 3.14 on the Linux machine is faster for generation than on the loaded M1 Pro (50.6 s versus 74 s); `main` requires 4.3 GB (Mac: 4.8 GB).

## 5. Full build of the four modules (measured)

`compile.sh`: `clang -O1 -fno-strict-aliasing -fvisibility=hidden -w -fPIC -march=x86-64-v3` (LASRecomp/Makefile Linux/x86-64 flags), `xargs -P 10`, largest files first; per-function files above a threshold use `-O0`; time/RAM per file via `/usr/bin/time`; total peak RAM sampled from `/proc/meminfo`; link with `clang -shared`.

| Run (generator revision) | Files (`-O1`/`-O0`) | Compile wall time | + link | Σ wall / Σ user | Median | >10 s / >60 s | Largest compiler | Total peak RAM | Library |
|---|---:|---:|---:|---|---:|---|---:|---:|---|
| 1 MB threshold (as in Spike), old revision | 1,248 / 10 | **688.5 s** | 1.2 s | 4,658 s / 4,584 s | 1.66 s | 44 / 9 | 1.6 GB | 1.96 GB | 341,792,872 bytes (`__text` 329.4 MB) |
| 300 KB threshold, old revision | 1,201 / 57 | **388.0 s** | 1.3 s | 3,097 s / 3,035 s | 1.61 s | 26 / 3 | 0.84 GB | 2.06 GB | 356,531,656 bytes (`__text` 344.2 MB) |
| 300 KB threshold, new revision (fixed 32-KiB windows, `ap-recomp-3`, 2,369 files), 10 jobs | 2,312 / 57 | **387.8 s** | 1.4 s | 3,038 s / 2,963 s | 0.74 s | 27 / 2 | 0.84 GB | 1.98 GB | 357,485,784 bytes (`__text` 345.0 MB) |
| Same, **6 jobs** | 2,312 / 57 | 384.0 s | — | 2,071 s / 2,014 s | — | — | 0.84 GB | 2.03 GB | — |
| Same, **12 jobs** | 2,312 / 57 | **309.9 s** | 1.4 s | 3,291 s / 3,189 s | — | — | 0.84 GB | 1.73 GB | 357,485,784 bytes |
| 1 MB threshold, new revision, **3 jobs** (comparison with Mac Spike) | 2,359 / 10 | **986.4 s** | 1.4 s | 2,934 s / 2,868 s | 0.51 s | 27 / 7 | 1.62 GB | 1.64 GB | 342,747,000 bytes (`__text` 330.3 MB) |

**Outliers** (old revision, 1 MB threshold): the three slowest files are the same single-function files as in the Mac Spike, but substantially more expensive in `c` mode:

| File | C size | Linux machine `-O1` (`c`) | Mac (`asm`) | Linux machine peak RAM |
|---|---:|---:|---:|---:|
| `main_357` (one function) | 372 KB | **497 s** | 214 s | 0.48 GB |
| `main_694` (one function) | 791 KB | 292 s | 87 s (870 KB) | **1.6 GB** |
| `sdk_048` (one function) | 488 KB | 204 s | 187 s | 0.68 GB |
| `main_639` function, 8 MB C, `-O0` | 8.0 MB | 3.3 s | 4.0 s | 0.84 GB |

- **The full-build time is governed by the slowest individual item:** with the 1 MB rule, the critical path is 497 s (one 372 KB function with 10 jobs; 242 s with 3 jobs); the sum of all files divided across 10 jobs would be only about 466 s, while wall time was 688 s. With `-O0` starting at **300 KB** (57 rather than 10 files), wall time falls to 310–388 s depending on job count; the slowest file is then 216 s (260 KB). Variation among 6, 10, and 12 jobs (384, 388, 310 s) is within the effects of SMT time slices and outlier order; a clean job-count curve was not measured. Recommendation: 10–12 jobs. Runtime cost of the additional 47 `-O0` files was **not measured**; the library grows by 14.7 MB.
- The largest per-file RAM use is 1.6 GB (not 3.3 GB). At 10 jobs, total machine peak RAM was **2 GB** (sampler, above idle): RAM is not a build bottleneck; cores are.
- **Median 0.5–1.6 s per file; 2,868 s compiler CPU (3 jobs) versus 2,711 s on Mac:** each x86 `c` file costs roughly as much as arm64 `asm`, although it produces more machine code. With 10 jobs on 6 cores (SMT), aggregate time rises to 4,584 s as two compilers share a core (individual times up to 60% longer). The 8 MB `main` outlier (one function) takes **108 s** and 0.83 GB with `-O1` (Mac: 153 s, 867 MB), and 3.3 s with `-O0`.
- Library: 327 MiB versus 224 MiB (`asm`, Mac); `c` mode produces about 57% more machine code. The binary is ELF rather than Mach-O, so sizes are only roughly comparable.

## 6. Linux LAS runtime and probes (measured)

### 6.1 LAS runtime (`las_runtime.sh`, no graphics)

`runtime/platform/linux.c`, core (`dispatch`, `kernel`, `ipc`, `loader`, …), `services/*`, `hle/*`, and `nvn/*` (without Vulkan backend) were compiled individually: **53 of 55 sources succeeded; 2 failed because files from `third_party` were missing** (`AreaTex.h`, `imstb_truetype.h`, intentionally not included). `platform/linux.c` compiled. The Linux machine had no SDL3, FFmpeg, Vulkan, or shaderc development packages and no internet; headers for this compile check came from Homebrew. **It was not possible** to link and launch LAS itself (requires libraries, Vulkan driver, graphics); packages in section 10 are missing, and that was outside this task.

### 6.2 Spike probes on x86 (`probe.sh`, c mode; results at 11:30 revision)

| Probe | Mac (Spike 2) | Linux x86 `c` |
|---|---|---|
| `eh`: exception test T0–T6 with real SDK unwinder | passed, 44.8 µs per throw+catch | **passed**, 26.8 µs per throw+catch (4 frames) |
| `eh-real`: 180 real LSDA functions from `main` | 100 reached, 100 correct, 25 not called, 55 environment, 0 mismatches | **identical** (100 / 100 / 25 / 55 / 0) |
| `rebase32`: 32-bit guest addresses | passed, 47.0 µs | **passed**, 29.8 µs |
| `gc`: stop at arbitrary point, pointers only in registers | 19,293/19,293 in window, only in `Cpu` + guest stack | **19,565/19,565** (Linux signal stop instead of Mach, x86 register set) |
| `bench`: recompiled versus native | factors 1.9 / 4.3 / 4.0 / 1.5, all results equal | integer **1.5**, `fib` **3.9**, indirect **1.6**, float **12.0** (result **differs**) |
| `boot`: custom mini-services | `sm:` → `lm` → `apm` → `appletOE` → `aoc:u` → `ectx:aw`, then `svcBreak` | **identical**: 8 distinct SVCs (`0x06 0x0c 0x1f 0x21 0x25 0x26 0x29 0x2c`), 29 calls (`GetInfo` 13, `SendSyncRequest` 9) plus 2 internal counters (`0xff`), `svcBreak`, 115 SDK constructors, peak RSS 115 MB |
| `boot-las`: LAS IPC/service layer | `am` commands 900/91 unhandled, then `svcBreak`; 557 SVCs, `QueryMemory` 514 | **identical** (557 SVCs, 9 distinct, `QueryMemory` 514, same service sequence) |
| `bdsp`: Gate 1 runtime `rt-bdsp` (11:46 revision, section 7) | — | builds and starts on Linux (Mach shim in `compat/`): 115 SDK and 417 `main` constructors run, guest thread created, guest reaches **`nnMain`** and stops in `nn::fs::QueryMountRomCacheSize` at RomFS (deliberately absent on the Linux machine). 12:18+ revision (NVN/Metal/UI, Gate 2) no longer links on Linux |

**x86 `c` boot probe: how far does the guest get?** Exactly as far as Mac `asm`: `nn::init::Start`, `nnosInitialize` (12 `GetInfo`, `QueryMemory`, thread ID/priority), all **115 SDK constructors**, `sm:` initialization, `lm` (domain conversion, `OpenLogger`), `apm`, `appletOE`; then the SDK aborts (`svcBreak`, reason 0) because `ectx:aw` is missing or LAS has not implemented `am` commands 900 (`ICommonStateGetter`) and 91 (`ISelfController`). This is the phase 2 finding and prompted Gate 1. **There is no behavioral difference between arm64 `asm` and x86 `c` CPU paths up to this point.**

**Probe findings:**

1. **Float benchmark differs (`bench`, FMA loop):** **Correction (`docs/recomp-diff.md`, section 6):** the difference is the NaN sign (ARM default NaN `0x7FF8…` in recompiled code and Unicorn, x86 default NaN `0xFFF8…` in native reference), not FMA fusion by the recompiled code; against Unicorn as reference, recompilation agrees in all runs. The original, superseded hypothesis was that the comparison used a *reference compiled natively for x86*; clang chose a different fusion for `b * a + v * 0.25` (which of the two multiplications to fuse into `fma`) than the aarch64 compiler for guest code. Thus the difference is in the **reference**, not shown to be in recompilation. It nevertheless shows that a bitwise comparison against true arm64 semantics is not possible on the Linux machine (see section 8). Float factor 12 (Mac: 4) shows the cost of `c` mode: guest registers and SIMD operations go through the `Cpu` register file in memory.
2. **T7 (`setjmp`/`longjmp`, newly added by `ap-recomp-3`) fails on the Linux machine:** `rt_nle_enter: no frame for pc=…514`; in test guest module, generator reports `setjmp_returns: 0`. Function `_find_setjmp_returns` searches `n.syms` for NSO symbols; the mini-linker (`mini_link.py`) does not write them for test modules. Whether the test currently passes on Mac was not checked (work in progress). In this case, the probe reruns without T7 so T0–T6 and throughput can still be measured.
3. `rt/cpu.h`/`rt32/cpu.h` change frequently; probes therefore rebuild their objects on each run (no stale objects when chunking changes), and `compile.sh` rebuilds everything after header or flag changes.

## 7. Gate 1 runtime (`rt-bdsp`) on the Linux machine

Of the runtime's nine source files in `ap-recomp-3` (11:46 revision), **seven compile unchanged** on Linux; `kernel.c` and `main.c` need Mach calls at four sites: time (`mach_absolute_time`), suspending other threads (Boehm GC: `thread_suspend`/`resume`), stack size (`pthread_get_stacksize_np`), and memory reporting (`mach_vm_region`, `task_info`, `mach_vm_allocate` for reserved window). `scripts/recomp/linux/compat/mach/*.h` supplies these for the Linux build only (not a replacement for Mac semantics); source files remain unchanged (`-I scripts/recomp/linux/compat`). Result (11:46 revision, `bdsp_boot` from runtime and `c` objects, 351 MB, images from `mkimages.sh`): runtime loads `main`/`sdk`/`subsdk0`, runs 115 SDK constructors, creates first guest thread (`CreateThread`), answers `IParentalControlService` with default response, executes 417 `init_array` entries from `main`, guest reaches **`nnMain`** (backtrace `nnMain+164` → `nn::fs::QueryMountRomCacheSize` → `CanMountRomForDebug` → `SendSyncRequest`), then runtime exits with `FATAL: RomFS folder work/romfs is not readable` (11 s, 172 MB RSS; crash handler subsequently reports SIGSEGV at host address 0x39 on shutdown; cause not investigated, likely cleanup path). **The RomFS stop was intentional:** RomFS and `main.npdm` were not part of the inputs (the task excluded game content other than NSOs). Gate 1 could not proceed past the first RomFS access on the Linux machine unless the user explicitly authorized data.

**12:18 and later:** `ap-recomp-3` added `rt-bdsp/nvn/` (NVN layer, Metal, SDL, `ui_run`, `nvn_glue_init`) for Gate 2. It is macOS-specific and no longer links on Linux; `probe.sh bdsp` then exits with a clear message (the log of the 11:46 run stayed on the former remote machine). The Linux machine remains useful for generation, builds, and CPU probes; from Gate 2 onward, the runtime needs the NVN/Metal layer and no longer runs on Linux. Moving the four Mach sites (time, thread suspension, stack, memory report) behind a small platform layer is required to continue booting on the Linux machine.

## 8. Limits

- **x86 `c` mode ≠ arm64 `asm` mode.** **Per `docs/recomp-diff.md`: c mode is bit-exact against Unicorn (Cortex-A57) and M1 for 93.5 million cases per variant (plus 560 million and 259.8 billion exhaustive cases), except for FPSR cumulative flags; the following limitation now applies only to those flags and compiler/MXCSR state.** The `c` mode lowers FP/SIMD to portable C (`simd.h`, `simd_fp.h`); `asm` mode runs arm64 inline assembly on Apple Silicon. Float/SIMD bit semantics (NaN handling, rounding, FPCR/FPSR flags, `fmadd` fusion, denormals) are **verified against real arm64 instructions only on Mac**; a successful run on the Linux machine says nothing about that. This also applies to performance: the factor measured there (float 12) is not the Mac/iPad factor.
- **Final macOS/iPad build always comes from Mac/Xcode** (Mach-O, arm64, `asm` mode, code signing, entitlements, Metal). The library built on the Linux machine is an ELF x86-64 object, usable only for probes.
- Functional probes (exceptions, memory model, boot, service layer, dispatch, GC window) are platform-independent and ran identically; thread suspension is not (Linux uses signals; Mac/iPad use Mach `thread_suspend`).
- The measurements built the **working-copy state at the time of the measurement** (including concurrent `ap-recomp-3` edits); compare figures only with runs from the same state.
- Not investigated: detailed header dependencies (only aggregate timestamp), `ccache`/`lld` (not installed, see section 10), LTO, `ld.bfd` link time (1.2–3.2 s, insignificant), startup time of 340 MB library, and interaction between concurrent probe/build load.

## 9. Mac versus Linux machine times and incremental rebuilds

**Comparison with Spike** (3 jobs, 1 MB threshold, new generator revision, 2,369 files):

| | Mac (Spike 2, asm, loaded) | Linux machine (c, dedicated) |
|---|---:|---:|
| Generate | 74 s | 53 s |
| Compile, wall clock | 937 s | 986 s |
| Total compiler CPU | 2,711 s | 2,868 s |
| Slowest file | 214 s | 242 s |
| Largest compiler RAM | 1.7 GB | 1.6 GB |
| Library | 224 MiB | 327 MiB |

At equal job count they are effectively tied; the Linux machine wins only with more jobs and the 300 KB rule (section 5: 310–692 s). Note that Mac load was 8–14 during the measurement; 3 jobs on an idle M1 Pro would probably be faster (not measured).

**Incremental builds** (measured on a copy of a completed build with `incr_test.sh`, newer fixed 32-KiB chunk-window revision):

| Scenario | Files recompiled | Compile wall time | Link |
|---|---:|---:|---:|
| A: no changes | 0 | 0.7 s | 3.2 s |
| B: five chunks changed (medium-sized, `main`) | 5 | 1.4 s | 1.4 s |
| C: seven SDK functions become HLE stubs (real generator change) | **3 of 298 SDK chunks** | 1.2 s | 1.4 s |

With the **old** chunk layout (sequential by size), seven HLE functions changed 14 of 180 SDK chunks (8%); the fixed-address windows from `ap-recomp-3` are much more stable. Generation itself is **not incremental** (53 s for everything, 43 s for `main`); `write_if_changed` leaves unchanged chunks alone so only changed chunks need compiling. A complete rebuild after a small generator change therefore costs about **1 minute** (generate + 1–5 chunks + link) rather than 7.5 minutes. The worst single chunk (a slow one, 220 s) remains an outlier if changed.

## 10. User installation list (missing packages; no sudo used)

Nothing was missing for the measurements (all present; `pip --user` was sufficient). Optional, only to build the LAS runtime itself or link faster:

- `lld` (provides `ld.lld`; LAS Makefile uses `-fuse-ld=lld`),
- `ccache` (incremental rebuilds),
- for the LAS program: `SDL3-devel` (3.2 or newer), `ffmpeg-devel` (or `ffmpeg-free-devel`), `vulkan-loader-devel`, `vulkan-headers`, `shaderc-devel`, `glslc`, `vulkan-validation-layers`, `VulkanMemoryAllocator-devel`, `mesa-vulkan-drivers` (RADV); and LAS clone `third_party` (imgui, `AreaTex.h`) for `nvn/smaa_data.c` and `nvn/texpatch.c`,
- `gdb` (crash analysis; missing, but probes do not need it),
- no network access was needed for the measurements; the Linux machine had none (the SDL3 source download failed).

## 11. Reproduction

The commands below are the local equivalents of the measurement runs. Run them from the repository root on a Linux machine; for the supported user workflow, see [BUILD.md](BUILD.md), section 6.

```
sha256sum work/exefs/rtld work/exefs/main work/exefs/sdk work/exefs/subsdk0 > work/exefs.sha256   # optional input manifest
bash scripts/recomp/linux/local/setup.sh                                  # tools, Python packages, input checksums
bash scripts/recomp/linux/local/build_all.sh                              # generate (c) + compile (10 jobs) + link
bash scripts/recomp/linux/local/build_all.sh --nur-compile --tag=j3 --jobs=3 --schwelle=1000000   # compare with Mac Spike
bash scripts/recomp/linux/local/incr_test.sh                              # rebuild measurement (needs a finished build and rsync)
bash scripts/recomp/linux/local/las_runtime.sh                            # LAS runtime Linux path (compile check)
bash scripts/recomp/linux/local/probe.sh alle                             # eh, eh-real, rebase32, gc, bench, boot, boot-las
bash scripts/recomp/linux/local/probe.sh bdsp                             # Gate-1 runtime (section 7; the NVN layer does not link on Linux)
```

The scripts write the measurement files (`*.stats`, `*.times`) to `logs/` in the repository root.
