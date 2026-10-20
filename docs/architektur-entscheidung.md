# Architecture Decision (Proposal, No Decision Yet)

Status: 2026-10-18. Based on the project's own notes in `docs/`. Figures are measurements from our dump; estimates are labeled. The user makes the decision.

## Baseline in Numbers
- **Game logic:** about 6,200 types (53%) with about 39,100 methods (around 60% of methods outside the .NET base library). Main areas: battle (1,816 types), UI (1,232), field classes (935). Engine and middleware (Unity, uGUI, DOTween, TMP, Wwise, Nintendo SDK) account for around 20% of methods (`spielcode-inventar.md`).
- **Reconstruction tool:** Ghidra with 166,095 named functions is the primary source. Cpp2IL produces only 27.9% clean method bodies; 65.5% have placeholders. There is no automatic C# reconstruction of usable quality (`cpp2il-bewertung.md`).
- **Save:** format documented and checked with a custom validator (size 0xEF0A4, version 0x34, MD5 at 0xE9818). Internal layouts of substructures remain open (`save-spec-entwurf.md`, `save-validator.md`).
- **Data:** 14,052 UnityFS bundles (v7, Unity 2019.4.27f1, LZ4HC), 696 Wwise banks (v135), and 3,241 WEM files (Vorbis) (`daten-inventar.md`).
- **Shaders:** Switch bundles `shaders` (63 shaders) and `fxparticle` (1 shader), no source code. Ryujinx cache has 2,971 entries and 5,937 SPIR-V modules. `spirv-cross` translates all 5,932 graphics modules to MSL; image equivalence unverified (`shader-audio-machbarkeit.md`).
- **opendpr** (reference, no license): scaffold of about 3,800 files, 93% of dump type names, many placeholders. It compiles in Unity 2019.4 Editor under Rosetta, but boot fails (`UIManager.Instance` null, shader bundle missing) (`opendpr-aufbau.md`).
- **Recomp projects** (LASRecomp, letsgo-recomp): not Unity games, compile on the user's machine and include Nintendo code. Unsuitable for iPadOS. Useful only as a Switch-services checklist (`recomp-referenzen.md`).
- **Editor status:** Unity 2019.4.27f1 runs only as an Intel Editor under Rosetta. License fails in batch mode; GUI works.

## Options

### A – New Unity Project (Newer LTS) with Reconstructed C# Logic
- **Pros:** Unity provides the scene graph, animation, timeline, UI, and particles expected by the bundles. Only about 64 shaders need rewriting (ShaderLab); cache is a reference. IL2CPP is AOT and needs no JIT (not tested).
- **Cons:** roughly 39,100 logic methods must be reconstructed by hand from Ghidra pseudocode. Whether newer Unity LTS loads 2019 bundles is untested. Wwise runtime for Mac/iPad unclear. Licensing and batch mode for newer LTS untested.

### B – Custom Native Runtime (Metal)
- **Pros:** Full control, no foreign-engine overhead, matches `goal.md` (Metal or SPIR-V/MoltenVK). Shaders could be translated SPIR-V→MSL.
- **Cons:** Unity serialization (bundles), animation, timeline, UI layout, and particles must be built from scratch. Same logic reconstruction as A, plus runtime. By far the largest scope.

### C – Reference and Analysis Only
- **Pros:** No release risk. All results remain documentation and tools (save validator, inventories).
- **Cons:** No playable result.

### D – Vertical Slice on A, Then Decide (Proposal for Discussion)
- A small vertical slice in a newer Unity LTS: boot, load data (master data), menu, read save. Goal: measure effort and compatibility (bundle loading, Wwise, shaders), then choose A, B, or C.

## Criteria Compared (Estimates, Not Measured)
| Criterion | A | B | C |
|---|---|---|---|
| No JIT on iPadOS | good (AOT) | good | – |
| Engine effort | low | very high | – |
| Game logic effort | high | high | – |
| Shaders | about 64 new, reference available | SPIR-V→MSL | – |
| Save compatibility | good (format documented) | good | validator available |
| Legal status | sensitive if distributed | sensitive if distributed | unproblematic |

## Legal Note
Reconstructed code from decompilation may raise copyright issues if distributed. This applies equally to A and B. Our principle remains: assets only from the user's own dump; no game files, keys, or extracted content in the repository. Separating specification from implementation may reduce risk. This is not legal advice.

## Open Questions for the User
1. Is the goal a fully playable game or first a vertical slice with save import?
2. How will distribution work (private only or public)?
3. Should the vertical slice (Option D) use a newer Unity LTS, and what are the licensing/Unity account arrangements?
4. How much manual reconstruction of game logic is acceptable, and where should it begin (save-related classes, battle, field)?
5. Wwise: custom playback from converted WEMs or Wwise SDK runtime?
6. What is the role of Ryzen and M2 mini (batch analysis only)?

## User Decision (2026-10-18)
- **Direction D:** vertical slice in a newer Unity LTS, then choose A, B, or C.
- **Goal:** fully playable game.
- **Distribution:** public later, code only with no game content. Legal separation matters: no game files, keys, or extracted content in repository; specifications in our own words; implementation separate. This is not legal advice. Clarify legal status before release.
- **Unity version for vertical slice:** 6.3 LTS (6000.3.26f1, native Apple Silicon build), because it is the current LTS. Unity 6.0 LTS (6000.0.85f1) is an alternative.

## Target Platforms and Order (User Requirement, 2026-10-18)
- **End goal:** native ARM Metal app for iOS/iPadOS (no JIT, AOT/IL2CPP).
- **Preliminary step:** macOS port (Apple Silicon), may be simpler as MVP.
- **Cross-platform** (e.g. Windows/Linux) is considered but matters later: do not make architecture choices that preclude macOS/iPadOS specifics; no cross-platform build yet.
- Milestones: M0 vertical slice (Unity 6.3 LTS, macOS), M1 macOS MVP (1080p 16:9, Metal, save import), M2 iPadOS build (memory budget, touch/controller), then cross-platform.
- **Observed:** `/Applications/Xcode.app` exists, but `xcode-select` points to `/Library/Developer/CommandLineTools`; an iPhoneOS SDK is not found there. iOS builds require selecting Xcode's developer environment (e.g. `DEVELOPER_DIR` or `xcode-select -s`, latter requires admin). Unity iOS Build Support module is not installed yet.

## Decision 2 (Autopilot, 2026-10-18 23:55): Recompilation Deferred
Basis: `docs/recomp-machbarkeit.md` (measured spike).
- **Continue with Option D** (Unity 6.3 LTS, reconstruct logic, faithfully port shaders with Maxwell translator).
- **Reasons against R as main path:** C++ exceptions in 2,917 functions break LAS model “host stack = guest stack” (research effort unestimated); Boehm GC thread suspension missing from LAS (8 of 50 SVCs); 32-bit rebasing for iPadOS address space (estimated 3–6 weeks); performance unmeasured; 1.01 GB generated C.
- **Reasons for R:** automatically preserves logic 1:1, very broad CPU coverage (58 of 14.1 million words unsupported), repository can contain no derived code.
- **Kept open:** R as reference implementation for fidelity comparisons (hybrid). Phase 2 spike starts with exception test as gate; only if time remains.
- User delegated the choice to autopilot (“wisest decision”). Reversible.

### Addendum to Decision 2 (2026-10-19): Phase 2 Spike Results, Decision Left to User
Basis: `docs/recomp-spike-2.md` (measured). The three main objections to R changed: **C++ exceptions** are solvable in LAS model (SDK's real unwinder works when recompiled; 100 of 100 reached real BDSP functions choose the correct landing pad; 1–2 weeks production work); **Boehm GC thread suspension** is solvable (Mach API, 2–4 days); **32-bit memory model** works as a header switch (1.5–3 weeks instead of 3–6). All four modules generated and compiled (270,299 functions, 15.6 min, 224 MiB library); SDK initializes when recompiled through first service request. Open: performance, iPad memory, Unity startup in guest, service layer. Spike recommends **hybrid** (R as a parallel main candidate, decide after 4–6 weeks on Mac; D continues without new large reconstruction blocks). This does not replace decision 2; decision remains with user.

## Decision 3 (Autopilot, 2026-10-19 15:30): Recompilation Becomes Main Path, Unity Rebuild Remains Comparison
Basis: `docs/recomp-gate2.md`, `docs/recomp-diff.md`, `docs/recomp-spike-2.md` (measured), and run at 2026-10-19 15:25.
- **Evidence:** recompiled BDSP code runs on Mac through rtld, opening video, title, and save to 3D city (Metal, 45 fps, RSS about 1.0–1.5 GiB, stable for 135 s); under Linux/Vulkan (RTX 2080 Ti), same code renders language selection. Logic, UI, events, battles, save format, and engine behavior are thus original 1:1.
- **Reasons:** exceptions, GC suspension, and 32-bit rebasing are measured as solvable; C mode is bit-exact (0 mismatches, `docs/recomp-diff.md`); shaders run through our Maxwell translator (0 errors across 5,959 programs). Estimated effort R 18–35 weeks vs D 40–80 weeks (±50%); R has advanced significantly since.
- **Main path:** (R) recompilation → macOS app (arm64, Metal), then iPadOS (rebase32, memory window ≤ 4 GiB), Linux/Windows (Vulkan, x86 C mode) as additions. Repository contains only recompiler, runtime, scripts, docs; generated code is produced during build from the user's dump.
- **Unity rebuild (D):** continues as reference and fallback (oracle, specs, data/save tools, image checks); no new large blocks.
- **Open/risks:** iPadOS (Metal buffers 5-GiB window, rebase32 on device unmeasured, generated-code build time in Xcode), touch/controller input, audio currently silent (being explored, Todo `rc-audio`), online services are stubs, clarify legal status before public distribution.
- User delegated strategy to autopilot; reversible.

## Decision 4 (User, 2026-10-19 16:57): Unity Rebuild Is Deprecated
- **User's words:** “so completely deprecate the Unity rebuild! don't waste any more work on it!”
- **Effect:** Unity rebuild (`unity/`, stubs, UI windows, field/battle/event recreation, Unity shader wrappers) will **no longer be developed**. Removed from `main`, retained on branch `unity` (origin). No new tasks or fixes there, except when a tool is directly needed for recompilation. Code remains in repository as reference (oracle fixtures, specs `docs/kampf-spezifikation-*.md`, `docs/pokepara-spezifikation.md`, `docs/evscript-spezifikation.md`), but is no longer built or tested.
- **Main path and sole development track:** recompilation (`scripts/recomp/`, macOS `BDSP.app`, iPadOS `dev.local.xnubdsp`, Linux/Vulkan). Build with `scripts/build_all.sh`, stage `recomp`.
- **Shared tools still used:** extraction (`tools`, `extract`, `il2cpp`), Maxwell→MSL/GLSL translator (`shader_translator/`), video conversion, ASTC transcode, save tools (`scripts/bdsp_save.py`, `ryujinx_sync_save.sh`, `ios_push_save.sh`), image checks (`visual_*`, Ryujinx references), Ryzen farm (`scripts/recomp/linux/`).
- **Retired (do not delete):** build stage `shaders` (Unity wrappers), Unity portions of `assets`, `stubs`, `unity-build`, `scripts/unity_safe.sh`, `shader_wrap*.py`, `stub_gen.py`, `material_*.py`, and Unity `ap-*` todos. Details: `unity/DEPRECATED.md`.
- Reversible only by the user.
