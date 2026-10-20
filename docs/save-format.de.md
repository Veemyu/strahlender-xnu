# Save Format (BDSP) – Verification Status

## Ryujinx-to-title mapping
- `Ryujinx/bis/system/save/8000000000000000/0/imkvdb.arc` is the save index. Entries are 0x8c bytes each: `SaveDataAttribute` (0x40 bytes, program ID as the first u64 LE), followed by the value (save ID as u64 LE).
- Title `0100000011d90000` has three entries: account save, user `3f48f5c7…` → save ID `6` (type 1), another user → save ID `7` (type 1), device save → `0xc` (type 2, empty).
- The save is under `bis/user/save/<SaveID>/0/` (index `1` is the second copy).
  - `.../6/0/SaveData.bin` and `Backup.bin`, 979,108 bytes each (0xEF0A4)
  - `.../7/0/rp*.dat` (~600 KB per file, purpose unknown)

## Format (measured from a local save; structure source: PKHeX `SAV8BS`, GPL-3.0, reference only)
- File size `0xEF0A4` (matches PKHeX v1.3); version at the start as u32 LE = `0x34`.
- No container header; fixed offsets (according to PKHeX, e.g. flags at 0x4, items at 0x563C, party at 0x14098, boxes at 0x14EF4).
- Checksum: MD5 (16 bytes) at offset `0xE9818` over the entire file, with the hash field set to 0.
  **Verified:** valid for `SaveData.bin` and `Backup.bin`.
- Pokémon slots are encrypted individually in PKM format (according to PKHeX; not independently verified yet).
- Version v1.3 has no hash at the end of the file (the final 16 bytes are `ff`).

## Open
- Write an independent specification of the blocks in `PlayerWork.SaveData` (Ghidra export) instead of adopting PKHeX's layout.
- Purpose of `rp*.dat`; filename on a physical Switch (not verified).
- Nintendo Switch/yuzu saves: whether the same `SaveData.bin` is expected has not yet been checked.

## Further research findings
- **Cpp2IL** (MIT): NSO loader and metadata v24.5 available; output formats include `dll_il_recovery`, `diffable-cs`, and `isil`. macOS arm64 build available only as pre-release `2022.1.0-pre-release.21`. Quality on BDSP untested.
- **Il2CppInspectorRedux** (AGPL): not a decompiler; provides names/types for Ghidra/IDA.
- **AssetRipper 1.1.8** has `AssetRipper_mac_arm64.zip`. Latest version is 2.0.0.
- **Wwise:** BDSP version not established. `vgmstream` (+ `wwiser` for `.txtp`) can read `.bnk/.wem` without the SDK.
- **libil2cpp:** officially available only in the Unity Editor; public source not verified.
