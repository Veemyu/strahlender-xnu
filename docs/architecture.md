# Architecture: how the static recompilation works

This project turns the ARM64 code of Pokémon Brilliant Diamond (BDSP) into C, compiles it on your machine, and links it with a
runtime that replaces the Switch operating system and the NVN graphics API. The result runs natively on macOS (Metal), iPadOS
(Metal) and, in progress, Linux (Vulkan). This page is the technical overview; build steps are in [BUILD.md](BUILD.md).
Numbers below were measured on the project's own dump unless marked *inferred* or *unverified*.

## Principles

- The repository holds only original code: the generator extensions, the runtime and the build scripts. It never holds game data,
  keys, saves, screenshots or generated C. Everything generated lives under `work/` (gitignored).
- A built app contains your own game data and is for personal use only; only the repository is shared.
- The recompiler and the NVN layer are based on LASRecomp (`peiikai/LASRecomp`, MIT; only `LICENSE`, `cpu.h`, `simd.h`, `simd_fp.h` and the Windows files are kept in
  `scripts/recomp/upstream/`, the rest of the former full copy is in the git history; changes and provenance in `scripts/recomp/rt-bdsp/NOTICE.md` and `shader_translator/NOTICE.md`).
  `raulzrrs/letsgo-recomp` (a LASRecomp derivative) was read as a second reference. Both target other, non-Unity games on macOS only; iPadOS
  and Boehm GC/exception support are our own work. No code of third-party game ports (for example opendpr) is used.

## How we got here (short)

1. **Feasibility.** Measuring the dump showed that the LAS lifter covers 14,105,420 instruction words with only 58 rejected
   (`LDXP/STXP/LDAXP/STLXP`), that the generated C is about 1 GB, and that three blockers needed answers: C++ exceptions (2,917
   functions with landing pads), Boehm GC thread suspension, and the 12.5 GiB fixed address window (impossible on iPadOS).
2. **Spike.** All three blockers were solved in prototypes (below). A full generation takes about 75 s and a cold compile about
   15 minutes on a busy M1 Pro. Microbenchmarks of recompiled versus native code gave a factor of 1.4 to 4.3.
3. **Decision.** An earlier plan to rebuild the game logic in Unity was dropped in favor of the recompilation, because the
   original code and engine behavior carry over 1:1 and saves stay compatible. The Unity work lives on the branch `unity`.
4. **Boot, graphics, platforms.** The guest booted to `nnMain` in under a second (Gate 1), then drew its first frames through Metal
   (Gate 2: movie, title screen, save, city). Since then: audio, controller input, icons, iPadOS, a Vulkan/Linux path, and the
   performance work in [rendering.md](rendering.md).

## The game binary

| Module | Role | Size (image) | Functions | Instructions |
|---|---|---:|---:|---:|
| `main` | game, Unity engine, IL2CPP code, Wwise (statically linked) | 84.3 MB | 218,098 | 11.8 M |
| `sdk` | Nintendo SDK: `nn::*`, libc/libc++, libunwind, the NVN driver | 13.8 MB | 38,289 | 1.5 M |
| `subsdk0` | Nintendo multimedia (`movie::`, WebM parser) | 7.0 MB | 13,689 | 0.9 M |
| `rtld` | runtime linker (replaced by our loader) | 16 KB | 43 | 1.6 K |

`main` imports 1,040 symbols, almost all from `sdk` (733 `nn::*`, 125 libc/libm, 80 C++ ABI, 23 `movie::`) and only one NVN
entry point, `nvnBootstrapLoader`; every other NVN function is fetched by name from the loader. The code is plain ARMv8.0: no
atomics extension, no pointer authentication, no crypto in `main`. All 77 SVC call sites are in `sdk`.

## Generator and execution model

`scripts/recomp/gen_all.sh` drives the native C generator `bdsp_codegen` (`scripts/recomp/native-generator/`), which ports the analysis, lifter and emitter of the LAS Python generator; that original lives only in the git history.

- Every guest function becomes a C function `void f_<address>(Cpu *c)`. Guest registers live in an in-memory `Cpu` structure
  (`x[32]`, `sp`, flags, `tpidr`, `v[32]`); every instruction reads and writes it. Simple and exact, but registers are not kept
  across calls, which is where the slowdown against native code comes from.
- Direct `BL`/`B` become C calls (tail calls use `musttail`). A guest `RET` is a host `return`, so the **host stack mirrors the
  guest call stack**. Indirect calls go through `rt_dispatch` (per-thread cache, then binary search in a sorted table; four
  tables for the four modules).
- Jump tables (`br xN`) are resolved by running the address computation in Unicorn for each index. Our fix for compact byte-offset
  tables (the base `adr` lies inside the function) raised resolved tables in the SDK from 41 to 515.
- FP/SIMD runs in two modes: `asm` (arm64 host: the original instruction encodings as `.inst` blocks, bit-exact) and `c`
  (portable C). 128-bit exclusive pairs (`LDXP` and friends) are emulated with helpers in `rt/cpu.h`. Floating-point state is set
  to the guest mode (FPCR 0) at thread start and after every SVC (`c_exact/fp_env.h`); FPSR/QC flags are not modeled.
- Output is chunked by 32 KiB of guest address space (`<module>_<window>_<n>.c`), so changing one function recompiles one chunk.
  Full generation: 270,299 functions, 2,495 files, about 1 GB of C, 75 to 90 s, up to 5 GB RAM for `main`.
- Compiling: `clang -O1` per chunk. Single huge functions would need minutes and GB of RAM at `-O1`, so chunks above a size
  threshold (default 300 KB of C, option `--recomp-o0-kb`) are built with `-O0`. The functions that dominate CPU time are listed in
  `scripts/recomp/hot_o2.txt` and rebuilt with `-O2`. A cold build takes roughly 15 to 28 minutes; the library is about 224 MiB.
- Performance: recompiled code is 1.4 to 4.3 times slower than native code from the same source (integer about 2×, call- and
  FP-heavy code 3 to 4×). The consequences for frame rate and how it was tuned are in [rendering.md](rendering.md).

## C++ exceptions (IL2CPP)

The game throws and catches C++ exceptions through the SDK's own LLVM libunwind. The LAS model cannot do that (a guest `RET` returns
to the host caller; `rt_dispatch` only knows function starts). Our solution keeps the **unmodified guest unwinder** and adds
reentry points:

- Each function that has a landing pad (from the LSDA) or a `setjmp` return point pushes an `EhRec` (`prev, lo, hi, sp, jmp_buf`)
  on entry and calls `_setjmp`; every exit unlinks it. Only 3,447 of 270,299 functions need this.
- When the unwinder ends in `ret` after `mov sp` (libunwind `jumpto`, `longjmp`), `rt_dispatch` finds the innermost record that
  contains the target and `_longjmp`s into it (`rt_nle_enter`). About 350 lines of Python and 30 lines of C.
- Tested with a synthetic guest, a countercheck under Unicorn, throws from real SDK code, and 100 of 100 reachable real
  functions out of 180 selected, with exact landing-pad prediction. Cost: about 45 µs per throw and catch across four frames.
- Loader duties that follow: `QueryMemory` must report text/rodata/data segments so the SDK can find `eh_frame_hdr`; the FDE
  cache mutex uses real kernel arbiter SVCs; `ExitThread` with open frames `longjmp`s to the thread entry.
- *Unverified:* typed catches matched against the real type object, and the 17 real `setjmp` return sites, were not exercised.

## Threads and the Boehm GC

The game's GC suspends every thread (`SetThreadActivity`, `GetThreadContext3`, SVCs 0x32/0x33). The kernel implements this with Mach
`thread_suspend` / `thread_get_state` on the host thread and returns the guest context from `Cpu` (plus a mirror of host
registers and the top of the host stack as a safeguard). Measured: 8 µs per thread. In a test with recompiled guest code, the
pointer was found in `Cpu` and the guest stack in 19,293 of 19,293 critical windows, because every guest memory access and call
forces a write-back. A suspend stress run during boot (a thread suspended every 200 µs) passed 40 of 40 times. Guest threads
are host `pthread`s with small host stacks (1 to 16 MiB; about 16 KiB resident per thread). *Unverified:* a long allocation stress
test with the real GC on a running game.

## Memory model

| | Variant A (macOS) | Variant B (`--rebase32`, iPadOS) |
|---|---|---|
| Guest address | equals host address | 32-bit offset: `*(T*)(g_base + (uint32_t)ea)` |
| Window | fixed 12.5 GiB at `0x70_0000_0000` (`mach_vm_allocate`, `VM_FLAGS_FIXED`) | everything below 4 GiB |
| Why | simplest; no per-access cost | iOS allows far less address space, a fixed 448 GiB base fails, and the free-team profile has no Extended Virtual Addressing |
| Cost | none | about 5 % in the exception test; FP/SIMD must be generated in `c` mode |

**Variant A-low (iOS, `MODEL=a`).** The compact layout of variant B shifted to a fixed host address (`BDSP_COMPACT_BASE`, default `0x8_0000_0000`),
so guest address == host address again: no `G2H`, NEON inline assembler (`--simd asm`), the same compile flags as the Mac build. A probe on the M2 iPad Pro
showed that a fixed 12.5 GiB `vm_allocate` succeeds at `0x4_0000_0000` and `0x8_0000_0000` in every start (`0x1_` is invalid, `0x2_`/`0x3_` are taken by the system,
everything from `0x10_0000_0000` up is invalid, which is why the Mac address could never work). Measured on the Mac with the beach scene (same game work per frame):
A needs about 31 ms CPU per frame, B about 36 ms, the M2 iPad Pro with B about 47 ms. Build: `MODEL=a scripts/recomp/ios/gen32.sh all`,
`IOS_MODEL=a scripts/recomp/ios/deploy_ios.sh build`.

Rules: host code converts guest addresses only through `G2H()`/`H2G()` (`rt-bdsp/guestmem.h`). The game obtains all its
application memory (3.14 GB, as reported by `GetInfo`) as one `MapPhysicalMemory` region from the alias region in `nninitStartup`;
it never calls `SetHeapSize`. For variant B the reported total must be capped so that everything fits below 4 GiB. A scan of
`main` found no pointer tags. iPadOS memory entitlements and measured limits are in [recomp-ios.md](recomp-ios.md).

## The runtime (`scripts/recomp/rt-bdsp/`)

The LAS runtime was used as a design reference and reimplemented for BDSP; only `cpu.h`/`simd.h` are reused. Main parts:

| Part | What it does |
|---|---|
| `kernel.c` | Horizon kernel: handle table, real host threads, mutex/condvar/arbiter, memory map, SVCs, Mach suspension |
| `ipc.c`, `services*.c` | HIPC/CMIF with domains and the 47 services in the NPDM (`sm:`, `lm`, `apm`, `appletOE`, `acc:u0`, `pctl*`, `hid`, `time`, `set`, `aoc:u`, …). `fsp-srv` serves RomFS as a **virtual image** (tables in memory, file data read from `work/romfs`) and saves from a host folder. Online services return error stubs. Audio services in `services_audio.c`, see [recomp-audio.md](recomp-audio.md) |
| `dispatch.c`, `loader.c` | the four dispatch tables, HLE slots, reentry; module images built by `mkimg.py` (relocations, cross-module imports, `operator new/delete` interposition as in the real loader) |
| `nvn/` | the graphics layer, below |
| `main.c`, `app/` | window and input (SDL3 / AppKit), options, the monitor thread; the macOS and iPadOS app shells |

Bugs worth remembering: a lost wake-up in `WaitProcessWideKeyAtomic` (the key must be set before the mutex is released) and a
self-deadlock after a timed wait (do not reacquire the mutex on timeout, as the real kernel does) stopped real Unity runs after
seconds. Host-side `HLE_FUNC` overrides replace individual guest symbols (`nvnBootstrapLoader`, `nn::vi`, `nv::*`, `movie::*`,
`nn::hid::GetNpadState`).

## Graphics (`scripts/recomp/rt-bdsp/nvn/`)

BDSP draws through NVN; the runtime implements NVN, so the game's own command stream is executed by us.

- **Shared layer** (vendored from LAS and changed): objects, pools and builders (`objects.c`), command recording in guest memory
  (`cmdbuf.c`), block-linear layout, formats and the ASTC decoder (`tegra.c`, `formats.c`, `astc.c`).
- **Metal backend:** `renderer.m` executes commands (pipelines, render targets, a single render worker thread), `metal.m` handles
  window, textures and presentation. The complete source lives in `nvn/src/`; `prepare.sh` only copies it.
- **Vulkan backend:** `nvn/vulkan/`, see [recomp-linux.md](recomp-linux.md).
- **Shaders:** guest programs are read from game memory when the game passes them to NVN (container with SPH header and Maxwell
  code). The LAS translator fails on every BDSP shader (bindless `TEX.B`); our translator `shader_translator/` accepts all 13,710
  programs of the corpus and compiled all 5,959 programs of a run without errors. Details in [shaders.md](shaders.md).
- Things the game needs that LAS did not: separable programs (one `NVNprogram` per stage), the device value `0x5e` = 16 (GPU code
  version, otherwise Unity treats most shaders as unsupported), texture and sampler tables from constant buffer 2, the window
  crop, MSAA resolve, compute skinning. How they were debugged is in [rendering.md](rendering.md).
- **Movie:** the `movie::` interface (23 imports) is replaced by FFmpeg in `movie_glue.c`. **Input:** `nn::hid` is replaced by
  SDL-based input state plus a scriptable input for tests. **Audio:** [recomp-audio.md](recomp-audio.md).

## Where to look next

| Topic | Document |
|---|---|
| Build and install | [BUILD.md](BUILD.md) |
| Working rules, commands, tests | [development.md](development.md) |
| Renderer debugging and performance | [rendering.md](rendering.md) |
| Shader translator | [shaders.md](shaders.md) |
| Save format and handling | [saves.md](saves.md) |
| macOS app / iPadOS / Linux | [recomp-macapp.md](recomp-macapp.md), [recomp-ios.md](recomp-ios.md), [recomp-linux.md](recomp-linux.md) |
| Audio, icons | [recomp-audio.md](recomp-audio.md), [recomp-icons.md](recomp-icons.md) |
| QA harness, bit-exactness test | [recomp-qa.md](recomp-qa.md), [recomp-diff.md](recomp-diff.md) |

Reproduction scripts for the spike measurements (`scripts/recomp/test/run_eh_test.sh`, `run_gc_proof.sh`, `run_eh_rebase32.sh`,
`run_bench.sh`, `run_boot_probe.sh`) and the survey tool `scripts/recomp_survey.py` are still in the repository. The original
feasibility, spike and gate reports (about 1,700 lines) are in the git history.

## Open and unverified

- Full-game performance on iPad and the 60 fps target there; thermal behavior over long sessions.
- A long soak test of the GC and exceptions on a running game; the real `longjmp` sites.
- Floating-point details: FPSR/QC flags are not modeled ([recomp-diff.md](recomp-diff.md)).
- Legal status of public distribution of the recompiler is unresolved; built binaries are not to be redistributed.
