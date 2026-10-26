# NOTICE: design and portions derived from LASRecomp

The runtime in this directory follows LASRecomp's design and contains **verbatim portions of upstream code**. A comparison dated 2026-10-19 (lines at least 25 characters long, whitespace normalized) found identical lines in `kernel.c` (45%), `ipc.c` (47%), `services.c` (42%), `services_fs.c` (37%), `dispatch.c` (17%), `bdsp.h` (19%), `main.c` (10%), and `loader.c` (8%). Some are constants and common idioms; the rest is adopted code. It is covered by the upstream MIT license (`LICENSE-LASRecomp`; retain it with every copy). The `research/LASRecomp` clone remains unchanged. Unmodified `cpu.h`, `simd.h`, and `simd_fp.h` are in `scripts/recomp/upstream/runtime/` (license: `scripts/recomp/upstream/LICENSE`).

| Item | Details |
|---|---|
| Project | LASRecomp |
| Repository | https://github.com/peiikai/LASRecomp |
| Revision | Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5` (the clone's only commit) |
| Author | Peiikai |
| License | MIT, “Copyright (c) 2026 Peiikai”. Unchanged text in [`LICENSE-LASRecomp`](LICENSE-LASRecomp). |
| Excluded | Upstream `third_party/`, `fonts/`, and clone metadata (`.git`, Makefile, README, `docs/`). The runtime and generator are vendored in full (`scripts/recomp/upstream/`); see the provenance and NVN sections below. |

The upstream license excludes Nintendo property and third-party components. None of that content is included here. The repository user explicitly authorized use and further development.

## Provenance

| Local file | LASRecomp model (`runtime/`) | Adopted design/code and local changes |
|---|---|---|
| `kernel.c` | `kernel.c` | Mutex/condition-variable/address-arbiter semantics (`ArbitrateLock`, `WaitProcessWideKeyAtomic`, `WaitForAddress`), handle table, `KThread`/`KObject` layout. New: Mach suspension, SVCs `0x20/0x23/0x28/0x2F/0x30/0x31/0x32/0x33/0x36/0x37/0x5F`, host stack size, counters, `G2H` memory mapping. |
| `ipc.c`, `bdsp.h` IPC types | `ipc.c`, `ipc.h` | HIPC/CMIF message encoding and domain management. New: logging, table-driven registry, error stub, `G2H`. |
| `services.c` | `services/am.c`, `acc.c`, `hid_set.c`, `time.c`, `misc.c` | Response layouts: time-service shared memory, language lists, profile structure, application proxy. New: complete command tables, events, logging. |
| `services_fs.c` | `romfs_build.c`, `services/fs.c` | RomFS image layout (0x50 header, data at 0x200, tables afterward), IFileSystem/IFile/IDirectory commands. New: virtual image without a 5-GB file. |
| `dispatch.c`, `loader.c`, `main.c` | `dispatch.c`, `loader.c`, `main.c` | Cached dispatch with HLE slots, startup through `nn::init::Start`. New: four tables, re-entry, watchdog. |

The native generator (`../native-generator/`) adapts the analysis, lifter and emitter from the vendored tools in `scripts/recomp/upstream/generator/`: gen.py, lifter.py, analyze.py, nso.py, patches.py, and simd_c.py; the complete `tools/` revision, excluding `__pycache__`, under `scripts/recomp/upstream/LICENSE`. `patches.py` contains game-specific hooks.

## NVN layer (Gate 2, `nvn/`)

The graphics layer **adopts source code from the clone**, with explicit user approval and under its MIT license (Copyright (c) 2026 Peiikai; text in [`../upstream/LICENSE`](../upstream/LICENSE)). Sources in `nvn/src/` (Metal) and `nvn/vulkan/src/` (Vulkan differences) are **modified** from commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`. Changes now live directly in these files, not in patches. The unmodified reference remains in `scripts/recomp/upstream/runtime/`. The translator comes from `shader_translator/`.

The earlier patch-based workflow copied sources to `work/recomp/nvn-src` using `nvn/prepare.sh` and applied `nvn/las-nvn.patch` and `fixes.patch`. Its claim that changes existed only in patches is historical, not a description of the current directly modified source tree.

| Included upstream components | Excluded |
|---|---|
| Everything under `scripts/recomp/upstream/runtime/` (Metal, Vulkan, `hle/`, `services/`, `platform/`, `ui/`) and `scripts/recomp/upstream/generator/` (including `rando/`) | Upstream `third_party/`, `fonts/`, clone metadata |
| `maxwell/translate.c` and `maxwell/shader.h` are **replaced** by `shader_translator/`, itself derived from LASRecomp; see `../../../../shader_translator/NOTICE.md` | |

Locally authored components include `nvn/shim/*`, `nvn/nvn_glue.c`, `nvn/build_nvn.sh`, `nvn/prepare.sh`, and the earlier patches (`las-nvn.patch`, `fixes.patch`, `debug.patch`). The upstream license excludes Nintendo property and third-party components; neither is included.

**Video layer (`nvn/movie_glue.c`):** Independently written based on the clone's `runtime/hle/movie.c`: `MediaData` layout, extractor, decoder, output queue, and events. BDSP adaptations: vtable slot 2, directly imported calls, video-only track, and writes into the player's buffer. Links FFmpeg (LGPL/GPL depending on build configuration), which is not distributed here.

**Vulkan version (Linux/Windows):** Also adopts the clone's `runtime/nvn/vulkan/*`. This originally used build-time copying and a local patch; the current source layout is described above. Details, dependencies, and licenses: [`nvn/vulkan/NOTICE.md`](nvn/vulkan/NOTICE.md).

## Other third-party code

`third_party/stb_truetype.h` is stb_truetype v1.26 (Sean Barrett, public domain or MIT, your choice; the license text is at the end of the file) in the slightly modified form that Dear ImGui ships. The on-screen keyboard uses it to rasterize the fonts of the user's own firmware (`swkbd_text.c`). The library is not meant for untrusted font files; it only reads the firmware's fonts.
