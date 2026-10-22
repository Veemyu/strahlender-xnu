# Project Status 2026-10-19 (17:10)

Purpose: explain where things stand, what is supported, what is missing, and where to find details, without requiring prior context. Numbers are measured or marked as assumptions. Document index: `docs/README.md`. Work rules, commands, save distribution, agent/todo status, and unsupported assumptions: `docs/betriebshandbuch.md`.

## 1. Goal and Rules

- **Goal (user):** Use this repository and a personally owned NSP/XCI of Pokémon Brilliant Diamond (BDSP) to build a native, tested game for **macOS and iPadOS** (later Linux/Windows with Vulkan). The repository contains **no** game data, keys, dumps, generated code, saves, or screenshots. Built apps are for personal use only.
- **Audio:** currently silent (audio services are stubs). The previous “no audio” requirement has been lifted; audio may now be investigated and implemented (`todo/neustart.md`, Todo `rc-audio`).
- **Saves** remain compatible with Ryujinx/Switch (`SaveData.bin` 979,108 bytes, version 0x34, MD5 at 0xE9818).
- **Work rules:** no sudo, no whole-disk scans, commits only with the user's identity (no co-author trailer), repository files only via `edit`/`create`; `scripts/repo_check.py` runs before each commit (hook).

## 2. Strategy (Decisions in `docs/architektur-entscheidung.md`)

| No. | Date | Decision |
|---|---|---|
| 1 | 2026-10-18 | User: path D (Unity rebuild), fully playable, later public (code only). |
| 2 | 2026-10-18 | Autopilot: recompilation (LAS method) deferred (exceptions, GC, 12.5-GiB window). |
| 3 | 2026-10-19 15:30 | Recompilation becomes main path (exceptions solvable, C mode bit-exact, game reaches the city). |
| 4 | 2026-10-19 16:57 | **User: Unity rebuild is deprecated; do not develop it further** (`unity/DEPRECATED.md`). |

There is now **one** development track: recompilation.

## 3. Recompilation (Main Path)

**Principle:** The game's original ARM64 code (NSO `main`, `sdk`, `subsdk0`, `rtld`) is statically translated to C (lifter from LASRecomp, MIT). Custom runtime `scripts/recomp/rt-bdsp/` replaces the Switch operating system: kernel SVCs, IPC services (HIPC/CMIF), RomFS from the dump, save data, NVN graphics through Metal (macOS/iPadOS) or Vulkan (Linux), and video through FFmpeg. Logic, UI, events, battles, and AI are therefore the original, 1:1.

### 3.1 Measurements (Sources: `recomp-gate1.md`, `-gate2.md`, `-spike-2.md`, `-diff.md`, `-linux.md`, `-macapp.md`)
- **Scale:** 270,299 functions; 985.6 MB (C) or 1,037 MB (assembly) of C; 14.1 million instruction words. Initially only 58 words (LDXP/STXP family) were unsupported; 116 are now generated.
- **Build time:** generator 51–74 s; compile on Mac 937 s (3 jobs); cold `recomp` stage about 27.5 min including everything; Linux machine 310–388 s (10–12 jobs, `-O0` for individual functions over 300 KB). Incremental: seconds to 1 min (fixed 32-KiB chunk windows).
- **Exceptions (gate criterion):** SDK's real libunwind works when recompiled; 100 of 180 real LSDA functions in test show no landing-pad mismatch, 55 crashed in the synthetic environment (not in game).
- **GC:** suspend threads via Mach `thread_suspend`/`thread_get_state` (SVC 0x32/0x33), about 8 µs per thread.
- **Bit-exactness (`recomp-diff.md`):** x86 C mode vs ARM64: 0 mismatches (93.5 million cases per variant, 44 instructions exhaustively over 2^32 inputs). Required: `rt_fp_guest_mode()` in guest thread (otherwise FTZ/DAZ cases differ), flags `-O1 -ffp-contract=off -fno-fast-math`.
- **Mac run (Metal):** rtld → opening video (VP8, FFmpeg) → title after 21.9 s → “Continue” → save → 3D city (Zone 24) at 45 fps, RSS 1.0–1.5 GiB, 24–37 threads, no crash for 135 s.
- **Linux run (Vulkan, RTX 2080 Ti):** language selection with correct text at 60 fps; all 4,276 unique game programs pass through translator + `glslc`, deterministically (1,206 SPIR-V files byte-identical).
- **iPad (app `dev.local.xnubdsp`):** runs at 50–52 fps (previous measurement 41), footprint 1.6–2.1 GiB (8-GiB limit with Increased Memory Limit), 37–39 threads, memory model B (all guest addresses below 4 GiB, 1.98 GiB app memory). Details in `recomp-ios.md`.
- **Reference comparison:** recompilation language selection pixel-identical to Ryujinx (SSIM 0.999). City image colors are close (difference 15–17 per channel); water is missing (white instead of blue).

### 3.2 Components (Where Things Live)
| Path | Contents |
|---|---|
| `scripts/recomp/*.py,sh` | generator pipeline (`gen_all.sh`, `regen_inc.sh`, `build_all.sh`, `mkimg.py` module images, `eh_*` exception handling, `il2sym.py` IL2CPP symbols, `symres.py`) |
| `scripts/recomp/rt-bdsp/` | runtime: `kernel.c`, `ipc.c`, `services*.c`, `loader.c`, `dispatch.c`, `main.c`, `guestmem.h` (G2H/H2G), `install_save.sh`, `app/` (macOS wrapper) |
| `scripts/recomp/rt-bdsp/nvn/` | NVN→Metal: `prepare.sh` copies LAS sources to `work/` and applies `fixes.patch`; `nvn_glue.c`, `movie_glue.c` (FFmpeg video), `debug.patch`; `vulkan/` Linux path (`prepare_vk.sh`, `las-vk.patch`, `vk_glue.c`) |
| `scripts/recomp/rt`, `rt32/` | LAS runtime header extensions (exceptions, 32-bit rebasing) |
| `scripts/recomp/app/` | `BDSP.app` wrapper (Info.plist, menu, import, input) |
| `scripts/recomp/ios/` | iPad build (rebase32, FFmpeg for iOS, Xcode, deploy), in progress |
| `scripts/recomp/linux/` | Linux builds: the former remote helpers were removed; local helpers are in `scripts/recomp/linux/local/` |
| `scripts/recomp/qa/` | test harness (`qa_run.sh`, scenarios), in progress |
| `scripts/recomp/diff/`, `c_exact/` | differential test of C mode vs ARM64, FP environment |

### 3.3 Open Bugs (Priority)
1. **Water** (`Delphis/Map/FlowmapWater`, transparency, no GrabPass; inputs `_OpaqueDepthTexture`, `_ReflectionTex`): reference `work/visual/ref/ryujinx/views/free_wasser_a/b.png` (targets in `docs/wasser.md`). Suspected: render-target textures are read incorrectly in Metal path. Owner: `ap-recomp-qa`.
2. **Pokémon Center interior** solid blue, dark lines on right (NVN/shader layer).
3. **iPad:** crash if intro video is not skipped immediately (not reproduced); startup took 2–3 attempts. Software VP8 decoder (FFmpeg) works; H.265 via VideoToolbox is an alternative. Owner: `ap-recomp-ios`.
4. Camera offset 28 px relative to Ryujinx (camera pan timing, probably timing only).
5. Title image: no Ryujinx reference (F8 needed at title).
6. Memory buffers/compute read wrapped guest memory; 32-bit model (`rebase32`) not yet proven on device; SDK requires 3.14 GB contiguous.
7. Not implemented: MetalFX, hardware controller test, iPad touch controls, Vulkan on Windows, audio (currently silent; being investigated in Todo `rc-audio`).

## 4. Shared Tools (Remain in Use)
- **Extraction:** build hactool, XCI/NSP → `work/exefs`, `work/romfs` (`scripts/build_all.sh` stages `tools`, `extract`); Il2CppDumper → `work/il2cpp`; Ghidra project `work/ghidra/bdsp` (166,095 functions).
- **Shaders:** Maxwell→MSL/GLSL translator `shader_translator/` (LASRecomp MIT base, `NOTICE.md`, 4,276/4,276 blobs recognized, 0 failures across 5,959 programs, fidelity measured).
- **Conversions:** VP8→H.265 (`video_convert.sh`, CRF 18, +41% size), BC→ASTC (`texture_transcode.py`, 6×6: median 46.2 dB PSNR), Switch→player bundle platform (`bundle_retarget.py`).
- **Saves:** `bdsp_save.py` (validate, fix hash), `ios_push_save.sh` (iPad), `install_save.sh` (recompilation); the Mac ↔ Ryujinx save sync was removed. **Standard test save:** city (Zone 24), 69:08:16 play time, SaveData SHA-256 `0396a4a62735…`.
- **Image checks:** `visual_compare.py`, `visual_ref.py`, `visual_scenarios.py`, `visual_auto.sh`; Ryujinx references (F8, Linux machine) were fetched by a script and triggered with a key player at the time; both have since been removed, so references are now copied and imported by hand (`visual_ref.py import`). Phase B (Unity capture) is discontinued.
- **Analysis assets (Unity-era, still useful as reference):** oracles `battle_oracle*.py`, `pokepara_oracle.py` (Unicorn runs real ARM64 functions), specifications `kampf-spezifikation-1…7`, `pokepara-spezifikation`, `evscript-spezifikation`, `masterdata`, `bundle-katalog`, `ui-spezifikation-1…3`.

## 5. Unity Rebuild (Deprecated, Frozen)
At retirement: 763 EditMode tests passing; battle (handlers, flow, AI complete), event interpreter (597 of 599 host commands), game core, field, UI windows via stubs, render remapping with generated shaders (99.8% of variants). No longer built or maintained; now serves only as reference and comparison. Both Unity Editors are closed.

## 6. Environment
| Device | Role |
|---|---|
| MacBook Pro M1 Pro, 16 GB | Main computer; generator, Mac app, iOS build (Xcode 26.0.1 via `DEVELOPER_DIR`), about 36 GB free |
| Linux machine (Ryzen 5 7500F, 30 GB, RTX 2080 Ti, Fedora) | Temporary build/test helper, Vulkan run, Ryujinx 1.2.78 for reference images; no longer connected to this workflow |
| iPad Pro 12.9-inch (M2), iPadOS 26 | Target device; Increased Memory Limit: 8 GiB instead of 5 GiB (free team, 7-day signature) |

Local and never in repository: `work/`, `tools/`, `research/`, `nsp/`, `Ryujinx/`, `Ryujinx_July23/`, `unity/Assets/XnuStubs|XnuGenerated`, `cache/`.

## 7. Open Decisions and Risks
- Clarify **legal status** before public distribution (repository contains only recompiler/runtime/docs; generated C and binaries stay local).
- **iPad device storage:** full RomFS (about 4–5 GB) on device; strategy (full vs. subset) in progress.
- **Build time for generated code in Xcode** on iOS (about 1 GB C) not measured.
- **Free-team signature** expires after 7 days.

## 8. Next Steps (In Order)
1. Fix water and interior in Metal, then repeat image comparison against Ryujinx.
2. iPad: reproduce and fix video crash, make startup reliable, finish `recomp-ios.md`.
3. Run QA scenarios (menu, Pokémon Center, battle, save/load, sustained run), track bugs in `recomp-qa.md`.
4. Test touch controls and controller on iPad.
5. Repeat Linux/Vulkan run with video and save (port Mac fixes to Vulkan).
6. Add `recomp-ios` stage to `build_all.sh`; remove Unity stages from default run.

## 9. Working with Subagents
- Large models (Sonnet) for debugging and kernel/NVN/codec code; small models (Haiku/Luna) for runs, measurements, inspection, and docs. At most two large agents at once.
- Agents never commit; tests and commit are handled by the main agent. Long runs use `nohup`/`setsid` plus a log file.
