# Saves: format, validator, and where saves live

The recompiled game runs the original save code, so a save file written by the app is a normal Brilliant Diamond save and stays
compatible with Ryujinx and a Switch. This page records the format (as far as it was established), the validator script, and the
conventions for finding and moving saves. How the app imports and stores saves is in [recomp-macapp.md](recomp-macapp.md) and
[recomp-ios.md](recomp-ios.md). The real save must never be changed by tests: use copies (see [development.md](development.md)).

Labels: **verified** = visible in pseudocode/disassembly or on a local save; *inferred* = a conclusion from structure or names;
**open** = unresolved. Offsets are file offsets unless noted. The specification was derived from our own static analysis, not from
third-party code (PKHeX's layout was used only as a cross-check).

## 1. The format

- The save is **not** a serialization format: it is the Marshal image of the managed structure `PlayerWork.SaveData`. Fixed
  offsets, no compression, no encryption of the file as a whole. **Verified.**
- Size `0xEF0A4` (979,108 bytes); the first four bytes are the version as a little-endian `int`, currently `0x34` (the earliest
  version that is hash-checked is `0x25`; the game does not check versions below that).
- **Checksum:** an MD5 (16 bytes) at `0xE9818`, computed over the whole file with that field zeroed. The length hashed depends on the
  version (`BINARY_SIZE`): `0x25` 0xE9828, `0x26` 0xE9BE8, `0x27` 0xED158, `0x28`/`0x29` 0xED188, `0x2A` 0xED680, `0x2B`-`0x31`
  0xEDC20, `0x32`/`0x33` 0xEED8C, `0x34` 0xEF0A4. Verified valid for both `SaveData.bin` and `Backup.bin`. A version above `0x34` would
  index past the table (*inferred*: the game fails).
- **Two files:** `SaveData.bin` (main) and `Backup.bin`. The game writes main then backup (`nn::fs`: delete, create, write, commit)
  and loads from either (`LoadAsync(fromBackup)`). The two can hold different positions, so the start position can alternate.
  The mapping main = first write is *inferred* from function names.
- **Load:** a shorter older file is zero-padded; a missing file is `NOT_EXIST`, a failed hash `CORRUPTED`. Versions below `0x34`
  go through the game's own migration (`TakeOverOldVersion`).
- **Pokémon slots** are 344 bytes each and encoded individually (Gen 4/5-style 16-bit XOR with an LCG keystream, factor
  `0x41C64E6D`, increment `0x6073`, 16-bit checksum). All 1,206 slot checksums (6 party + 1,200 box slots) of the local save match.
  Details of the encoding are in the git history (`pokepara-spezifikation`).

## 2. Top-level layout (version 0x34)

Sizes are differences to the next field and may include padding.

| Offset | Size | Field |
|---:|---:|---|
| `0x00000` | 4 | `version` |
| `0x00004` | 2000 | `intValues` int[500] |
| `0x007D4` | 16000 | `boolValues` bool[4000], 4 bytes per element |
| `0x04654` | 4000 | `systemFlags` bool[1000] |
| `0x055F4` | 64 | `rivalName` (32 UTF-16 characters) |
| `0x05634` | 4 | `zoneID` |
| `0x0563C` | 48,000 | `saveItem` 3,000 entries of 16 bytes (count u32 @0, new flag, favorite, sort number u16 @12) |
| `0x111BC` | 11,988 | `saveUgItem` |
| `0x14098` | 2,066 | `playerParty` (6 x 344 bytes plus count and marker) |
| `0x14EF4` | 412,800 | `boxTray` 40 trays x 30 x 344 bytes |
| `0x79B74` | 1,972 | `playerData` (name at `0x79BB4`, 13 UTF-16 characters; trainer ID `+0x5C`; money `+0x60`, clamped 0 to 999,999; badges `+0x69`; play time `+0x90`..`+0x93`) |
| `0x7A328` | 12,472 | `zukanData` |
| `0x7EA3C` | 68,000 | `fieldObj_Save` |
| `0x8F3DC` | 1,440 | `record` |
| `0x9D03C` | 201,508 | `gmsdata` |
| `0xE9818` | 16 | **`saveDataHash`** (MD5) |
| `0xE9828` ... `0xEED8C` | | blocks added by later versions (`recodeAddData`, `mysteryGiftSaveData`, `poketoreCountArray`, `playReportData`, `mtData`, `dendouSaveAdd`, `tvData`, `ballDecoExtraData`) |

The complete table (about 50 fields with the Marshal routine for each) is in the `TOP_LEVEL_FIELDS` table of `scripts/bdsp_save.py`
(`python3 scripts/bdsp_save.py dump-fields`). Open: the internal layout of nested structures (`PLAYER_DATA`, `ZUKAN_WORK`,
`SaveBoxData`), exact padding, the meaning of `sex` (0/1) and `badge` (count or mask).

## 3. Validator (`scripts/bdsp_save.py`)

A dependency-free checker for `SaveData.bin` and `Backup.bin`; it reads version and size, recomputes the MD5 as the game does, and
holds the field table.

```sh
python3 scripts/bdsp_save.py check <file> [--fields]      # exit 0 = size and hash match, 1 = mismatch, 2 = cannot validate
python3 scripts/bdsp_save.py dump-fields
python3 scripts/bdsp_save.py fix-hash <input> <output>    # writes a new file only; never overwrites
python3 -m unittest discover -s scripts/tests             # includes the validator tests (synthetic bytes)
```

Limits: only version, size and hash are checked, not nested contents or Pokémon legality. Unknown versions are reported, not
guessed; truncated files are errors (the game would zero-pad them). A modified save has not been run through the real game or a
Switch, so *acceptance of edited saves is open*. `scripts/save_layout.py` and `scripts/save_toplevel.py` reconstruct the layout
from the IL2CPP dump and the decompiled Marshal routine (the source of the table).

## 4. Where saves live

**Ryujinx** (local data directory, for example `~/Library/Application Support/Ryujinx`; `Ryujinx/` in this checkout):
- The save index is `bis/system/save/8000000000000000/0/imkvdb.arc`: entries of `0x8C` bytes (a `SaveDataAttribute` key with the
  program ID first, then the save ID). For Brilliant Diamond (`0100000011D90000`) there are two type-1 entries (account saves,
  IDs 6 and 7) and one type-2 entry (device save, empty).
- The save is in `bis/user/save/<SaveID as 16 hex digits>/0/` (`SaveData.bin`, `Backup.bin`), next to `1/`, `ExtraData0` and
  `ExtraData1`. `0/` and `1/` hold identical `SaveData.bin` files; `Backup.bin` is an older, also valid save. Ryujinx creates one
  folder per profile: if the game shows the language selection despite a save, the wrong profile folder was used. The user ID is in
  `ExtraData0` (bytes 8 to 23, each 8-byte half byte-reversed). Close Ryujinx before writing a save.
- `rp*.dat` in the other save directory (about 600 KB each): purpose unknown.

**Other tools (not checked locally, from public descriptions):** yuzu and forks keep
`nand/user/save/0000000000000000/<UserId>/<TitleId>/SaveData.bin`; JKSV and Checkpoint back up the mounted save contents
(`SaveData.bin` plus `Backup.bin`) under `JKSV/<game>/<backup>/` or `switch/Checkpoint/saves/0x<TitleID> <game>/<backup>/`. Whether a
backup tool accepts a generated directory on a real console, and whether a save is bound to a console or account, is **open**.
Shining Pearl (`010018E011D92000`) was not examined.

**The app:** the macOS app keeps its save under `~/Library/Application Support/dev.local.xnubdsp`; development runs use
`work/recomp/save/save_1`. The app imports a save with Cmd+I, drag and drop, or `--import-save`; all three validate it first and back up the previous one.
`scripts/recomp/rt-bdsp/install_save.sh` copies a Ryujinx save into the development folder (previous version kept in a
`backup-<time>` folder; it logs sizes and hashes only). On the iPad a `SaveData.bin` dropped into `Documents/` is imported on the
next "Continue" (`scripts/ios_push_save.sh`). A test save should always be a copy (`BDSP_SAVE=<dir>`).
