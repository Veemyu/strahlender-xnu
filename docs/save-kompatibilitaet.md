# Save Compatibility: Write Path, Import/Export, and Storage

Todos `ap-save-write` and `ap-save-compat`. Labels follow `docs/save-spec-entwurf.md`: **[verified]** = demonstrated on the local save, in disassembly/pseudocode, or by a running test; **[inferred]** = conclusion from structure/naming; **[not checked]** = taken from public descriptions or recollection, not checked locally; **[open]** = unresolved. The real save was only read; figures are used instead of contents.

## 1. Overview (C#, assembly `Xnu.Save`, directory `unity/Assets/Scripts/Save`)

| File | Contents |
|---|---|
| `SaveData.cs` | `SaveData`: loads/copies an image (version 0x34 only), edits regions, `ToBytes()`/`Seal()` recompute the MD5. Player basics, money, items |
| `SavePlayerLayout.cs` | Offsets in `PLAYER_DATA`, `rivalName`, `SaveItem` |
| `SaveFileIO.cs` | Read with size limit, backup before overwrite, atomic write with read-back verification |
| `SaveInspector.cs` | Detect/validate directories, individual files, and ZIPs; Ryujinx/yuzu/JKSV/Checkpoint/app conventions; bounded search |
| `RyujinxSaveIndex.cs` | Read `imkvdb.arc` → a title's save-ID directory |
| `SaveExporter.cs` | Export to Ryujinx (`0` and `1`), generic directories, path construction for JKSV/Checkpoint |
| `SaveStore.cs` | App-managed storage (slots, backups) |
| `../PokePara/SaveDataPokemon.cs` | `SaveData` extensions: party and boxes through `Xnu.PokePara` (`SetParty`, `SetBox`, `GetBox`, `VerifySlots`) |

`Xnu.Save` does not depend on `Xnu.PokePara` (PokePara depends on Save); Pokémon access is therefore implemented as extension methods in `Xnu.PokePara`.
Both assemblies are independent of UnityEngine and compile against `netstandard2.1` (Unity: `apiCompatibilityLevel 6`; built in a throwaway netstandard2.1 project, 0 warnings/errors).

## 2. Editable regions and source of offsets

All offsets in `PLAYER_DATA` come from the Marshal routine `0x2e9050` (managed → native; `bool` = 4 bytes, `string` = fixed UTF-16 field), disassembled with `work/dotnet-savewrite/disasm_marshal.py` (Capstone, ELF file `work/elf/main.patched.elf`; Ghidra address − 0x100000 = virtual address).
The helper script exists only in the untracked `work/` directory.

| Field | File offset | Size | Evidence |
|---|---|---|---|
| Player name (`MYSTATUS.name`) | 0x79B74 + 0x40 = 0x79BB4 | 13 UTF-16 characters (26 bytes), NUL-terminated, at most 12 visible | Disassembly: string copied into native field with length 0xD; save contains 5 characters, NUL, then old residue **[verified]**; limit of 12 follows from 13 characters including NUL **[inferred]** |
| Trainer ID (`id`) | +0x5C | u32 | Disassembly **[verified]** |
| Money (`gold`) | +0x60 | i32 | Disassembly **[verified]**; `PlayerWork.SetMoney` (0x2defc80) writes managed value at `PlayerWork+0xEC` = `_saveData`(0x18) + `playerData`(0x90) + `mystatus`(0x38) + `gold`(0xC) **[verified, calculated]**; `MoneyWork.Set` (0x207d350) clamps to 0..999999 (`MAX_MOENY`) **[verified]** |
| Gender (`sex`, bool) | +0x64 | 4 bytes (0/1) | Disassembly; mapping of 0/1 to gender is not established, so exposed as `SexRaw` **[open]** |
| Badges (`badge`) | +0x69 | byte | Raw value `BadgeRaw`; whether it is a count or mask is unverified **[open]** |
| Play time | +0x90 / +0x92 / +0x93 | u16 hours, byte minutes, byte seconds | Disassembly **[verified]**; plausible values in save (two-digit hours, minutes/seconds < 60) **[verified]** |
| Rival (`rivalName`) | 0x55F4 | 32 UTF-16 characters (64 bytes) | Top-level field; “Lutz” found as UTF-16 in save **[verified]**; game's limit unknown, `SaveData` permits at most 12 characters **[decision]** |
| Items (`saveItem[3000]`) | 0x563C + 16·Index | 16 bytes per entry | Entry layout from `0x2af6d0`: Count u32 @0, VanishNew (4) @4, Favorite @8, ShowWazaName @9, Dummy @10/11, SortNumber u16 @12 **[verified]**; maximum count 999 (`ItemMaxCount`) **[verified]** |
| Item index = item number | | | Save has 171 entries with count > 0, highest index 644, all counts ≤ 999, and low indices match known item IDs; proof via `ItemWork` is missing **[inferred]** |
| Party | 0x14098 | 6 × 344 bytes + count + marker | `docs/pokepara-spezifikation.md` **[verified]** |
| Boxes | 0x14EF4 | 40 × 30 × 344 bytes | Same source **[verified]**; `TrayMax()` reads how many boxes are unlocked; writes do not check this |

`SaveData` edits only the named bytes; tests compare the file byte-for-byte before and after, allowing changes only in the target region plus hash field.
When setting a name, it is NUL-terminated and the rest of the 13-character field is zeroed (old residue in the original is **not** retained; the two padding bytes after it are left untouched).
Other top-level fields (flags, Pokédex, records, clothing, etc.) are not editable except as raw bytes through `Buffer`.

## 3. Round trip against the real save

Test `SaveWriteTests.RealSaveRoundTripIsByteIdentical` (both `SaveData.bin` and `Backup.bin`, read-only, processing in memory): `SaveData.FromBytes` → `ToBytes()` produces **byte-identical** files (length 979108, same SHA-256 on both sides, valid save hash) **[verified]**. Further runs against the real save, in memory or in a throwaway directory:

- Rewrote all 1206 slots (6 party + 1200 boxes) using `SaveData.SetPartyMember/SetBox` → file remained byte-identical; all 1206/1206 checksums valid **[verified]**.
- Changed money, item count, play hours, and the first party member's item → only those bytes and the hash differ; after `WriteAtomic` and reloading, values match; restoring the four values reproduces the original file **[verified]**.
- Name changes stay within the name field **[verified]**.
- The original files and timestamps remained unchanged (SHA-256 prefixes for `SaveData.bin`/`Backup.bin` matched before and after all runs).

Not demonstrated: that the **game** (or Ryujinx/Switch) loads a modified save. This requires running the game **[open]**; only our validator accepting the save (MD5, size, version) and valid slot checksums are established. Pokémon legality is not checked.

## 4. Directory and container conventions

### Ryujinx **[verified]** (local data directory)
- Save index `bis/system/save/8000000000000000/0/imkvdb.arc`: `"IMKV"`, u32, u32 count (12); entries are 0x8C bytes each: `"IMEN"`, u32 key size (0x40), u32 value size (0x40), key = `SaveDataAttribute` (program ID u64 @0, user ID 16 bytes @8 **[inferred, Horizon layout]**, type u8 @0x20), value starts with save ID (u64 LE). For `0100000011D90000`, it has two type-1 entries (save IDs 6 and 7) and one type-2 entry (12) **[verified]**.
  `RyujinxSaveIndex.FindSaveDirectories` derives `bis/user/save/<SaveId 16 Hex>`; a test on the local directory finds `…0006`.
- The save is in `bis/user/save/<SaveId>/0/` (`SaveData.bin`, `Backup.bin`), alongside `1/`, `ExtraData0`, `ExtraData1`. Locally, `0/` and `1/` contain identical `SaveData.bin` files (same SHA-256); `Backup.bin` matches between directories but is **not** identical to `SaveData.bin` (an older, also valid save) **[verified]**.
- Export: `SaveExporter.ExportToRyujinx` writes `SaveData.bin` to `0/` and, if present, `1/`; `Backup.bin` only when requested (`WriteBackupFile`). That Ryujinx treats `0` as the authoritative (committed) copy and refreshes `1` from it when mounting is **[inferred]**; both are therefore written.
  Ryujinx must be closed while writing (the code cannot detect this) **[not checked]**. `ExtraData0/1` are untouched; they depend on size/type, not contents **[inferred]**.
- Emulator data directory (defaults: macOS `~/Library/Application Support/Ryujinx`, Linux `~/.config/Ryujinx`, Windows `%AppData%\Ryujinx`; in portable mode, a `portable` directory) **[not checked]**; local directory is under the repository root (`Ryujinx/`, ignored).

### yuzu and forks **[not checked]**
- `<DataDirectory>/nand/user/save/0000000000000000/<UserId 32 Hex>/<TitleId 16 Hex>/` with `SaveData.bin`, `Backup.bin` directly inside. This layout is based on memory/public descriptions; yuzu is not installed locally.
  `SaveInspector` recognizes it, and `ExportToDirectory` writes into an existing title directory.

### Switch tools (JKSV, Checkpoint) **[not checked; public descriptions]**
- JKSV: `<SD>/JKSV/<GameName>/<BackupName>/` with save files; JKSV can also create ZIPs. Checkpoint: `<SD>/switch/Checkpoint/saves/0x<TitleID> <GameName>/<BackupName>/`.
- According to descriptions, a backup contains the mounted save contents, for BD/SP `SaveData.bin` (+ `Backup.bin`); whether additional metadata files are included is unchecked. `SaveInspector` recognizes directories by both path **and** files (`Jksv`, `Checkpoint`), ZIPs by entry name (shortest path), and never reads more than `MaxFileSize` (1 MiB) per file/entry (ZIP-bomb protection). `SwitchBackupFolder` constructs new backup paths according to these conventions (path construction only; names are sanitized for FAT).
- Whether JKSV/Checkpoint can restore a generated directory on real hardware, and whether the save is tied to a console/user account, has not been tested **[open]**. `SaveData.bin` itself has no account or console association besides the hash **[verified for the file, not the Switch filesystem]**.

### Title IDs
- Brilliant Diamond `0100000011D90000` **[verified]** (local index and directory; `scripts/tests`). Shining Pearl `010018E011D92000` **[not checked]**; whether SP uses the same format has not been investigated **[open]**.

### App-managed storage
```
<Root>/Saves/<Slot>/SaveData.bin (+ Backup.bin)
<Root>/Backups/<Slot>/<UTC-Timestamp>/<File>        before each overwrite
```
- `Root` = `Application.persistentDataPath` in the Unity player (`Xnu.Save` receives the path from its caller): macOS Application Support (`~/Library/Application Support/<Company>/<Product>`), iPadOS `…/Documents` in the app container **[not checked; Unity documentation]**.
  To make saves visible in the iPad Files app, the app needs `UIFileSharingEnabled` and `LSSupportsOpeningDocumentsInPlace` in Info.plist **[not checked; Apple documentation, not yet set in the build pipeline, open]**.
- Slot names: `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and no `..` (prevents path traversal); other names are rejected.

## 5. Detect, validate, write

- **Detection** (`SaveInspector.Inspect(path)`): directory, save-ID directory (→ `0`), individual file, or `.zip`; returns kind, title ID/user ID/save ID (when available in path), per-file size/version/validation (`Validate`: version, size, MD5), and notes; does not throw for invalid files.
  `Find(root, maxDepth, maxResults, maxDirectories)` searches within bounds under the specified root (does not scan the disk).
- **Selection** (`ReadBest`): `SaveData.bin`, otherwise `Backup.bin`—valid files only; `preferBackup` reverses the order. This follows the main/backup file order in the spec (the mapping there is only [inferred]).
- **Writing** (`SaveFileIO.WriteAtomic`): (1) validate data (invalid → `SaveFormatException`, destination unchanged; `AllowInvalid` only when explicitly requested), (2) if destination exists, `BackupDirectory` is required and the destination is copied to `<Backups>/<Timestamp>/<Name>` and verified,
  (3) create a temp file in the same directory (`CreateNew`, `Flush(true)`), (4) `File.Replace` (fallback to delete+move on `PlatformNotSupportedException`), (5) read back and compare; on mismatch restore from backup, (6) always remove temp file.
  Missing destination directories are created only with `CreateDirectory` (never emulator directories).
- Limitations: `File.Replace` is a `rename` on Unix (atomic); untested on iOS/Mono; directory `fsync` is not performed **[open]**. Concurrent processes (emulator running) are not detected.
- Only version 0x34 is editable. `SaveData` does not load older saves (0x25–0x33); migration (`TakeOverOldVersion` in the game) is not implemented **[open]**.

## 6. Tests

Developed in throwaway project `work/dotnet-savewrite` (`dotnet test`, temp directory via `TMPDIR` in project directory): **56 tests passing** (35 new + 21 existing `SaveValidatorTests`); 6 exercise the local save (`Real*`, skipped via `Assert.Ignore` if the file is absent—the dotnet run did execute this path because the local save was present).
Also compiled `Save`, `PokePara`, `Battle`, `Data` against `netstandard2.1` without errors. Running `Xnu.Tests.EditMode` in the Unity Editor remains pending.

| File | Contents |
|---|---|
| `unity/Assets/Tests/EditMode/SaveWriteTests.cs` | Edits (name, ID, money, time, items, party, boxes), range checks, round trip, 6 real-save tests |
| `unity/Assets/Tests/EditMode/SaveStorageTests.cs` | Detect all conventions, ZIP, size limit, search, Ryujinx index, backup/atomic write, export, app storage, slot names, 1 test on real directory |
| `unity/Assets/Tests/EditMode/SaveTestSupport.cs` | Synthetic saves (deterministic noise + empty encoded slots), diff helpers, local-save lookup (`XNU_REAL_SAVE` or search upward for `Ryujinx/bis/user/save/0000000000000006/0/`) |

`Xnu.Tests.EditMode.asmdef` required no changes (references to `Xnu.Save`, `Xnu.PokePara` already existed).

## 7. Open items
- Run tests in the Unity Editor; compile the new files in Unity (only checked against netstandard2.1 so far).
- Acceptance of modified saves by the real game, Ryujinx, and Switch hardware; Ryujinx behavior with copy `1/`.
- Check actual yuzu, JKSV, and Checkpoint layouts against installations.
- Meaning of `sex` (0/1), `badge`, `region_code`, `rom_code`, item-index mapping via `ItemWork`; whether `MoneyWork` limits are clamped again on load.
- Remove the “0x34 only” restriction (migration of older saves).
- iPadOS: Info.plist keys for file access, behavior of `File.Replace` under Mono/iOS.
- Shining Pearl: same structure? (title ID only from public sources).
