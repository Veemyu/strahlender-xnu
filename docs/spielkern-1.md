# Game core: game loop, event host, battle and encounter integration (`ap-game-flow`)

Historical Unity-rebuild report, 2026-10-19; the rebuild is deprecated. Names, counts, and structure only; no game text, data, or real saves in Git. Code: `unity/Assets/Scripts/Game` (`Xnu.Game`, pure C#, `noEngineReferences`); tests: `unity/Assets/Tests/EditMode/GameFlowTests.cs` and `GameFixture.cs`. Evidence levels follow `docs/evscript-spezifikation.md`: **[P]** handler pseudocode inspected; **[A]** assumption from name, argument shape, or partial findings; **[N]** name and call list only; **[O]** running-original oracle: **unavailable for all items**.

**Continuation/corrections: `docs/spielkern-2.md`** accounts for all 599 host IDs. Command 523 is `GET_POKE_COUNT2`: non-Egg party members, not party size (its section 3).

## 1. Results

- Modules form a **working headless core**: `GameSession` (save and variables in `SaveData`) → `GameEvHost` (concrete `IEvHost`) → `GameLoop` (`Field/Event/Battle/Menu` state machine) → `BattleSession` (`BattleFlow`) and `IFieldHost` (field interface). Input and field signals are plain `GameInput`/`FieldSignal` data.
- **Host commands:** **168 of 599 IDs** (28%) implemented, covering **11,537 of 13,623 commands** (**84.7%**). Evidence: **38 P IDs**, 5,977 commands (43.9%); 31 A, 2,068 (15.2%); 99 N, 3,492 (25.6%). State changes: 30 IDs; field/UI delegation: 117; input/field waits: five; **16 deliberately silent audio IDs**, 903 commands, following the then-current no-sound rule. Plus 61 core interpreter commands (`docs/evscript-spezifikation.md`); 431 host IDs remain gaps (section 8).
- **Real-data run** (section 6): Opening event (`d27r0101`, `ev_d27r0101_rival`), mock input, real script book/messages/master data reaches **first battle** in 233 ticks, 15 windows, starter selection, `ADD_POKEMON`, `FIRST_BTL_SET`. Battle wins in two turns; event ends without error. All 13,139 scripts run with the real host without errors: 12,811 end, 328 loop under mocks.
- 28 new synthetic scenario tests plus 38 EvScript tests: **66/66 passed** in disposable `work/dotnet-game`. **Not run** in Unity Test Runner (Editor prohibited); Unity generates `.meta` on first import.

## 2. Architecture

```
Field layer (Unity)         Game core (Xnu.Game, no UnityEngine)                  Existing modules
 FieldSignal  ───────────►  GameLoop ──► EvInterpreter ──► GameEvHost ──► GameSession ──► SaveData / EvSaveVariables
 GameInput    ───────────►     │                              │  │             │
 IFieldHost  ◄───────────────  │                              │  └► DialogModel/ChoiceModel (Xnu.Text: MessageBank, MessageComposer)
                               └──► BattleSession ──► BattleEngine (Xnu.Battle.Flow) ──► PokemonParam (Xnu.PokePara)
```

| File | Contents |
|---|---|
| `GameTypes.cs` | `GameState`, `GameInput`, `FieldSignal`, `EncounterKind`, `BattleRequest` |
| `GameData.cs` | `IGameData/GameData`: `IBattleData`, `MessageBank`, trainers, encounter tables, `TrainerID/ZoneID` name resolution from local `dump.cs` |
| `GameSession.cs` | Save, event variables, Bag limit 999, money 0…999,999, party, healing, new Pokémon, badge count, session RNG |
| `GameEvHost.cs`, `HostCommands.cs` | `IEvHost`; command table with evidence/kind; unknown IDs increment `Gaps` and complete immediately |
| `DialogModels.cs` | `DialogModel` pages from `ComposedMessage`, confirmation to advance; `ChoiceModel` Yes/No/custom windows |
| `IFieldHost.cs` | Field interface; immediate/logging `NullFieldHost` for tests/local runs |
| `BattleSession.cs` | Builds `BattleSetup` from save party, trainer/wild opponents, Bag, badges, money; accepts command data; writes party/Bag/money back |
| `EncounterService.cs` | Wild encounters from `FieldEncountTable` (section 5) |
| `GameLoop.cs` | State machine; `AutoPlayer` confirms text, selects choices/starter, uses first viable move |

### State machine

| State | Tick behavior | Transitions |
|---|---|---|
| `Field` | `Talk/Contact` signal → `StartEvent(label)`; `Warp` → `IFieldHost.ChangeZone`; `Step` rolls encounter table; Menu button opens menu | `Event`, `Battle`, `Menu` |
| `Event` | `GameEvHost.FeedInput` to open windows, then `EvInterpreter.Update`; battle requests (`TRAINER_BTL_SET`, `WILD_BTL_SET`, `FIRST_BTL_SET`, `SP_WILD_BTL_SET`) pause script | `Battle`; end/error → `Field` |
| `Battle` | `BattleSession.Step`: player command/replacement from `GameInput`; completion writes results and prize/penalty | Win/escape → requesting `Event` or `Field`; **loss → recovery** |
| `Menu` | Cancel/Menu closes | `Field`; contents unimplemented |

As in the original, interpreter execution pauses during battle (`TRAINER_BTL_SET` waits in `BattleIsDone`), then resumes at the next command.

- **Input as data:** Buttons mean “just pressed” per tick. A newly opened window does not consume its opening button; input is distributed before interpreter execution. Battle: `GameInput.Battle` (`BattleCommand`) in `AwaitCommands`, `Replacement` party index in `AwaitReplacement`; `StarterChoice` 0–2.
- **Dialog:** `TALKMSG/TALK_KEYWAIT/EASY_*_MSG` → `MessageBank.TryGetLabel(file, label, language)` → `MessageComposer` with configured message words → pages. `ScrollPage`/end delimit pages; `NewLine/ScrollLine` stay on-page; `Wait` events ignored **[A]**. Missing label opens empty window and increments `MissingLabel`.
- **Yes/No:** Index 0 = Yes **[A]**; cancel = No **[A]**. Custom window returns cursor value via `ADD_CUSTUM_WIN_LABEL`; cancel selects final row **[A]**.
- **Map changes:** `MAP_CHANGE(zoneName, locator)` → `IGameData.ResolveZoneName` → `IFieldHost.ChangeZone`; script waits for `ChangeZoneIsDone()`. Tracks `BeforeZoneId`; unknown names retain zone but still execute transition.

## 3. Interfaces

- Field implements `IFieldHost`: `ChangeZone/ChangeZoneIsDone`, `SetEventMode`, `TurnToTalkPartner`, `SetObjectVisible`, `SetObjectGrid`, `GetPlayerGrid`, `Fade/FadeIsDone`, `AnimateObject/AnimationsDone` (`AC_*` movement scripts in the same `EvData` file), plus `RunVisual(EvCommandCall)` for camera/effects/doors/shops/lists/saving. It may write result work through the call.
- `IGameData`: Master data and name resolution. Real tables use `MasterDataReader/MasterData2Reader`; example `work/dotnet-game/check/Program.cs`.
- Inputs: `GameLoop.Tick(dt, GameInput, FieldSignal?)`, `StartEvent(label)`. Outputs: `GameLoop.State`, display `Host.Dialog/Host.Choice`, battle display `Battle.Engine.Log`, counters, `Trace`.
- Naming collision: `Xnu.Game.GameInput` snapshot versus `Xnu.Input.GameInput` input MonoBehaviour. Consumers importing both must qualify or rename the data type; recommendation for field integration: `GameInputFrame`.

## 4. Evidence for host commands

Full table: `HostCommands.Table` (ID/name/evidence/kind). Newly inspected pseudocode from `work/decomp/evscript2`, helper `work/evscript/fn.py`, **[P]**:

| ID | Name | Finding |
|---|---|---|
| 479 | GET_MY_SEX | `Work[arg1] = playerStatus.sex ^ 1` (byte +0x10). Save `SexRaw` holds it; 0/1 ↔ gender unresolved. |
| 448, 450 | SYS_FLAG_BADGE_GET/COUNT | GET: `Work[arg2] = Systemflag[arg1]`; COUNT sums 0x7C…0x83. **Real-save confirmation:** eight set flags = eight badges. |
| 290 | GET_NOW_ZONE_ID | `Work = PlayerWork.zoneID` |
| 554 | GET_TIME_ZONE | `Work = GameManager.currentPeriodOfDay`; numeric mapping **[A]**, clock supplied by field |
| 522 | GET_POKE_COUNT | `Work = playerParty.count`, party size |
| 563 | TEMOTI_POKE_CHK | `Work[arg1] = 1` if a nonempty, non-Egg party member has species `arg2`, otherwise zero |
| 326 | FIRST_POKE_NO_GET | `Work = PlayerWork.defaultPokeNo`, starter species; save offset unknown, so session value |
| 194 | GET_POCKET_NO | `Work[arg2]` receives item pocket (item parameter 0xE), `ItemRecord.FieldPocket` **[A: field mapping]** |
| 480 | PC_KAIFUKU | `playerParty.RecoverAll()`, `BoxPokemonWork.RecoverAll()`: full HP/PP, clear status, party and Boxes |
| 218 | ADD_POKEMON | `InitialSpec{monsno = arg1, level = arg2, talentVNum = arg5}`, nonzero item arg3, `SetFromCapture`, `playerParty.AddMember`, `Work[arg4] = result & 1`, caught Pokédex entry, Pokétch history. Generation randomness **[A]**, section 5. |
| 401, 403 | WILD_BTL_SET, FIRST_BTL_SET | `SetBattleReturn`, then `FieldManager.EventWildBattle(arg1 = species, arg2 = level, …)`; FIRST also sets battle flag 0x100 and tutorial effects |
| 402 | SP_WILD_BTL_SET | Header read: arg1 species, arg2 level; remaining arguments including rare flag not evaluated |
| 478 | SET_WARP_ID | `FieldManager.ZoneChangeSetZenmetu(zone)`: **post-defeat recovery zone** (“Zenmetsu” = wipeout), set by Pokémon Center scripts |
| 259 | FIRST_POKE_SELECT_PROC | Starts `Demo_Gosanke`, returns zero until callback sets state 2. Starter species 387/390/393 derived from script branches **[A]**; original `FIRST_POKE_SELECT_SET_AND_DEL` (260), `SET_MAP_PROC` (230) are no-ops. |
| 453, 454, 455 | SYS_FLAG_PAIR_GET/SET/RESET | System flag 2; companion-following meaning inferred only from name/`NPCToPartner`. RESET also calls field `FieldWalkingManager.NPCToPartner(…, false)`. |
| 306, 307 | PLAYER_NAME, RIVAL_NAME | `MessageWordSetHelper.SetPlayerNickNameWord/SetRivalNickNameWord(slot = arg1)`; save `PlayerName/RivalName` |
| 310, 314 | ITEM_NAME, NUMBER_NAME | `SetItemWord(slot, item, x)` (third value unresolved/ignored), `SetDigitWord(slot, number)`; `ss_itemname`, label `ITEMNAME_nnn`, index = item ID (`docs/masterdata.md`) |
| 155, 154, 151, 152, 153, 156, 157 | EVENT_START, TALK_START, TALK_OBJ_START(_TURN_NOT), TALK_OBJ_END, TALK_END, EVENT_END | Per EvScript spec [P]: stop/resume objects, lock/unlock input, face conversation partner |
| 146, 147, 158, 161, 283, 284, 836, 784 | OBJ_ADD/DEL, PLAYER_POS/DIR_GET, BLACK_OUT/IN, FADE_SPEED/WAIT | Spec [P]; movement 503/506/507 and `WHITE_*` arguments **[A]** |

Other findings, not implemented at this stage: `CMPWK` (19) belongs in core, not host table: it writes interpreter `_cmp_flag` (a<b → 0, equal → 1, otherwise 2), one data occurrence. `TALK_OPEN` (80) sets `Work[199] = 1` only when line state and both texts are set (original window parameters). `TRAINER_MSG_SET` (337) opens `GetTrainerMsg(trainer, type)`. `ZENKOKU_ZUKAN_FLAG` (651): mode 1 = `ZukanWork.ZenkokuON`; mode 2 reads state; implemented as session state **[A]**.

Delegated **[N]** (`HostKind.Field`, `RunVisual`): camera (`EVENT_CAMERA_INDEX/…`), effects, doors, gaze/blinking/animation speed, extras (`DUMMY_*`), object pause/scale/position, shops (`DPR_SHOP_*`, `SHOP_OPEN_*`), lists/Bag/Box/Hall of Fame UI, saving, healing animation, sight-trainer movement, bicycle. UI writes result work; original behavior unread. Signs (`EASY_BOARD_MSG/EASY_INFOBOARD_MSG`) open text and await confirmation **[N]**; `AB_KEYWAIT` waits for confirm/cancel.

Interpreter never dispatches original no-ops 149 `VANISH_DUMMY_OBJ_DEL`, 825–828 `EVENT_CAMERA_MODE/…` to host. `EveryCatalogEntryIsAHostCommandOfTheInterpreter` ensures every table entry is actually classified as host; it found these five mistaken entries.

## 5. Encounters, battle, defeat

- **Trainer battle** (`TRAINER_BTL_SET`): Name → `TrainerID` → `TrainerRecord` → `PokemonFactory.FromTrainerPokemon` party; prize from `TrainerData.Gold` ([P], `docs/kampf-spezifikation-5.md`: `(Gold & 0xFF) × final level × 4`). Missing-party requests are skipped (`BattlesSkipped`) to avoid blocking. Scripts set `TRAINER_FLAG_SET`; original additional post-battle flag handling was not read.
- **Scripted wild battle:** Species/level from arguments; `PokemonFactory.CreateWild` generates nature/stats/ability/gender **[A]**. Original `Pml.PokePara.InitialSpec`/`EncountTools` generation not decompiled.
- **Field wild encounter** (`FieldSignal.Step`): `EncounterService.Roll` uses verified `FieldEncountTable` zone/rate (`encRate_*`)/slots. **Assumed [A]:** Step test `Random(100) < rate` and slot weights (grass 20/20/10/10/10/10/5/5/4/4/1/1; water/fishing from earlier games). Public `EncounterService.*Weights` can be replaced after reading `Encount`. Time/weather/multiple lists (`Day`, `Night`, `Swarm`, GBA, `FormProb`) remain **gaps**.
- **Post-defeat recovery:** `EvInterpreter.Abort`, money deduction (`CalcPenaltyMoney` [P], table [A], battle spec 5), heal party/Boxes, warp to `SET_WARP_ID` zone (`Session.WipeoutZone`; −1 stays), state `Field`. Exact original recovery selection and Pokémon Center dialog are supported only by command names/call site **[A]**.
- **Healing:** `PC_KAIFUKU` [P], section 4. Nurse ball animation/dialog are in scripts and delegated `POKECEN_*/PC_RECOVER_ANM`.

## 6. Verification

**28 synthetic `GameFlowTests`**, invented species/text/trainers from `BattleFlowTestData/GameFixture`, empty save: dialog pages/confirmation; name/item/number words; Yes/No/custom choice; work/flags/system flags/Bag/money persist through `ToBytes` and reload; limits 999/999,999; `ADD_POKEMON`, full party, `PC_KAIFUKU`, `GET_MY_SEX`; event trainer battle/prize/resumption; experience persistence; defeat deduction/healing/warp/abort; missing trainer; starter/`FIRST_BTL_SET`; `WILD_BTL_SET`; waiting `MAP_CHANGE`; event frame/objects/fade/silent audio; gaps; Talk/Warp signals; grass table encounter; zero rate/missing table; slot weights; menu; reject event start during battle; catalog consistency.

**Local run** (`work/dotnet-game/check`, counts only; save read-only, memory edits, then verified byte-identical):

| Metric | Result |
|---|---|
| Data | 856 script files, 12,985 labels, 707 trainers, 183 encounter zones, 119 German message files, 709 TrainerID/659 ZoneID names |
| Real-save variables | Flags 4000/4000 ∈ {0,1}, 573 set; system flags 1000/1000 ∈ {0,1}, 411 set; eight badges. Trainer field 0: 707/707 ∈ {0,1}, 324 set; field 1: 707/707 zero. Four-byte flag stride **verified**; trainer win/search layout (four bytes each) **[A]**, consistent but search never set. |
| A1 opening `ev_d27r0101_rival` | First battle after 233 ticks (≈ 7.8 s at 30 Hz), 130 commands (86 core, 39 host, five no-op), 15 text windows; party 0 → 1, starter = choice 1 |
| A2 battle | Tutorial wild battle: species 396 level 2 versus level-5 starter |
| A3 battle end | Victory after two turns/ticks; returns to `Event` |
| A4 event end | 51 more ticks; `Ended`, no error, 21 field calls, **one gap**, 324 `RIVAL_POKEMON_NAME` |
| B all 13,139 scripts (level-50 party, mock input, 4000 ticks) | 12,811 ended; 328 waiting: 822 `OPEN_CUSTUM_WIN` ×126, 70 `TALKMSG` ×122, 83 ×40, 4 `TIME_WAIT` ×37, 96 `YES_NO_WIN` ×3 (menu/dialog loops under repeated confirmation); **zero errors** |
| B battles | 370 ended, 210 test-party losses, five skipped for missing trainer party |
| B host calls | 1,307,386 implemented (168 IDs), 78,569 gaps (406 IDs): 94.3% of calls weighted by loop repetition; static coverage 84.7% |
| Frequent gaps (ID × calls) | 527 `UG_SHOP_MENU_INIT` 22,551; 892 `CON_WAIT_CONTEST_MENU` 12,043; 995 `TEMOTI_BOX_MONSNO` 12,003; 1144 4,000; 711/710 `MONUMENT_NAME` ≈ 3,300 each; 19 `CMPWK` 2,999; 1061 1,747; 334 `TRAINER_ID_GET` 1,726 |

“Runs without error” means every ID is core/no-op/implemented/countable gap and no script crashes. It **does not** establish original ordering, duration, or presentation: **no [O] oracle**. Opening ran with `NullFieldHost`, so movement/camera/animation were not checked.

## 7. Evidence overview

| Area | Level |
|---|---|
| Core interpreter and save work/flags/system flags | [P]; flag/system-flag layout confirmed in real save |
| 38 host IDs, section 4 | [P] |
| 31 host IDs: partial findings, argument order, audio | [A] |
| 99 delegated/sign/wait IDs | [N] |
| Battle integration, prize, defeat deduction | Formulas [P], table [A] |
| Encounter rates/slots | Data verified; step check/weights [A] |
| Wild stats/nature/gender generation | [A] |
| Dialog pages, Yes/No mapping | [A] |
| Timing/frame behavior | Missing [O] |

## 8. Gaps and estimated effort

| Gap | Estimate |
|---|---|
| `IFieldHost` for `Xnu.Field`: `MapWarp`, `PlaceData` objects, `AC_*` movement, camera/fade; talk/contact/sight signals | 4–6 days |
| Start-label rules: `PlaceData.TalkLabel`, `StopData.ContactLabel`, `MapWarp.ScriptLabel`, per-map `SCENE_CHANGE_LABEL/INIT_CHANGE_LABEL`, scene work | 2–3 days |
| UI: text/menu/shops (delegated only), party/Bag, empty `Menu`, saving | 5–8 days |
| Remaining 431 host IDs: pseudocode per group (99 Pokémon/party/PC/Pokédex, Tower, Contest, Underground, TV, words 311–322) | 2–3 days per major group |
| Wild/encounter `Encount/EncountTools/InitialSpec`: steps, weights, time/weather/swarms, random form | 2–3 days; Ghidra `Dpr.Encount.*` |
| Trainers: sight groups/fields, `TRAINER_MULTI_BTL_SET`, post-battle win flag, rematches | 3–4 days |
| Original defeat dialog/Center/destination and penalty table | 1–2 days |
| Core `CMPWK/CMPVAL`, `TALK_OPEN`, `TRAINER_MSG_SET`, `TRAINER_ID_GET` | One day |
| Enemy AI (battle spec 5), capture, learning, battle evolution | As in that specification |
| Dialog/movement oracle [O] | Requires running original |
| Unity Runner, `.meta`, `GameInput` rename | 15–30 minutes |

## 9. Reproduction

- Tests: `dotnet test work/dotnet-game/Game.csproj`; disposable non-repository NUnit project compiles Unity sources directly.
- Real data: `cd work/dotnet-game/check && dotnet run -c Release -- ../../..`; reads `work/masterdata`, `work/il2cpp/dump.cs`, local save; writes nothing.
- Pseudocode: `python3 work/evscript/fn.py EvCmdName …` (`work/decomp/evscript2` exports), `bash work/evscript/show.sh <ID>` (handler). No new Ghidra run required.
