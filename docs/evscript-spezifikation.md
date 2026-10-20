# Event Scripts (EvData): Commands and Interpreter (Todo `ap-evscript`)

As of 2026-10-19. Names, numbers, and structure only; no game text or data in the repository. Pseudocode is local under `work/decomp/evscript*`
(Ghidra, `-readOnly`); analysis is under `work/evscript/` (not in repository).

**The story order for the opening route is unconfirmed.** Dependent claims are marked **[A]** (assumption).

Continuation: the concrete host for host commands, game loop, and real-data run through the first battle are in `docs/spielkern-1.md` (assembly `Xnu.Game`); all 599 host IDs, `CMPWK` (19), and `CASE_CANCEL` (38) as **core commands** (now 63 instead of 61), the Pokémon Center flow, and story run are in `docs/spielkern-2.md`.

## 1. Summary

- Original format and runtime model (`EvDataManager.UpdateEvdata`, `RunEvCmd`, `CallLabel`, `ReturnEvData`) are understood from pseudocode.
- The `RunEvCmd` jump table (1,234 entries) was read from the ELF and each ID mapped to a handler. Result: **484 IDs have no effect in the original** (return 1 immediately), including 206 IDs used by data (8,739 commands, 13.5%).
- New C# module `Xnu.EvScript` (`unity/Assets/Scripts/EvScript`, pure C#, no UnityEngine): script book, state machine, host interface, variables (memory and `SaveData`). **61 core commands** implemented semantically (65.5% of all 64,741 commands); 599 additional IDs (21.0%) are passed to the host.
- 38 synthetic tests (`unity/Assets/Tests/EditMode/EvScriptTests.cs`), passing outside Unity with `dotnet test` (throwaway project `work/dotnet-evscript`); not yet run in Unity Test Runner (editor was unusable; Unity generates `.meta` files on first import).
- Real-data run (section 6): all 13,139 scripts run with a mock host, with no unknown commands or errors; 8,095 need no host commands at all.

## 2. Format and execution model

### Data
`EvData { Scripts[Label, Commands[Arg[argType, data]]], StrList }` (see `docs/masterdata.md`, section 13). First argument is the ID
(`EvCmdID.NAME`, `argType` 0). Argument types: `Float` 1, `Work` 2, `Flag` 3, `SysFlag` 4, `String` 5. [P]

### Resolving an argument value (`val`)
`Work` → current work value; `Float` → interpret the **bits** of `data` as `float`, then truncate to `int` (`fcvtzs`, toward zero); all other types → 0. Integers are stored as floats in scripts (e.g. 7 = `0x40E00000`). Target arguments (destination Work index, Flag index) are taken **raw** from `data`, without type checking. [P]
A string argument is an index into `StrList` for the file containing the running script; a non-string argument yields `""`. [P]

### Variables (`FlagWork` → `PlayerWork`)
| Kind | Save storage | Size | Notes |
|---|---|---|---|
| Work | `intValues` | 500 × int | `GetInt/SetInt`; out-of-range index → exception |
| Flag | `boolValues` | 4,000 × bool | In flag commands, index −1 or 4000 means “not set”/is ignored |
| System flag | `systemFlags` | 1,000 × bool | indices 0x326–0x329 always return true (`GetSytemFlag`) |
| Trainer win flag | `tr_battleData` | 707 entries | one `ushort` per trainer: low byte win, high byte “still searching” (`TrainerWork.SetWinFlag`/`GetBattleSearcher`) |

In the file's Marshal image, each bool is 4 bytes and each trainer is 8 bytes according to `docs/save-spec-entwurf.md`; `EvSaveVariables` places win at offset 0 and search at offset 4 **[A]**.
Work values with special roles: 199 (`TALK_CLOSE` sets to 0), 0xF2/0xF3 (`FLD_ITEM_EVENT`), 0xF8 (`CASE_CANCEL`). `EvWork.WORK_INDEX` names 441 values (`LOCALWORK0…`, `OBJCHRWORK0…`,
`WK_SCENE_T01…` for per-location scene progress); `INDEX_NUM` names flag ranges (FH 0–63, FE 63–314, FV 314–603, FT 603–859, FV_FLD 859–1115, TMFLG from 1115). [P]

### Execution (`UpdateEvdata`)
- State: event list (loaded `EvData` files, each with `LabelIndex`/`CommandIndex`), current list index (−1 = no event), call stack `EvCallData(List, Label, Command)`. [P]
- Each update: read command, execute `RunEvCmd(ID)`. If handler returns 0, repeat command next frame. If it returns 1, increment `CommandIndex` by 1,
  **unless** command changed list or label (jump, call, return). Then `VariableReset` (sets `_talkStart`, `_procCmd`, `_timeWait`, etc. to 0). [P]
- Loop limit 5,000 commands per frame (`MUGEN_LOOP`); after that the event ends. [P]
- End: `END` (and `NOP`, `SP_EVENT_DATA_END`, `SCENE_CHANGE_END`) sets list index to −1. When `CommandIndex` passes the final command, call `EventEnd()` and clear call stack. [P]
- Labels: global dictionary `_findAllLabel: Label → [ListIndex, ScriptIndex]`. `JUMP` jumps to command 0 of the script; `CALL` pushes `(List, Label, Command+1)` and jumps;
  `RET` restores it. Unknown or empty label is **not an error**; command returns 1 without jumping. `RET` with empty stack follows END path (ends event). [P]
- Comparison strings (`EQ NE GT GE LT LE`): `IFVAL_*` compares two `val` values (`GT`: `a > b`). `IF_JUMP/IF_CALL` and flag macros read `_cmp_flag` (0 less, 1 equal, 2 greater; EQ = 1, NE ≠ 1, GT = 2, GE ≥ 1, LT = 0, LE ≤ 1). [P]
  Aliases in `ReEQType` (`==`, `ON`, `OFF`, etc.) have not been resolved individually **[A]**; only the six abbreviations appear in data.

### Jump table (`RunEvCmd`)
`RunEvCmd(id)`: if `id − 1 ≥ 0x4D2` (i.e. `id ≤ 0` or `id > 1234`, including placeholder −1, 88 occurrences in data), immediately return 1. Otherwise jump through a `ushort` table at `0x3EDAB7C` (Ghidra address).
Analyzed with `llvm-objdump` on `work/elf/main.patched.elf`:

| Cases | Count | Meaning |
|---|---:|---|
| Return 1 without call (`0x2D60154`) | 484 | no effect in original (e.g. `LAST_KEYWAIT`, `AC_*`, `ACMD_END`, `TRAINER_LOSE*`, leftover `BOARD_*`, VM registers 5–18) |
| Same handler | – | `22=28` (CALL), `23=29` (RET), `32=34`, `33=35`, `70=83` (TALKMSG), `81=82`, `1=3` (END), `168=171` (END path), `169=172=173=174` (jump to label), `285=286`, `555=556` |
| Other | 750 | real handler (core command or host) |

`AC_*` commands are therefore not separate commands: they occur as data in movement scripts passed to an object by `OBJ_ANIME` (`EvEntityCommand.SetScriptMoveData`); the interpreter forwards the command list unchanged to the host.

## 3. Evidence levels

- **[P]** Handler pseudocode read (Ghidra `-readOnly`, functions `Dpr_EvScript_EvDataManager$$…`, `FlagWork`, `TrainerWork`, `MoneyWork`).
- **[T]** From jump table only (no call = NoOp; same address = same handler).
- **[N]** Name and argument shape only (`scripts/evscript_stats.py`, handler call list); behavior inferred.
- **[O]** Oracle (running original or emulator): **none available for any command**; all claims about in-game display, duration, and order are unverified.
- **[A]** Assumption.

## 4. Core commands (implemented in interpreter)

Arguments are numbered from 1. `v` = `val` (Work/Float), `W` = destination Work (raw), `L` = string label.

| ID | Name | Count | Level | Effect / arguments |
|---|---|---:|---|---|
| 3, 1, 168, 171 | END, NOP, SP_EVENT_DATA_END, SCENE_CHANGE_END | 7,389 | [P] | End event |
| 24 | JUMP | 5,059 | [P] | `L` |
| 28, 22 | CALL, CHG_COMMON_SCR | 1,404 | [P] | `L`; push stack |
| 29, 23 | RET, CHG_LOCAL_SCR | 1,992 | [P] | pop stack; empty → end event |
| 32, 34 | IFVAL_JUMP, IFWK_JUMP | 3,096 | [P] | `v1, "EQ…", v2, L` |
| 33, 35 | IFVAL_CALL, IFWK_CALL | 1,532 | [P] | as above, with call |
| 36, 37 | SWITCH, CASE_JUMP | 966 | [P] | SWITCH stores Work index; CASE_JUMP `v, L`: jump if `Work[stored] == v` |
| 19 | CMPWK | 1 | [P] | `_cmp_flag` from `Work[v1]` vs. `Work[v2]` (both arguments are treated as Work indices and dereferenced again); 0 less, 1 equal, 2 greater (slice 2) |
| 38 | CASE_CANCEL | 1 | [P], type [A] | Macro: compare `Work[0xF2]` to `Work[0xF8]`; if equal, jump to `L` (assumed comparison type “EQ”; slice 2) |
| 30, 31 | IF_JUMP, IF_CALL | 1 | [P] | `"EQ…", L` against `_cmp_flag` |
| 60, 61, 62 | LDVAL, LDWK, LDWKVAL | 2,958 | [P] | `W = v` |
| 58, 59 | ADD_WK, SUB_WK | 173 | [P] | `Work[a] = Work[a] ± v(b)` |
| 4 | TIME_WAIT | 756 | [P] | `v` frames (÷30 s), `W`: 1 while waiting, then 0 |
| 41, 43, 50 | FLAG_SET, FLAG_RESET, FLAG_SET_WK | 1,937 | [P] | raw Flag or via Work; −1 ignored |
| 42, 873, 874 | ARRIVE_FLAG_SET, SET_SYS_FLAG, RESET_SYS_FLAG | 259 | [P] | raw system flag (even for string argument, `data` is used as index, 12 cases); afterward badge count = sum of flags 0x7C–0x83 |
| 45–48 | IF_FLAGON/OFF_JUMP/CALL | 1,159 | [P] | Flag/System flag, `L`; index −1/4000 counts as “off” |
| 51–53 | TRAINER_FLAG_SET/RESET/CHECK | 149 | [P] | trainer as Float, Work, or `TrainerID` name (String → `ResolveTrainerId`); CHECK sets `_cmp_flag = win && !searching` |
| 54–57 | IF_TR_FLAGON/OFF_JUMP/CALL | 27 | [P] | `_cmp_flag = win`, then jump/call |
| 70, 83 | TALKMSG, TALK_KEYWAIT | 4,842 | [P] | `"file%label"` (split at `%`), optional `v` (== 1 → Flag). Host opens window; command waits until done |
| 81, 82 | TALK_CLOSE, TALK_CLOSE_NO_CLEAR | 2,525 | [P] | `Work[199] = 0`, close window |
| 84, 85 | EASY_OBJ_MSG, EASY_MSG | 544 | [P] | Macro: (TALK_OBJ_START,) TALKMSG, close window, (TALK_OBJ_END); each stage costs one frame |
| 96 | YES_NO_WIN | 265 | [P] | `W`, optional `v` (== 1: “Yes” preselected); result = menu index → `Work[W]`; mapping 0 = Yes is **[A]** |
| 821, 822 | ADD_CUSTUM_WIN_LABEL, OPEN_CUSTUM_WIN | 639 | [P] | Row `"file%label"` with return value `v` (default: running number); OPEN `W`: `Work[W] = return value[selection]` |
| 136, 140 | OBJ_ANIME, OBJ_ANIME_WAIT | 3,587 | [P] | `Object(String or index), Label[, v speed]`; script in same file; WAIT optional object name, empty = all |
| 169, 172–174 | SCENE_/FLAG_/OBJ_/INIT_CHANGE_LABEL | 59 | [P] | jump to `L` |
| 170 | SCENE_CHANGE_DATA | 154 | [P] | `v1, v2, L`: **CALL** if equal |
| 175, 176, 177, 1207 | ADD_GOLD, SUB_GOLD, COMP_GOLD, GET_GOLD | 55 | [P] | `MoneyWork.Add(±v)` (0…999,999); COMP: `W = (v ≤ money)`; GET: `W = money` |
| 189–192 | ADD_ITEM, SUB_ITEM, ADD_ITEM_CHK, ITEM_CHK | 223 | [P] | `Item, Quantity, W`; ADD/SUB write 1; CHK: `W = IsAddItem`; ITEM_CHK: `W = (Quantity ≤ available)` |
| 187 | FLD_ITEM_EVENT | 308 | [P], label [A] | `Work[0xF2] = v1`, `Work[0xF3] = v2`, jump to fixed label constant; only matching data uses `ev_fld_item2` |
| 285, 286 | MAP_CHANGE, MAP_CHANGE_NONE_FADE | 109 | [P] partial | `ZoneName(String), Locator`; same handler. Only setup fields read so far; host waits for map transition to finish |
| 335 | TRAINER_BTL_SET | 131 | [P] | Trainer1 (`TrainerID` name), Trainer2 optional; original saves return position, ends event, resumes there after battle. Interpreter waits for `BattleIsDone` (same effect for host) |
| 555, 556 | GET_RND, GET_RND_NEXT | 81 | [P] | `W = Random.Range(0, v)` |

## 5. Important host commands (selection of most frequent; 599 IDs total)

These commands go to `IEvHost.ExecuteCommand(call)` (`true` = finished; otherwise repeat with incremented `Phase`). Level [N], except where [P] is shown (handler call list read, behavior inferred from it).

| ID | Name | Count | Level | Expected host behavior |
|---|---|---:|---|---|
| 153, 156, 157 | TALK_OBJ_END, TALK_END, EVENT_END | 2,276 | [P] | `Cmd_ObjPauseClearAll`: resume objects (`MVCodeRestart`), enable input |
| 151, 152, 154 | TALK_OBJ_START(_TURN_NOT), TALK_START | 697 | [P] | turn player and conversation partner toward each other (neck), pause all objects, selection sound |
| 155 | EVENT_START | 396 | [P] | hide Pokétch, pause objects |
| 942, 943 | EVENT_CAMERA_INDEX, EVENT_CAMERA_END_WAIT | 1,127 | [N] | event camera (`EventCameraTable`); `943` waits for end |
| 507, 503, 506, 505 | SXY_EXIT_POS_CHANGE, SXY_POS_CHANGE, SXY_DIR_CHANGE, SXY_MV_CHANGE | 937 | [P] | set object (name) to grid position/direction (`gridPositionDirect`, `SetYawAngleDirect`) |
| 146, 147 | OBJ_ADD, OBJ_DEL | 606 | [P] | show/hide object (name/index); DEL also sets a flag |
| 1062 | OBJ_POS_CHANGE_WORLD | 150 | [N] | move object to world position |
| 158, 159, 161, 813 | PLAYER_POS_GET, OBJ_POS_GET, PLAYER_DIR_GET, GET_REL_POS_HERO | 233 | [P] | grid position → two Work values |
| 283, 284, 784, 836 | BLACK_OUT, BLACK_IN, FADE_WAIT, FADE_SPEED | 584 | [P] | fade to/from black (`Fader.FadeOut/FadeIn`); FADE_WAIT waits |
| 306, 307, 308, 310, 314, 318 | PLAYER_NAME, RIVAL_NAME, SUPPORT_NAME, ITEM_NAME, NUMBER_NAME, NICK_NAME | 898 | [P] | set placeholder word `slot` for next text (`MessageWordSetHelper`) |
| 479, 448 | GET_MY_SEX, SYS_FLAG_BADGE_GET | 152 | [P]/[N] | Work value from player data/system flag |
| 92, 93 | EASY_BOARD_MSG, EASY_INFOBOARD_MSG | 181 | [N] | sign/information-board text |
| 109, 111, 112–116, 118… | SE_*, ME_*, VOICE_*, BGM_* | 963 | [N] | **Audio is not implemented** (no-sound rule); host immediately returns `true` |
| 829, 830, 831 | HIT_DOOR_ANIME(_WAIT), SET_DOOR_OBJ | 213 | [N] | door animation |
| 981, 982, 1102, 1143, 881, 880 | CHARA_LOOK_*, OBJ_ANIME_SPEED, SET_FORCE_BLINK, AC_ANIM_* | 497 | [N] | object facing/speed/animation |
| 1052, 1053, 1054, 1161 | CALL_EFFECT, STOP_EFFECT, RELEASE_EFFECT, EFF_SCALE | 326 | [N] | effects (`EffectDatabase`) |
| 563, 216, 194 | TEMOTI_POKE_CHK, CB_ITEM_NUM_ADD, GET_POCKET_NO | 139 | [N] | party/bag queries with Work result |

Family summary of all 599 used host IDs (IDs / commands): objects, movement, doors 65 / 6,916; camera 15 / 1,319; audio 16 / 963; name words 51 / 829; fades 9 / 615;
menus, windows, signs 42 / 539; Pokémon, party, PC, Pokédex 99 / 548; effects 5 / 330; battle, trainers 46 / 262; bag 22 / 157; map, zones, traversal 34 / 139;
Underground, Union, network, contest, TV 23 / 124; other 172 / 882.

## 6. Counts (real data, counters only)

Source: `scripts/evscript_stats.py` (command frequency) and local run `work/dotnet-evscript/check` (`dotnet run`).

| Measurement | Value |
|---|---|
| Files / scripts / commands (excluding 4 empty files) | 856 / 13,139 / 64,741 |
| Distinct IDs in data | 866 (+ placeholder −1) |
| Core / no-op / host IDs | 61 / 206 / 599 |
| Commands: core / no-op (including 88 × −1) / host | 42,379 (65.5%) / 8,739 (13.5%) / 13,623 (21.0%) |
| Scripts with no host command (static) | 8,095 of 13,139 (61.6%) |
| Labels / duplicate labels | 12,985 / 154 |
| Most frequent 10 IDs cover | 46.8% of commands (END, JUMP, TALKMSG, IFVAL_JUMP, LDVAL, TALK_CLOSE, OBJ_ANIME, RET, ACMD_END, TALK_KEYWAIT) |
| Mock-host run (all variables 0; every host query answers “not yet” once): completed | 12,778 |
| Still waiting after 2,000 updates (dialog loops with constant mock responses: TALKMSG, TIME_WAIT, camera, menus) | 361 |
| Errors / unknown commands | 0 / 0 |
| Scripts with at least one missing jump target (despite all files loaded) | 54 (59 locations); original ignores them too |
| Commands executed in run | 1,713,776 (core 1,174,715, no-op 152,438, host 386,623); all 61 of 61 used core IDs executed |

“Runs without unknown command” means every ID is core, no-op (table), or delegated to host. It says nothing about whether the host correctly handles the 599 delegated commands.

## 7. C# structure (`Xnu.EvScript`)

| File | Contents |
|---|---|
| `EvCmdId.cs` | IDs for core commands, special Work indices |
| `EvCommandTable.cs` | classify as `Core / NoOp / Host` (NoOp set from jump table), `Classify(id)` |
| `EvScriptBook.cs` | loaded `EventScriptFile`s (from `Xnu.Data.MasterData2Reader.LoadEventScripts`), global label dictionary (case-insensitive, first file wins **[A]**) |
| `EvInterpreter.cs` | state machine: `Start(label)`, `Update(dt)` → `Idle/Waiting/Ended/Error`, `Abort()`, statistics (`EvRunStats`) |
| `IEvHost.cs` | host: text, choices, battle, map changes, object movement, bag/money, helpers, generic `ExecuteCommand`, `EventEnded` |
| `EvVariables.cs` | `IEvVariables`; `EvMemoryVariables` (tests) and `EvSaveVariables` (reads/writes `SaveData.Buffer`) |
| `EvMockHost.cs` | host without game world (for tests and batch runs) |

Intentional differences from original: errors (missing argument, out-of-range index) produce `EvStatus.Error` instead of throwing; `TRAINER_BTL_SET` does not end the event but waits (host starts the battle and
signals completion); `MAP_CHANGE` waits similarly. If state must survive a scene change, keep the interpreter in memory (position and stack are stored there).

## 8. Assumptions

- **[A] Story order of opening route:** unconfirmed. Route scripts (map IDs `t01*`, `d27*`, `sp_*`, scene Work `WK_SCENE_T01R0101…`) were not run in sequence; which scripts run at startup
  (`SCENE_CHANGE_LABEL`, `INIT_CHANGE_LABEL` per map) and in what order Work values are created is unverified.
- **[A]** Yes/No menu selection index: 0 = “Yes”. Callbacks (`DisplayClass460/461`) write menu index unchanged to Work.
- **[A]** `FLD_ITEM_EVENT` jumps to `ev_fld_item2` (label constant unresolved).
- **[A]** Duplicate labels, case sensitivity, comparison-type aliases, trainer layout in save (section 2).
- **[A]** Trainer names (`TrainerID` enum, 709 values in dump) correspond to string arguments (`LEADER3_01`, etc.): original search compares enum name; `ResolveTrainerId` must provide this table (source `dump.cs`, not in repository).
- Original quirks: `TALKMSG` name without `%` (43 + 21 + 14 + 2 cases) would fail during splitting in original; interpreter uses whole string as filename and label `""`.
  `FLAG_CHECK_WK` (49, unused) is inverted (1 = flag not set).

## 9. Gaps and effort

| Gap | Estimate |
|---|---|
| Host for opening route through first battle: text (`Xnu.Text`), objects, map changes, camera, fades, name words, grid movement from `AC_*` | 3–5 days (largest item: field/text integration) |
| Check remaining 599 host IDs (read pseudocode effects per family; Ghidra export exists for all `EvCmd*`) | 2–3 days per major family; first 60 IDs cover 77% of host commands |
| Battle: trainer ID from name, `BattleTrainer` setup (sight-battle groups, `Btl_TrainerType1/2`), return after loss (`TRAINER_LOSE*` is no-op in original; loss flow is through `BattleReturn`) | 2 days |
| `MAP_CHANGE` details (pseudocode read only through setting fields), zone/locator resolution with `MapWarp` | 1 day |
| Startup logic: which label the game starts (`PlaceData.TalkLabel`, `StopData.ContactLabel`, `MapWarp.ScriptLabel`, `ScriptStartCheck`, `SpLabel_*`, `CheckSceneChangeLabel`) | 2–3 days |
| Oracle [O] for dialog/movement flows (timing, frame accuracy) | impossible without running original |
| Multi-trainer (`TRAINER_MULTI_BTL_SET`), bag variants (`ADD_GOODS`, etc.), shops, Underground, Union, contest | later, not needed for opening route |
| Unity Runner test, `.meta` files | 15 minutes once editor is available |

## 10. Reproduction

- Statistics: `python3 scripts/evscript_stats.py 70` (writes `work/evscript/stats.json`).
- Pseudocode: `ExportDecompiled.java` (regex `^Dpr_EvScript_EvDataManager\$\$`, etc.) and `DecompAt.java` for jump-table cases (Ghidra `-readOnly`, `-noanalysis`, heap ≤ 6 GB, lock `work/ghidra.lock`).
- Jump table: `llvm-objdump -d` on `work/elf/main.patched.elf`, range `0x2C5B290–0x2C60250`; table `0x3DDAB7C` (file offset from program headers).
- Tests: `dotnet test work/dotnet-evscript/EvScript.csproj` (throwaway project, not in repository; copy against Unity sources: `UnityCheck.csproj`).
- Real-data run: `cd work/dotnet-evscript/check && dotnet run`.
