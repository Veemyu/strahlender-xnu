# Night Report (Status 2026-10-18, approx. 21:15)

## Completed Work
| Todo | Result | File |
|---|---|---|
| Save specification | complete, confirmed against a real save (MD5, rival name) | `save-spec-entwurf.md` |
| Save validator | 23 tests passing; `check` against SaveData.bin and Backup.bin succeeds | `scripts/bdsp_save.py`, `save-validator.md` |
| Data inventory | 14,052 UnityFS bundles, 696 banks, 3,241 WEM (Vorbis), 18 videos (VP8) | `daten-inventar.md` |
| Game code inventory | 6,200 gameplay-logic types, 39,100 methods, engine about 20% | `spielcode-inventar.md` |
| Cpp2IL assessment | only 27.9% clean method bodies; Ghidra remains the main source | `cpp2il-bewertung.md` |
| Shaders and audio | 2,971 cache entries, 5,937 SPIR-V modules, MSL translation 5932/5932, vgmstream decodes samples | `shader-audio-machbarkeit.md` |
| Architecture proposal | options A, B, C, and a vertical slice D; no decision | `architektur-entscheidung.md` |

## Problems and Workarounds
- Cpp2IL prerelease: `Killed: 9` (unsigned); fixed with ad hoc signing. It stopped at the NSO segment boundary, so `master` was built locally and patched (in `tools/`, not the repository).
- vgmstream: the prebuilt version would not start without Homebrew libraries, so it was built locally.
- Unity 2019.4 in batch mode: license error (GUI only).
- opendpr: boot fails (see `opendpr-aufbau.md`); blocker B1 (Windows shader bundles) remains.

## Status
- Repository: everything pushed, Veemyu as the only author, no co-author trailer.
- Local, gitignored: `work/` (dump, Ghidra project, exports), `tools/`.
- Ghidra project `work/ghidra/bdsp`: 166,095 functions, pseudocode export in `work/decomp/`.
- Not touched: `~/.copilot/mcp-config.json` (except for the earlier REA configuration), or the Linux machine.

## Open Decisions
See `architektur-entscheidung.md` (section “Open Questions”).

## Suggested Next Steps
1. Discuss the architecture gate (option D, vertical slice).
2. Analyze the inner layouts of save substructures (extend the spec and validator).
3. Open the master-data bundles (`personal_masterdatas`, `masterdatas`) and clarify the format.
4. Trace the `UIManager.Instance` error in opendpr (as a reference for the boot sequence).
