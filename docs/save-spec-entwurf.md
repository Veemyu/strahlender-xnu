# Save Specification (Draft) – Brilliant Diamond, SaveData.bin

Source: independent static analysis of `work/elf/main.patched.elf` (Ghidra project `work/ghidra/bdsp`) and
`work/il2cpp/dump.cs` / `global-metadata.dat`. Addresses are Ghidra addresses (RVA + 0x100000).
Labels: **[verified]** = directly visible in pseudocode/disassembly or metadata,
**[inferred]** = conclusion from structure/naming, **[open]** = unresolved.
Pseudocode exports: `work/decomp/` (PlayerWork.c, Dpr_NX_SaveSystem.c, …) and `work/decomp/save-spec/`.

## 1. Overview

- The save is **not** a serialization format (no MessagePack/JSON/BinaryFormatter); it is the
  **Marshal image** (`Marshal.SizeOf` / StructureToPtr) of the managed structure `PlayerWork.SaveData`. The file
  has fixed offsets, no compression, and no encryption of the file as a whole. [verified: `PlayerWork$$ToBytes<PlayerWork.SaveData>` 0x1b8c2f0 calls SizeOf, AllocHGlobal, a StructureToPtr-like call, and `Marshal.Copy`; file contents are written unchanged, see section 2.]
  The conclusion that the second call is exactly `StructureToPtr<T>(T, IntPtr, bool)` follows from its signature (struct, pointer, `1`). [inferred]
- Pokémon slots are additionally encoded individually with the known LCG-XOR method (factor `0x41C64E6D`, increment `0x6073`, 16-bit checksum). [verified: `Pml.PokePara.Encoder$$Encode` 0x21524d0, `$$CalcChecksum` 0x2152460, `$$CalcNextRandCode` 0x2152500]
- Version is an `int` at the start of the file; current value `0x34` (`PlayerWork.SaveData.CURRENT_VERSION = 52`,
  `LAUNCH_VERSION = 37 (0x25)`). [verified: dump.cs; `PlayerWork$$Initialization` 0x2deb000 sets 0x34; OnPreSave 0x2decd90 raises lower versions to 0x34]

## 2. Save flow

1. `PlayerWork$$SaveAsync(a,b)` 0x2ded680 → `PlayerWork$$DataSave(1,a,b)` 0x2ded1d0. [verified]
2. `DataSave` sets `_isMainSave` (+0x828) and `_isBackupSave` (+0x829), calls, among others, `FieldWalkingManager.UpdatePartnerPokeIndex`,
   `PlayReportManager.SaveRecordDataEvent`, `SystemTimeWork.GetSaveTime/SetSaveTime`, `UgFieldManager.SAVE_POKE`, then
   `PlayerPrefsProvider<PlayerWork>$$Save(isAsync)` 0x2424f60. [verified]
3. `Save` calls `OnPreSave` through the vtable (slot 11 = offset 0x1e0), then slot 7 (`CustomSaveOperation`, sync) or slot 9
   (`CustomSaveAsyncOperation`, async). [verified: slot-to-method mapping from dump.cs `PlayerPrefsProvider<T>`; offsets 0x170+0x10·(slot−4)]
4. `PlayerWork$$OnPreSave` 0x2decd90: serializes the party (`Pml.PokeParty$$SerializeFull` 0x2157350, destination `_saveData.playerParty`),
   saves player position (`SetPlayerPosData`), sets `version = max(version, 0x34)`. [verified]
5. `CustomSaveOperation` 0x2debf00 / `CustomSaveAsyncOperation` 0x2dec400: `ToBytes<SaveData>(_saveData)` → `byte[] _writeSrcBuffer`
   (+0x820), then `PlayerWork$$makeSaveDataHash` 0x2debff0. [verified]
6. **Checksum** `makeSaveDataHash`: zero bytes 0xE9818..0xE9827, call `MD5CryptoServiceProvider.ComputeHash(buf, 0, Marshal.SizeOf(SaveData))`
   (= entire file, 0xEF0A4 bytes), copy result (16 bytes) to 0xE9818. [verified]
   The type handle (`PTR_DAT_04cbfcf8`) is the same as in `Dpr.NX.SaveSystem$$_cctor`; that it is `PlayerWork.SaveData` follows from its size 0xEF0A4. [inferred]
7. `Dpr.NX.SaveSystem$$Save(data, writeMain, writeBackup)` 0x1edf3e0 (async: `SaveAsync` 0x1edf680 → thread `StartThread` 0x1edf830 →
   `ThreadLoop` 0x1edfe50): mounts `SaveData` (`MountSaveData` 0x1edf5a0), then for the main file and afterward the backup, calls
   `nn::fs::DeleteFile`, `CreateFile(size = data.Length)`, `OpenFile(Mode 2)`, `WriteFile(0, data, data.Length)`, `CloseFile`; finally
   `FileSystem.Commit`. Data is written to disk 1:1 (no transformation). [verified]
   Paths: `SaveData:/SaveData.bin` and `SaveData:/Backup.bin` (dump.cs constants `SAVEDATA_PATH`, `BACKUP_PATH`). Mapping main file = first
   write/`SaveDataExists`, backup = second/`BackupExists`. [inferred from function names]

## 3. Load flow

1. `PlayerWork$$LoadAsync(fromBackup)` 0x2ded780 sets `_isBackupSave` (+0x829) and calls `PlayerPrefsProvider<PlayerWork>$$Load(false, true)` 0x2424ae0. [verified]
2. Slot 8 `CustomLoadAsyncOperation` 0x2dec1e0 → `SaveSystem$$LoadAsync` 0x1edfba0 (thread). `LoadCore` 0x1edf9b0: zero-fills buffer (`SAVELOAD_BUFFER_SIZE`
   = `Marshal.SizeOf` at class construction, `_cctor` 0x1ee01d0), opens file through `nn::fs`, calls `GetSize`, then `ReadFile` with `min(file size, buffer size)`
   (shorter older saves remain zero-padded at the end). [verified; min() inferred from pseudocode]
3. Callback `PlayerWork$$OnPostLoadAsync` 0x2dec2a0 (sync variant: `CustomLoadOperation` 0x2deb850):
   - file missing → `LoadResult.NOT_EXIST (1)` (checks `SaveDataExists`), read error for existing file → `FAILED (3)`,
   - `VerifySaveData` fails → `CORRUPTED (2)`,
   - otherwise `LoadBytes<PlayerWork.SaveData>` 0x1b8bf60 (PtrToStructure-like, see `ToBytes`) → `_saveData`, `SUCCESS (0)`. [verified; enum from dump.cs]
   - Sync path only: if `version < 0x29`, runs `Array.Clear(buf, 0x9D03C, 0x31304)` before loading (GMS region; dump.cs: `GMS_WORK_ADDR = 643132 = 0x9D03C`,
     `GMS_WORK_SIZE = 201476 = 0x31304`). [verified]
4. **Validation** `PlayerWork$$VerifySaveData` 0x2deba00: `version` = LE `int` at `buf[0]`; `version < 0x25` → considered valid (no checks).
   Otherwise: `N = BINARY_SIZE[version − 0x25]`. Buffer < 0xE9828 → invalid; save 16 bytes at 0xE9818, zero them,
   `MD5.ComputeHash(buf, 0, N)`, compare byte-by-byte, restore hash. [verified]
   Version > 0x34 would exceed the table index (IndexOutOfRange). [inferred]
5. `PlayerWork$$OnPostLoad` 0x2dec500: `version < 0x20` → `Initialization` (vtable slot 5); `version < 0x34` → `TakeOverOldVersion` 0x2dec6e0
   (version-specific migration, e.g. `ZukanWork.CheckLangFlags`, `GMSWork.ResetGMSData`, `TvWork.Initialize`, `BallDecoWork.ResetBallDecoExtraData`); then `OnPostLoad_NeedMD` 0x2dec8e0. [verified]

### BINARY_SIZE (length used by the hasher for each version, 0x25 … 0x34)
Static `int[16]` from `PlayerWork.SaveData..cctor` 0x1c29610 (`RuntimeHelpers.InitializeArray`); contents from the metadata data row (`fieldDefaultValues`):

| Version | 0x25 | 0x26 | 0x27 | 0x28 | 0x29 | 0x2A | 0x2B–0x31 | 0x32 | 0x33 | 0x34 |
|---|---|---|---|---|---|---|---|---|---|---|
| Size | 0xE9828 | 0xE9BE8 | 0xED158 | 0xED188 | 0xED188 | 0xED680 | 0xEDC20 | 0xEED8C | 0xEED8C | **0xEF0A4** |

The values exactly match the starting offsets of newly added blocks (recodeAddData, mysteryGift, poketore, playReport/mt, dendouSaveAdd/tv, ballDecoExtra). [verified; version-to-block mapping inferred]

## 4. Layout (version 0x34, total size 0xEF0A4 = 979,108 bytes)

Derivation: the Marshal routine generated by the IL2CPP compiler (managed → native) is at **0x2abf40–0x2acb64** (reverse direction starts at 0x2acb90). Ghidra did not identify it as a function; it was found via `scripts/ghidra/ScanScalars.java` (constant 0x9818) and decompiled in memory with `scripts/ghidra/DecompAt.java` (`work/decomp/save-spec/marshal_savedata.c`). Native offsets for each top-level field were derived with `scripts/save_toplevel.py`. Cross-checks: hash offset 0xE9818 and GMS offset 0x9D03C match dump.cs constants, total field sizes add up to exactly 979,108 (0xEF0A4), and rival name at 0x55F4 matches UTF-16 “Lutz” in the local save. [verified]

For this Marshal layout: each `bool[]` element is 4 bytes (Marshal BOOL), `string` is a fixed UTF-16 field (`rivalName` 0x40 bytes), and nested structures are inline.
The “Size” column is the difference to the next field and may include padding. “mgd” offsets from dump.cs are **managed** offsets (not file offsets).

| File offset | Size | mgd | Field | Type | Marshal routine |
|---|---|---|---|---|---|
| 0x00000 | 4 | 0x000 | version | int | |
| 0x00004 | 2000 | 0x008 | intValues | int[500] | |
| 0x007D4 | 16000 | 0x010 | boolValues | bool[4000] (4 B/Elem) | |
| 0x04654 | 4000 | 0x018 | systemFlags | bool[1000] | |
| 0x055F4 | 64 | 0x020 | rivalName | string (32 UTF-16) | |
| 0x05634 | 4 | 0x028 | zoneID | ZoneID | |
| 0x05638 | 4 | 0x02C | timeScale | float | |
| 0x0563C | 48000 | 0x030 | saveItem | SaveItem[3000] à 16 | 0x2af6d0 |
| 0x111BC | 11988 | 0x038 | saveUgItem | SaveUgItem[999] à 12 | 0x2af780 |
| 0x14090 | 8 | 0x040 | saveItemShortcut | ushort[4] | |
| 0x14098 | 2066 | 0x048 | playerParty | SavePokeParty | 0x2b8e30 |
| 0x148AA | 1610 | 0x058 | boxData | SaveBoxData | 0x2afb90 |
| 0x14EF4 | 412800 | 0x088 | boxTray | SaveBoxTrayData[40] à 10320 (30 × 344) | 0x2b0780 |
| 0x79B74 | 1972 | 0x090 | playerData | PLAYER_DATA | 0x2e9050 |
| 0x7A328 | 12472 | 0x118 | zukanData | ZUKAN_WORK | 0x2a74a0 |
| 0x7D3E0 | 5656 | 0x220 | tr_battleData | TR_BATTLE_DATA[707] à 8 | 0x2a3c40 |
| 0x7E9F8 | 68 | 0x228 | topMenuData | TOPMENU_WORK | 0x2a3a20 |
| 0x7EA3C | 68000 | 0x238 | fieldObj_Save | _FIELDOBJ_SAVE | 0x2a9530 |
| 0x8F3DC | 1440 | 0x240 | record | RECORD_ARRAY | 0x2eb8e0 |
| 0x8F97C | 392 | 0x248 | enc_sv_data | ENC_SV_DATA | 0x2e4070 |
| 0x8FB04 | 128 | 0x298 | player_save_data | PLAYER_SAVE_DATA | 0x2e95a0 |
| 0x8FB84 | 17032 | 0x318 | ballDecoData | SaveBallDecoData | 0x2ab680 |
| 0x93E0C | 2400 | 0x328 | saveSeal | SaveSealData[200] à 12 | 0x2aba20 |
| 0x9476C | 1584 | 0x330 | randomGroup | _RANDOM_GROUP | 0x2aa2f0 |
| 0x94D9C | 12 | 0x338 | fieldGimmickSaveData | FieldGimmickSaveData | 0x2e48c0 |
| 0x94DA8 | 2056 | 0x340 | kinomiGrowSaveData | KinomiGrowSaveData | 0x2e5d30 |
| 0x955B0 | 1604 | 0x350 | poffinSaveData | PoffinSaveData | 0x2ea860 |
| 0x95BF4 | 440 | 0x360 | btlTowerSave | BTLTOWER_SAVEWORK | 0x2e1a50 |
| 0x95DAC | 308 | 0x388 | systemData | SYSTEMDATA | 0x2a3790 |
| 0x95EE0 | 416 | 0x3F8 | poketchData | POKETCH_DATA | 0x2e9760 |
| 0x96080 | 704 | 0x438 | azukariyaData | AzukariyaData | 0x2cae90 |
| 0x96340 | 14768 | 0x458 | dendoudata | _DENDOU_SAVEDATA | 0x2a9210 |
| 0x99CF0 | 8 | 0x468 | badgeSaveData | BadgeSaveData | 0x2e1ec0 |
| 0x99CF8 | 24 | 0x470 | boukenNote | BoukenNote | 0x2e2050 |
| 0x99D10 | 2956 | 0x478 | tvDataOld | byte[] | |
| 0x9A89C | 10144 | 0x480 | ugSaveData | UgSaveData | 0x2a5f80 |
| 0x9D03C | 201508 | 0x508 | gmsdata | GMS_DATA | 0x2e49d0 |
| 0xCE360 | 1712 | 0x518 | networkdata | PLAYER_NETWORK_DATA | 0x2e9380 |
| 0xCEA10 | 12 | 0x540 | unionSaveData | UnionSaveData | 0x2a6e10 |
| 0xCEA1C | 24 | 0x54C | contstPhotoLangData | CON_PHOTO_LANG_DATA | |
| 0xCEA34 | 100 | 0x568 | zukanPersonalRndData | ZUKAN_PERSONAL_RND_DATA | 0x2a7110 |
| 0xCEA98 | 160 | 0x580 | contestPhotoExtData | CON_PHOTO_EXT_DATA[] | 0x2e31b0 |
| 0xCEB38 | 104000 | 0x588 | gmsPointExtData | GMS_POINT_HISTORY_EXT_DATA[] | 0x2e51d0 |
| 0xE8178 | 32 | 0x590 | ugCountRecord | UgCountRecord | |
| 0xE8198 | 5760 | 0x5B0 | reBuffNameData | ReBuffnameData | 0x2a16a0 |
| **0xE9818** | 16 | 0x5B8 | **saveDataHash** | byte[16] (MD5) | |
| 0xE9828 | 960 | 0x5C0 | recodeAddData | RECORD_ADD_DATA | 0x2eb030 |
| 0xE9BE8 | 13680 | 0x5D0 | mysteryGiftSaveData | MysteryGiftSaveData | 0x2e8a40 |
| 0xED158 | 48 | 0x608 | poketoreCountArray | POKETCH_POKETORE_COUNT_ARRAY | 0x2ea060 |
| 0xED188 | 248 | 0x610 | playReportData | PLAYREPORT_DATA | |
| 0xED280 | 1024 | 0x708 | mtData | MT_DATA | 0x2abb10 |
| 0xED680 | 1440 | 0x710 | dendouSaveAdd | DENDOU_SAVE_ADD | 0x2e3ca0 |
| 0xEDC20 | 4460 | 0x718 | tvData | TV_DATA | 0x2a3ca0 |
| 0xEED8C | 792 | 0x7A8 | ballDecoExtraData | SaveBallDecoExtraData | 0x2ab830 |

Array lengths for `intValues`, `boolValues`, `systemFlags`, `saveItem`, `saveUgItem`, `saveItemShortcut`, `boxTray`, `tr_battleData` also come from
`PlayerWork$$Initialization` 0x2deb000 (500, 4000, 1000, 3000, 999, 4, 40, 0x2c3=707). [verified]
Managed `PlayerWork.SaveData` is 0x7B8 bytes (last field 0x7A8 + 16); `PlayerWork` itself stores `_saveData` at +0x18 and `_writeSrcBuffer` at +0x820. This is only the wrapper with references to arrays/structures, not the file image. [verified: dump.cs, memcpy(…,0x7b8) in ToBytes/LoadBytes]

### Pokémon slots
- A box/party slot is a `byte[]` (`SerializedPokemonFull.buffer`); box slot size is 10320 B per tray / 30 slots = **344 bytes** per slot. [inferred from tray size; 30 slots not independently verified]
- Encoding: Gen 4/5-like—16-bit words XORed with an LCG keystream (`Encoder$$Encode/Decode` 0x21524d0/0x2152520), with the sum of 16-bit words as checksum (`CalcChecksum` 0x2152460).
  Keys/seeds and encoded regions are in `Pml.PokePara.Accessor` (`UpdateChecksumAndEncode` 0x25a3f20, `DecodeAndCheckIllegalWrite` 0x25a42f0; export `work/decomp/save-spec/Pml_PokePara_Accessor.c`). [open: complete description]

## 5. Check against the local save
`Ryujinx/bis/user/save/0000000000000006/0/SaveData.bin`: size 979,108, version 52, MD5 over the file with the field at 0xE9818 zeroed matches the stored hash. [verified, independently recomputed]

## 6. Open questions
- Internal layouts of nested structures (e.g. `PLAYER_DATA`, `ZUKAN_WORK`, `SaveBoxData`): their Marshal routines (the “Marshal routine” column) contain the offsets; automated analysis remains to be done. Managed dump.cs offsets are insufficient because arrays are stored inline (fixed length) and `bool` uses 4 bytes. [open]
- Exact padding/alignment gaps within sizes calculated as differences in the table (e.g. `gmsdata` 201,508 vs. `GMS_WORK_SIZE` 201,476). [open]
- Pokémon encoding details (seed source, encoded regions, direct verification of 344-byte slot size). [open]
- Confirm that the second ToBytes/LoadBytes call is `StructureToPtr`/`PtrToStructure`, and that type handle `PTR_DAT_04cbfcf8` = `PlayerWork.SaveData`. [inferred]
- Mapping path constant ↔ main file/backup in `SaveSystem` (literal pointers `PTR_DAT_04cbfc68/70`). [inferred]
- Purpose of `rp*.dat` in the other save directory (`docs/save-format.md`) remains unknown.

## 7. Custom analysis tools
- `scripts/ghidra/ExportDecompiled.java` (regex → .c per class), `ScanScalars.java` (search scalar operands), `DumpRange.java` (listing for a range),
  `DecompAt.java` (create a function in memory and decompile it; with `-readOnly`, does not modify the project).
- `scripts/save_layout.py` (dump.cs ↔ metadata fields, 105,088 fields match), `scripts/save_toplevel.py` (native top-level offsets from the decompiled Marshal routine).

## 8. Addendum: Pokémon slots
Slot layout (344 bytes), encoding (LCG-XOR, 16-bit checksum, block shuffle), all fields, and stat calculations are documented in `docs/pokepara-spezifikation.md`
(C#: `unity/Assets/Scripts/PokePara`); this resolves the Pokémon-encoding items marked open in sections 4 (“Pokémon slots”) and 6. All 1206 slot checksums match in the local save.

## 9. Addendum: player basics, items, write path
Native offsets in `PLAYER_DATA` (name 0x79BB4, trainer ID 0x79BD0, money 0x79BD4, play time 0x79C04), the 16-byte `SaveItem` layout, and the write path (`SaveData`, atomic write, directory conventions)
are documented with evidence in `docs/save-kompatibilitaet.md` (C#: `SavePlayerLayout`, `SaveData`).
