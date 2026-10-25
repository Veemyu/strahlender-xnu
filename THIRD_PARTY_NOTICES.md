# Third-party notices

This repository contains original code and the components listed below. It contains no game data, keys, or content derived from them.

## LASRecomp (MIT)

- **Location:** `shader_translator/translate.c`, `shader_translator/shader.h` (modified; changes documented in `shader_translator/NOTICE.md`).
- **Source:** https://github.com/peiikai/LASRecomp, commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`.
- **Copyright/license:** Copyright (c) 2026 Peiikai, MIT. The unchanged license text is in `shader_translator/LICENSE-LASRecomp`.
- **Upstream disclosure:** The README describes the code as “almost exclusively” AI-generated (Claude through Claude Code), with human direction and review.
- **Other sources mentioned upstream (comments only; no files copied from those projects):** Field layouts based on Ryujinx decoders and envytools documentation. Their licenses have not been reviewed here; the extent of their contribution to upstream is unresolved.
- **Original additions (part 2, not third-party code):** TEX.B, HSETP2 (cbuf/immediate), resource map, and fast-math pragmas. TEX.B and HSETP2 field positions were reconstructed from memory of the Ryujinx decoder-table layout and checked only numerically against the Ryujinx reference (`scripts/shader_fidelity.py`); no Ryujinx source was copied or read.

## Other LASRecomp components (MIT, Copyright (c) 2026 Peiikai)

- **Location:** `scripts/recomp/rt-bdsp/` (runtime design, including verbatim portions; comparison and details in `scripts/recomp/rt-bdsp/NOTICE.md`; license in `scripts/recomp/rt-bdsp/LICENSE-LASRecomp`), and `scripts/recomp/rt-bdsp/nvn/movie_glue.c` (based on `runtime/hle/movie.c`).
- **Headers and generator:** Unmodified `cpu.h`, `simd.h`, and `simd_fp.h` in `scripts/recomp/upstream/runtime/`; generator tools in `scripts/recomp/upstream/generator/` and adapted native NSO/EH analysis and instruction lifting in `scripts/recomp/native-generator/src/` (license: `scripts/recomp/upstream/LICENSE`).
- **NVN graphics layer (Metal and Vulkan):** Modified from LASRecomp (license: `scripts/recomp/upstream/LICENSE`, commit `09f8e5e`); sources in `scripts/recomp/rt-bdsp/nvn/src/`, upstream reference in `scripts/recomp/upstream/runtime/`. Details: `scripts/recomp/rt-bdsp/NOTICE.md` and `scripts/recomp/rt-bdsp/nvn/vulkan/NOTICE.md`.
- **Vendored in full:** Unmodified `runtime/` (including `hle/`, `services/`, `platform/`, `ui/`, and `nvn/`) and `generator/` (including `rando/`).
- **Not included:** Upstream `third_party/` (separate licenses, including imgui, smaa, fonts, and the LAS randomizer; Nintendo exclusion in the upstream LICENSE), `fonts/`, and clone metadata (`.git`, Makefile, README, CONTRIBUTING, `docs/`). The `runtime/ui/` components cannot build without `third_party/`; we do not build them.

## Other third-party dependencies (references only)

The installer vendors **iced_winit 0.14.1** under the MIT license in
`installer/vendor/iced_winit/`. The original license is included there. A local
fix for synchronous window resizing is documented in `PATCHES.md` beside it.

- **FFmpeg** (LGPL/GPL depending on its build configuration): Linked for video playback, not distributed here. Check the build configuration as described in `docs/BUILD.md`.
- **Build tools** `capstone`, `unicorn`, and `lz4` (`tools/pydeps`): Used locally, not distributed.

## LZ4 1.9.4 (BSD-2-Clause)

The native generator vendors the upstream `lz4.c` and `lz4.h` under
`scripts/recomp/native-generator/vendor/lz4/`. The unchanged BSD-2-Clause license
and copyright notice are included there. `source.json` records the upstream tag
and SHA-256 of every imported file. This is independent of the Python LZ4 wrapper.
