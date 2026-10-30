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

- **Location:** `scripts/recomp/runtime/` (runtime design, including verbatim portions; comparison and details in `scripts/recomp/runtime/NOTICE.md`; license in `scripts/recomp/runtime/LICENSE-LASRecomp`), and `scripts/recomp/runtime/nvn/movie_glue.c` (based on `runtime/hle/movie.c`).
- **Headers and generator:** Unmodified `cpu.h`, `simd.h`, and `simd_fp.h` in `scripts/recomp/upstream/runtime/`; the generator tools (`gen.py`, `lifter.py` and others) are no longer in the tree and survive only in the git history; adapted native NSO/EH analysis, instruction lifting and function/assembly emission in `scripts/recomp/native-generator/src/` (license: `scripts/recomp/upstream/LICENSE`).
- **NVN graphics layer (Metal and Vulkan):** Modified from LASRecomp (license: `scripts/recomp/upstream/LICENSE`, commit `09f8e5e`); sources in `scripts/recomp/runtime/nvn/src/`, the unmodified upstream originals are in the git history (vendoring commits `e43b466`, `2d01ade`, `d1c40e7`) and upstream (https://github.com/peiikai/LASRecomp, commit `09f8e5e`). Details: `scripts/recomp/runtime/NOTICE.md` and `scripts/recomp/runtime/nvn/vulkan/NOTICE.md`.
- **Reduced vendoring (2026-10-29):** `scripts/recomp/upstream/` keeps only the license and the three headers above. The rest of the former full copy (`runtime/` including `hle/`, `services/`, `ui/` and `nvn/`, and `generator/` including `rando/`) was removed because no build used it; it remains in the git history.
- **Not included:** Upstream `third_party/` (separate licenses, including imgui, smaa, fonts, and the LAS randomizer; Nintendo exclusion in the upstream LICENSE), `fonts/`, and clone metadata (`.git`, Makefile, README, CONTRIBUTING, `docs/`). The `runtime/ui/` components cannot build without `third_party/`; we do not build them.

## Other third-party dependencies (references only)

The installer vendors **iced_winit 0.14.1** under the MIT license in
`installer/vendor/iced_winit/`. The original license is included there. A local
fix for synchronous window resizing is documented in `PATCHES.md` beside it.

- **FFmpeg** (LGPL/GPL depending on its build configuration): Linked for video playback, not distributed here. Check the build configuration as described in `docs/BUILD.md`.
- **Build tools** `capstone` and `lz4` (`tools/pydeps`): Used locally, not distributed.
- **Unicorn 2.1.4** (GPL-2.0-only, the wheel's "BSD" classifier is wrong): distributed with the installer runtime and the Windows tools archive. The project owner accepted the GPL-2.0 terms on 2026-10-30; the Windows archive contains the unmodified source, `COPYING` and a written offer (`NOTICES/README.md`).

## LZ4 1.9.4 (BSD-2-Clause)

The native generator compiles the upstream `lz4.c` and `lz4.h`. They are not stored
in this repository: `scripts/recomp/native-generator/build.py` downloads the pinned
files into the ignored `work/` folder and verifies them against the SHA-256 values in
`scripts/recomp/native-generator/vendor/lz4/source.json`. The unchanged BSD-2-Clause
license and copyright notice are kept next to that pin. This is independent of the
Python LZ4 wrapper.

## Native installer firmware import dependencies

- **zip 2.6.1** (MIT): Rust ZIP parsing, CRC checking and Deflate decoding. Source
  and license are fetched by Cargo at build time; version is locked in
  `installer/Cargo.lock`. No external archive program is required at runtime.
- **ttf-parser 0.25.1** (MIT OR Apache-2.0): bounds-checked parsing of locally decoded
  firmware font tables; also used by the GUI font stack. Fetched by Cargo at build
  time and locked in `installer/Cargo.lock`. Firmware font bytes are never shipped
  in this repository or public installer packages.
