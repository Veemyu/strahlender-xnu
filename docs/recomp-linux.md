# Linux: build host and Vulkan backend

The same recompilation also builds for Linux x86-64 with a Vulkan renderer and a Qt 6 frontend. Linux is tested on x86-64 only. A Linux ARM64
build compiles but is not tested yet; its backend and installer path are complete. **Status: work in progress, not playable.** Rendering, input and frame rate work in a window; audio, compute-heavy scenes, long sessions and Windows are not done.
The user workflow (packages, commands, session variables) is in [BUILD.md](BUILD.md), section 6, and the guided installer
`./install-linux.sh`. This page records how the Linux path is put together and what was measured. The figures come from an earlier
workflow with a dedicated remote Linux machine (x86-64, 6 cores / 12 threads, 30 GB RAM, RTX 2080 Ti, Fedora 44) that no longer
exists; treat them as reference values from 2026-10-19/20.

## 1. Scripts (`scripts/recomp/linux/local/`, run from the repository root)

| File | Purpose |
|---|---|
| `setup.sh` | checks tools and Python packages (`lz4`, `capstone`, `unicorn`), compares the inputs with `work/exefs.sha256` if present; installs nothing |
| `gen.sh [c\|asm]` | generates the C of the four modules with the LAS lifter; `c` (portable SIMD) is the default, `asm` is only for comparison |
| `compile.sh`, `build_all.sh` | compile in parallel with `-O1` (chunks above `THRESH_O0`, default 300 KB, get `-O0`) and link `libgame.so`; `build_all.sh` runs generation and compile with timing |
| `vk_build.sh [--qt]` | builds `rt-bdsp` with the Vulkan backend (`NVN_BACKEND=vulkan`); `--qt` adds the in-process Qt frontend |
| `vk_run.sh` | runs the Vulkan build, headless by default (`--headless`, `--window WxH`, `--timeout S`, `--screenshot-after N`) |
| `vk_qt.sh`, `vk_qt_build.sh` | launch the Qt frontend (in-process; `BDSP_QT_PROCESS=1` selects the older separate-process X11 host) and build that host (CMake) |
| `probe.sh <test>` | Linux counterparts of the spike probes: `eh`, `eh-real`, `rebase32`, `gc`, `bench`, `boot`, `bdsp` |
| `incr_test.sh` | measurement of incremental rebuilds |

`compat/mach/*.h` is a Mach compatibility layer (time, thread suspension by signal, `task_info`, `mach_vm_*`) so that the shared
runtime compiles on Linux; `deps.sh` holds the dependency checks the scripts use. A final macOS or iPadOS build always comes from the
Mac (Mach-O, arm64 `asm` mode, signing, Metal); the x86 library is an ELF object for Linux and for probes.

## 2. Dependencies

Development packages come from the distribution and are found through pkg-config: Qt 6 Widgets, Vulkan headers and loader, SDL3,
shaderc, the Vulkan Memory Allocator headers, FFmpeg (libavcodec, libavformat, libavutil), clang, CMake, GNU `time`. Nothing is
downloaded, copied or vendored by the scripts; the package table is in BUILD.md. Native Wayland needs the Qt Wayland platform plugin.

## 3. Build measurements (Linux machine, `c` mode)

| | Mac (spike, `asm`, loaded M1 Pro) | Linux machine (`c`, dedicated) |
|---|---|---|
| Generate, four modules, one core | 74 s | 51 s |
| Compile all, 3 jobs, 1 MB `-O0` rule | 937 s | 986 s |
| Compile all, `-O0` from 300 KB, 12 / 10 / 6 jobs | not measured | 310 s / 388 s / 384 s |
| Library | 224 MiB | 327 MiB (`c` mode emits more machine code) |
| Largest compiler peak | 1.7 GB | 1.6 GB |

- Per core the x86 machine is not faster than the M1 Pro; its advantage is parallelism and the `-O0` rule for outliers. The full
  build is governed by the slowest single file (up to 497 s for a 372 KB single function at `-O1` in `c` mode).
- **The generator is platform-independent and deterministic:** the `asm` run on Linux produced byte-for-byte the same 1,400 files as
  the Mac. Generation on Linux fully replaces generation on the Mac.
- **Incremental builds:** with the fixed 32 KiB chunk windows a change of seven SDK functions recompiled 3 of 298 SDK chunks; a build
  without changes costs under a second. Generation itself is not incremental (about 53 s), but unchanged chunks are left alone.
- RAM is not a bottleneck at 10 jobs (about 2 GB above idle); cores are.

CPU probes (exceptions, 180 real landing-pad functions, 32-bit rebase, GC stop in arbitrary registers, boot through the first
services) gave **identical results** on x86 `c` mode and on the Mac; thread suspension uses signals on Linux and Mach calls on
macOS. The float microbenchmark differed only by the NaN sign (ARM default NaN against x86 default NaN), not by fusion; against
Unicorn, recompilation agrees in all runs (see [recomp-diff.md](recomp-diff.md)). Limits: `c` mode lowers FP/SIMD to portable C and
is bit-exact against Unicorn for the cases tested except for the FPSR cumulative flags.

## 4. The Vulkan backend (`scripts/recomp/rt-bdsp/nvn/vulkan/`)

It reuses the shared NVN layer (objects, command recording, formats, ASTC, our shader translator) and replaces the Metal part with
the LAS Vulkan code (`device.c`, `exec.c`, `shaders.c`, `textures.c`, VMA) plus our changes (full source in `vulkan/src/`):

- separable programs (stages combined at bind time), separate samplers, bindless textures from constant buffer 2
  (`shader_handle`, with the table rule in the finding below), no resolution scaling, tint path removed;
- `--headless`: an instance without surface extensions and three offscreen images, so rendering and screenshots need no display
  (images to `BDSP_SHOT_DIR` or `work/recomp/shots`);
- the SPIR-V cache under `work/recomp/cache/spirv`: the translator's GLSL is compiled with shaderc at run time. Two runs with an
  empty cache produce the same 1,206 SPIR-V modules (key = FNV-1a over stage and GLSL); the Ryujinx cache is not used. All 4,276
  unique game programs translate and compile with `glslc --target-env=vulkan1.3`;
- `vk_glue.c` supplies the platform hooks (`plat_written_pages` always "unknown", so the vertex cache is off and textures are
  re-checked by hash).

**Finding that also applied to Metal:** for two-word bindless handles the **texture** table starts at `0x168` and the **sampler**
table at `0x568` (not the other way round; Unity binds texture and sampler of one unit at the same index). Wrong tables bound the
wrong textures in about 24 % of fragment programs and produced broken text.

**Results (RTX 2080 Ti, Vulkan 1.4):** the guest boots to `nnMain`, loads RomFS, creates 3,025 programs in about 3 s, and shows the
language selection with 7 draw calls per frame at 59.8 fps (about 0.1 ms GPU time per frame). With a save, the early runs hit the
title movie (the codec path) and stopped; the movie support of the Mac path is not ported everywhere yet.

## 5. Running it

- `BDSP_FPS=30|60|120` sets pacing (vsync event in `services_gfx.c`, limiter `frame_pace`); measured 30.0 / 60.0 / 120.0 fps in a
  window. At run time F5, F6, F7 = 30, 60, 120 fps.
- `BDSP_WINDOW=WxH` at launch; F1 to F4 = 960x540, 1280x720, 1920x1080, 2560x1440; F11 = full screen (not verified).
- `BDSP_MANGOHUD=1` enables the MangoHud overlay (runtime package `mangohud`, off by default; `MANGOHUD_CONFIG` overrides it).
- The Qt shell (`scripts/recomp/rt-bdsp/app/linux/`, C++/Qt6 Widgets) provides menus, keyboard input, pause, window sizes, frame-rate
  choices and original-icon language selection, with translations in `lproj/*.lproj/Localizable.strings` (selected by
  `LC_ALL`/`LANG`). The in-process host owns its Vulkan surface (native Wayland or X11, `QT_QPA_PLATFORM=wayland|xcb`).
  Run with `XDG_RUNTIME_DIR=/run/user/<UID>` and the session's `WAYLAND_DISPLAY`/`DISPLAY`; never commit session IDs.
- Diagnostics: `BDSP_VK_PROF=1` (CPU/GPU time per category), `BDSP_DEBUG_FRAME=N`, `BDSP_SAVE_MSL=1`, `BDSP_VK_VALIDATION=1`,
  `BDSP_VK_NO_SPIRV_CACHE=1`.

## 6. Open items and limits

1. Guest-page write tracking (Soft-Dirty or `userfaultfd`) so the vertex cache and texture change checks can work cheaply.
2. Compute skinning, particles and MRT were not reached (0 dispatches at the title); binding guest memory as a Vulkan buffer
   (`VK_EXT_external_memory_host`) is untested and can pin several GB (`BDSP_VK_NO_GMEM=1` disables it).
3. The pipeline cache is not saved at exit; X11 and full screen are untested; no audio; input state is not reported to the game.
4. The fixes made on the Mac since (the vertex and index ring buffer, MSAA resolve, the crop inside the window, the worker and
   `-O2` performance work in [rendering.md](rendering.md)) are not ported everywhere.
5. Windows is not supported. It would need Win32 replacements for the Mach calls (time, thread suspension, stack size, memory
   reporting), `VirtualAlloc` for the window, and a toolchain such as MSYS2 `clang64`; a small platform layer for those four Mach
   sites would also remove `compat/`.
6. A package-only full native build (after installing the packages) has to be repeated and verified on a clean machine.
