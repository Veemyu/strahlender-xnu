# Master Data in the Bundles

Status: `ap-masterdata` task. All statements come from our own dump (UnityFS v7, Unity 2019.4.27f1) and
`work/il2cpp/dump.cs`. This document contains class/field names and numbers only, no game content.

## 1. Summary

- The master-data bundles contain **complete TypeTrees**. They can be read without Unity or the script DLL; the UnityPy Python package (MIT), installed only under `tools/pydeps`, is sufficient (`pip install --target tools/pydeps UnityPy`).
- Each table is a `MonoBehaviour` (ScriptableObject, assembly `Assembly-CSharp.dll`) with one or more lists (“Sheets”), whose rows are flat structures containing numbers, strings, and numeric arrays.
- For all 88 data classes and their nested row classes (one level deep), field names and order match `dump.cs` (zero differences). This also establishes memory offsets.
- Why does `LoadAllAssets` return zero objects in Unity 6? The classes (`XLSXContent.*`) are absent from the new project. This is not a bundle defect, so we read JSON instead of Unity objects.

## 2. Tool and data flow

```
Bundle (UnityFS) --UnityPy/TypeTree--> scripts/masterdata_export.py --> work/masterdata/<bundle>/<Class>.json
                                                                    --> Xnu.Data.MasterDataReader (C#, POCOs)
```

`scripts/masterdata_export.py`:

| Command | Effect |
|---|---|
| `survey [--messages]` | Lists objects/classes/rows per bundle, compares against `dump.cs`, writes `work/masterdata/_survey.json` (field schema per class, including dump offsets) |
| `export [--messages]` | Writes a JSON file per class to `work/masterdata/<shortname>/<Class>.json` |

Only `MonoScript` and `MonoBehaviour` objects are touched; audio, texture, and mesh objects are never read.
`work/` is gitignored. A full export takes a few seconds and is about 72 MB including text.

### JSON format

```json
{"class":"<ScriptClass>","namespace":"XLSXContent","assembly":"Assembly-CSharp.dll","bundle":"<path relative to AssetAssistant>",
 "instances":[{"name":"<m_Name>","data":{"<SheetName>":[{<row>}, ...]}}]}
```

- `data` contains all serialized fields except Unity boilerplate (`m_GameObject`, `m_Enabled`, `m_Script`, `m_Name`).
- Rows are objects with original field names; numeric arrays are JSON arrays; nested structs (e.g. `Vector3f`) are objects.
- Classes with multiple instances (e.g. `MapWarp`, `PlaceData`, `MsbtData`) have multiple entries in `instances`.
- Per-bundle output directories: `dpr_masterdatas`, `pml_personal`, `battle_masterdatas`, `ui_masterdatas`, `effect_database`,
  `contest_masterdatas`, `gms_masterdatas`, `fureai_masterdata`, `underground_masterdata`, `union_masterdata`;
  with `--messages`: `msg_english`, `msg_german`, `msg_common`.

## 3. Findings by bundle

“Objects” means MonoBehaviour instances (excluding MonoScript/AssetBundle). `Dpr/masterdatas` has 1,118 container entries
but 1,141 MonoBehaviours; this difference has not been investigated.

| Bundle | Objects | Classes | Classes (rows in main sheet) |
|---|---:|---:|---|
| `Pml/personal_masterdatas` | 16 | 16 | `PersonalTable` (560), `WazaTable` (827), `ItemTable` (1,823 + 201 machines), `EvolveTable` (560), `WazaOboeTable` (560), `TamagoWazaTable` (560), `AddPersonalTable` (651), `GrowTable` (8), `TamaTable`, `PedestalTable`, `SealTable`, `StoneStatuEeffect`, `UgItemTable`, `UgFather{Expansion,Pos,ShopTable}` |
| `Dpr/masterdatas` | 1,141 | 34 | `TrainerTable` (6 sheets, 707 trainers), `PlaceData` (484 instances), `MapWarp` (552), `StopData` (53), `ShopTable` (10 shops), `PokemonInfo` (1,959), `FieldCommonParam`, `MsgWindowData`, `Tower*`, `Kinomi*`, `HoneyTree`, `TvDataTable`, `TvSchedule`, `ZenmetuZone`, `UgJumpPos`, `CharcterAnime{Event,Table}`, `CharacterGraphics`, `GimmickGraphics`, … |
| `Battle/battle_masterdatas` | 4 | 4 | `BattleDataTable` (19 sheets, including 828 move-data rows and 1,013 message frames), `BattleDefaultPlacementData`, `BattleSetupEffectLots`, `BattleWaitCameraData` |
| `UIs/masterdatas/uimasterdatas` | 6 | 6 | `UIDatabase` (32 sheets), `PlaceNameTable` (774), `TownMapTable` (218), `TownMapGuideTable` (135), `DistributionTable`, `InputLimitTable` |
| `Effects/masterdatas/effectdatabase` | 1 | 1 | `EffectDatabase` (4 sheets, 2,168 battle effects) |
| `Contest/md/contest_masterdatas` | 2 | 2 | `ContestMasterDatas` (12 sheets), `ContestConfigDatas` (9) |
| `GMS/md/gms_masterdatas` | 1 | 1 | `GMSMasterData` (10 sheets) |
| `FureaiHiroba/fureai/masterdata` | 20 | 20 | `FreeSanpo*`, `Poffin*`, `PokeWalking*`, `Monohiroi*`, `HirobaPokeTalk`, … (one sheet each) |
| `UnderGround/masterdata` | 36 | 2 | `UnderGroundFossilNum`, `UnderGroundFossilPos` (35 instances) |
| `Union/unionroom/masterdata` | 2 | 2 | `UnionCharacterTable`, `UnionNpcColorTable` |
| `Message/<language>` | 119 | 1 | `MsbtData` (`Dpr.Message`), one object per text file; `Message/common_msbt`: 90 objects |

All classes are in namespace `XLSXContent`, except `TagPlaceData` (no namespace) and `MsbtData` in `Dpr.Message`.
In TypeTree, row classes are called `Sheet<Name>` (or `Sheet1`); in the dump they are `Table.Sheet<Name>`.

## 4. Mapping to dump.cs

- Table class: `public class WazaTable : ScriptableObject` in namespace `XLSXContent`; its fields are arrays of the row class, with the first field at offset `0x18` (after the 0x18-byte ScriptableObject header).
- Row class: nested as `WazaTable.SheetWaza` (empty namespace); fields begin at `0x10` (IL2CPP object header). Some sheets inherit fields from a base class (`SheetBuyBase`, `SheetDistributionTable`); the comparison resolves inheritance.
- TypeTree field names exactly match dump field names (case included, as are original typos such as `StoneStatuEeffect`). Type mapping is 1:1 for `byte/sbyte/ushort/short/int/uint/float/string`; arrays become JSON arrays. Values are `byte` in the dump even when they represent flags or enums.
- Key offsets (sample, row classes): `SheetPersonal.monsno` 0x14, `.basic_hp` 0x1C, `.tokusei1` 0x34; `SheetWaza.wazaNo` 0x10, `.power` 0x18, `.flags` 0x34; `SheetItem.no` 0x10, `.price` 0x18. All others are in `work/masterdata/_survey.json` (`dump.nested.<Sheet>.offsets`).

## 5. Selected core types and C# models

Code: `unity/Assets/Scripts/Data` (assembly `Xnu.Data`, no Unity dependency).

| Area | Original (bundle) | Model | Notes |
|---|---|---|---|
| Pokémon base data | `PersonalTable.SheetPersonal` (Pml) | `SpeciesRecord` | 43 fields; 560 rows (species + forms) |
| Moves | `WazaTable.SheetWaza` (Pml) | `MoveRecord` | 33 fields; the three `rankEff*1..3` stage fields are arrays |
| Items | `ItemTable.SheetItem` / `SheetWazaMachine` | `ItemRecord`, `MachineRecord` | `wk_*` effect bytes stored in an `Effects` dictionary |
| Evolution | `EvolveTable.SheetEvolve` | `EvolutionRecord` | `ar` is a flat numeric field; group meanings remain to be determined |
| Text | `Dpr.Message.MsbtData` (Message/*) | `MessageFile`, `MessageLabel`, `MessageWord` | style/tag data not yet represented |

`MasterDataReader` (`LoadSpecies/Moves/Items/Machines/Evolutions/Messages`) reads JSON and validates class name and instance count; `Parse*` methods operate on strings (testable without files). `MiniJson` is a small custom parser (Unity does not include System.Text.Json); it also understands `NaN`/`Infinity` in Python JSON output.
Property names are local names derived from Japanese abbreviations. Uncertain interpretations:
`ExpValue`/`GiveExp` (`exp_value`/`give_exp`), `EggBirth`, `Rank`, `EggFormHeldStone*` (`…kawarazunoishi`),
`HoldEffect`/`HoldPower`/`ThrowPower` (`eqp`/`atc`/`nage_atc`). Field names support these interpretations, but behavior has not verified them.

Verification against the actual extraction (counts only): 560 species, 827 moves, 1,823 items, 201 machines,
560 evolution rows, and 119 text files with 42,557 English labels load successfully.

## 6. Tests

- Python: `python3 -m unittest scripts/tests/test_masterdata.py` (synthetic TypeTree nodes, dump excerpt, export).
- C# EditMode: `unity/Assets/Tests/EditMode/DataMasterDataTests.cs` (synthetic JSON; MiniJson, all parsers, errors, directory reader). It was also built and run outside Unity with .NET and NUnit (9 tests passed); it has not yet run in Unity's test runner.

## 7. Open questions (Part 1 status; updated in section 14)

1. **Type chart:** no bundle table exists. `Pml.Battle.TypeAffinity.TYPE_AFF_TBL` is a static `byte[][]` built in the class constructor (`.cctor`) (values x0/xH/x1/x2 = 0/2/4/8). Reading it requires Ghidra analysis of the `.cctor` or reconstruction from a known effectiveness chart.
2. **Tokusei/abilities:** no data table, only the `TokuseiNo` enum and behavior in code; names and descriptions are in message files (`*_ss_tokusei`, `*_ss_tokuseiinfo`). The mapping from enum values to text labels still needs confirmation.
3. **Names:** Pokémon, move, item, and type names exist only in message files (`*_ss_monsname`, `*_ss_wazaname`, `*_ss_itemname`, `*_ss_typename`; Pokémon text in `Message/common_msbt`). The label-to-ID scheme (`labelIndex` versus label names) needs confirmation.
4. **Maps/zones:** these bundles contain placement data (`PlaceData`, `MapWarp`, `StopData`, `ZenmetuZone`, `PlaceNameTable`), but no map geometry or zone metadata table. `ZoneID` is an enum in code; actual zone data and encounter tables are likely in `Dpr/scriptableobjects`, `Dpr/field`, or `ev_script` and have not been investigated.
5. `EvolveTable.ar`: grouping of numbers (method/parameter/target) is unknown; likely groups of three.
6. It is unclear whether Pml tables (`ItemTable`, `WazaTable`) add rows to the battle table `BattleDataTable.BattleWazaData` (828 rows).
7. The comparison checks only one nesting level; deeper structures (e.g. `StyleInfo`, `TagData`) are present in TypeTree but not compared against `dump.cs`.
8. Not tested in Unity Editor (instruction: do not modify the Editor through tools); the test runner and automatically generated `.meta` files remain outstanding.

## 8. Estimated effort for remaining types

- Up to 88 data classes with about 215 sheets have already been exported successfully; only C# models and readers are missing.
- Handwritten models such as the five above take roughly 0.5–1 hour per sheet, including tests. Trainer data (`TrainerTable`, its 157-field `TrainerPoke` sheet), shops, wild encounters, and battle data (`BattleDataTable`) are estimated at 1–2 days.
- A faster route is a generator that creates POCOs and readers from `_survey.json` (about 1 day), followed by name refinement. This should be sufficient for UI, effects, contests, GTS, and leisure data, which are mostly needed later.
- The larger gaps are not the bundles but code-side tables (type chart, ability behavior, evolution rules): 1–3 days of Ghidra/dump work each.

---

# Part 2: Trainers, Encounters, Maps, and Scripts (Task `ap-masterdata`, continued)

Here too, only names, numbers, and structure are included; no game text or data is in the repository (everything remains under `work/`).
Open items 2, 4, and 5 from section 7 are answered in Part 2 (see section 14).

## 9. Where the additional tables are

The new `scan` command opens all bundles under `AssetAssistant` except `Environments` (2.2 GB of map/object models)
and `Pokemon Database` (models), and reads only `MonoScript` objects. Result (`work/masterdata/_scan.json`):
71 bundles contain table classes (`XLSXContent.*`, `Dpr.Message.MsbtData`, `EvData`, `TagPlaceData`). New relative to
Part 1 are these bundles (option `--set extra`, output under `work/masterdata/<shortname>/`):

| Bundle | Short name | Classes (instances → rows) |
|---|---|---|
| `Dpr/scriptableobjects/gamesettings` | `gamesettings` | `FieldEncountTable` (2 instances, 183 zones each), `MapInfo` (658 zones + 658 cameras), `ZoneTable` (2 grids), `AttributeBlock` (2,878), `AttributeMatrix` (614), `MapAttributeTable` (256 codes), `MapAttributeExTable` (114), `CalenderEncTable` (69 days, 366 weather days), `ArenaInfo` (106), `WaterSettings` (5) |
| `Dpr/ev_script` | `ev_script` | `EvData` (856 files, 13,139 scripts, 64,745 commands) |
| `UnderGround/data/ugdata` | `ug_data` | `UgEncount` (12 instances, 491 rows), `UgPokemonData` (493), `UgSpecialPokemon` (77), `UgRandMark` (20), `UgEncountLevel` (9), `UgMiniMap`, `UgNpc{List,Pos,Talk}` (50/42/73), `UgPokemonPos` (75), `UgTamagoWazaIgnoreTable` (113) |
| `LightStone/uglightstonedata`, `UnderGround/lightstone/prefabs/lightstonemanager` | `lightstone`, `lightstone_ug` | `LightStonePosTable` (35), `LightStoneTable` (6); two versions, only `lightstone_ug` matches the dump (see 10) |
| `Dpr/spfishing` | `spfishing` | `RareFishTable` (531 grid points) |
| `Dpr/statueeffectdata`, `StatuePlacementEdit/sb/sbcontroller`, `DigFossil/dig/digfossilcontroller` | `statueeffect`, `secretbase`, `digfossil` | `StatueEffectRawData` (430), `Pedestal` (35), `SecretbaseUpgrade` (3), `HardStoneRawData`, `DepositItemRawData`, `StoneBoxRawData` |
| `FureaiHiroba/fieldwalking` | `fieldwalking` | `FieldWalkingKinomiTable`, `…KinomiSeikakuTable` (25), `FieldWalkingPokeTalk` (235) |
| `Dpr/scenes/title` | `title` | `TitleSettings` (9); the credits list `StaffrollList` (text data) is intentionally not exported |

Not found in `AssetAssistant`: `CharacterTable`, `EffectTable`, `EvMsgList`, `Resources`, `ArenaInfoExtensionMethods` (possibly in other resources or code). Audio classes `AudioTable`, `BgmInfo`, `DebugAudioDatabase` are in none of the scanned bundles; audio is never touched anyway. `Contest/music/*` contains only `NotesInfo` (contest), and `UIs/searchdatas/*` only `SearchIndexData` (text, 9 languages); neither is exported. Non-table classes in the same bundles are also excluded (`EnvironmentSettings` 175, `GameSettings`, `EventCameraData` 526, `EventCameraTable`); references to them are resolved by name only.

There are now 125 JSON files (88 Part 1 + 37 Part 2); `work/masterdata` is about 102 MB.

## 10. Exporter additions (additive only)

Without new options, `scripts/masterdata_export.py` behaves as before (all Part 1 tests still pass unchanged).

| Addition | Effect |
|---|---|
| `--set base\|extra\|all` | `base` (default) = Part 1; `extra` = bundles in `EXTRA_BUNDLES`; `all` = both. Applies to `survey` and `export`. `survey --set extra` writes `_survey_extra.json` (Part 1 stays in `_survey.json`). |
| `counts` | writes instance and row counts for all JSON files to `_counts.json` (numbers only) |
| `scan` | lists table classes per bundle in `_scan.json` (MonoScript only, about 5 minutes) |

Extra-export additions:
- Instances include `path_id` (object ID in bundle). PPtr references to objects in the same bundle (`{m_FileID:0, m_PathID}`) receive `target_class` and `target_name`; for example, `MapInfo…Attribute` resolves to the `AttributeMatrix` name. Resolution occurs before class filtering, including for classes not exported (e.g. `EnvironmentSettings`).
- Per-bundle class filters (`EXTRA_BUNDLES`): by default namespace `XLSXContent` only; `ev_script` only `EvData`; `title` only `TitleSettings`.
- New tested helpers: `want_class`, `filter_records`, `resolve_pptr_names`, `table_counts`, `ev_stats`, `scan_wanted`.

Comparison against `dump.cs` (class name, field names, order, offsets): 37 classes, 47 row classes, zero differences in names/order, with one exception. In `LightStone/uglightstonedata`, `LightStonePosTable.SheetData` differs (bundle: `ZoneID, Digda, Dugtrio`; dump: `ZoneID, MinNum, MaxNum, MinProbability, MaxProbability, Diglettrate, Dugtriorate, Locator`), as does `LightStoneTable.SheetData` (bundle: `ZoneID, LightStoneNum, EventTime, BonusTime`; dump: `ZoneID, LightStone, BonusTime`). The `UnderGround/lightstone/prefabs/lightstonemanager` bundle matches the dump schema exactly. This suggests the romfs bundle `LightStone/uglightstonedata` is newer than the dump. Therefore the dump is not authoritative for every table; this matters for the Underground section, not the initial route.
It was also verified that the C# reader consumes every dump field in the 33 covered row classes (zero unread fields).

## 11. New C# models and reader (`Xnu.Data`)

Files: `MasterDataModels2.cs` (POCOs), `MasterData2Reader.cs` (reader; custom JSON helpers; `MiniJson` and the Part 1 reader remain unchanged). No UnityEngine dependency. Reader constants specify expected paths under `work/masterdata`.

| Area | Source (Class.Sheet) | Model / reader | Counts from real data |
|---|---|---|---|
| Trainers | `TrainerTable.{TrainerType,TrainerData,TrainerPoke,TrainerRematch}` | `TrainerTables` → `TrainerTypeRecord`, `TrainerRecord` (+ `Party`), `TrainerPokemonRecord`, `TrainerRematchRecord`; `LoadTrainers` | 108 classes, 707 trainers, 706 with teams, 1,563 party slots (max 6), 238 rematches |
| Wild encounters | `FieldEncountTable.{table,urayama,mistu,honeytree,safari,mvpoke,legendpoke,zui}` | `FieldEncounterTables` → `ZoneEncounterRecord`, `EncounterSlot`, etc.; `LoadFieldEncounters(instance)` | 183 zones (171 with grass lists, 53 with water/fishing), 6 honey, 4 honey trees, 64 Safari, 29 roaming zones, 37 fixed encounters, 18 `zui`, 16 `urayama` |
| Honey trees | `HoneyTree.{HoneyTreeIndex,HoneyTreeShake}` | `HoneyTreeTables`; `LoadHoneyTrees` | 21 locations, 4 shake results |
| Calendar | `CalenderEncTable.{data,weather}` | `CalendarEncounterTables`; `LoadCalendar` | 69 days, 366 weather days |
| Zones | `MapInfo.{ZoneData,Camera}` | `MapInfoTables` → `ZoneInfoRecord`, `ZoneCameraRecord`; `LoadMapInfo` | 658 zones, 658 cameras, 67 field zones, 648 with map bundles (377 distinct) |
| Zone grids | `ZoneTable` | `ZoneGridRecord`; `LoadZoneGrids` | 2 grids (30×30 with 196 occupied zones, 4×5 with 6) |
| Map attributes | `AttributeBlock`, `AttributeMatrix`, `MapAttributeTable` | `AttributeBlockRecord`, `AttributeMatrixRecord`, `MapAttributeCodeRecord` | 2,878 blocks (2,863 × 1,024, 15 × 1,056 values, width 32), 614 matrices, 256 codes |
| Warps | `MapWarp` | `MapWarpSet` → `MapWarpRecord`; `LoadMapWarps` | 552 maps, 1,931 warps |
| Shops | `ShopTable.{FS,FixedShop,BPShop}` | `ShopTables`; `LoadShops` | 59 / 75 / 90 entries (other shop sheets not modeled) |
| Learnsets | `EvolveTable.ar`, `WazaOboeTable.ar`, `TamagoWazaTable`, `GrowTable` | `EvolutionListRecord`/`EvolutionStepRecord`, `LearnsetRecord`, `EggMoveRecord`, `GrowthCurveRecord` | 560 lists, 254 evolution steps, 8,384 level/move pairs, 560 egg-move rows, 8 curves of 101 values |
| Event scripts | `EvData` | `EventScriptFile` → `EventScript` → `EventCommand` → `EventArgument` | 856 files, 13,139 scripts, 64,745 commands, 17,328 strings |

Verification: all tables load successfully; peak memory while loading all (including 20 MB of attributes and scripts) is about 410 MB. Cross-checks (real data, counts only): trainer type IDs: zero unknown; team ID equals row index for all 707; all 707 `NameLabel` and all 658 `PokePlaceName` values exist in corresponding message files; zone `Attribute` references → matrices → blocks: zero unresolved; grid zones ↔ `MapInfo`: zero missing; all 25 “zones” without a `MapInfo` entry in `FieldEncountTable` and all 18 warps without a destination are `-1` placeholders.

Interpretation notes (based on field names/numbers, not behavior):
- `TrainerData` has no ID field; trainer ID is the row index (confirmed by `TrainerPoke.ID`).
- `FightType` occurs 681 × 0 and 26 × 1 (likely single/double). `AIBit` is a bitmask with six distinct values (9 for 613 trainers, 111 for 83, 107 for 6, 11 for 3, and 8 plus one other value for one trainer each). Bit meanings are in battle code.
- Slot counts per zone are fixed: grass 12, time-of-day (day/night) 2 each, mass outbreak 2, shaking grass 4, water and each of three fishing tiers 5, GBA lists 2 each. The table contains only each species' overall rate (`encRate_*`), **not per-slot probabilities**; those must come from code (`Encount`/`FieldEncount`) or be reconstructed.
- `FieldEncountTable_d` and `_p` are two editions (grass lists differ in 11 zones). Reader defaults to `_d` (Brilliant Diamond).
- `zui` has 28 Boolean values per zone (possibly matching Unown's number of forms).
- Zone grid: index = row × width + column; `-1` = empty. Attribute blocks contain 32 values per row; matrices concatenate blocks by row (block name, empty = no block). Meaning of attribute values (e.g. 128) is in `MapAttributeTable`/`MapAttributeExTable` (the latter also contains sound-label names, not modeled).
- `MapWarp.GruopID` is an original typo and remains `GroupId`.

## 12. Map, scene, and bundle mapping

- `MapInfo.ZoneData.AssetBundleName` is relative to `Environments/`: 377 distinct names (249 `prefab_map/*`, 114 `underground/*`, 14 `fields/*`); 375 exist as files, two are missing (`prefab_map/c08r0501`, `c08r0601`). Multiple zones share a bundle (e.g. identical house interiors). Ten zones have no map bundle. The folder contains 384 map bundles (`fields` 15, `prefab_map` 255, `underground` 114), 9 not referenced by any zone.
- Field maps (`fields/areaNNN`) contain multiple zones (town + routes); `AreaID` groups them (14 field bundles + `safari`).
- Placement tables are named after the map: `PlaceData_<MAP>` (484 instances, 4,197 rows), `MapWarp_<MAP>` (552 / 1,931), `StopData_<MAP>` (53 / 116). Instance names only partly match map bundle names (277 / 326 / 38 matches); `PlaceData.zoneID` and `MapWarp.WarpZone` point directly to zone IDs and are more reliable keys.
- Scenes (`Dpr/scenes/*`, one bundle each): `battle`, `contest`, `digfossil`, `evolvedemo`, `field`, `gms`, `opening`, `sealpreview`, `title`. The field scene loads maps through `AssetBundleName`; battle backgrounds use `ArenaInfo` (106 entries with ground/sky bundles under `Environments/bg/arenas/{ground,sky}`: 104 + 19 files).
- `ZoneID` has 658 values (0–657; enum has 659 entries including `-1`) and maps 1:1 to `MapInfo` rows.

## 13. Event scripts (`EvData`) — structure only

Format (dump and TypeTree agree): `EvData { List<Script> Scripts; List<string> StrList }`,
`Script { string Label; List<Command> Commands }`, `Command { List<Aregment> Arg }`, `Aregment { ArgType argType; int data }`
(original spelling: “Aregment”). This is **not a bytecode blob**, but structured numeric lists.

- `ArgType` (enum in dump): `Command` 0, `Float` 1, `Work` 2, `Flag` 3, `SysFlag` 4, `String` 5.
  Counts in real data: 64,741 / 26,305 / 13,255 / 2,959 / 458 / 33,054 (140,772 arguments total).
- First argument of a command has `argType` 0 and is the command ID (`EvCmdID.NAME`, 1,236 values 0–1,235).
  Data contains 867 distinct IDs, plus 88 × `-1` (placeholder) and 4 empty commands.
- `Float` arguments store the bits of a `float` in `data` (e.g. 1,065,353,216 = 1.0f); `String` is an index into `StrList`;
  `Work`/`Flag`/`SysFlag` are indices into event variables.
- 856 files, 13,139 scripts (1–952 per file), 64,745 commands, 17,328 string-table entries, about 5.4 MB JSON.
  Filenames are map abbreviations (238 match map bundle names) and `sp_*` (300; special events).
- Command meanings and variable model have not been interpreted. That is the script interpreter's job (dump classes: `EvDataManager`, `EvCmdID`); see `docs/evscript-spezifikation.md` for current status.
- Links from other tables: `PlaceData.TalkLabel` (3,868 set, 3,849 match a `Script.Label`, case-insensitive) and `StopData.ContactLabel` (106/106) are script labels; `PlaceData.ContactLabel` is always empty. `MapWarp.ScriptLabel`/`ExitLabel` are numeric label/exit indices. There are 12,985 distinct labels.

## 14. Updated status of questions from section 7

- **Abilities, natures, types (item 2, partly 1):** still no data table for ability behavior or type effectiveness. Name tables do exist as message files for every language: `ss_tokusei` and `ss_tokuseiinfo` (268 labels each, `TOKUSEI_000…`), `ss_seikaku` (25, `SEIKAKU_nnn`), `ss_typename` (18, `TYPENAME_nnn`), `ss_wazaname` (827), `ss_itemname*` (1,823, six versions). Label index equals ID (`TokuseiNo` has 270 enum values including boundary values, `Seikaku` 26, `PokeType` 21, `TypeAffinity.AffinityID` 16). Highest ability used in `PersonalTable`: 256. The type matrix itself still requires code analysis.
- **Names (item 3 confirmed):** label pattern `<PREFIX>_<nnn>` with `labelIndex == arrayIndex == ID`; trainer and place names are found through table label text (`NameLabel`, `PokePlaceName`; 707 / 658 matches, see 11).
- **Zones/encounters (item 4 resolved):** zone metadata, grids, attributes, cameras are in `gamesettings` (section 9); encounters in `FieldEncountTable`; scenes/maps via `AssetBundleName` (section 12).
- **Evolution (item 5 resolved):** `EvolveTable.ar` consists of groups of five `(method, parameter, target species, target form, level)`; all 560 lists have lengths divisible by 5 (254 groups total). For species 1, `(4, 0, 2, 0, 16)` plausibly means “level up to species 2 at level 16”. There are 25 method values (4 occurs 163 times, 8 occurs 28 times); their meanings have not been individually confirmed. `WazaOboeTable.ar` consists of pairs `(level, move)` (levels 0–100, moves 1–791, 8,384 pairs).
- **Learnsets (item 6, probabilities, `Encount`):** still open (see 11).
- Also open: `EnvironmentSettings` (lighting per map and time of day) and `EventCameraData` are not exported; `PlaceData` row fields (`EventType`, `MoveCode`, `TalkBit`, etc.) can be modeled but have no model yet.

## 15. Text (counts only)

Note: label counts below include padding entries (4,261 empty labels per language; 9,940 in `common_msbt`); actual labels: 38,296 per language, 46,500 in `common_msbt`. Format, tags, and reader (`Xnu.Text`): `docs/lokalisierung.md`.

All languages share the same structure: 119 text files with 42,557 labels total (except `common_msbt`: 90 files, 56,440 labels).
Word count per language: English 71,411, German 75,508, French 76,495, Italian 76,727, Spanish 74,546,
Japanese 79,900 (79,880 kanji), Korean 81,549, Simplified Chinese 77,970, Traditional Chinese 81,633;
`common_msbt`: 64,775 words. Export (`--messages`) includes English, German, and `common`; other languages can be exported by adding them to `MESSAGE_BUNDLES`. Filenames carry a language prefix (`german_…`). Label-to-table mapping:
`TrainerData.NameLabel` → `dp_trainers_name` (1,045 labels), `MapInfo.PokePlaceName` → `dp_fld_areaname` (218), `…MSLabel` → `dp_fld_areaname_display` (142), trainer dialogue → `dp_trainer_msg` (3,014) and `…_sub` (245), trainer classes → `dp_trainers_type` (101).

## 16. Tables for the first playable route (start to first battle)

Route based on internal zone names: zones 422–426 (starting town with rival's and player's houses, interiors and exteriors),
354 (first route), 346, and 323–325 (lake and shore zone). These contain 68 `PlaceData` rows across 8 maps; route zone has trainers 1–3, lake map (324) has trainers 322, 323, 328, 329; wild lists for zones 323, 324, and 354 are identical (grass rate 30), while zone 422 has none. Story order was not verified from the data; the scope is intentionally generous.

| Priority | Table | Total scope (needed for route) |
|---|---|---|
| Core | `PersonalTable` 560, `WazaTable` 827, `ItemTable` 1,823, `GrowTable` 8×101, `EvolveTable` 560, `WazaOboeTable` 560 | all (battle needs species, moves, learnsets, growth curves) |
| Core | `TrainerTable` (Type 108, Data 707, Poke 707) | trainers 1–3 and lake trainers; include type classes |
| Core | `FieldEncountTable` (183 zones, instance `_d`) | 3–4 zones; time/water lists empty except grass |
| Core | `MapInfo` 658/658 | 10 zones; `ZoneTable` 30×30 grid; `MapAttributeTable` 256; `AttributeMatrix` 614 / `AttributeBlock` 2,878 (only blocks for these zones) |
| Core | `MapWarp` 552 maps/1,931 warps, `PlaceData` 484/4,197, `StopData` 53/116 | about 8–12 maps per table |
| Core | `EvData` 856 files/13,139 scripts | files for the involved maps (map prefixes `t01*`, `d27*`, field area, `sp_*`) |
| Core | `MsbtData` (German: 119 files/42,557 labels; `common_msbt` 90/56,440) | dialogue, names, move text |
| Battle | `BattleDataTable` (19 sheets), `ArenaInfo` 106, `BattleSetupEffectLots`, `BattleDefaultPlacementData`, `EffectDatabase` (2,168 entries) | battle presentation; no audio |
| Presentation | `PokemonInfo` 1,959, `CharacterGraphics`, `FieldCommonParam` 281, `MsgWindowData` (2,380 speaker names, etc.), `PlaceNameTable` 774 | models/UI; rest later |
| Later | Shops (`ShopTable`: FS 59, Fixed 75, BP 90), `HoneyTree` 21, `CalenderEncTable`, Underground (`ug_data`), Fureai, contest, GTS, Tower | not needed for first battle |

## 17. Tests, gaps, next steps

- Python: `python3 -m unittest scripts/tests/test_masterdata.py` (22 tests, 11 new for Part 2).
- C#: `unity/Assets/Tests/EditMode/DataMasterData2Tests.cs` with synthetic examples (14 tests: trainers, encounters, zones, grids/attributes, warps, shops, evolution/learnsets, event scripts, errors, directory reader). Also run outside Unity with `dotnet test` (throwaway project `work/dotnet-masterdata2/`, NUnit 3.14): 23 tests passed (9 Part 1 + 14 Part 2); not yet run in Unity test runner (Unity generates `.meta` files for new files on first import). Real-data run is under `work/dotnet-masterdata2/check/` (not in repository).
- Gaps: encounter-slot probabilities; meanings of `AIBit`/`FightType`/evolution methods; type chart and ability behavior (code); `PlaceData` model; script interpreter (command semantics); `EnvironmentSettings`; unmodeled shop sheets and Underground/Fureai models.
- Next useful step: model `PlaceData`/`StopData` and connect them to `MapWarp` to produce a map-loading plan per zone; then derive encounter probabilities from `Encount` (dump/Ghidra).
