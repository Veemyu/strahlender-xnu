# Native Linux Vulkan backend

Current build instructions and verified development-package names:
[BUILD.md](BUILD.md), section 6.

The native runtime uses Vulkan, SDL3, shaderc, VMA, and optional FFmpeg movie
decoding. Qt6 can own the Vulkan surface in the runtime process, supporting
native Wayland or X11. A separate-process X11 embedding host remains available.
Linux audio, full rendering parity, and extended gameplay are not complete.

## Build dependencies, not vendored libraries

Install development packages on the Linux machine. Runtime-only packages do not
supply the compiler headers or pkg-config metadata. The current path obtains
flags through pkg-config and uses the distribution's Vulkan loader, SDL3,
shaderc, Qt6, and matching FFmpeg development files. VMA headers are installed
through the distribution (or a separately reviewed package on Arch).

No automatic Homebrew header transfer, VMA download, or copied-library fallback
is part of the maintained build. Existing approved MIT runtime sources and
notices remain unchanged in purpose. Generated code, binaries, images, source
icons, keys, and game data stay outside Git under ignored work/.

## Commands

The supported user workflow runs locally on Linux: use
`scripts/recomp/linux/local/build_all.sh` for guest modules,
`scripts/recomp/linux/local/vk_build.sh --qt` for the runtime/frontend, and
`scripts/recomp/linux/local/vk_qt.sh` to launch. See BUILD.md for package and session requirements.

Both Qt hosts were built and briefly launched before the system-package cleanup.
The user confirmed visible Linux icons. Source identity and Qt syntax were
checked on the Linux machine. The new package-only path deliberately fails when development
packages are missing; its full native build must be repeated after installation.
Unit tests verify preflight success/failure and no automatic replacement downloads.

Historical renderer measurements and investigations:
[recomp-vulkan.de.md](recomp-vulkan.de.md). They describe earlier builds, including
the now-retired copied-header workflow, not the current installation procedure.

## Historical renderer investigation report

The measurements below describe earlier builds and investigations. Their copied-header workflow is retired; see the maintained package installation and commands above for the current build path.

### Recompilation: Linux Vulkan path (later Windows target) (`ap-recomp` Vulkan)

Status: 2026-10-19, interim after phase 3 (updated after each phase). Based on `docs/recomp-gate2.md` (NVN/Metal layer, backend abstraction), `docs/recomp-linux.md` (Linux machine, earlier measurements), `docs/shader-translator.md`, and `research/LASRecomp/docs/linux.md`. Task: render recompiled BDSP on Linux x86-64 with Vulkan (no audio), window via SDL3, and offscreen PNG output for tests.

**Labels:** **measured** = measured with the Linux `vk_*.sh` scripts (now under `scripts/recomp/linux/local/`) on the Linux machine (Ryzen 5 7500F, RTX 2080 Ti, Vulkan 1.4.329 driver, Fedora 44) or on Mac; raw logs (`vk-*.log`) are not in the repository. *Suspected* = inference without a test. No game binaries, generated code, shaders, cache, or images are in the repository (all under `work/`).

## Summary

| | |
|---|---|
| **Vulkan path** | **Runs** on the Linux machine: guest boots through `nnMain`, NVN initialization, RomFS game data, shaders, and draw calls. **Device: NVIDIA GeForce RTX 2080 Ti** (Vulkan 1.4.329), detected and used. No crashes in any run (up to 40 s offscreen, 22 s in Wayland window). |
| **Image** | **Recognizable, complete image**: guest renders the **language selection** screen (first launch: English, Español, Français, Deutsch, Italiano, にほんご, 日本語, 한국어, 简体中文, 繁體中文 over a crystal background, with “Select the language you would like to play in.” below), with **7 draw calls per frame**, 59.8 fps, about 0.1 ms GPU time per frame (measured with `BDSP_VK_PROF=1`). It appears in the upper-left 1280×720 area of the 1920×1080 target (rest is black; see requested changes). Metal path produces a black image at the same revision (see “Comparison with Metal”). |
| Shaders | Our translator (`shader_translator/`, `--glsl`) translates **4,276/4,276** unique game programs (3,593 fragment, 683 vertex); `glslc --target-env=vulkan1.3` compiles **4,276/4,276** (Mac, 95 s with 8 threads; measured). Runtime compiles 3,025 programs (keyed pairs) to SPIR-V in about 3 s; **1,206** unique SPIR-V modules, 115 MB. Cold (empty cache) and warm (populated) differ little (first draw calls at 3.6 s cold, 3.3 s warm). |
| Determinism | Two runs with an empty cache produce the **same 1,206 filenames and identical contents** (combined file checksum identical). Key = FNV-1a hash over stage and GLSL source; source is produced solely from Maxwell program data in our dump and the `ShaderKey`. **Ryujinx cache is not used.** |
| Build | `NVN_BACKEND=vulkan scripts/recomp/rt-bdsp/build.sh` (on the Linux machine: `scripts/recomp/linux/local/vk_build.sh`): Vulkan portion builds in **5 s** (15 files, `clang -O2`), linked size 353 MB. On Mac, `VK_SYNTAX=1 …/nvn/vulkan/build_vk.sh` checks syntax using Homebrew headers (all 12 sources pass). |
| Offscreen | `--headless` renders to a custom-sized image (1920×1080, B8G8R8A8), **without a window or display connection** (needs no desktop session); `--screenshot-after N` writes `work/recomp/shots/frame_NNNNN.png` (1920×1080). |
| Window | SDL3 + Wayland: 22 s in 1280×720 window (swapchain 2176×1224 due to desktop scaling), 1,060 frames, 59.8 fps, no focus stealing (`BDSP_NO_USER_INPUT=1`). |
| Unresolved | no guest-page write tracking (vertex cache disabled, textures rechecked); compute skinning/particles/MRT not reached (0 dispatches); pipeline cache not saved at exit; Windows not attempted. |
| **Finding (also applies to Metal)** | **The bindless texture and sampler tables were swapped:** for two-word handles, **textures** are in the table starting at `0x168`, and **samplers** in the table starting at `0x568` (not vice versa; Unity binds a texture and sampler for a unit at the same index). Programs where the compiler assigned different texture and sampler indices bound the wrong textures. This affects **847 of 3,592** unique fragment programs with bindless textures (**23.6%**, measured on blobs using `maxwell2msl --info`); the remaining 2,745 have matching indices, where the old assumption had no effect. It was visible in TextMeshPro text (font atlas bound as the “face texture,” producing broken narrow glyphs); after correction, text is **pixel-identical** to an independent second mapping (reverse mapping within texture count). Metal's `renderer.m` (`shader_handle`, `las-nvn.patch`) makes the same old assumption as the Vulkan path; it needs the same swap (change request 1). |

## Structure (`scripts/recomp/rt-bdsp/nvn/vulkan/`, all new in the historical implementation)

| File | Contents |
|---|---|
| `prepare_vk.sh` | Calls `../prepare.sh` with `NVN_SRC=work/recomp/nvn-src-vk` (shared pieces: `objects.c`, `cmdbuf.c`, `formats.c`, `tegra.c`, `astc.c`, our translator, `las-nvn.patch`—shared-file patching remains with the other agent); then copies the clone's Vulkan portion (`device.c`, `exec.c`, `shaders.c`, `shaders.h`, `textures.c`, `vk.h`, `vma.cpp`), overlays `shim/`, and applies `las-vk.patch` |
| `las-vk.patch` | Our changes to the Vulkan code (listed below, 287 lines) |
| `shim/` | `platform.h`, `kernel.h`, `settings.h`, `ui/menu.h`: replacement clone headers, overlaying `nvn/shim/` |
| `vk_glue.c` | `plat_written_pages` (always “tracking unavailable”), `plat_terminate`, `g_blocked_ns`, default `BDSP_PACE=0` |
| `build_vk.sh` | Builds objects into `work/recomp/rt-bdsp-vk/nvnvk/`; `VK_INC` (header directory, default `./include-vk` or Homebrew), `VK_SYNTAX=1` |
| `NOTICE.md` | LASRecomp origin (MIT) and third-party components (Vulkan headers, VMA, SDL3, shaderc); none are in the repository |

The shared `rt-bdsp/build.sh` was changed minimally after rereading it: the `vulkan)` branch calls `build_vk.sh`, sets `RT=…-vk`, `OUT=…_vk`, and libraries `-l:libvulkan.so.1 -l:libSDL3.so.0 -l:libshaderc_shared.so.1 -lstdc++`. One sentence was also added to `rt-bdsp/NOTICE.md`.

The former private-test scripts (file transfer and detached jobs) were removed. The Linux scripts (prefix `vk_`) now live under `scripts/recomp/linux/local/` and run locally. The obsolete header-copy step is not part of the current package-based workflow.

### Changes to the clone sources (`las-vk.patch`)

| File | Change |
|---|---|
| `exec.c` | **Separable programs** (`CMD_BIND_PROGRAM` with stage mask; stages combined into one program), **separate samplers** (`CMD_BIND_SAMPLERS`, `st.smp`), **bindless textures** (`shader_handle`: texture word from `0x568`, sampler word from `0x168`, 8 bytes each, from constant buffer 2—the same rule as `renderer.m`), `no_rscale`, remove tint path (`uses_tint` no longer exists in translator), program table with 16,384 entries |
| `device.c` | **`--headless`** (`BDSP_HIDDEN`): instance without surface extensions, device selection without present check, three offscreen images instead of swapchain, no present; images to `BDSP_SHOT_DIR` or `work/recomp/shots`; pipeline cache under `work/recomp/cache`; pool memory range from `nvn_glue_mem_range()`; window title |
| `shaders.c` | SPIR-V cache under `work/recomp/cache/spirv` (LAS wrote to `cache/` in working directory) |

Unchanged: `textures.c`, `vk.h`, `vma.cpp`, `shaders.h`. Patch applies cleanly to a fresh clone and produces the same copy as the working tree (checked with `diff -r`).

## Phase 1: headers and libraries without sudo (measured)

The Linux machine has runtime libraries but no development packages and no internet. Present and linked by **full path** (no `-dev` symlinks): `/usr/lib64/libvulkan.so.1`, `/usr/lib64/libSDL3.so.0` (3.4.16), `/usr/lib64/libshaderc_shared.so.1` (package `libshaderc-2026.1`). **Correction to the assumption that “shaderc is missing”:** runtime library is present as a dependency of other packages; only the header is missing. This removes the planned workaround of precompiling with `glslc` on Mac: the clone compiles GLSL at runtime as intended, with the cache making it deterministic and inexpensive.

The former header-copy step copied **headers only** to `include-vk/` on the Linux machine (27 MB): `vulkan/`, `vk_video/` (Homebrew `vulkan-headers` 1.4.363), `SDL3/` (Homebrew `sdl3` 3.4.18), `shaderc/` (Homebrew `shaderc` 2026.4; only C API used), and `vk_mem_alloc.h` (VMA, MIT, downloaded from GitHub to `work/recomp/deps-vk/` because no Homebrew formula was available). VMA license is alongside it (`LICENSE-VMA.txt`).

The copied inputs were checked on the Linux machine against Mac's SHA-256 list, all four **OK** (short hashes are first 16 hex digits):

| File | Size (bytes) | SHA-256 (short) |
|---|---:|---|
| `rtld` | 7,187 | `bc175ad9865adb48` |
| `main` | 37,895,896 | `9c6b1d847d8fb3a1` |
| `sdk` | 5,755,393 | `1c9f198a91c0bcfe` |
| `subsdk0` | 3,409,290 | `67a38fcf89cd13e0` |

Not copied: `main.npdm`, keys, NCA/XCI/NSP, RomFS, saves, LASRecomp `third_party`. Total required on the Linux machine: about 4 GB (1 GB generated C each for `c` and `asm`, 0.8 GB objects per mode, 0.35 GB library).

Optional user package list (only if using system packages instead of `include-vk/`; Fedora names, unverified; no sudo was run):

```sh
sudo dnf install vulkan-headers vulkan-loader-devel SDL3-devel libshaderc-devel VulkanMemoryAllocator-devel
sudo dnf install vulkan-validation-layers     # diagnostics only (BDSP_VK_VALIDATION=1)
```

Then set `VK_INC=/usr/include` (or remove `include-vk/`); `build.sh` stays the same. None of these packages were required for the historical build.

## Phase 2: backend integrated (measured)

Findings on the first build on the Linux machine (all fixed without touching shared files): `g_debug_frame` was defined by both `nvn_glue.c` and `exec.c` → compile `nvn_glue.c` for Vulkan with `-Dg_debug_frame=bdsp_glue_debug_frame`; `kernel_heap_size` already exists in `kernel.c` (Vulkan implementation uses it); `g_blocked_ns` (time spent in wait calls, used for clone frame pacing) was missing → added `vk_glue.c`; disable frame pacing (`BDSP_PACE=0`), since game pacing uses the Vsync event from `services_gfx.c`. Shims supply missing headers/symbols (`plat_written_pages`, C `menu_render`, `UPSCALE_FSR1`). Otherwise, `exec.c` (3,790 lines) compiled without logic changes.

## Phase 3: local run on the Linux machine (measured)

Requires RomFS and `main.npdm` from the user's **own** dump in `work/romfs/` and `work/exefs/` on the Linux machine (RomFS about 4.7 GB; never in the repository; see BUILD.md, section 6.2). Earlier runs intentionally stopped before RomFS; it is needed for draw calls.

Run (`scripts/recomp/linux/local/vk_run.sh --headless --timeout 40`): `[vk] gpu 0: NVIDIA GeForce RTX 2080 Ti (api 1.4.329)` → device, 1920×1080 swapchain/offscreen → `nvnBootstrapLoader`, device, window with 3 textures → 3,025 programs in ~3 s → from t=4 s, 7 draw calls per frame, 240 frames/2 s. Duration 40 s, RSS 2.4 GB (offscreen, including 650 MiB via MapPhysicalMemory, Vulkan memory, and shader cache), 0 NVN functions without host implementation.

Same 7 draw calls as Metal path (full-screen quad, meshes with 1,086/48/96/54/6 indices from 2048×2048 ASTC atlas, then text mesh with 384 indices sampling 1024×1024 R8 font atlas).

## Comparison with Metal and finding about shared runtime

Mac Metal path (copy of `work/recomp/bdsp_boot` from 14:01, same images `img_gfx`, `--headless --screenshot-after 300`) produces **all-black** frames 300, 600, 900, 1,200 (mean 0). Vulkan shows language selection in the **same game state** (same counts: 7 draw calls per frame). Pixel difference **cannot** be calculated because Metal has no image. Once Metal produces an image, compare both outputs with `scripts/visual_compare.py` (already present, from another agent); Vulkan images are in `work/recomp/shots/`.

**Important finding in investigation of black Metal image (measured):** both paths see the **same inputs** in frame 300: same program addresses (`vs=72c0fcbd00 fs=72c0fcc000` …), same constant-buffer addresses (`f0(72beb71600,16)`, `f0(72beb71d00,112)`, `v1(72beb71700,480)`), same values (fragment constant buffer 3: `[1 1 1 1]` for full-screen quad, `[0 0 0 0]` for atlas meshes, time vector `[0.26 5.1 10.3 15.4]` for text; Vulkan log with `BDSP_DEBUG_FRAME=300`, Metal log with `BDSP_DEBUG_FRAME=300 BDSP_DEBUG_DATA=1`), and same 7 draw calls with same textures (1280×720 `0x3f`, 2048×2048 ASTC `0x7d`, 1024×1024 R8, 4×4 `0x25`). Thus atlas-mesh color factor `[0 0 0 0]` is **not** the cause (Vulkan renders those meshes visibly; these factors apparently are not what the shader reads). **Game flow is therefore fine and failure is in Metal execution** (`renderer.m`/`metal.m`: render target/blend/presentation), not guest logic, timing, or constant buffers. Swapping the texture/sampler table in `renderer.m` alone (copy under `work/recomp/nvn-src-mtest`, 40 s Metal run) does not change the image (values ≤2/255). Next step for Metal: dump frame 300's passes individually (`BDSP_DEBUG_FRAMES`) and compare with Vulkan passes (`vk` can do this with `build/pass_*.png`; create `build/` first).

## Run with the new save (14:58, measured)

Build: `nvn_glue.c` (new Gate 2 input layer) includes `SDL3/SDL.h`, `stdatomic.h`, `string.h` only under `__APPLE__`; Linux then lacked all `SDL_SCANCODE_*` and `atomic_fetch_*` (20 errors, **not** a header issue: `include-vk/SDL3/SDL_scancode.h` was present). Workaround in Vulkan build: `build_vk.sh` compiles `nvn_glue.c` with `-include SDL3/SDL.h -include stdatomic.h -include string.h -include strings.h`. Change requested in `nvn_glue.c`: move those four includes out of the `#ifdef __APPLE__` block (only `mach-o/*` belongs there), eliminating workaround.

Run `scripts/recomp/linux/local/vk_run.sh --headless --timeout 60 --screenshot-after 4 --save work/recomp/save` (save SHA-256 `0396a4a62735` on the Linux machine, `user_id.hex` present):

- `[acc] user ID from work/recomp/save/user_id.hex`, `[fs-save] cmd 7 …/main2`, commands 7 and 8 on `…/SaveData.bin`: **save opens and is read**.
- Language screen no longer appears (until crash around frame 120, Vulkan renders only black; first draw calls normally occur after ~3 s of shader compilation).
- **Crash in guest code after 6.5 s (SIGSEGV, address 0)** at `android::OMXCodec::findMatchingCodecs` ← `android::ACodec::UninitializedState::onAllocateComponent` ← `onMessageReceived`: guest creates a video decoder (MIME chain `vnd.on2…`, VP8: title movie), but OMX/codec integration (nvdrv/nvdec or similar) is missing. **Same crash with identical guest stack in Mac Metal run** (copy of `bdsp_boot` from 14:53, after 16.9 s): not a Linux/Vulkan issue, but a missing video service in shared runtime.
- Input (`hid`) was not needed; run does not get that far.

Images: `work/visual/recomp/vk_save/` (30 PNGs, all black except frame 120, mean 0.3).

## Open items (priority order)

1. **Resolved (finding above):** TextMeshPro text in language-selection dialog. Investigation (measured): font atlas itself is correct (R8 1024×1024 dumped as PGM), vertex data and constant buffers plausible (projection 1/640, 1/360), swizzle `0,0,0,R` is correct; fragment shader samples `t0` with atlas UVs (`uv0`), but binding supplied a 4×4 white texture → table swap. No longer open. Still **open**: validate translator's GLSL output overall against Ryujinx reference (MSL: 332/387 pairs ≤1/255; GLSL never measured).
2. Guest-page write tracking (`plat_written_pages`): currently always “unknown” → vertex cache disabled (`vcache`), textures rechecked by hash (4 full + 56 samples every 60 frames, 19.8 MB upload every 2 s). Linux offers Soft-Dirty (`/proc/self/clear_refs`, `pagemap`) or `userfaultfd`; needed as load grows.
3. Pipeline cache (`work/recomp/cache/vk_pipelines.bin`) is not saved: process exits via monitor's `_exit`; `quick_exit_handler` does not run. Optional.
4. Compute (skinning, particles, `LDG/STG`): 0 dispatches at title screen; clone supports binding guest memory as Vulkan buffer (`VK_EXT_external_memory_host`), but untested and pins up to 5 GB. If import size fails, disabled path `BDSP_VK_NO_GMEM=1` would be needed.
5. Frame pacing (same gap as Metal) and input (`hid` reports no state): shared runtime.
6. Window: brief Wayland test passed; X11 (`SDL_VIDEODRIVER=x11`) and fullscreen untested.

## Change requests for shared runtime

(I did not modify these files, except `build.sh`, as noted above.)

1. **`renderer.m` (Metal), `shader_handle` in `las-nvn.patch`:** swap texture and sampler tables (see “Finding”): for `bindless_has_sampler`, derive **texture index from `bindless_sampler_offset` (starting at `0x168`)** and **sampler index from `bindless_offset` (starting at `0x568`)**. Affects 23.6% of fragment programs and may change Metal image.
2. **Target size/crop:** game renders 1280×720 into 1920×1080 window image and calls `nvnWindowSetCrop` (stored as `crop[4]` in window object in `objects.c`, never passed to `backend_present`). `widescreen_present_crop` in `nvn_glue.c` always returns full image; display and screenshots therefore have black at bottom/right. Pass `WIN->crop` to presentation for both backends.
3. **`nvn/nvn_glue.c`**: put `bool g_debug_frame;` behind `#ifndef BDSP_NVN_VULKAN` or in its own section (Vulkan version defines it itself; current workaround is `-Dg_debug_frame=…` in `build_vk.sh`). Generalize log line `[nvn] Metal buffer at …` to “NVN pool memory range.”
4. **`kernel.c`**: provide `__thread uint64_t g_blocked_ns` (time thread spends in wait/sleep calls) when clone frame pacing is needed; currently `nvn/vulkan/vk_glue.c` supplies a zero definition (remove it there then).
5. **`build.sh`**: default `NVN_BACKEND=vulkan` on Linux if `include-vk/vulkan` or `pkg-config vulkan` is available (currently `none`).
6. **`kernel.c`/`main.c`**: put four Mach sites behind a small platform layer (time, thread suspension, stack, memory report), removing `scripts/recomp/linux/compat` (also in `docs/recomp-linux.md`, section 7); same layer is prerequisite for Windows.
7. Investigate Metal (`renderer.m`/`metal.m`): black image arises in execution, not guest logic (see “Comparison with Metal”); compare individual passes of frame 300 with Vulkan passes.
8. `--headless` in `main.c` says “rendering remains Metal”; for Vulkan it also means “without a display connection”—update comment.

## Windows outlook (not attempted, *suspected*)

The clone's Vulkan component builds for Windows (MSYS2 `clang64`: `mingw-w64-clang-x86_64-{clang,SDL3,vulkan-headers,vulkan-loader,vulkan-memory-allocator,shaderc}`; Visual Studio with `clang-cl` is awkward because runtime uses GNU inline assembly and `__attribute__`). Runtime remains to be ported: **Mach replacements → Win32**: `mach_absolute_time` → `QueryPerformanceCounter`; `thread_suspend/resume/get_state` (Boehm GC suspension) → `SuspendThread`/`GetThreadContext`; `mach_vm_allocate` at fixed addresses (`0x7000000000`, 12.5 GB window) → `VirtualAlloc(MEM_RESERVE)` at requested address (Windows supports up to 128 TB); `mach_vm_region`/`task_info` → `VirtualQuery`/`GetProcessMemoryInfo`; signals → structured exceptions; ELF/Mach-O sections for `HLE_FUNC` (`__start_hle_impls`) → PE sections with `.hle$a`/`.hle$z` markers. Reference: `research/LASRecomp/runtime/platform/windows.c`. Estimated effort: *suspected* 3–5 days after platform layer in request 4.

## Reproduction (local)

Run from the repository root on the Linux machine, with `work/exefs/` and `work/romfs/` in place (BUILD.md, section 6.2):

```sh
scripts/recomp/linux/local/build_all.sh           # guest modules (needed before vk_build.sh)
scripts/recomp/linux/local/vk_build.sh            # NVN_BACKEND=vulkan → work/recomp/bdsp_boot_vk
scripts/recomp/linux/local/vk_run.sh --headless --timeout 40 --screenshot-after 300
# Window (brief, no focus stealing; desktop Wayland session):
scripts/recomp/linux/local/vk_run.sh XDG_RUNTIME_DIR=<SESSION_RUNTIME_DIR> WAYLAND_DISPLAY=wayland-0 SDL_VIDEODRIVER=wayland BDSP_NO_USER_INPUT=1 --window 1280x720 --timeout 22
# Mac syntax check with Homebrew headers:
VK_SYNTAX=1 scripts/recomp/rt-bdsp/nvn/vulkan/build_vk.sh
```

Clone diagnostic environment switches: `BDSP_VK_PROF=1` (CPU/GPU time per category), `BDSP_DEBUG_FRAME=N` (draw calls for frame N in log), `BDSP_SAVE_MSL=1` (GLSL to `build/glsl/`; create `build/` first), `BDSP_VK_VALIDATION=1`, `BDSP_VK_NO_SPIRV_CACHE=1`.

## Linux: frame rate, window size, overlay (as of 2026-10-20)

- `BDSP_FPS=30|60|120` sets pacing (Vsync event in `services_gfx.c`, limiter `frame_pace` in `nvn_glue.c`); measured in window: 30.0 / 60.0 / 120.0 fps. At runtime: F5 = 30, F6 = 60, F7 = 120.
- Window size: `BDSP_WINDOW=WxH` at launch; while running F1–F4 = 960×540, 1280×720, 1920×1080, 2560×1440 (like Cmd+1 through Cmd+4 on Mac), F11 = fullscreen. Vulkan path only (`nvn/vulkan/src/nvn/vulkan/device.c`, `ui_run`); Mac path unchanged.
- `BDSP_MANGOHUD=1` enables MangoHud overlay (off by default). Dependency: `mangohud` package (Fedora, implicit Vulkan layer), runtime only, not needed to build. `MANGOHUD_CONFIG` overrides defaults (fps, frametime, CPU/GPU).
- **Qt shell with menu bar** (`scripts/recomp/rt-bdsp/app/linux/`, Linux only): C++/Qt6 Widgets program `bdsp_qt_host.cpp`, menus and text based on `app_ui.m`, translations under `lproj/*.lproj/Localizable.strings` (de, en, en_US, en_GB; selected by `LC_ALL`/`LC_MESSAGES`/`LANG`, falls back to en). Vulkan canvas runs as child window with `BDSP_EMBED=1` and `SDL_VIDEODRIVER=x11` (Xwayland under Wayland). **Qt6 build dependency:** `build_qt.sh` (CMake) checks Qt6 Widgets and, if absent, prints the distribution-specific install command from `deps.txt` (apt, dnf, pacman; package-name versions are documented there; nothing is installed). On the Linux machine: `scripts/recomp/linux/local/vk_qt_build.sh`; launch: `scripts/recomp/linux/local/vk_qt.sh`. Program resides in `work/recomp/qt-host/`; `bdsp_l10n.py` remains only as reference for testing `lproj` files (`scripts/tests/test_bdsp_l10n.py`).
