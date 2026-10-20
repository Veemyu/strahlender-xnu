# Extraction and Tools (Status: Paused Before REA Analysis)

## Tools (Local, Not in Repository)
- `tools/hactool` (SciresM/hactool, `make`): LibHac/hactoolnet is no longer reachable on GitHub.
- `tools/nx2elf` (shuffle2/nx2elf, CMake): NSO to ELF conversion for Ghidra.
- Ghidra 12.1.4 (`brew install ghidra`, Formula, not Cask), REA 6.7.0 (`npm i -g rea-agents`).
- REA-MCP is registered for Copilot CLI (`rea setup --client copilot_cli`), backup at `~/.copilot/mcp-config.json.rea.backup`.
  Ghidra path: `GHIDRA_INSTALL_DIR=/opt/homebrew/opt/ghidra/libexec`.

## Extraction
- Base game: XCI, secure partition, Program NCA with standard crypto (Master Key Rev 0xA).
- Update: title `0100000011d90800`, Titlekey crypto, Master Key Rev 0xC, Common Ticket.
- Update was applied to the base RomFS using `--basenca`.

```
work/base, work/update   decryptable NCAs (local, can be deleted as needed)
work/exefs               main, rtld, sdk, subsdk0, main.npdm
work/romfs               Data/ (Unity), Data/Managed/Metadata/global-metadata.dat
work/elf/main.elf        converted with nx2elf (6630 .dynsym entries)
```

Note: hactool warns with key values when key names are unknown. Always filter output with `2>/dev/null`.

## Next Steps
1. REA/Ghidra: open `work/elf/main.elf` (auto-analysis takes a long time; watch memory usage).
2. Build Il2CppDumper and analyze `global-metadata.dat` plus ELF; import `script.json` into Ghidra.
3. Assets (AssetRipper) and save format.

## IL2CPP Dump (Complete)
- `tools/Il2CppDumper` (Perfare, `dotnet build -f net8.0 -o ../il2cppdumper-bin`), launch with `DOTNET_ROLL_FORWARD=Major dotnet ... <NSO main> <global-metadata.dat> <outdir>`. NSO `work/exefs/main` is read directly. The “press a key” prompt at the end causes a harmless exception.
- Metadata v24.4 (detected as 24.5), CodeRegistration `0x4aeb238`, MetadataRegistration `0x4aebed8`.
- Output in `work/il2cpp/`: `dump.cs` (~11,800 namespaces, ~6,200 classes), `DummyDll/` (including Assembly-CSharp), `il2cpp.h`, `script.json`, `stringliteral.json`. Classes include `SaveData`, `PlayerWork`.

## Ghidra
- Importing `main.elf` with a 2G heap failed (OutOfMemoryError). Now 8G, analyzer “GCC Exception Handlers” off, timeout 60 min (`~/.copilot/mcp-config.json`).
- Future Ghidra/REA runs will use a background subagent.

## Ghidra Import (Complete, via REA Subagent)
- `work/elf/main.elf`: image base `0x100000`, 30 segments, 55,357 procedures, 31,224 strings. Unity IL2CPP (Mar 1 2022), Editor 2019.4.27f1, Assembly-CSharp 1.6.28.12450.
- Evidence bundle: `work/rea/main.elf.evidence.json`.
- **Addresses:** Il2CppDumper addresses are relative to 0; in Ghidra add `+0x100000`.
- Bulk renaming over MCP is impractical (~100,000 methods). Instead, `scripts/il2cpp_lookup.py '<regex>'` returns Ghidra addresses, then REA renames selected methods.

## nx2elf Patch (Section Header)
- nx2elf sets `.text` to end at `.plt` (0x1732f98). IL2CPP game code lies after that but still in the `R E` segment (through 0x2cf6a30). Ghidra created a non-executable block there, so functions were missing (e.g. `PlayerWork$$SaveAsync`).
- Workaround: copy to `work/elf/main.patched.elf`, changing only `.plt` `sh_size` to `0x15c3a98` (4 bytes different from `main.elf`). Original is preserved.

## Ghidra with Patched ELF (Complete)
- `work/elf/main.patched.elf`: 96,450 procedures (previously 55,357), 31,280 strings. Evidence: `work/rea/main.patched.evidence.json`.
- Confirmed: Il2CppDumper address + 0x100000 gives function starts (`PlayerWork$$SaveAsync` 0x2ded680, `AutoSave` 0x2df60f0, `LoadBytes<SaveData>` 0x1b8bf60). `LoadBytes` copies a 0x7b8-byte struct (save data).
- Gap: `PlayerWork$$LoadAsync` (0x2ded780) has no function because Ghidra does not create functions without incoming references. IL2CPP methods are invoked through function-pointer tables. A script would need to create functions at every address in `script.json`.
- REA session annotations (names) exist only in the session and evidence bundle, not persistently.

## Ghidra Project and Pseudocode Export (Complete)
- Persistent project `work/ghidra/bdsp` (import `main.patched.elf`, without auto-analysis; `scripts/ghidra/SeedIl2Cpp.java` creates functions from `script.json`, then analysis).
  Result: 166,095 functions, seeding 43 s (100,685 created), analysis 1,692 s, 0 errors. 8G heap via `GHIDRA_HEADLESS_MAXMEM`.
- `scripts/ghidra/ExportDecompiled.java`: 394 functions in 15 classes exported to `work/decomp/<Class>.c` (PlayerWork, Dpr.NX.SaveSystem, SaveData types). Largest file `PlayerWork.c` (250 KB).
- Key functions: `PlayerWork$$SaveAsync` calls `PlayerWork$$DataSave`; `LoadAsync` calls `PlayerPrefsProvider<PlayerWork>.Load`; `LoadBytes<PlayerWork.SaveData>` copies the 0x7b8-byte struct. `VerifySaveData` (0x2deba00) is the next lead for checksum/validation.
- There is no `SaveManager`.

## AssetRipper Export (Complete)
- `scripts/assetripper_export.py --input work/ripper/in` (symlinks only to `exefs` and `romfs`), output `work/ripper/out/ExportedProject/Assets`.

## Unity Editor
- `brew install --cask unity-hub`; install Editor through Hub CLI: `Unity Hub -- --headless install --version 2019.4.27f1 --changeset 23dc10685eb4 --architecture x86_64` (Intel, Rosetta). At Hub GUI startup a login window appears; CLI download does not need it. License activation is required only when opening the Editor.
