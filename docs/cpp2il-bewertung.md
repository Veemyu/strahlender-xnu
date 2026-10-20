# Cpp2IL Assessment (BDSP Dump, ARM64 NSO)

Status: 2026-10-18. Question: can Cpp2IL reconstruct readable C# method bodies from `work/exefs/main` + `global-metadata.dat` to replace or supplement our Ghidra pseudocode?

**Short answer:** Not as a replacement. Cpp2IL produces a body *formally* for every method, but most are useless for save logic (static fields, field accesses, and many calls are missing). As a **supplement**, the ISIL dump is useful (resolved method names, parameters, field names).

## Inputs and Setup

| Item | Value |
|---|---|
| Binary | `work/exefs/main` (NSO, unchanged) |
| Metadata | `work/romfs/Data/Managed/Metadata/global-metadata.dat`, detected by Cpp2IL as v24.5 |
| Unity | 2019.4.27 (`--force-unity-version 2019.4.27`) |
| Invocation | `--force-binary-path`, `--force-metadata-path`, `--force-unity-version`, `--output-as <Format>` |
| Output | `work/cpp2il/{il_recovery,diffable-cs,isil}`, logs `work/cpp2il/run-*.log` |

## Installation: Pitfalls

1. macOS terminates prerelease asset `Cpp2IL-2022.1.0-pre-release.21-OSX-ARM64` (under `tools/Cpp2IL/`) with `Killed: 9` because the binary is unsigned (quarantine attribute was absent; only `com.apple.provenance` was set). `codesign --force --sign -` on that exact file fixes it; `--help` then runs.
2. **This release fails on our NSO.** Exception: `NSO: Address 0x2CF6A30 is not present in any of the segments`: the last method at end of `.text` (0x2CF6A00) is disassembled up to and beyond the segment boundary. This is a Cpp2IL bug, not our data (prerelease 21 is newest release; boundary fix is only on `master`).
3. Workaround: cloned `master` (b5ad444) and built with `dotnet build -c Release -f net10.0` into `tools/Cpp2IL/build/` (.NET 10 SDK is available). Same case then failed again in the “unmanaged function” path (reads past segment without checking until first `B`). **Local one-line patch** to `NewArm64Utils.cs` (stop at segment boundary), only under `tools/Cpp2IL/src`. Did not try 2022.0.7 stable because it is older. Important for future use: it does not run without a custom build.
4. For viewing `dll_il_recovery` DLLs, installed `ilspycmd` 11.1 locally under `tools/ilspy/` (`dotnet tool install --tool-path`).

## Measurements

| Format | Runtime | Peak RSS | Output size |
|---|---:|---:|---:|
| `dll_il_recovery` | 24 s | 2.4 GB | 38 MB (DLLs) |
| `diffable-cs` | 11 s | 2.3 GB | 32 MB |
| `isil` | 36 s | 2.4 GB | 334 MB |
| ILSpy decompilation of Assembly-CSharp.dll (helper step) | 31 s | 2.4 GB | 106 MB, 3,764 `.cs` files |

6-GB limit was never reached; free space on data volume after runs: 76 GB.

Method counts:
- Metadata: 11,812 types; Cpp2IL assigned 71,155 code pointers to method definitions (Assembly-CSharp: 48,084 pointers).
- `dll_il_recovery` reports “100% decompiled (48,645 / 48,645).” This means only that a body was generated, not that it is correct. 6 methods were skipped as too large (static constructors for text lists/tables, e.g. `Pml.DebugViewTable::.cctor`, 540 KB).
- `diffable-cs` contains **no** method bodies, only signatures with `{ }` and length comment (`PlayerWork.cs`: 1,818 lines, every method empty). Not a Ghidra replacement; useful only as a type/field overview with offsets.
- Analysis of Assembly-CSharp ILSpy decompilation (script heuristic `work/cpp2il/stats.py`, counts 35,888 regular methods; property accessors and special forms omitted):

| Category | Count | Share |
|---|---:|---:|
| Methods counted | 35,888 | 100% |
| Empty body | 1,563 | 4.4% |
| Body without placeholders (“clean”) | 9,998 | 27.9% |
| Body with placeholders + real code | 23,519 | 65.5% |
| Body made only of placeholders | 808 | 2.3% |

  Overall 330,241 `NoteDecompilerIssue` lines in 1.86 million code lines (about 18%). ILSpy also failed on 2 constructors (`INL1.PacketWriter/Reader`). “Clean” bodies are mostly small getters/setters and delegate stubs.

## Quality of Save Methods (PlayerWork)

All four bodies are non-empty. Line counts exclude comments.

| Method | Cpp2IL (`il_recovery`) | Placeholder lines | Real calls | Ghidra (`PlayerWork.c`) |
|---|---:|---:|---:|---|
| `SaveAsync` | 16 | 4 | 0 (only `DataSave`) | 18 lines, fully readable |
| `LoadAsync` | 39 | 10 | 0 | 27 lines |
| `DataSave` | 244 | 60 | 3 | 144 lines |
| `VerifySaveData` | 927 | 115 | 4 | 167 lines |

Assessment in our own words:
- **`SaveAsync`:** Cpp2IL correctly recognizes call `DataSave(isAsync: true, writeMain, writeBackup)` including parameter names from metadata. The rest is IL2CPP class initialization and static check (flag bit 1 and field at +0xE0), represented as “Unmanaged memory load” with constant 0. Ghidra shows same structure more concisely, including actual offsets and parameter link (`& 1`).
- **`LoadAsync`:** body consists of initialization check, a tangle of `goto` labels, and two “Method not found” calls (addresses 0x2324910 / 0x2324AE0). Main logic (read save through `PlayerPrefsProvider<PlayerWork>`, flag `fromBackup`) is completely missing. Ghidra shows call `…PlayerWork___Load` and setting backup flag at field offset 0x829. Ghidra is clearly better here.
- **`DataSave`:** named calls found: `FieldWalkingManager.UpdatePartnerPokeIndex`, `PlayReportManager.SaveRecordDataEvent`, `SystemTimeWork.GetSaveTime`. Static fields (`PlayerWork` singleton, instance fields) and field assignments (e.g. `writeMain`/`writeBackup` flags at 0x828/0x829 of `PlayerPrefsProvider` singleton) are **not** reconstructed; method reads like a sequence of zeros. Ghidra provides more useful structure.
- **`VerifySaveData`:** 927 lines with 100 “Unmanaged memory load” and only 4 named calls; checksum/length logic is not understandable. Also IL comments “Expected Obj, but got I4”: type conflicts in generated IL.
- Positive: ISIL renders `CustomSaveAsyncOperation` as `SaveSystem.SaveAsync(this._writeSrcBuffer, …Flags)` with field names; IL recovery only partially does so (recognizes `makeSaveDataHash(ref buf)`, not calls to special addresses).

## Typical Failure Patterns

1. `Unmanaged memory load: [address]` replaces every singleton or static-field read; value is treated as 0, so subsequent accesses (`->0x12F`, `->0xE0`) look constant.
2. `Method not found @address`: calls to helper functions not mapped to metadata methods (e.g. IL2CPP runtime functions such as `il2cpp_codegen_initialize_method`, internal helpers, type initialization, marshalling).
3. `Indirect call` (virtual/interface dispatch via class vtable) is not resolved.
4. Loops full of `goto` and helper variables typed as `object` instead of actual types.
5. Generic instantiations are only roughly resolved; `PlayerPrefsProvider<PlayerWork>` does not appear with type arguments.

## Limits of This Assessment

- Statistics are a text heuristic over ILSpy output, not an exact metadata count; they cover about 74% of 48,645 methods (the remainder includes property accessors, operators, special forms).
- Built `master` (b5ad444) with local patch, not a release; behavior may differ from `2022.1.0-pre-release.21`.
- ISIL format was inspected only by sample (`PlayerWork`).
- Game-code output is only under gitignored `work/cpp2il/` and is not copied into this document.

## Recommendation

- **Ghidra pseudocode remains the primary source for reconstructing C# logic.** As of this measurement, Cpp2IL `dll_il_recovery` is not a replacement; it is badly fragmented, especially where logic uses static fields/singletons and field accesses—that is, throughout the save chain.
- **Useful as a supplement:**
  - `diffable-cs` for types, field offsets, and method signatures with parameter names (complements existing Il2CppDumper `dump.cs`).
  - `isil` for cross-reading: resolves direct calls and instance fields (`this._isMainSave`) to names that appear in Ghidra as `param_1 + 0x…`.
- **Workflow if used:**
  1. Run `tools/Cpp2IL/build/Cpp2IL` (custom-built, patched) with `--output-as isil` and `diffable-cs` (about 50 s, about 2.4 GB).
  2. Read each target method's ISIL block alongside Ghidra function; use offsets from Ghidra and names from ISIL.
  3. Put result into our spec (`docs/save-spec-entwurf.md`) and test vectors; validate against real saves with save validator.
  4. Update Cpp2IL version/patch when a release supports NSO segment boundaries.
