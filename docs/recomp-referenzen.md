# Reference: Static recompilation projects (as of 2026-10-18)

Summary of our own read-only research (nothing cloned, no code reused). Sources: `peiikai/LASRecomp` (MIT, Link's Awakening Switch) and `raulzrrs/letsgo-recomp` (based on LASRecomp).

## Findings

- Both projects translate the complete NSO code (`main`, `sdk`) to C through a scripted pipeline, replace Switch OS services (SVC, IPC) and NVN with a custom runtime, and translate Maxwell shaders to MSL (Metal) at runtime.
- Their target is macOS arm64 (Metal, with a guest-memory window allocated through `mach_vm_allocate`). iOS/iPadOS and freedom from JIT requirements are not addressed.
- The target games (Link's Awakening and Let's Go) are **not Unity/IL2CPP games** (LAS uses Grezzo's own engine according to a secondary source; this was not independently verified). Their metadata, `libil2cpp`, and IL2CPP function-pointer tables were not examined.
- Game code is generated and compiled on the user's machine (`dlopen`); this is not possible on iPadOS (no compiler) and would distribute Nintendo code.
- LASRecomp is a beta (release `beta_4`), MIT-licensed with game files excluded. Its README describes the code as “almost exclusively” AI-generated. The repository contains no game files.

## Assessment for BDSP

- Useful as a checklist for Switch services and graphics imports, not as an execution path.
- BDSP has 166,095 functions (about 1.3× as many as Let's Go). The estimate of 0.7–1 GB of generated C is an extrapolation.
- The IL2CPP code comes from C#. Therefore **Option A** (a new Unity project with reconstructed logic) remains clearly preferable to NSO recompilation. The architecture gate will make the decision.
