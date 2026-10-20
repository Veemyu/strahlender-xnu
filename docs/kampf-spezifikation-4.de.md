# Battle Flow, Slice 4: Specification

> **Historical report:** This document describes the deprecated Unity rebuild. It is retained as project history; the native static recompilation is the current product.

Status: Slice 4 interim report (a headless, runnable 1-v-1 battle, wild and trainer, pure C# logic without UnityEngine, rendering, or audio). Continuation: `docs/kampf-spezifikation-5.md` (handler effects, side/field effects, prize money; gaps 1–3 and 5 below were partly closed there).
Implementation (`unity/Assets/Scripts/BattleFlow`, assembly `Xnu.Battle.Flow`) builds on Slice 1 (calculators, `Xnu.Battle`), Slices 2/3 (event system and handlers, `Xnu.Battle.Events`), and the Pokémon model (`Xnu.PokePara`). Evidence conventions, addresses (Ghidra address = Il2CppDumper RVA + 0x100000), and verification levels **[O]**, **[OK]**, **[P]** follow section 0 of `docs/kampf-spezifikation-2.md`.

## 1. Results

| | |
|---|---|
| Playable scope | Single wild and trainer battles: setup from `PokemonParam` teams; move/item/switch/run commands as data; turns proceed until `Finished` |
| New oracle cases (real ARM64 functions) | 5,900 cases in `Fixtures/BattleFlow.json` (2.7 MB, numbers only), across 8 groups (section 9) |
| New tests | 40 (10 oracle comparisons, 30 flow tests); together with 101 existing battle tests, 141 passing in .NET project `work/dotnet-battleflow`; plus one local test using real game data (60 real trainer teams simulated) |
| Existing code changed | None (`Xnu.Battle`, `Xnu.Battle.Events`, `Xnu.PokePara`, `Xnu.Data` unchanged); `Xnu.Tests.EditMode.asmdef` only gains a reference to `Xnu.Battle.Flow` |

## 2. State machine overview

```
Setup (BattleSetup) ──Start()──> AwaitCommands ──Submit(player command[, opponent command])──> Turn
                                      ^                                                    │
                                      │                       ┌────────────────────────────┤
                                      │                       v                            v
                              SubmitReplacement()       Finished (Win/Lose/Draw/Run)  AwaitReplacement
                                      ^                                                    │
                                      └────────────────────────────────────────────────────┘
```

Turn flow (mirrors `Section_Root_ProcessActions.Execute @0x22c9a10`) [P, structure from pseudocode; details below]:

1. **TurnStart** (`Section_TurnStart.Execute @0x2274fa0`): wake all sleeping factors (`WakeAllFactors`), validate event-variable stack, reset Pokémon special priorities to 1.
2. **Collect actions** (`Section_StoreActions`): one action per side; container order is player first, opponent second.
3. **Sort, set special priorities, sort again** (`sortPokeActionOrder`, `setSpActPriority`, `sortPokeActionOrder`): each sort recalculates all keys and draws a random value for each tie (section 3). A tie therefore consumes **two draws**.
4. **Execute actions** (`ProcessAction`, sections 4–6) in order; actions of fainted or switched-out Pokémon are skipped.
5. If a side is eliminated (`CheckShowdown`), the battle ends immediately (Win, Lose, or Draw).
6. **TurnCheck** (`Section_TurnCheck.turnCheck @0x226fa20`): step 1 weather (duration/end, otherwise weather damage in speed order), step 4 friendship healing, step 5 event 0x91, step 8 statuses (`TurnCheck_Sick`, section 5), step 0xb side effects, 0xc field, 0xd event 0x92, 0x10 event 0x93. The original checks for showdown and switch requests between groups. Weather and statuses are implemented.
7. **CoverCheck** (`Section_CoverCheck`): replace fainted Pokémon on the field; the opponent chooses through AI, while the player's phase changes to `AwaitReplacement`. Replacement therefore happens **after** end-of-turn effects (weather damage, poison, …) [P: order from `ProcessActions.Execute`; whether switch requests inside TurnCheck (steps 3/7/10/15) can happen earlier is evidenced only for unimplemented special cases].
8. **TurnEnd** (`Section_TurnEnd.Execute @0x2273cb0`): clear turn flags, remove isolate factors (`RemoveIsolateFactors`), increment counter.

## 3. Turn order [O/OK]

### 3.1 Sort key `ActPri` [O]

`ActPri.Make(dominant, operation, wazaPri, spPri, agility)` [`@0x1bbd360`] =
`(dominant & 7) << 25 | (operation & 7) << 22 | (wazaPri & 0x3f) << 16 | (spPri & 7) << 13 | agility & 0x1fff`.
Larger values act first. All eleven helpers (`ChangeAgility`, `ChangeWazaPriority`, `Get*`, `Set*`, `ToHandlerPri`, `ToWazaOrgPri` = `wazaPri - 7`) are oracle-confirmed (500 cases, including values beyond the masks).

The speed field is only **13 bits**. Values ≥ 8192 wrap (practically irrelevant); in the ordering range, `10000 - speed` is calculated and then masked (9900 → 1708). Order stays correct as long as speed does not exceed 1808.

### 3.2 Action key (`Section_CalcActionPriority.Execute @0x22ad570`) [P, table values from pseudocode]

- **Dominance:** 0 (interrupting actions use higher values; not implemented).
- **Operation:** move 1, item 4, switch 5, run 6 (a **wild Pokémon's** run counts as 1), G start 2, cheer 3, recording timeout 0. Run beats switch, switch beats item, item beats move, regardless of speed.
- **Move-priority stage** (`Event_GetWazaPriority @0x1e178a0`): move priority + 7 from WazaTable, then event 17 (`GET_WAZA_PRI`, variable `WAZA_PRI`); 0 for non-moves. Thus switch/item/run use stage 0 and are ordered by operation type.
- **Special priority** (`Event_CheckSpecialActPriority @0x1e1c7f0`, event 15, variable `SP_PRIORITY`): 0 low, 1 normal, 2 high (handler effects such as Prankster and Stall); set only for move actions, between the two sorts.
- **Speed** (`Event_CalcAgility @0x1e179a0`, event 19) [OK]: value with stages and handler ratios (starts at 0x1000, bounds `[0x19a, 0x20000]`), `MulRatio`; paralysis halves it (×50/100) while event variable `GEN_FLAG` (initially 1) remains set (abilities such as Quick Feet may clear it); capped at **10000**. With `TRICK_FLAG` set (Trick Room), use `10000 - speed`.

### 3.3 Sorting (`Section_SortActionOrder.sort @0x22cd470`) [OK]

Selection sort with nested loops `i < j`: swap when `pri[i] < pri[j]`; on a **tie, draw once with `GetRand(2)`** and swap when the result is nonzero.
There is no further rule (no side, level, or other tie-breaker). With a Python container, the oracle compares the real function's order **and** next random value (therefore the number of draws) across 700 cases. End-of-turn ordering (`Section_SortByAgility @0x22cd6a0`) uses the same tie rule.

## 4. Action execution

### 4.1 First failure check `CheckFail_1st` (status issues) [P; pseudocode order at `@0x227ee20`, counters/random functions [O]]

Order and random draws, **before PP is deducted**:

1. Sleep: counter +1 (+2 with Early Bird, ability 48, if active); wake when counter ≥ duration (`CheckNemuriWakeUp`) [O], otherwise fail with cause 2. No draw.
2. Freeze: a move with flag 10 (“thaws user”) or one `IsOccurPer(20)` draw thaws; otherwise fail with cause 4.
3. Flinch (turn flag 4) → cause 6. No draw.
4. Confusion: counter +1; ends when counter ≥ duration (`CheckKonranWakeUp`) [O], otherwise draw `IsOccurPer(33)` for self-hit (cause 5).
   Self-hit (`Section_ConfDamage.calcDamage @0x22b56a0`) [OK]: first draw `GetRand(16)`, then `DamageBase(40, attack, level, defense)` (both stats with stages); `(base & 0xffff) * (100 - draw) / 100`, minimum 1.
5. Paralysis: draw `IsOccurPer(25)` → cause 3. 6. Infatuation: draw `IsOccurPer(50)` → cause 8.

Not implemented: disobedience, `Event_CheckWazaExecute` (handler failures, bad luck/Truant), Disable/Taunt/Heal Block/Gravity/Imprison checks, `Event_ExeFailThrew` (Sleep Talk/Snore).

### 4.2 PP and successful execution (`Section_WazaExecStart.Execute @0x227b3d0`) [P]

`CheckFail_1st` → targets → **PP −1** (`decrementPP @0x227be60`; pressure via `Event_DecrementPPVolume` is not connected) → second/third failure checks → execution.
A move that fails the first check consumes **no PP**. If all PP are empty, the Pokémon uses **Struggle** (move 165, recoil equal to ¼ maximum HP, no type effectiveness).
Move handlers (`WazaHandlers.Add`, only those implemented in Slice 3) are registered for the duration of the move.

### 4.3 Hit, immunity, damage (random-draw order)

No effect (type effectiveness 0, including paralysis moves against Electric) is checked **before** accuracy (`CheckWazaInvalid` runs before category dispatch) [P]. Draw order for a hit-capable move:

1. Hit count (`HitCountStd`, only “2–5 hits”, type 5) [O]—its position relative to accuracy is [P].
2. Accuracy: `Event_CheckHit` through `BuildHitInput`/`AccuracyCalculator` (one `GetRand(100)` draw; accuracy 0 or >100 always hits without a draw; moves targeting the user do not check) [OK].
3. Per hit: critical check (`CriticalHit.Check`, one draw), then damage (`DamageCalculator.Calc` via `BuildDamageInput`, one draw for random factor). Stop the hit loop if the target faints; damage ≤ current HP.
4. Additional effects (`Section_WazaAdditionalEffect.Execute @0x2279760`: flinch → drain → target status/stat → user's stat) [P; order evidenced]:
   - Drain/recoil: percentage of **total** damage (`damageRecoverRatio` > 0 drain, < 0 recoil), minimum 1.
   - Status (category 4): probability `sickPer`; target stat (category 6) or user stat (7): each entry uses `rankEffPer`. 0 and ≥100 are guaranteed (no draw) [P].
   - Flinch only if target has not acted this turn (turn flag 0); draw only when `shrinkPer` < 100 [P].

Categories (`WazaCategory`): 0 damage, 1 status, 2 stats, 3 healing, 4 damage+status, 5 stats+status, 6 damage+stat, 7 damage+user stat, 8 drain, 9 one-hit KO (accuracy + user level − target level [P], damage = current HP), 10 field (weather), 11–13 side/special/handler moves (**not implemented**: log `MoveFailed` with `NotImplemented`).

### 4.4 Stats, healing, status conditions

- Stages 0..12 (6 neutral), `ChangeRank`: `StatChangeBlocked` at limits. Values: 1 Attack … 7 Evasion; critical-hit stage (9) not implemented.
- Healing (category 3): `MaxHP × hpRecoverRatio / 100`, minimum 1; fails at full HP [P].
- Apply status (`Section_AddSickCheckFail.checkFail_byBasicRules @0x21dc0a0`, excerpt) [P]: fails if the same status is already active, a primary status (1–5) exists, paralysis targets Electric, freeze targets Ice or sun, burn targets Fire, poison targets Poison/Steel; infatuation only between opposite sexes.
- Status duration (`calc.MakeDefaultPokeSickCont @0x2074d20`): paralysis, freeze, burn, poison are permanent (type 1); **sleep** type 2 for `RandRange(2, 4)` turns (one draw); confusion type 2 with `RandRange(min, max)` from move data; bind type 4; **bad poison** is a permanent status with counter capped at 15 (`MakeMoudokuCont`; move data `sickTurnMin = sickTurnMax = 15`).

### 4.5 Weather (`Section_WazaExec_Category_FieldEffect`, `FieldStatus.TurnCheckWeather @0x19fa950`) [P/O]

Weather moves: Sunny Day 241, Rain Dance 240, Sandstorm 201, Hail 258 (local game data confirms types Fire, Water, Rock, Ice). Duration = 5 + extension (items through `Event_WazaWeatherTurnUp` are not connected). The same weather fails. At turn end, increment the counter; when counter ≥ duration, weather ends **without** damage that turn (so four damage turns for duration 5). Otherwise deal `max(1, MaxHP/16)` weather damage in speed order (Sand: Rock/Steel/Ground immune; Hail: Ice immune). Weather damage modifier: Slice 1 [O].

## 5. Status conditions and end of turn [O]

### 5.1 Duration `BTL_SICKCONT` [O]

A 64-bit value per condition: bits 0–2 type (0 none, 1 permanent, 2 turns, 3 Pokémon, 4 Pokémon+turns), 3–7 source, 8–13 turn count / maximum count / Pokémon ID, parameter from bit 14 (16 bits; for type 4 Pokémon ID is at 14–19 and parameter starts at 20), bit 30 flag. `MakeNull` = `0x1f << 3`. All `Make*`/`Get*` methods of `SICKCONT` are oracle-confirmed (600 cases, 11 constructors). Each condition also has a byte counter (`BTL_POKEPARAM` +0x50).

### 5.2 Advance counters (`WazaSick_TurnCheck @0x20e10f0`) [O]

Applies to all conditions **except sleep (2) and confusion (6)** (those advance during the action, section 4.1): if inactive, type 0 → stop. For duration 0 (permanent), if maximum counter ≠ 0 (bad poison: 15) and counter < maximum, increment counter; condition remains active. With a duration, increment counter; if counter < duration, remain active; otherwise **expire** (duration zero, counter zero, cure message).
If it did not expire, deal damage through `CalcSickDamage @0x20de0c0` [O]: burn `max(1, MaxHP/16)`, poison `MaxHP/8`, bad poison `MaxHP/16 × counter`, nightmare `MaxHP/4` only while asleep (or with ability 213), Curse `MaxHP/4`, bind `MaxHP/8` (`cont_Bind`, factor 8 [P]; Binding Band = 6 is not connected). Bad poison's counter increases **before** damage: 1/16, 2/16, 3/16 …

### 5.3 Condition order [O]

The real `tables.GetTurnCheckWazaSickByOrder` table (from `.cctor`, 42 entries) begins `36, 21, 18, 5, 4, 9, 10, 8, 43, 11, 12, 23, …`: Aqua Ring, Ingrain, Leech Seed, **poison, burn**, Nightmare, Curse, Bind, Whirlpool, … For each condition, iterate over all Pokémon in speed order (`Section_TurnCheck_Sick.Execute @0x2270720)); sort Pokémon once (`SortByAgility`, one draw on ties).

## 6. Running, switching, items

### 6.1 Run formula [OK]

`Section_Escape_Sub.checkEscapeEnableByAgi @0x22b73c0`, using **base speed without stages** (`GetValue_Base(AGILITY)` & 0xffff) for the fleeing Pokémon and opponent:

- If own speed is **greater** than the opponent's: success, **no random draw**.
- Otherwise draw `GetRand(256)`; `ratio = opponent == 0 ? 0 : (own << 12) / opponent`; success when `(attempts & 0xff) * 0x50 + ((int)(ratio << 7) >> 12) > draw`.

Each failed attempt adds **0x50 = 80** (not 30 as in the classic formula). At equal speed, chance is (128 + 0) / 256 = 50% on the first attempt and (128 + 80) / 256 = 81% on the second.
Attempts are `ESCAPE_TRIED_COUNT`, incremented on every failure (`onEscapeFailed`: `IncBattleCount(1)`). The oracle checks 900 cases, including draw count.

Before this (`Section_Escape_Sub.checkForceSucceed @0x22b72a0`), Ghost type (type 7) and handler event `SKIP_NIGERU_CALC` (11) force success without calculation (Smoke Ball, Run Away; handlers are not implemented).
After it (`Section_Escape_Core @0x22b6e80`), `Event_CheckNigeruForbid` (status 22 “run prevention” or bind 8; handlers may extend it, event 12) causes failure, **after** the random draw.
Running is disallowed in trainer battles (`EscapeMode` ≠ WILD): `Submit` rejects the command. Run has the highest operation type (6) and resolves before all others.

### 6.2 Switching and replacements

Switch (operation type 5): remove old Pokémon's factors, clear its stat stages and non-primary statuses, register new Pokémon's factors (`Tokusei.Add`, `Item.Add`), and mark opponents encountered for experience (`Confronted`). Replacement after a knockout works similarly. Event `MEMBER_IN` (108) and entry effects (Intimidate, hazards) are not connected.

### 6.3 Items

Healing uses game-data value `wk_prm_hp_rcv` (255 = full HP); item is consumed from the bag. Status healing, berries, PP items, and Poké Balls (capture) are missing.

## 7. Fainting, experience, effort values

- **Faint:** one event per Pokémon; temporary conditions are removed. When an opponent faints, award experience/EVs immediately (`Section_CheckExpGet` runs in the original after damage, weather, and statuses) [P].
- **Experience** [O for formula, P for distribution]: for each able Pokémon on the player's side, `ExpCalculator.Calc` (Slice 1, `Exp.CalcExp @0x19f7d70`); inputs from `calcExp_Poke @0x19f8c10`: species `give_exp`, levels, friendship, `isMatch` = whether it faced the fainted Pokémon (`CONFRONT_REC`), Exp. Share, Lucky Egg (item 231 = 0xe7), and traded Pokémon.
  **There is no ×1.5 trainer-battle bonus in this path:** `competitor` is not read by `Exp.CalcExp` (this answers gap 5 from Specification 1: no bonus).
- **Level-up:** recalculate stats from growth table; HP increases by the difference in max HP. Move learning belongs to the UI, not the battle flow.
- **Effort values** (`calcEffortExp_Poke @0x19f9060`) [P]: only for Pokémon awarded experience (`exp ≠ 0`). Yield for the defeated species is in `PersonalTable.exp_value`, two bits each in order: HP, Attack, Defense, Speed, Sp. Atk, Sp. Def [locally checked against real species: Pikachu +2 Speed, Mewtwo +3 Sp. Atk, Gyarados +2 Attack]. Macho Brace (item 215 = 0xd7) doubles it. Caps are 252 per stat, 510 total [P, assumed]. Power items and Pokérus are not implemented (table in `ExpCalculator`'s `.cctor` has not been extracted).
- Write results back to source data (`BattleMon.WriteBack`): HP, experience, PP, level, stats.

## 8. Event log

`BattleEngine.Log` is a list of structured `LogEvent` records (kind `LogKind`, turn, Pokémon ID, target, ID, two values). Pokémon IDs: player 0–5, opponent 6–11.
Kinds: `BattleStart, SendOut, TurnStart, ActionOrder, MoveUsed, MoveFailed, MoveMissed, NoEffect, Critical, Effectiveness, Damage, HitCount, Recover, Drain, Recoil, StatChange, StatChangeBlocked, SickAdded, SickFailed, SickCured, SickDamage, ConfusionDamage, WeatherStart, WeatherEnd, WeatherDamage, Faint, ExpGained, LevelUp, EvGained, Switch, ItemUsed, RunAttempt, RunSuccess, RunFailed, TurnEnd, BattleEnd`; flinch appears as `MoveFailed` with cause 6.
Each field's meaning is documented on its entry in `FlowTypes.cs`. Output is bit-for-bit reproducible for the same seed (test `IdenticalSeedsGiveIdenticalLogsAndDifferentSeedsDiffer`).

## 9. Verification

### 9.1 Oracle (`scripts/battle_oracle_flow.py`, fixture `unity/Assets/Tests/EditMode/Fixtures/BattleFlow.json`)

| Group | Real function(s) | Cases | Level |
|---|---|---:|---|
| `actpri` | `ActPri.Make/Change*/Get*/Set*/ToHandlerPri/ToWazaOrgPri` | 500 | [O] |
| `sickcont` | `SICKCONT.Make*` (11), `IsNull/IsMoudokuCont/GetPokeID/GetTurnMax/GetParam` | 600 | [O] |
| `sickturn` | `WazaSick_TurnCheck` (700), `CheckNemuriWakeUp`/`CheckKonranWakeUp` (300+300), `CalcSickDamage` (500) with synthetic guest memory (condition and counter arrays) | 1,800 | [O] |
| `escape` | `Section_Escape_Sub.checkEscapeEnableByAgi` | 900 | [OK] |
| `sort` | `Section_SortActionOrder.sort` with Python container | 700 | [OK] |
| `agility` | `Event_CalcAgility` (handler results as inputs) | 900 | [OK] |
| `confdmg` | `Section_ConfDamage.calcDamage` | 500 | [OK] |
| `tables` | `tables..cctor`: end-of-turn condition order | 42 | [O] |

For [OK] groups, the tested function runs as-is (including real `Xoroshiro128+` and `calc.GetRand/MulRatio/DamageBase`); neighboring functions (`BTL_POKEPARAM.GetValue*`, event functions, containers) are stubs with test values.
Each random case also stores the **next** random value, verifying draw count. Reproduce:

```
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_flow.py            # regenerate BattleFlow.json (about 1 minute)
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_flow.py --out work/battleflow-oracle --only escape sort
cd work/dotnet-battleflow && dotnet test                                  # 142 tests without Unity Editor
```

### 9.2 Flow tests (`BattleFlowEngineTests`, 30)

Order (speed, priority, ties with two draws), damage calculation and draw order (hit → critical → random factor), type effectiveness/immunity, accuracy rates, 2–5 hits and Double Kick, drain/recoil/healing, stat-stage bounds, burn/poison/bad poison/sleep/freeze/paralysis/confusion (frequency and exact duration), type-based status rules, weather duration/damage/modifier, switching (priority, target), running (success without draw, random roll, increasing odds, prevention, trainer battle), knockout with experience/EV/level-up, Exp. Share and Macho Brace, replacement phase and trainer replacement, items, Struggle, PP deduction after first check, determinism, and 120 randomized battles (invariants and termination).

### 9.3 Local test with real game data (not in repository)

`work/dotnet-battleflow/tests/BattleFlowRealDataLocal.cs` (ignored when `work/masterdata` is absent): weather moves/types, EV yields, Mewtwo/Gyarados, and 60 real trainer teams (from `TrainerPoke`) played to completion against a two-Pokémon player team (59 wins; no crash; every battle ends). The test reads locally, writes nothing, and is not part of the Unity tests.

## 10. Verification levels at a glance

| Claim | Level |
|---|---|
| ActPri packing, SICKCONT packing, condition counters, sleep/confusion counters, status damage, end-of-turn condition order | [O] |
| Run formula, sorting including tie draws, speed (paralysis/cap/Trick Room), confusion damage | [OK] |
| Operation table, move-priority stage, special priority, turn structure, first-failure-check order, PP deducted only after first check | [P] (pseudocode; structures cross-checked repeatedly) |
| Hit-count/accuracy/critical/damage order, additional-effect order, replacements after end-of-turn effects | [P] (some evidence; details partly assumed) |
| Game-data interpretation (`sickPer 0` = guaranteed, `hitPer > 100` always hits, weather move IDs, EV bits, 252/510 caps) | [P], some checked locally against real data |

## 11. Gaps

1. **Effect API and effectful handlers** (Intimidate, weather abilities, berries, Leftovers, Focus Sash, flinch abilities, events 91–93, `MEMBER_IN`, etc.) are not connected. Slice 3 handlers only work where they change event variables (power, attack, defense, accuracy, speed, priority, final damage).
2. **Moves:** only WazaTable categories 0–10. Moves with handler logic (categories 11–13: protection, Hidden Power, Curse, special moves, fixed damage, status tables, etc.), sleep-specific rules, conditional double damage, and more are logged as `MoveFailed` (`NotImplemented`). Fixed-damage events 87–89 are missing.
3. **Side, position, and field effects** (barriers, hazards, room effects, terrain): none; `Handler.Side/Pos/Field` were not implemented in Slice 3. “Order” field events are wired but have no handlers.
4. **AI:** opponent chooses a random move with PP (`RandomEnemyBrain`); trainers do not use items or switch; original AI (`BtlAiExpert`, `AiBit`) is not reconstructed.
5. **Capture** (Poké Balls, `Capture.checkCapureSuccessByRandom`), prize money (`calc.CalcWinMoney`), friendship effects, move learning, post-battle evolution, disobedience, capture bonus, power items, Pokérus.
6. **Wild generation** (nature, stats, ability, sex) differs from original (`Pml.PokePara.InitialSpec`); `PokemonFactory.CreateWild` is a helper only. Real encounter tables are in `Xnu.Data`.
7. **Seed:** original live seed comes from `UnityEngine.Random`; here it is a parameter (Specification 1, section 4.2).
8. Unresolved: random draw order for multi-hit moves (hit count before or after accuracy), draw when `sickPer` = 100, flinch draw, replacement/end-of-turn handler order in special cases (section 2, step 7).

## 12. Remaining effort (estimates)

| Block | Scope | Estimate |
|---|---|---|
| **Double battles** | Targets (`PokePos`, 4 positions), target selection (move targets 0–13), multi-target damage (`TargetRatio` prepared), ordering 4 actions, spread events, replacement choice per side, experience participation, command phase with two commands per side | 3–4 days with oracle for sorting and target selection (`Section_RegisterWazaTargets`) |
| **Trainer AI** | `BtlAiExpert`, AI script interpreter (`AiScriptCommandHandler`, `aiSeqNo` from WazaTable, `AiBit` from `TrainerData`), item/switch decisions | 3–5 days (large but schematic script VM; individual commands can be oracle-checked) |
| **Effect API** (`Common.*`, 56 `Section_FromEvent_*`) | prerequisite for nearly all effectful handlers | 2–3 days (Slice 3 estimate); flow layer is partly in place here |
| **Side/field/position effects** | 37 IDs, 40 functions | 1 day after effect API |
| **Capture, prize money, learning, evolution** | Poké Balls, `Capture`, `CalcWinMoney`, learnsets (`WazaOboeTable`), evolution checks | 2 days |
| **Dynamax/additional mechanics** | **None required:** BDSP has no Dynamax, Mega Evolution, or Z-Moves. “G mode” and raid remnants in code (`GMode`, `RaidBoss`, `Section_G_Start`) belong to Sword/Shield and are not needed | 0 |
| Handlers over 60 lines, berries/items | See `docs/kampf-spezifikation-3.md` | 3 days |

Completing “all wild and trainer battles in the main story like the original” was estimated at roughly 2–3 weeks, about one third spent on oracle work.
