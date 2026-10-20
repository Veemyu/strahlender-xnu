# Game core, slice 2: host commands, Pokémon Center sequence, bulk and story runs (`ap-game-flow-2`)

Historical Unity-rebuild report (2026-10-19); the rebuild is deprecated. Names, counts, and structure only; no game text, data, or real saves in Git. Code: `unity/Assets/Scripts/Game` (`Xnu.Game`, pure C#); tests: `unity/Assets/Tests/EditMode/GameSlice2Tests.cs`. Evidence levels follow `docs/evscript-spezifikation.md` and `docs/spielkern-1.md`: **[P]** handler pseudocode read (read-only Ghidra export); **[A]** assumption (arguments, labels, mapping); **[N]** name/signature/call list only, with behavior delegated through `IFieldHost.RunVisual`; **[O]** running-original oracle: **still unavailable for every item**.

## 1. Results

- **All 599 host IDs are accounted for**, previously 168 (28%): 597 in `HostCommands.Table`, plus `CMPWK` (19) and `CASE_CANCEL` (38), now **core interpreter commands** (63 instead of 61). No gaps remain; `GameEvHost.Gaps` is retained for future IDs.
- **Evidence for the 597 entries** (IDs / commands in data): **P 173 / 10,241 (75.2%)**, A 69 / 1,719 (12.6%), N 355 / 1,661 (12.2%), out of 13,621 host commands. Slice 1 had P 38 / 5,977 (43.9%). “Implemented” means state-changing (138 IDs), delegated to field/UI and visible with duration in the event log (Field 414, Wait 29), or silent (Audio 16, 903 commands). **N entries are delegation, not reconstructed behavior**; correctness in field/UI remains separate (section 8).
- **Slice 1 corrections:** **523 is `GET_POKE_COUNT2`, counting non-Egg party members, not party size** (section 3). `SXY_EXIT_POS_CHANGE` (507) has no object name (section 6); `TEMOTI_MONSNO` (543) returns zero for Eggs.
- **Bulk run:** All 13,139 scripts, real host, `NullFieldHost`, random answers after repeated confirmation: **zero unknown commands/errors; 13,106 end**, including 263 requiring random answers; **33 remain blocked** (section 7; previously 12,811/328).
- **Story run:** Opening script → **first tutorial battle**, 20/20 runs; then **first Pokémon Center healing visit**, 20/20, four to six zone entries and 13–14 events without errors or hangs.
- **Tests:** 92/92 passed in disposable `work/dotnet-game` (38 EvScript, 28 slice 1, 26 new). The 38 EvScript tests also passed in `work/dotnet-evscript`. Other disposable projects passed: BattleEvents 101, BattleHandlers 101, PokePara 44, MasterData2 23, Text 35, Save 21, SaveWrite 56, Effects 17. `work/dotnet-battleflow` did not compile (concurrent AI tests `IAiHost`/`AiScriptBase`, stale project file); `work/dotnet-battleai` had one failure from the same concurrent work. Neither affects `Xnu.Game`. Unity Test Runner was not run; Editor use was prohibited.

## 2. Structure and changes

**Code provenance:** All C# files were written manually from inspected pseudocode and tested; no machine-translated code is in Git. `Vis("id:NAME …")` lists are ID/name tables from `scripts/evscript_stats.py`, not logic.

| File | Contents |
|---|---|
| New `HostCommandsMore.cs` | State-changing commands: party/Box, Bag, flags/time, message words, movement/objects/warps, trainers, dialog/input |
| New `HostCommandsVisual.cs` | Delegated `Vis` commands (N), shops, camera, Pokémon Center animation, TV values, save requests, `Promote` evidence upgrades after pseudocode inspection |
| New `WorldState.cs` | Session state: bicycle/surf, Pokétch apps, sight trainers, object visibility/position, records, capsule stickers, BP, camera, healing balls, last healing zone; `HostEvent` |
| New `GameSessionWorld.cs` | `GameSession.World`, script party/Box access `GetMon(pos, tray)`, counts, clock → work 0x1A2, time of day |
| New `ShopModel.cs` | `ShopRequest`, `ShopTables` inventory, `Buy`/`Sell` with money/BP/Bag limit |
| New `GameEvHostEvents.cs` | `GameEvHost.Events` log (only with `Record`), message words from labels |
| `HostCommands.cs`, `GameSession.cs`, `GameEvHost.cs`, `GameTypes.cs`, `GameData.cs`, `GameLoop.cs` | Small backward-compatible hooks: `partial`, `InstallMore`, `GameInput.Text`, `GameData.Shops`, `ExecuteCommand` duration/log, defeat handling (section 3) |
| `EvInterpreter.cs`, `EvCmdId.cs`, `EvCommandTable.cs` | Core `CMPWK` (19), `CASE_CANCEL` (38) |

`IFieldHost` is **unchanged** (already implemented by the UI agent's `FieldHostAdapter`); all new requests use `RunVisual(EvCommandCall)`. Field code may consume `Events` (ID, name, arguments, frame duration) instead of individual calls. **Duration** counts invocations until completion, at 30 Hz like `TIME_WAIT`; it arises from waiting on field code, not a duration table. Script `TIME_WAIT` remains in the interpreter. New `GameInput.Text` supports naming: null means no input; confirmation without text keeps the name **[A]**.

## 3. Pokémon Center, healing, defeat (verified correction)

Nurse script (`common_scr`, labels listed only by name): `TEMOTI_BALL_LOAD_WAIT` → `GET_POKE_COUNT2` (523) → loop `POKECEN_PUT_BALL n` (979), sound, `TIME_WAIT 15` until n equals count → four `PC_RECOVER_ANM` (663) with `TIME_WAIT 15` → `POKECEN_CLEAR_BALL` (980) → camera → text → `PC_KAIFUKU` (480).

| ID | Name | Finding (`EvCmdGetPokeCount*`, `EvCmdPokecenPutBall` pseudocode) |
|---|---|---|
| 522 | GET_POKE_COUNT | `Work = playerParty.count`, party size **[P]** |
| **523** | **GET_POKE_COUNT2** | **Iterates party, counts `!IsEgg`**, non-Egg members **[P]**. Slice 1's party-size assumption would place one extra ball for an Egg. |
| 524 | GET_POKE_COUNT3 | Nonempty, not Egg, HP ≠ 0 **[P]**; 525/1213 same count **[A]** |
| 979 | POKECEN_PUT_BALL | nth **non-Egg** member, ball from `GetGetBall`; core stores `World.PokecenterBalls`, field supplies model/placement **[P]** |
| 980, 663 | POKECEN_CLEAR_BALL, PC_RECOVER_ANM | `FieldPokemonCenterEntity.DestroyAllBall` / `PlayHealEffect` **[P]**, field responsibility |
| 480 | PC_KAIFUKU | Heal party and Boxes **[P]**; slice 2 also records `World.LastHealZone` **[A]** |

**Defeat:** New `work/decomp/zenmetu` Ghidra export, two read-only runs under `work/ghidra.lock`, 5-GB heap. `FieldConnector.ZenmetuProc` sets Zenmetsu warp type, **clears partner system flag 2**, removes companion, and places player using `ZenmetuZone` (19 Pokémon Center entries `T02PC0101` … `C11PC0101`, grid 8/6, exit 0, `townMapZoneID`) **[P]**. Select by `zoneID == PlayerWork.transitionZoneID`; `SET_WARP_ID` (478, only three occurrences) sets it through `ZoneChangeSetZenmetu`.

`transitionZoneID` is read by `FieldConnector.SwitchingOperation/PrepareOperation/SetupOperation` and reset to −1 afterward: a transition argument, not persistent state **[P]**. Persistent last Pokémon Center is in the save (`PlayerSaveData.zenmetu`/`ReturnZenmetsu_Ground`, `LOCATION_WORK`); layout **unresolved**. Core therefore substitutes the last `PC_KAIFUKU` zone **[A]**; partner reset is **[P]**. `TRAINER_LOSE*` remain original no-ops as established in slice 1.

## 4. Command groups

IDs from `HostCommands.Table`, data occurrences from `scripts/evscript_stats.py`; grouping by name.

| Group | IDs | Commands | P / A / N IDs | P / A / N commands |
|---|---|---|---|---|
| NPCs, objects, movement, doors, effects | 82 | 3,528 | 42 / 1 / 39 | 3,001 / 203 / 324 |
| Dialog, menu, input | 44 | 2,909 | 11 / 1 / 32 | 2,539 / 5 / 365 |
| Camera | 24 | 1,376 | 8 / 0 / 16 | 1,316 / 0 / 60 |
| Other (helpers, random, map/Gym mechanics) | 41 | 1,179 | 4 / 3 / 34 | 1,068 / 10 / 101 |
| Message words | 37 | 1,142 | 13 / 18 / 6 | 853 / 252 / 37 |
| Audio (silent events) | 16 | 903 | 0 / 16 / 0 | 0 / 903 / 0 |
| Networking, Underground, Union, Contest, Battle Tower, TV, Safari, Nursery, park, companions, horse | 143 | 654 | 0 / 6 / 137 | 0 / 155 / 499 |
| Fades | 9 | 615 | 6 / 0 / 3 | 609 / 0 / 6 |
| Pokémon, party, Pokédex | 86 | 495 | 31 / 11 / 44 | 264 / 74 / 157 |
| Bag, money, shops | 23 | 283 | 12 / 2 / 9 | 204 / 66 / 13 |
| Flags, work, system flags | 17 | 173 | 15 / 2 / 0 | 158 / 15 / 0 |
| Trainers, battle | 20 | 134 | 8 / 4 / 8 | 65 / 13 / 56 |
| Pokémon Center, Box | 13 | 65 | 7 / 0 / 6 | 56 / 0 / 9 |
| Bicycle, surf, hidden moves | 24 | 62 | 8 / 3 / 13 | 17 / 21 / 24 |
| Time, random | 7 | 52 | 4 / 1 / 2 | 49 / 1 / 2 |
| Warp, map, zone | 11 | 51 | 4 / 1 / 6 | 42 / 1 / 8 |
| **Total** | **597** | **13,621** | **173 / 69 / 355** | **10,241 / 1,719 / 1,661** |

### 4.1 Pseudocode-backed, state-changing implementations (selection, all [P])

| Area | IDs (arguments numbered from 1) |
|---|---|
| Party counts/checks | 522–524 counts; 696 `PARTY_MONSNO_CHECK(species, W)`; 1041 `TEMOTI_POKE_CHK_NUM(W, species)` (species 0: duplicates?); 1141 `…GET_POS` (first slot or −1); 543 `TEMOTI_MONSNO(pos, W)` (Egg → 0); 683 `COUNT_MONSBOX_SPACE(W)` (1 = Boxes full) |
| Party/Box access (`GetPokemonParam(tray, pos)`: tray ≥ 0 Box, otherwise party) | 221 `CHK_POKE_WAZA`, 571 `WAZA_COUNT`, 572 `WAZA_DEL` (close gaps), 557/558 friendship (0–255), 654/655 ribbons, 657 total EVs, 717/1197 level, 625 nature, 995 Box species, 994 party/Box species, 1216 all IVs 31, 1230 personality value, 653 total party ribbons, 1172 nickname |
| Message words | 313 move, 315 number (leading zeros or number word), 322 species, 324/325 rival/companion species, 328 nature, 574 party member's move |
| Flags/system flags | 417–420 Pokétch (flag 0xCB, apps), 445 (0x69 + enable Pokédex), 447 (0x4A), 449 set badge, 452, 456, 459, 461/463, 464, 467; 510 → work 0xCD; 840 `LDVAL_VERSION` → work 0xEE; 19 `CMPWK` (work-of-work); 38 `CASE_CANCEL` (work 0xF2 against 0xF8) |
| Time | 658 `CHK_WEEK`, 702 `GET_NOW_HOUR` read **work 0x1A2** (`USE_COMMAND_TIME`): week = value / 10⁸ − 1, hour = (value mod 10⁴) / 100. Core writes from `WorldState.Clock`; middle-part encoding **[A]**. |
| Bag/shops | 195 `CHECK_POCKET`, 215/216 capsule stickers, 747 (item range 0x12A + 16), 612 increment record, 236; shops 912 (zone name), 921 (number), 926 (sell), using `ShopRequest` |
| Movement mode | 293 query bicycle, 1171 mode (1 bicycle, 2 surf), 292 `NAMINORI` (surf on/bicycle off), 302/303 Flash/Defog, 1093 color |
| NPCs/objects | 165 partner object, 505 movement code, 503 position (`set_gridPosition` + Direct), 507 exit position (section 6), 813 player relative position on numeric-keypad grid (7 8 9 / 4 5 6 / 1 2 3; 0 nonadjacent), 549/550 visible/hidden |
| Trainers | 334/276 sight trainers (`EyeTrainerIds`), 338 `TRAINER_TALK_TYPE_GET` (single 0/2/0, otherwise 3/5/6), 337 `TRAINER_MSG_SET` (types 0/3/7 before battle, 2/5/9 after, 6 one Pokémon, 17–19 rematch), 404 capture demonstration (species 399, level 2) |
| Camera | 942 `EVENT_CAMERA_INDEX(index)` = `EventCamera.SetCameraData`; 943 waits for completion flag; duration supplied by field |
| Dialog | 114 `EASY_VOICE_MSG` (like `EASY_MSG` with object frame, no voice), 77 `AB_KEY_TIME_WAIT`, 80 `TALK_OPEN` (work 199 = 1) |
| Other | 734 `GET_RANDOM_HIT(%, W)`, 1186 `SET_TELEPORT_ID`, 914 door transition, 1088 `AUTO_SAVE` (counts requests; UI performs writes) |

Also promoted to [P] after reading their central calls, while effects remain field responsibilities: white fade 281/282; door animation 829/830; gaze/animation speed 981/982/1102/880/881; effects 1052–1054, 1161; pause/position/direction/size/visibility 142–145, 163, 504, 509, 1062, 1191, 1103, 1035, 1192; extras 816–819; 3D waits 487, 973; camera movement 1038/1069/972/814/815; money windows 948/949; bow 1218; move cut-in 304; search calls 1050/1051; 983, 1162, 323, 289.

### 4.2 Assumptions [A] (ID: inferred detail)

Message-word labels: 311 Bag pocket, 319 Pokétch, 327 berries, 656 ribbons, 759 stickers, 970 speaker, 1095/1114 park/Underground items, 1180 types, 1181 Poffins, 1182 clothing. File and `NNN` numbering follow filenames; the call was read. Also 320 trainer-class label; argument order in party queries 217/545/599/626/671/672/762; 219 `ADD_TAMAGO` (level-1 Egg, ball 4); 278/710 naming through `GameInput.Text`; 316 birthday check; 336 double-battle request; 348 `2VS2_BATTLE_CHECK`; 275 sight-trainer type; 670/1055 cartridge (10 = Diamond, supported only by `LDVAL_VERSION`); 722/731/765/1189 world counters; 935 `TELEPORT`; 1105 Underground items; 1145–1147/1211 TV topic values (empty); zone/badge shop mapping (friendship shop), selling for half price, 923 BP shop.

## 5. Shops, naming, menus

- **Shops:** `SHOP_OPEN_FIXED(number)` (921) uses `ShopTables.FixedShop`; `DPR_SHOP_OPEN(zone)` (912) uses friendship-shop inventory filtered by zone and badges ≥ `BadgeNum`; `SHOP_OPEN_BATTLE` uses BP inventory. Price = `ItemRecord.Price` (BP: `BpPrice`) **[A]**. `GameSession.Buy/Sell` check money/BP, Bag limit 999, and stock; half-price sales **[A]**. UI displays `Session.Shop.Items`, calls `Buy/Sell`; `DPR_SHOP_OPEN_WAIT` (913) ends when field reports completion. Seal, flower, weather, boutique, and Pal Park shops are N-level requests only.
- **Naming:** `NAMEIN_POKE(pos, box, W)` applies `GameInput.Text`, writes party/Box, result 1 = changed. Confirmation without text or cancellation leaves it unchanged.
- **Choices:** Unchanged from slice 1 (Yes/No, custom window). `TALKMSG_SP` (71, 31 occurrences) takes file/label from the running script rather than a string argument. Resolution **unresolved**; delegated to UI, opens no text itself.

## 6. Issues discovered by runs and fixed

| Finding | Fix |
|---|---|
| 523 assumed party size (section 3) | Counts non-Eggs [P]; test with Egg |
| Missing `CMPWK` (2,999 repetitions in slice 1 bulk run) | Core work-of-work comparison [P] |
| `SXY_EXIT_POS_CHANGE` (507, 470 occurrences) treated like object-named `SXY_POS_CHANGE`; data has three numbers (exit, x, z) | Dedicated handler: exit → world position; `RunVisual` delegation [P] |
| `TEMOTI_MONSNO` (543) returned species for Eggs | Egg/empty → 0 [P] |
| Species names missing: `ss_monsname` is in `msg_common`, not `msg_german` | Run loads German common messages. **UI note:** `GameDataLoader.Load` only reads `msg_german`, missing `POKEMON_NAME`, `FIRST_POKEMON_NAME`, `RIVAL_POKEMON_NAME`, etc. |
| Defeat partner flag/reset zone handled only through `SET_WARP_ID` | Clear partner [P]; fall back to last healing zone [A] |
| Test `UnknownHostCommandsAreCountedAsGapsAndDoNotBlock` used now-assigned ID 1234 | Find a free host ID; `Assert.Ignore` if none |

## 7. Real-data runs (counts only)

Source: `work/dotnet-game/check`, `dotnet run -c Release -- ../../..`; local save read-only, modified in memory, then verified byte-identical. Data: 856 script files, 12,985 labels, 707 trainers, 119 + 9 German message files, 659 `ZoneID` names.

### 7.1 All 13,139 scripts (mock field host, level-50 party, 4,000 ticks, repeated confirmation, then up to six random-answer runs)

| Metric | Slice 1 | Slice 2 |
|---|---|---|
| Unknown IDs / scripts calling gaps | 406 IDs / many | **0 / 0** |
| Errors | 0 | **0** |
| Ended | 12,811 | **13,106**, including 263 needing random answers |
| Blocked after 4,000 ticks | 328 | **33**: `TALKMSG` 19, `TALK_KEYWAIT` 8, `TIME_WAIT` 4, `YES_NO_WIN` 2 |
| Battles | 370 (210 losses) | 368 (209 losses; five skipped for missing trainer parties) |
| Host calls | 1,307,386 implemented, 78,569 gaps | 1,335,736, zero gaps: P 1,021,343 / A 205,693 / N 108,700 |

The 33 blocked cases begin mid-sequence and cannot finish without predecessor state: healing loops with unset counters (`pcwoman_pc_kaihuku_anim_common_loop*`; same animation completes in story runs), network/Union guides, monument naming requiring actual text, library menu, Move Reminder selection, Hall of Fame ball display. None is a core interpreter error.

### 7.2 Story run (`Story.cs`; 20 random-answer runs, random starter)

Data-derived setup: New Game clears all work/flags, then runs `ev_init_script` (init_scr). Starting zone is opening `D27R0101`: `SP_D27R0101_SCENE` calls rival event when `WK_SCENE_D27R0101 == 0`, ending with `MAP_CHANGE "L01"`. Each entry runs `SP_<ZONE>_INIT`, `_FLAG`, `_SCENE`, then contact fields (`StopData`: `Work == Param`).

Routing uses shortest paths through `MapWarp` interiors and adjacent `ZoneTable` outdoor grid cells, targeting the nearest Pokémon Center (even seeds explicitly target `C01PC0101`), then nurse `PlaceData` label `…pcwoman…`.

| Metric (20 runs) | Result |
|---|---|
| First battle (opening tutorial wild battle, level-2 opponent) | 20/20 |
| Pokémon Center reached, nurse dialog ended, `PC_KAIFUKU` executed | 20/20 |
| Zone entries per run | 4–6: e.g. `D27R0101 > L01 > C02 > C02PC0101`; targeting `C01PC0101`: `… > C02 > R218 > C01 > C01PC0101` |
| Events / ended / blocked / errors / unknown commands | 13–14 / all / 0 / 0 / 0 |
| Executed host IDs | 61 (127 calls) |

**Limits:** Routes are graph searches, not actual gameplay paths. Contact fields did not trigger: initial work values lack prerequisites normally established through omitted conversations. Sight battles, other conversations, positions, and warp-blocking flags are not modeled. This demonstrates traversal of initial-zone/scene scripts, rival event, battle, zone changes, and healing through the host, not matching timing, order, or presentation. **No [O] oracle.**

## 8. Gaps and estimated effort

| Gap | Estimate |
|---|---|
| 355 N-only IDs: Battle Tower, Contest, networking/Union/Underground, Nursery, Safari, park, companions, horse, capsules, TV generation, Gym mechanics, berry plots, honey trees. Inspect pseudocode and implement state per group. | 1–2 days/group; Nursery/berries/honey first; Tower three days |
| Field/UI: `RunVisual` for 414 field and 29 wait IDs; timed event log; shop/party/Bag/Box UI, naming keyboard | 5–8 days (field 3–4, UI 3–4) |
| `WorldState` not mapped to save: Pokétch apps, records, stickers, Underground items, BP, TV, `zenmetu`, Pokédex. Add offsets from `docs/save-spec-entwurf.md` or lose state on save. | 2–3 days |
| Wild generation, encounter-step checks, time/weather (unchanged from slice 1) | 2–3 days |
| `TALKMSG_SP`, `SEACRET_POKE_RETRY_CHECK`, `GROUP_EXIST_CHECK`, `WAZA_ITEM_CHK`/`ITEM_WAZA_NAME` (machine table in `IBattleData`), `GET_TAG_PATNER_ID` | One day |
| Story run with actual conversations/contact fields, positions, warp flags, sight battles | 3–4 days; needs field |
| Dialog/movement/camera oracle [O] | Requires running original |
| Unity Test Runner and new `.meta` files (generated on import) | 15–30 min once Editor available |

## 9. Reproduction

- Tests: `dotnet test work/dotnet-game/Game.csproj`; disposable project compiles Unity sources directly, excluding Unity-dependent `GameUnityTests.cs`.
- Bulk/story: `cd work/dotnet-game/check && dotnet run -c Release -- ../../..` (all), `… -- ../../.. story 20` (20 story seeds), `… -- ../../.. table` (ID/name/evidence/kind).
- Pseudocode: `python3 work/evscript/fn2.py <ID> …` (compact handler, follows calls one level); `python3 work/evscript/listscr.py <file> [label-regex]` (command list).
- Only defeat needed a new Ghidra run: `scripts/ghidra/run_headless.sh … -postScript ExportDecompiled.java 'ZenmetuProc|ZoneChangeSetZenmetu|…' work/decomp/zenmetu`, plus `CallersOf.java`, under `work/ghidra.lock`.
