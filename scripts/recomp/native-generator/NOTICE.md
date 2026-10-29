# Native generator source attribution

The NSO layout, symbol/relocation semantics, exception-table boundary discovery and
initial instruction-entry heuristics, scalar, portable SIMD/FP and assembly instruction lifting and
function/inline-assembly emission, iterative scanning and whole-module chunking
are adapted from the statically vendored
LASRecomp generator (Copyright (c) 2026 Peiikai, MIT), together with this project's
`eh_gen.py`, `eh_lsda.py` and `mkimg.py`. The upstream license remains in
`../upstream/LICENSE`; repository-wide attribution is in `THIRD_PARTY_NOTICES.md`.
This native port is maintained independently of upstream.

The unmodified LZ4 1.9.4 implementation (downloaded at build time, not stored here) is Copyright (c) 2011-2020 Yann Collet,
BSD-2-Clause. Its license and the pinned per-file SHA-256 values are in `vendor/lz4/`.

No Nintendo code, game data, keys or generated game code are included here.

Unicorn 2.1.4 is reused through its native C API and shared library, not reimplemented.
It is pinned by the installer runtime locks; its GPL-2.0-only attribution remains
in the runtime/SBOM notices. The native tool copies that library alongside its
executable and records the library SHA-256. Redistribution of a linked tool must
include the applicable Unicorn notices and corresponding source availability.
