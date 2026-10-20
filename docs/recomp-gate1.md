# Recompilation, Gate 1 “Unity boot” (`ap-recomp` Gate 1)

Status: 2026-10-19. Work log with progress after each phase. Based on `docs/recomp-spike-2.md` (phase 2), `docs/recomp-machbarkeit.md`, and `docs/architektur-entscheidung.md`. Task: run recompiled BDSP code (`rtld`, `sdk`, `subsdk0`, `main`) on Mac (no graphics, **no audio**) through the first Unity/IL2CPP startup log lines, preferably into game initialization (player loop starts, guest calls `nvnBootstrapLoader`). Recompilation is a separate parallel effort; the Unity rebuild (`unity/`, `shader_translator/`, `scripts/shader_*`) was not touched.

**Labels:** **measured** = obtained using scripts under `scripts/recomp/` on local dump; *suspected* = inference without a test. No game binaries, generated code, or game addresses are in the repository; all figures come from runs on local dump (`work/`, gitignored). Game addresses in this log are module offsets, included only to make debugging traceable (as in `docs/recomp-machbarkeit.md`).

## Summary

| | |
|---|---|
| **Gate 1** | **Reached**: recompiled BDSP code (`rtld`, `sdk`, `subsdk0`, `main`) runs on Mac without graphics/audio through `nninitStartup` and `nnMain` to the first call of `nvnBootstrapLoader` (task criterion), in **0.3–0.7 s**, **100/100 runs**, including suspend stress (40/40) and 1 MiB host stack |
| At the gate | 24 threads (20 workers), 649 SVCs (23 distinct), 141 IPC requests (74 distinct service/command pairs, 19 services), RomFS mounted (11 reads, 12 MiB), RSS 258 MiB (219 MiB via `MapPhysicalMemory`), host stack 16 KiB/thread, 0 exceptions, no guest log line |
| Full build | Generation 74 s, compilation 699 s (4 jobs, 2,495 files, largest compiler 1.7 GB), link 0.6 s; incremental rebuild compiles only changed chunks (fixed 32 KiB address windows) |
| Found and fixed | undersized alias region, LDXP/STXP (116 words), jump-table detection window, **missing symbol interposition** (`operator new/delete`), `bsd:u` registration, `GetEntryCount` bug and crash report bug |
| Next blocker | **NVN/graphics** (Gate 2): SDK's own NVN driver crashes after first `nvdrv` ioctl; replace `nvnBootstrapLoader` and NVN functions with host functions (LAS layer) |

## Custom runtime layer: `scripts/recomp/rt-bdsp/`

The clone runtime (`research/LASRecomp/runtime`, MIT) remains unchanged and is **not** linked; its design is reimplemented (license: `scripts/recomp/rt-bdsp/NOTICE.md`, license text `LICENSE-LASRecomp`). Only `cpu.h`/`simd.h` are reused via `#include_next` (the `Cpu` state structure, memory/flag macros). Reason: clone kernel uses 256 MiB host stacks, does not know SVC `0x32/0x33/0x36/…`, calls guest pointers without address abstraction, and is intertwined with renderer, UI, and randomizer.

| File | Contents |
|---|---|
| `bdsp.h`, `guestmem.h` | shared header, address layouts (variants A/B), **`G2H()`/`H2G()`** as sole guest/host address conversion points |
| `kernel.c` | Horizon kernel: handle table (16,384), real host threads, mutex/condvar/arbiter, memory map, 36 SVCs, per-thread SVC counters, Mach suspension for Boehm GC |
| `ipc.c` | HIPC/CMIF (domains, control commands, buffer descriptors), record of all service/command pairs, error stub for unknown services |
| `services.c` | `lm`, `apm`, `appletOE` (complete), `acc:u0`, `aoc:u`, `pctl*`, `ectx:aw`, `set`, `set:sys`, `time:*`, `hid` |
| `services_fs.c` | `fsp-srv`: RomFS as a **virtual** image (tables in memory, file data via `pread` from `work/romfs`), saves under `work/recomp/save` |
| `services_net.c` | Error stubs for networking/online (`nifm:u`, `bsd:u`, `bsdcfg`, `ssl`, `friend:u`, `ldn:u`, `bcat:u`, `nim:eca`, `notif:a`, `nsd:u`, `sfdnsres`, …) and peripherals; `prepo:u`, `ldr:ro` return “success with no data”; `csrng` |
| `services_gfx.c` | `vi:u/s/m` and `nvdrv` logging stubs (no graphics output), 60 Hz Vsync event, “null GPU” responses for some `nvgpu` ioctls |
| `nvn_null.c`, `hle_nvn.txt` | Gate 2 preliminary experiment: `nvnBootstrapLoader` and NVN functions as no-op host stubs (only with images built using `mkimages.sh` and `HLE_LIST`) |
| `test/` | synthetic tests: `kernel_test.c`, `romfs_test.c` (RomFS and save directories), `excl_pair_test.c`, each with `run_*_test.sh` |
| `dispatch.c` | 4 dispatch tables (`main`, `sdk`, `subsdk0`, `rtld`), HLE slots, reentry for landing pads/`setjmp` (`rt_nle_enter`), gate observation, crash report |
| `loader.c`, `mkimages.sh` | load module images built with `mkimg.py` (relocations and cross-module references applied) |
| `main.c` | reserve window, start `nn::init::Start`, monitor, result report |
| `build.sh` | incrementally builds runtime and links it with module objects to `work/recomp/bdsp_boot` |

**Audio:** no sound or output. `audren:u`, `audout:u`, `audin:u`, `hwopus` return error stubs (`audren:u` is expanded to a silent stub only when needed; see phase 6).

## Phase 1: fix the phase 2 abort

**Phase 2 finding** (`run_boot_probe_las.sh`, LAS IPC layer linked): `svcBreak` after unhandled `am` commands. From the run:

| Service/object | Command | Meaning | Result if unanswered |
|---|---:|---|---|
| `ISelfController` | 91 | `GetAccumulatedSuspendedTickChangedEvent` | SDK expects an event handle in response; without it, `nn::os::AttachReadableHandleToSystemEvent` aborts (`svcBreak`, reason 0) |
| `ICommonStateGetter` | 900 | `SetCpuBoostRequestPriority` | harmless but unhandled |

Custom layer now answers **all** `ICommonStateGetter`, `ISelfController`, `IApplicationFunctions`, `IWindowController` commands issued by SDK in phase 2 and this run; commands returning events (`0, 13, 61`, `9, 91`, `130, 140, 150, 160`) return real kernel events. SDK then proceeds through `sm:` → `lm` → `apm` → `appletOE` → `pctl`, `pctl:s/a/r` → `aoc:u` → `ectx:aw`.

**Further obstacles, found and fixed in sequence** (with causes; details in phases 2 and 3):

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | `nn::diag::Abort` in `StandardAllocator::Initialize` (from `nninitStartup`) | In `nninitStartup`, BDSP requests nearly all application memory (3.14 GB from `GetInfo`) as **one** region and obtains it from the **alias region** with `MapPhysicalMemory`; initial runtime's alias region (4 GiB, based on LAS) was too small after modules/heap/stack, leaving no 3.14 GB hole | Alias region 6.25 GiB, heap 3.25 GiB, stack 512 MiB, modules/HLE/TLS at low addresses (layout in `bdsp.h`) |
| 2 | `rt_udf` in `main` (`ldxp x10, x11, [x0]`) | LDXP/STXP/LDAXP/STLXP missing from lifter (58 loops, 116 words) | Add lifter `excl_pair()` in `eh_gen.py` plus `ldxp64/stxp64/ldxp32/stxp32` helpers in `rt/cpu.h`; test in `rt-bdsp/test/excl_pair_test.c` |
| 3 | “no guest code at …” in `main` (jump into middle of hash function) | Byte-offset jump table: `adr xD, <first case>; ldrb w,[tab,idx]; add xD,xD,w,lsl #2; br xD`, with 11 words between `adr` and `br`; phase 2 fix scanned only 8 words | Increase window to 24 words (`is_jumptable_base_adr`); correctly split 12 more tables in `main` (2,231 rather than 2,219) |
| 4 | `nn::socket::Initialize` aborts (in `InitializeCommon`) | `bsd:u` reported error on registration (`RegisterClient`) | `bsd:u`: registration succeeds; all socket calls return `-1`/`ENETDOWN` |
| 5 | Heap check `nnmem_nlib_debug_break` freeing game's `std::string` (`TlsHeapCentral::UncacheSmallMemory_`) | **Missing symbol interposition in loader:** `operator new/delete` are present in both `main` and SDK; real rtld uses executable symbol precedence (ELF interposition), but `mkimg.py` bound SDK references to its own definition. SDK `std::string` therefore freed through SDK `delete` a pointer allocated by game's allocator (16-byte header) | `mkimg.py --interpose-from main.syms.json`: route other modules' `operator new/delete/new[]/delete[]` (and `typeinfo`) to `main` definitions (39 SDK references, 6 in `subsdk0`) |
| 6 | Crash report ended with `SIGTRAP` | Our bug: `rt_fatal_trace` was declared `noreturn` but returns (compiler emitted `brk`) | Remove attribute; create report from main thread in normal context |

**Phase 1 result: passed.** Guest runs through `nninitStartup`, all 115 SDK constructors and 417 game constructors, reaches `nnMain`, mounts RomFS, and calls `nvnBootstrapLoader` (see result report/gate status).

## Phase 2: SVCs, threads, heap, tables, LDXP, RomFS/SaveData

| Item | Status | Evidence |
|---|---|---|
| SVC `0x32` SetThreadActivity / `0x33` GetThreadContext3 | Implemented with Mach `thread_suspend/resume` on host thread; context (x0..x30, sp, vector registers, tpidr) comes from `Cpu` (Spike: all suspend-window state was there). In gate run, same sequence occurred **twice from game itself**: suspend, read context, resume; once thread 82 (priority 59) → main, once main → thread 82; result 0 each, both continued | `test/kernel_test.c`: thread starts, counter stops during suspension (30 ms), context returns `x19` and counter, resume works |
| SVC `0x36` SynchronizePreemptionState, `0x28` ReturnFromException, `0x2F`, `0x23`, `0x20`, `0x5F`, `0x2A/0x2B`, `0x30/0x31/0x37` | `0x36`, `0x5F`, `0x2A/B`, `0x30/31/37`: successful no-op; `0x28`: `FATAL` (used only in `rtld`); `0x2F`, `0x23`, `0x20`: error `0xDC01` (not implemented) with message. **Gate run did not call `0x23`, `0x28`, `0x2F`, `0x20`, `0x36`** (23 distinct SVCs, 654 calls) | SVC counters in result report |
| SVC `0x2C/0x2D` (`MapPhysicalMemory`) | Does not zero memory (window pages are fresh and allocated on access); `0x2D` discards via `mmap(MAP_FIXED)`. Earlier, `memset` of 3.14 GB immediately added 3 GB RSS; avoided | 157 calls, **219 MiB** mapped, RSS 258 MiB at gate |
| Boehm GC suspend path | Mechanism as in Spike (section 2 of `docs/recomp-spike-2.md`). **Suspend stress during boot** (`BDSP_SUSPEND_STRESS=1`: host thread suspends each guest thread in rotation, reads context and resumes it every 200 µs): 2,300–4,000 cycles/run, including during IPC/SDK and on main thread; **40/40 runs** reach gate (100/100 without stress). Game allocation/GC stress only possible after player loop starts | `main.c` (`suspend_stress`), result line “suspend stress test” |
| Threads and stack sizes | Host stack per guest thread **1–16 MiB** (env `BDSP_HOST_STACK_MB`, default 16; 1 and 2 MiB runs also reach gate unchanged). **Measured resident: 16 KiB/thread** (`mach_vm_region`, `pages_resident`) for 24 threads. Guest main stack: 1 MiB (NPDM); SDK allocates other thread stacks | `kernel_report` in result |
| TLS | Per thread, 0x200-byte `tpidrro` block from `TLS_BASE` (2 MiB = 4,096 threads); `tpidr` stays 0 until guest sets it | 24 threads running |
| Heap size (`SetHeapSize`) | **BDSP never calls `SetHeapSize` before gate.** Application memory comes entirely through `MapPhysicalMemory` (alias region). `GetInfo(TotalMemorySize)` = 3.14 GB (console value); `nninitStartup` requests `Total − Used` = **3.14 GB** as one region | Layout finding in phases 1/4 |
| 3 dispatch tables (+ `rtld`) | `main` 218,098, `sdk` 38,289, `subsdk0` 13,689, `rtld` 43 functions (after jump-table fix) | `dispatch.c` |
| LDXP/STXP/LDAXP/STLXP | In lifter (`eh_gen.py`, 116 words in `main`) and `rt/cpu.h` (helpers), `rt32/cpu.h` via `GPTR`; 128-bit counter loop with 4 threads × 50,000 steps agrees | `test/excl_pair_test.c` |
| RomFS | **Virtual image:** tables in memory (879 KiB for 18,022 files and 145 folders), file data via `pread` from `work/romfs` (4,826 MiB), no 5 GB image; game accesses before gate: 11 reads, 12 MiB (3 files, Unity level-0 defaults) | `test/romfs_test.c`: 8 synthetic files, search through hash tables as game does, contents/sizes, reads across file boundaries |
| SaveData | `fsp-srv` commands 51/52/53 mount host folder `work/recomp/save/save_<type>` (never in repo); game did not request it before gate | Synthetic test in `test/romfs_test.c` after RomFS tests: create file, duplicate create errors, write, read, size, `SetSize`, type, rename, count/read directory, delete. Test found and fixed a bug: `GetEntryCount` moved directory stream position on macOS |
| NCA mount | Not needed: game reads RomFS through `OpenDataStorageByCurrentProcess` (command 200) as memory image; `OpenDataStorageByDataId`/patch report “not found” | IPC log |

## Phase 3: production exception mechanism

| Item | Status |
|---|---|
| Landing-pad reentry | `rt_nle_enter` in `dispatch.c` (innermost frame containing address and whose entry SP is above target SP; `_longjmp`), with counters for reentries and unwound host frames. No reentries in gate run (0), so game had not thrown/caught an exception yet |
| `QueryMemory` with module segments | Loader registers text (type 3, rights 5), rodata (3, 1), and data (4, 3) for each module in memory map; SDK `GetExceptionInfo` can then find `MOD0`/`eh_frame_hdr` |
| FDE cache multithread mutex | Real SDK code using kernel arbiter SVCs; test: 2 threads, 4,000 locks, no loss (`kernel_test.c`) |
| `ExitThread` with open frames | `longjmp` to `thread_main` jump point; test confirms nothing runs after `ExitThread`, thread object is signaled |
| 17 reentry sites after `bl setjmp` (`main`; 10 in SDK) | Generator finds them (`setjmp_returns: 17` in `main`, 10 in `sdk`). **Mechanism tested synthetically** (`test/eh_guest.cpp`, test T7: custom AAPCS64 `setjmp`/`longjmp`, longjmp across 3 + 20 frames, twice in sequence, destructors do not run, frame chain empty afterward, return value and callee-saved registers correct). **The 17 real sites were not reached in gate run** (0 reentries); tested only once game runs |
| Regression | T0–T6 exception tests from phase 2 still pass with new chunk layout and larger jump-table scan (T6: 45.8 µs per throw/catch) |

## Phase 4 (pulled forward): memory model, decision, abstraction

**Decision:** Gate 1 uses **variant A**: fixed 12.5 GiB window at `0x70_0000_0000` (`mach_vm_allocate`, `VM_FLAGS_FIXED`, early constructor before host allocator occupies it), **guest address = host address**. **Variant B** (`--rebase32`, all guest addresses <4 GiB, access via `g_base + (uint32_t)ea`) remains the iPad path and belongs to Gate 2.

**Runtime now supports both:**

| Layer | Variant A | Variant B |
|---|---|---|
| Generated code | `LD8..ST64`, `ldx*/stx*`, `ldxp*/stxp*` from `cpu.h` using `(uintptr_t)` | Same code, but `-I scripts/recomp/rt32` before `rt/`: `rt32/cpu.h` replaces macros with `*(T*)(g_base + (uint32_t)ea)`, `GPTR(a)` for exclusive pairs; FP/SIMD in C mode (`--simd c`) |
| Host (kernel, IPC, services, loader) | Only `G2H(a)`/`H2G(p)` from `rt-bdsp/guestmem.h`: A = identity, B = `g_base + (uint32_t)a` (switch `-DBDSP_REBASE32`, `build.sh -DBDSP_REBASE32`) | Same; all runtime files pass syntax check with `-DBDSP_REBASE32 -I scripts/recomp/rt32` (compile check only). **Still needed for Gate 2:** reserve 4 GiB window and set `g_base` in `main.c` (currently A only), run with variant-B modules |
| Address layout | `bdsp.h`, block A (12.5 GiB) | `bdsp.h`, block B: modules, HLE, stacks, alias and heap below 4 GiB (layout documented, **untested**) |
| Modules | `mkimages.sh` using bases from `gen_all.sh` | Regenerate using bases <4 GiB (`gen_all.sh`/`mkimages.sh` through `base_of`) |

Rule for all host source: **no** conversion to `uintptr_t` outside `guestmem.h`; every guest address (register, IPC buffer, table in guest memory) goes through `G2H`, every pointer into guest memory returned to guest goes through `H2G`. `grep -n "uintptr_t" scripts/recomp/rt-bdsp/*.c` now shows only alignment calculations on IPC messages (relative to message start, so independent of model).

**Gate 1 finding relevant to variant B:** BDSP SDK obtains all application memory (3.14 GB) as a **contiguous** `MapPhysicalMemory` region from alias region in `nninitStartup` (phase 1, obstacle 1). This cannot fit in a 4 GiB window (variant B) **unless kernel `GetInfo(TotalMemorySize/UsedMemorySize)` reports lower values**. Gate 2 must cap application memory reported to guest (Info IDs 6/7/21/22) so modules, stacks and host side also fit in 4 GiB (target *suspected* 2.0–2.5 GB; BDSP Unity heap depends on reported amount, **unverified**). This is a kernel parameter, not a rewrite; whether Unity starts with less memory must be tested in Gate 2. Only measured so far: 219 MiB of 3.14 GB is in use before gate.

## Phase 5: full generation and compilation of four modules

**Changes since phase 2** (`scripts/recomp/`):

| Change | Purpose |
|---|---|
| `eh_gen.py --window 0x8000` (default) | Chunk boundaries every 32 KiB of guest code instead of sequential numbering; filenames `<module>_<window>_<n>.c`. If a function changes, **all other chunks remain unchanged** (previously numbering shifted; jump-table fix changed 823/1,046 files) |
| `regen_inc.sh` | Generates into `gen4.new`, uses `rsync --checksum` to copy only changed contents to `gen4`, removes obsolete chunks |
| `build_all.sh` | Removes objects whose source no longer exists (otherwise duplicate symbols after changed chunking); otherwise unchanged (only chunks whose object is older than source) |
| `rt-bdsp/build.sh` | Builds runtime (`rt-bdsp/*.c`, only if changed) and links with `obj4/*.o` to `work/recomp/bdsp_boot` |
| `mkimages.sh` | Module images (`mkimg.py`, now with `operator new/delete` interposition) |

**Measurement** (4 parallel compilers, shared machine load 12–19, 16 GB RAM, `clang -O1`, per-function C files >1 MB use `-O0`):

| Measurement | Result |
|---|---|
| Generation (Python, one core) | **74–90 s** total: `main` 62 s (peak 3.7 GB RAM), `sdk` 7.4 s, `subsdk0` 4.1 s, `rtld` 0.1 s |
| Chunks (files) | `main` 1,956, `sdk` 305, `subsdk0` 229, `rtld` 1, plus 4 table files: **2,495 files** (2,485 at `-O1`, 10 at `-O0`), 995 MB C |
| Full compile | **699 s = 11.7 min** wall, sum of per-file times 2,707 s (45 min CPU); slowest file 201 s (674 MB RSS), peak memory **1,676 MB** (one file at 1.6 GB: a single function), never more than 4 compilers simultaneously |
| Objects | 277 MiB; program `bdsp_boot` with runtime 224 MiB (file size) |
| Link | **0.6 s**, including runtime compilation |
| Incremental: regenerate with no changes | **0 changed files** across all modules (generation deterministic), then `build_all.sh` does no compilation (10 s to scan file list) |
| Incremental: lifter adds LDXP/STXP | 2 changed `main` chunks, **8 s** compilation (measured before windowing; generation itself remains 74 s) |
| Disk space | `df` before/after: 27 GB → 35–36 GB free (deleted `work/recomp/gen`, `gen32`, `libgame_probe.dylib`, `boot_probe*`; intermediate `gen4.new` after each run); ≥15 GB free throughout |

The phase 1 target of **build time under 30 min** remains met (11.7 min with 4 jobs on a heavily loaded machine). Each regeneration costs at least 74 s (generator is not incremental), but compilation afterward touches only changed chunks.

**Notes for other hosts and `eh_gen.py` users:** (1) `--window 0` disables window partitioning (chunks only by size, filenames `<module>_00000_<n>.c`). (2) Exclusive-pair helpers in `rt/cpu.h` use 128-bit atomics (`unsigned __int128`): inline on arm64; x86-64 compiler needs `-mcx16` (otherwise calls `__atomic_*_16` from libatomic); `excl_pair_test.c` tested only on arm64. (3) Ryzen run in `docs/recomp-linux.md` (separate workstream) was not measured with these changes.

## Phase 6: result report

Run: `BDSP_TIMEOUT=60 work/recomp/bdsp_boot` (default `BDSP_STOP_AT_GATE=1`; `main.c` emits result report; repeated runs 0.3–0.7 s to gate, same with host stack of 1, 2, and 16 MiB).

| Measurement | Result |
|---|---|
| **Gate status** | **Gate 1 reached**: guest calls `nvnBootstrapLoader` (first observed by dispatcher, `lr` in `main`; argument points to NVN function name), after **0.3–0.7 s** |
| Path to gate | `nn::init::Start` → `nnosInitialize` → 115 SDK constructors → `nninitStartup` (allocator) → 417 game constructors → `nnMain` → `nn::vi::Initialize`, time/filesystem/HID services, **RomFS mounted and read** (Unity level-0 defaults), `nn::socket::Initialize`/`nn::nifm`/`ssl` (error stubs), 22 more threads → `nvnBootstrapLoader` |
| Last guest log line | **None**: no `lm` line or `OutputDebugString` up to this point (Unity release build does not write). Log channels are connected (`lm:ILogger` and SVC `0x27`, counted in report) |
| Last SVC | Main thread at gate: `MapPhysicalMemory` (570 SVCs, 141 IPC so far); after gate (run without gate stop): `SendSyncRequest` to `nvdrv` (NVN driver's first requests; below) |
| SVCs | 23 distinct, 649 calls: `MapPhysicalMemory` 157, `SendSyncRequest` 141, `QueryMemory` 111, `StartThread`/`CreateThread` 23 each, `MapMemory` 23, `WaitProcessWideKeyAtomic` 24 (22 workers waiting), `SetThreadCoreMask` 42, `SetThreadPriority` 17, `GetInfo` 22 |
| Threads | **24** created and alive: main (priority 44, core 0), 1 SDK thread (priority 28, core 3), 1 priority 59, 1 priority 29 (any core), **20 workers at priority 44** (core 0). 22 wait on condition variables (Unity job-thread work queue) |
| Handles | 72 (peak 72) |
| RSS | **257–263 MiB** (219 MiB mapped/resident via `MapPhysicalMemory`; modules 101 MiB) |
| Host stack | 16 KiB resident per thread (24 threads) |
| IPC | 141 requests, **74 distinct service/command pairs**; unimplemented (default response): only `IParentalControlService` 1 and `ICommonStateGetter` 66 (no effect) |
| Services requested (in order) | `lm`, `apm`, `appletOE`, `aoc:u`, `ectx:aw`, `pctl`, `pctl:s`, `pctl:a`, `pctl:r`, `time:u`, `fsp-srv`, `nvdrv`, `vi:m`, `vi:s`, `vi:u`, `nifm:u`, `bsd:u`, `ssl`, `hid` (19 of 47 NPDM services) |
| Error stubs accepted by guest | `nifm:u` (command 5), `ssl` (command 5); `bsd:u` reports `RegisterClient` success and discards all subsequent work |
| Reentries (exceptions/`longjmp`) | 0: game had not thrown exception or called `longjmp` by then |
| RomFS | 11 reads, 12 MiB |
| Exception/kernel/service tests | `run_excl_test.sh`, `run_kernel_test.sh`, `run_romfs_test.sh`, `run_eh_test.sh` (T0–T7): all passed |

**“Unity startup” finding:** Through `nvnBootstrapLoader`, Unity's platform layer, 24-thread pool, and file access (`globalgamemanagers`, `globalgamemanagers.assets`, `resources.assets.resS`) run. Player loop start is **not** measured: Unity initializes graphics before its first frame, and guest stops at graphics. The gate criterion—first `nvnBootstrapLoader` calls—is met. IL2CPP metadata (`global-metadata`) had not yet been read.

### What happens after the gate (`BDSP_STOP_AT_GATE=0`)

Guest opens `/dev/nvhost-ctrl-gpu` via `nvdrv` and submits first ioctl `0xC0B04705` (176 bytes, `GET_CHARACTERISTICS`); NVN initialization then aborts on null pointer in SDK's own NVN driver (`SIGSEGV` at address 0, guest in SDK NVN code, caller `nnMain`). Crash is **unchanged** when stub returns plausible values (`services_gfx.c`, “null GPU”: `GET_CHARACTERISTICS` with GM20B values, `nvmap` CREATE/FROM_ID/GET_ID/PARAM, `as-gpu` ALLOC_SPACE/MAP_BUFFER_EX/GET_VA_REGIONS; all other ioctls return input and success, with **unverified layouts from memory**). Pointer comes from a guest-heap structure (`[x4+8]` in NVN driver function), not ioctl response. Expected: SDK's real NVN driver requires either a complete `nvhost-*` ioctl emulator (GPU-driver scope, not recommended) or, as in LAS/Gate 2, replacing `nvnBootstrapLoader` and NVN functions with host functions. First call was `nvnBootstrapLoader("nvnDeviceGetProcAddress")`: Unity obtains NVN functions by this name, as LAS does.

### Preliminary experiment: NVN functions as host stubs (`nvn_null.c`, `hle_nvn.txt`)

To characterize next blocker, `nvnBootstrapLoader` was bound to a host slot through `mkimages.sh` (`IMG=work/recomp/img_nvn HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt`; `mkimg.py --hle-list` works; run with `BDSP_IMG=work/recomp/img_nvn BDSP_STOP_AT_GATE=0 BDSP_TRACE_NVN=1`). Each NVN function fetched by Unity through `nvnBootstrapLoader("nvnDeviceGetProcAddress")` and `nvnDeviceGetProcAddress` is a no-op stub returning 0. Findings:

| | |
|---|---|
| Calls before crash | 16: `nvnDeviceGetInteger` (enums 0 and 1, version query; stub writes nothing), `nvnDeviceBuilderSetDefaults/SetFlags`, `nvnDeviceInitialize` (return 0 = “failed”), `nvnDeviceSetWindowOriginMode`, `nvnDeviceSetDepthMode`, 5 `nvnQueueBuilder*`, `nvnQueueInitialize`, `nvnQueueSetDebugLabel` with queue `NULL` |
| Unity behavior | **Does not check return values** and continues with unusable objects; also requests `ISelfController` command 44 (`CreateManagedDisplaySeparableLayer`, not implemented by stub). Then `SIGSEGV` (address 0x18) in SDK window code (`nn::vi`/Native Window) |
| Conclusion | Unity emits **no error log** and player loop cannot be reached without a real NVN implementation (return values, output parameters, object state). Gate 2 therefore needs a functional NVN layer with console values (`nvnDeviceGetInteger` for all enums, `nvnDeviceInitialize` true, windows/textures/queue); LAS layer is the model |

## Next blockers (ordered; effort is an estimate)

| # | Blocker | Effect | Effort (estimate, one developer) |
|---|---|---|---|
| 1 | **NVN/graphics:** replace `nvnBootstrapLoader` and about 495 NVN functions with host functions (LAS layer `runtime/nvn`, 9.5 kLOC, Gate 2) or emulate `nvhost-*` ioctls | Required for every frame and player loop | 3–6 weeks (phase 2 estimate; Unity-specific usage untested) |
| 2 | **`--hle-list` for NVN names** | Mechanism proven (experiment above); Gate 2 lacks NVN function name list (source: `work/recomp/nvn_names.json`, 524 names) and host implementation | 1 day for list |
| 3 | **Audio** (`audren:u`, `hwopus`, Wwise): not yet requested; silent stub required when guest opens `audren:u` (`RequestUpdate` needs valid response structure) | Wwise initialization | 2–4 days (silent stub only) |
| 4 | **Memory model B** (iPad): kernel must report less application memory (Info IDs 6/7/21/22); whether Unity runs with it is open | iPad path | 1.5–3 weeks (phase 2 estimate) |
| 5 | **Exceptions/GC during live game:** 17 `setjmp` sites and landing pads not reached by game; Boehm GC stress and 1-hour soak test | Decision criterion from `docs/recomp-spike-2.md`, section 6.2 | 3–5 days after blocker 1 |
| 6 | **Frame time** (target 16.7 ms), recompiled function performance | Decision criterion (b) | unknown; measurable only after graphics |
| 7 | Remaining NPDM services (28/47 not yet requested): `hid` with shared-memory input state, `acc:u0` profiles, `set`, `mm:u`, `caps:*`, `nfc/nfp`, … | Depends on game usage | hours to 1 day per service |

## Reproduction

```
scripts/recomp/gen_all.sh            # or regen_inc.sh: create/update work/recomp/gen4
scripts/recomp/build_all.sh 4        # compile modules incrementally, max 4 compilers
scripts/recomp/rt-bdsp/mkimages.sh   # module images (relocations, interposition) to work/recomp/img
scripts/recomp/rt-bdsp/build.sh      # build runtime and link to work/recomp/bdsp_boot
work/recomp/bdsp_boot                # run: BDSP_TIMEOUT, BDSP_STOP_AT_GATE, BDSP_TRACE_SVC, BDSP_TRACE_IPC, BDSP_FNPROF, BDSP_RING,
                                     # BDSP_DUMP, BDSP_LOG_FILES, BDSP_HOST_STACK_MB, BDSP_ROMFS, BDSP_SAVE, BDSP_LANG
scripts/recomp/rt-bdsp/test/run_{excl,kernel,romfs}_test.sh ; scripts/recomp/test/run_eh_test.sh
```

Runtime license notice: `scripts/recomp/rt-bdsp/NOTICE.md`, license text `scripts/recomp/rt-bdsp/LICENSE-LASRecomp`. Clone `research/LASRecomp` was not modified.
