# Native generator source attribution

The NSO layout, symbol/relocation semantics, exception-table boundary discovery and
initial instruction-entry heuristics are adapted from the statically vendored
LASRecomp generator (Copyright (c) 2026 Peiikai, MIT), together with this project's
`eh_gen.py`, `eh_lsda.py` and `mkimg.py`. The upstream license remains in
`../upstream/LICENSE`; repository-wide attribution is in `THIRD_PARTY_NOTICES.md`.
This native port is maintained independently of upstream.

The unmodified LZ4 1.9.4 implementation is Copyright (c) 2011-2020 Yann Collet,
BSD-2-Clause. Its license and per-file source checksums are in `vendor/lz4/`.

No Nintendo code, game data, keys or generated game code are included here.
