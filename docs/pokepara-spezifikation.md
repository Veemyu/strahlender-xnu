# Pokémon Parameters (Pml.PokePara) and Save Slots — Specification

Track B of the `ap-battle` / `ap-save-compat` tasks. Written entirely in my own words; based exclusively on static analysis of
`work/elf/main.patched.elf` (pseudocode export `work/decomp/battle_all/`, files `Pml_PokePara_*.c`), types and field offsets in
`work/il2cpp/dump.cs`, and cross-checks against a local save (numbers only; see section 7). No external projects were used.

Addresses are **Ghidra addresses** (Il2CppDumper RVA + `0x100000`), as shown in the export's commented headers. Offsets without a qualifier are byte offsets.
Labels: **[O]** confirmed by running the real game function in the emulator (oracle, section 7), **[B]** directly supported by pseudocode/`dump.cs`,
**[R]** confirmed against a real save, **[A]** assumed, **[open]** unresolved.
This binary layout is now part of the save specification (`docs/save-spec-entwurf.md`, “Pokémon slots”, previously marked open; resolved here).

## 1. Types and sizes

| Type (Pml.PokePara) | Size | Contents | Evidence |
|---|---:|---|---|
| `CoreData` | 328 = `0x148` | header (8 bytes) + four 80-byte blocks (`CORE_DATA_BLOCK_SIZE`) | `dump.cs CoreData.SIZE`; `Accessor$$Initialize` `0x25a39d0` allocates `0x148` bytes [B] |
| `CalcData` | 16 = `0x10` | calculated values (level, stats) | `dump.cs CalcData.SIZE` [B] |
| `SerializedPokemonCore` | `byte[0x148]` | `CoreData` only | `SerializedPokemonCore$$CreateWorkIfNeed` `0x21559e0` [B] |
| `SerializedPokemonFull` | `byte[0x158]` = 344 | `CoreData` (`0x148`) + `CalcData` (`0x10`) | `SerializedPokemonFull$$CreateWorkIfNeed` `0x21558c0`; `Accessor$$Serialize_FullData` `0x25a4410` copies core at +0 and CalcData at +`0x148` [B] |
| `SavePokeParty` | 2066 | `members[6]` (344 each), then `memberCount` (byte), `markingIndex` (byte) | `dump.cs`; `SavePokeParty$$Serialize_Full` `0x2155490`; size matches table in `save-spec-entwurf.md` [B][R] |
| `SaveBoxTrayData` | 10320 | `pokemonParam[30]`, 344 each | `dump.cs`; `BoxPokemonWork.TRAY_POKE_MAX = 30`, 40 trays (`TRAY_MAX`) [B][R] |

In the save, slots are contiguous **marshaled representations** (no length fields or gaps): party slot *i* at
`0x14098 + 344·i`, party count at `0x14098 + 2064`, marking index at +2065; box slot *p* in tray *t* at
`0x14EF4 + 10320·t + 344·p` (`playerParty` and `boxTray` in `SaveLayout`). Party serialization always writes **all six** slots, including empty ones
(`SavePokeParty$$Serialize_Full` copies `members[0..5]` regardless of `memberCount`, then writes `memberCount = party+0x18`, `markingIndex = party+0x1c`) [B].

The real save contains 6 + 1,200 slots, and all checksums match [R].

## 2. Slot layout (344 bytes)

```
0x000  CoreData (328)
         0x000  uint   personalRnd      encoding and block-shuffle seed; remains plaintext
         0x004  ushort headerFlags      bit 0 ppFastMode, bit 1 pppFastMode, bit 2 fuseiTamagoFlag (“Bad Egg”)
         0x006  ushort checksum         16-bit checksum over plaintext blocks
         0x008  four 80-byte blocks     encoded, in shuffled order (section 3)
0x148  CalcData (16)                    encoded with the same seed, or 16 × 0
```

Header: `CoreDataHeader` (`dump.cs`, `SIZE = 8`), bit accessors `get/set_ppFastMode/pppFastMode/fuseiTamagoFlag` `0x2143400–0x2143460` [B].
The first two bits are runtime-only accessor modes; in practice, only bit 2 is stored.

## 3. Encoding, checksum, and block shuffle

All functions are pure and were checked in the emulator against the Python/C# implementation [O].

**Checksum**, `Encoder$$CalcChecksum` `0x2152460`: sum all 16-bit little-endian words in the range into a 32-bit value (an odd trailing byte
would be ignored). The lower halfword is stored in the slot. Range: **offset 8, length `0x140` (320 bytes), plaintext**—the four
blocks, excluding the header and CalcData (`Accessor$$UpdateChecksumAndEncode` `0x25a3f20` calls `CalcChecksum(core+8, 0x140)`) [B][O].

**Keystream**, `Encoder$$CalcNextRandCode` `0x2152500`: LCG `z ← z · 0x41C64E6D + 0x6073 (mod 2³²)`, output `z >> 16` (16 bits).
`Encoder$$Encode` `0x21524d0` and `Encoder$$Decode` `0x2152520` are identical: XOR each 16-bit word in the range with the next output value;
initial state is the seed [B][O]. Each range restarts the stream from the seed.

**Encoding** (`UpdateChecksumAndEncode`): compute checksum of plaintext blocks and write at +6 → encode range +8..+`0x148` with
`personalRnd` seed (core offset 0) → encode CalcData (16 bytes) with **the same seed**, restarting the stream. **Decoding**
(`DecodeAndCheckIllegalWrite` `0x25a42f0`): reverse this process. If the recomputed checksum does not match +6, the game sets
`fuseiTamagoFlag` (header bit 2), turning the Pokémon into a “Bad Egg”; getters then return replacement data (replacement blocks from `Accessor$$Initialize`,
including species 494). The accessor re-decodes/re-encodes on every access; the save always contains the encoded state [B].

**Block shuffle**, `Accessor$$GetCoreDataBlockPos(personalRnd, blockId)` `0x25a3e00`: row `(personalRnd >> 13) & 0x1F` of a 32×4 table
(`Accessor..cctor` `0x25ac480`, jagged `byte[32][4]` initializer); column = logical block (A=0, B=1, C=2, D=3; `CoreDataBlockId`), result = physical position
0..3. Core byte offset: `8 + Position · 80`. The table (read from the real `.cctor` [O]) contains the 24 permutations of the standard order;
rows 24..31 repeat rows 0..7:

```
 0: 0123   1: 0132   2: 0213   3: 0312   4: 0231   5: 0321   6: 1023   7: 1032
 8: 2013   9: 3012  10: 2031  11: 3021  12: 1203  13: 1302  14: 2103  15: 3102
16: 2301  17: 3201  18: 1230  19: 1320  20: 2130  21: 3120  22: 2310  23: 3210
24..31 = 0..7
```
(Digits are the physical positions of A, B, C, D.)

**Empty slots:** `personalRnd = 0`, checksum 0, four zero blocks, **encoded** (zeros are XORed with the stream for seed 0, so the range is not all zero).
CalcData is either 16 × 0 (never calculated; `Serialize` writes this when the Calc array is absent, `0x25a4680`) or encoded zeros. In the real save,
1,060 empty box slots have no encoded CalcData and 5 do [R]. An all-zero slot without valid encoding would instead be “corrupt”, because the checksum of the
decoded random data would not be zero.

**Changing the seed:** `Accessor$$SetPersonalRnd` `0x25a85a0` writes only the field and re-encodes; it does **not** reshuffle the blocks. A new row therefore
changes the logical mapping (effectively a bug, reproduced 1:1 here: `CoreParam.PersonalRnd`). `CoreParam.ReseedPreservingBlocks` is an added helper (not in the original)
for lossless reseeding.

## 4. Fields

Offsets are relative to the **start of each block** (physical position as described in section 3). Evidence comes from field lists in `dump.cs`
(`CoreDataBlockA..D`) and the `Accessor` getters/setters (addresses in parentheses only for notable cases); every field was cross-checked using the real accessors [O].

### Block A (logical 0)

| Offset | Size | Field (`dump.cs` / local name) | Notes |
|---|---:|---|---|
| 0x00 | 2 | `monsno` / `SpeciesNo` | 0 = empty slot (`CoreParam$$IsNull` `0x214c9d0`) [B] |
| 0x02 | 2 | `itemno` / `HeldItem` | |
| 0x04 | 4 | `id` / `TrainerId` | full 32-bit Trainer ID; input to shiny calculation |
| 0x08 | 4 | `exp` / `Exp` | |
| 0x0C | 2 | `tokuseino` / `Ability` | ability stored directly |
| 0x0E | 2 | `_bitsA` | bits 0/1/2 ability 1/2/3 (`tokusei1..3Flag`), bit 3 favorite, bit 4 `special_g_flag`, bit 5 `debug_edit_flag` |
| 0x10 | 2 | `boxMark` / `BoxMark` | |
| 0x14 | 4 | `colorRnd` / `ColorRnd` | shiny-variation random value |
| 0x18 | 1 | `seikaku` / `Nature` | nature (0..24) when obtained |
| 0x19 | 1 | `seikakuHosei` / `NatureAdjust` | **nature used for stats** (Mints change only this field) |
| 0x1A | 1 | `_bitsB` | bit 0 `eventGetFlag`, bit 1 `officialBattleEnableFlag`, bits 2–3 `sex` (0 male, 1 female, 2 none; `Pml.Sex`) |
| 0x1C | 2 | `formNo` / `FormNo` | |
| 0x1E..0x23 | 6×1 | `effort*` / EVs | order: **HP, Attack, Defense, Speed (0x21), Sp. Attack (0x22), Sp. Defense (0x23)** |
| 0x24..0x29 | 6×1 | Contest stats | `style, beautiful, cute, clever, strong, fur` |
| 0x2A | 1 | `pokerus` | |
| 0x2C / 0x30 / 0x38 / 0x3C | 4 each | `ribbonA / B / C / D` | ribbon *n* = bit *n* % 32 in word *n*/32 (A, B, C, D); `HaveRibbon` `0x25a5b40` [B][O] |
| 0x34 / 0x35 | 1 each | `lumpingRibbonA/B` | combined ribbon counter |
| 0x40 | 1 | `_bitsC` → `camp_friendship` | accessor reads the full word; the lowest byte is usable |
| 0x44 | 4 | `camp_reserved` | |
| 0x48 / 0x49 | 1 each | `talentHeight` / `talentWeight` | size/weight value |
| 0x4A | 1 | `_bitsD` | bit 0 `dpr_illegal_flag` |
| 0x4B | 5 | Padding | |

### Block B (logical 1)

| Offset | Size | Field | Notes |
|---|---:|---|---|
| 0x00 | 26 | `nickname` | 13 UTF-16 characters, NUL-terminated, at most 12 visible; remainder 0 (`SetNickName` `0x25aa1e0`) [B][O] |
| 0x1A | 4×2 | `waza` | move IDs |
| 0x22 | 4×1 | `pp` | current PP |
| 0x26 | 4×1 | `pointupUsedCount` | PP Up use per move |
| 0x2A | 4×2 | `tamagoWaza` | egg moves |
| 0x32 | 2 | `hp` | current HP (max HP is in CalcData) |
| 0x34 | 4 | `_bitsA` | IVs, 5 bits each: **HP 0, Attack 5, Defense 10, Speed 15, Sp. Attack 20, Sp. Defense 25**; bit 30 egg (`tamagoFlag`), bit 31 nickname (`nicknameFlag`) [B][O] |
| 0x38 | 1 | `effortG` | |
| 0x3C | 4 | `sick` | status bits |
| 0x40 | 4 | `palma` | |
| 0x44 | 12 | Padding | |

### Block C (logical 2)

| Offset | Size | Field | Notes |
|---|---:|---|---|
| 0x00 | 26 | `pastParentsName` | same layout as nickname |
| 0x1A / 0x1B | 1 each | `pastParentsSex`, `pastParentLangID` | |
| 0x1C | 1 | `ownedByOthers` | nonzero: current owner differs from original owner (setter stores 0/1) |
| 0x1E | 2 | `othersFriendshipTrainerId` | |
| 0x20 | 1 | `othersFriendship` | |
| 0x21 / 0x22 / 0x23 | 1 each | `othersMemoriesLevel / Code / Feel` | |
| 0x24 | 2 | `othersMemoriesData` | |
| 0x26 | 14 | `pokejob` | bitfield; bit *i* = byte *i*/8, bit *i*%8, where *i* < `0x70` |
| 0x34 / 0x35 | 1 each | `enjoy`, `nadeNadeValue` | |
| 0x36 | 1 | `getCassette` | game version ID (“CassetteVersion”) |
| 0x37 | 1 | `battleRomMark` | |
| 0x3A | 1 | `langId` | language (not 0x38/0x39 = `padding_1/2`) |
| 0x3C | 4 | `multiWork` | |
| 0x40 | 1 | `equipRibbon` | |

### Block D (logical 3)

| Offset | Size | Field | Notes |
|---|---:|---|---|
| 0x00 | 26 | `parentsName` | original Trainer's name, same layout as nickname |
| 0x1A | 1 | `friendship` | friendship with original Trainer (`GetOriginalFriendship`) |
| 0x1B / 0x1C / 0x20 | 1 each | `memories_level / code / feel` | |
| 0x1E | 2 | `memories_data` | |
| 0x21..0x23 | 3×1 | `eggGetYear/Month/Day` | egg-hatch date (accessor `GetTamagoGet*`) |
| 0x24..0x26 | 3×1 | `firstContactYear/Month/Day` | catch/hatch date (accessor `GetBirth*`) |
| 0x28 / 0x2A | 2 each | `getPlace`, `birthPlace` | locations |
| 0x2C | 1 | `getBall` | Poké Ball |
| 0x2D | 1 | `_bitsA` | bits 0–6 `getLevel` (capture level), bit 7 `parentsSex` (Trainer's sex) |
| 0x2E | 1 | `trainingFlag` | bit *i* (*i* = HP 0, Attack 1, Defense 2, Sp. Attack 3, Sp. Defense 4, Speed 5): IV counts as 31 |
| 0x2F | 14 | `wazaRecordFlag` | bitfield < `0x70` |
| 0x3D | 8 | `bankUniqueID` | unaligned |
| 0x45 | 11 | Padding | |

**Friendship** (`Accessor$$GetFriendship` `0x25a5030`, `SetFriendship` `0x25a8a30`): when `ownedByOthers == 0`, use `D.friendship`; otherwise
use `C.othersFriendship`. The setter writes to the same field [B][O].

**Summary of equivalence with the original:** C# setters were compared byte-for-byte with slots generated by the game for 104 distinct setter functions
(three calls each with random/maximum arguments) and the name setters. Getters (101 functions, 463 values per slot) were checked on 32 slots [O].

### CalcData (16 bytes, encoded)

| Offset | Size | Field |
|---|---:|---|
| 0x0 | 1 | `level` |
| 0x2 | 2 | `maxHp` |
| 0x4 / 0x6 | 2 each | `atk`, `def` |
| 0x8 | 2 | `agi` (Speed) |
| 0xA / 0xC | 2 each | `spatk`, `spdef` |
| 0xE | 1 | `gState` |

(`CalcData` in `dump.cs`; accessors `GetLevel` `0x25a71a0`, `GetMaxHp` `0x25a73e0`, etc. [B][O].) Level is **not** derived from experience here;
it is read from this block. If CalcData is missing, `CoreParam$$GetLevel` `0x2143e30` calculates it from experience (`CalcLevel`).

## 5. Calculated values

All formulas are implemented in `unity/Assets/Scripts/Battle` and oracle-verified (`docs/kampf-spezifikation-1.md`, section 3); `PokemonParam` connects
them to slot fields such as `CoreParam$$CalcMaxHp_NotG` `0x2145460` and `CalcAtk_NotG` `0x2145570` [B]:

- **Inputs per stat:** level (from CalcData, otherwise experience), species/form base stat (master data, `Pml_Personal_PersonalTableExtensions.GetParam`), **IV**
  (5 bits in block B; 31 if that stat's training flag is set; `CoreParam$$GetTalentPower` `0x2144610`), **EV** (block A), **nature = `seikakuHosei`** (not `seikaku`).
- **HP** (`CalcTool$$CalcMaxHp` `0x25ad1b0`): `((2·base + IV + (EV & 0xFFFC)/4) · level) / 100 + level + 10`; species 292 always has 1 HP.
- **Other stats** (`CalcTool$$CalcAtk` `0x25ad200` …): `((2·base + IV + (EV & 0xFFFC)/4) · level) / 100 + 5`, then nature adjustment ×1.1 or ×0.9
  (`CalcCorrectedPowerBySeikaku`; table in `Nature.cs`).
- **Recalculation** (`CoreParam$$UpdateCalcDatas` `0x2144010`): derive level from experience (`CalcLevel`), calculate new max HP; if current HP != 0 (or fainted state is not preserved),
  `hp' = min(hp, newMax)`; if max HP does not decrease, `hp' = hp − oldMax + newMax` (no upper cap, 16-bit). Then Attack, Defense, Sp. Attack, Sp. Defense, Speed.
  `PokemonParam.RecalculateCalcData`.
- **Level from experience** (`CalcTool$$CalcLevel` `0x25ad0e0`): greatest *L* ∈ 1..100 where `exps[L] ≤ experience` (species growth-rate row, 101 entries) — `GrowthRate.LevelFromExp`.
- **Move max PP** (`CoreParam$$GetWazaMaxPP` `0x21480c0`): `PP₀ + (((min(Plus,3) · PP₀ · 5) & 0x3FFF) << 2) / 100`, lower byte only; `PP₀` = base PP from move master data.
- **Shiny check** (`CalcTool$$IsRareColor` `0x25ad790`, oracle-verified [O]): `((id & 0xFFF0) ^ (id >> 16) ^ (colorRnd >> 16) ^ (colorRnd & 0xFFF0)) < 0x10`.
- **Egg** (`CoreParam$$IsEgg` `0x2149370`, mode 0): `tamagoFlag && !fuseiTamagoFlag`.

## 6. Implementation (C#, assembly `Xnu.PokePara`, without UnityEngine)

| File | Contents |
|---|---|
| `PokeLayout.cs` | Sizes, block offsets, party/box constants |
| `PokeEncoder.cs` | Checksum, LCG, `Encode/Decode`, block shuffle (`BlockPosition`) |
| `CoreParam.cs` | 328-byte plaintext core, all fields as properties, `FromEncoded` / `EncodeTo` |
| `PokemonParam.cs` | Core + CalcData = 344-byte slot, stats, level, max PP, shiny status |
| `PokeSaveSlots.cs` | Read/write party and boxes in `SaveData.bin` (does not update file hash → run `SaveWriter.FixHash` afterward), `Verify`, `RewriteAll` |

Design decisions: (1) An invalid slot does **not** automatically become a Bad Egg on read (the game sets that bit); `markBadEggOnMismatch` enables it.
(2) On write, the checksum is always recalculated as in the game; `recomputeChecksum: false` preserves the stored checksum (lossless pass-through for corrupt slots).
(3) If CalcData is 16 × 0 in the save, `HasCalcData = false` and writing emits zeros again; otherwise it is decoded as in the game.
(4) The game's Bad Egg replacement data is not reproduced [open].

## 7. Verification

1. **Round-trip against a real save** (throwaway project `work/dotnet-pokepara`, numeric data only; `SaveData.bin` and `Backup.bin` yield the same figures): 1,206 slots (6 party + 1,200 boxes),
   141 occupied (6 party, 135 boxes), **1,206/1,206 valid checksums**, 1,206/1,206 byte-identical after decode + encode, entire file byte-identical after `RewriteAll`, file hash also identical after `FixHash`.
   Party count 6, `trayMax` 18, no Bad Eggs [R].
2. **Oracle** `scripts/pokepara_oracle.py` (Unicorn, same method as `scripts/battle_oracle.py`): runs real functions — `Encoder.CalcChecksum/Encode/Decode/CalcNextRandCode`,
   `Accessor..cctor` and `GetCoreDataBlockPos`, `UpdateChecksumAndEncode` (so the game itself encodes test slots), 101 getters, 104 setters, three string setters,
   `CalcTool.IsRareColor`. Results are numeric values or hex strings from **synthetic random data** in
   `unity/Assets/Tests/EditMode/Fixtures/PokeParaCodec.json` (27 checksums, 32 crypto cases, 16 LCG steps, 72 block positions, 32 table rows, 48 shiny checks),
   `PokeParaAccessor.json` (32 slots, all 32 shuffle rows), and `PokeParaSetters.json` (312 setter cases, 18 string cases). No real save data.
   Oracle limit: functions that access `PersonalSystem`/master data (`CalcLevel`, `GetBasicPower`, `GetWazaMaxPP`) do not run in the emulator; they are covered by
   pseudocode and the already oracle-verified formulas in `Xnu.Battle`.
3. **NUnit tests** (`unity/Assets/Tests/EditMode/PokeParaCodecTests.cs`, `PokeParaAccessorTests.cs`, `PokeParaSlotTests.cs`, assembly `Xnu.Tests.EditMode`) use fixtures and synthetic slots/saves generated in tests.
   Developed in throwaway project `work/dotnet-pokepara` (44 tests, including the local-save check that exists only there).
   Python helper tests: `scripts/tests/test_pokepara_oracle.py`.

Reproduce fixtures: `PYTHONPATH=tools/pydeps python3 scripts/pokepara_oracle.py` (fixed seed, deterministic).

## 8. Open questions

- **Bad Egg path:** replacement blocks and replacement CalcData from `Accessor$$Initialize` (including species 494 and language from `PlayerWork.msgLangID`) are not reproduced; `IsBadEgg` is tracked only as a bit [open].
- **Meaning** of individual fields (ribbon indices, `memories*`, `sick` bits, `palma`, `effortG`, `gState`, `camp_reserved`, `battleRomMark`) is modeled only as raw values; mapping these to names/text belongs in the master-data/UI layer [open].
- **Box auxiliary data** (`SaveBoxData`, 1,610 bytes at `0x148AA`): only `trayMax` (45 bytes before end; value 18 = `TRAY_NUM_1ST`) is confirmed [R]. Structures before it (tray names, team names, team slots,
  background) contain suspicious pointer-like values (8-byte patterns) in the real save and have not been decoded [open]. The end-field layout inferred from offsets is: `teamPos` (32 × `0xFFFF`), `teamLock`, `trayMax`,
  `currentTray`, `isOpened` (1 byte), `wallPaper[40]`, `statusPut` (ushort) [A].
- The exact marshaled layouts of `SavePokeParty`/`SaveBoxTrayData` were not read from the marshal routines (`0x2b8e30` / `0x2b0780`); they were inferred from table sizes and the real-save round trip [R].
