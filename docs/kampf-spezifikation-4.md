# Battle Flow, Slice 4: Specification

Status: Slice 4 interim results (a headless, playable 1:1 single battle, wild and trainer; pure C# logic without UnityEngine, rendering, or audio). Continuation: `docs/kampf-spezifikation-5.md` (handler effects, side/field effects, prize money; gaps 1–3 and 5 below are partly closed there).
The implementation (`unity/Assets/Scripts/BattleFlow`, assembly `Xnu.Battle.Flow`) builds on Slice 1 (calculators, `Xnu.Battle`), Slices 2/3 (event system and handlers, `Xnu.Battle.Events`), and the Pokémon model (`Xnu.PokePara`). Evidence conventions, addresses (Ghidra address = Il2CppDumper RVA + `0x100000`), and verification levels **[O]**, **[OK]**, **[P]** follow section 0 of `docs/kampf-spezifikation-2.md`.

## 1. Results at a glance

| | |
|---|---|
| Playable scope | Single wild and trainer battles: setup from `PokemonParam` teams; move/item/switch/run commands as data; turns proceed until `Finished` |
| New oracle cases (real ARM64 functions) | 5,900 cases in `Fixtures/BattleFlow.json` (2.7 MB, numeric data only), across 8 groups (section 9) |
| New tests | 40 (10 oracle comparisons, 30 flow tests); together with 101 existing battle tests, 141 pass in the dotnet project `work/dotnet-battleflow`; plus one local test using real master data (played 60 real trainer teams) |
| Existing code changed | None (`Xnu.Battle`, `Xnu.Battle.Events`, `Xnu.PokePara`, `Xnu.Data` unchanged); `Xnu.Tests.EditMode.asmdef` only gains a reference to `Xnu.Battle.Flow` |

## 2. Overview: state machine

```
Setup (BattleSetup) ──Start()──> AwaitCommands ──Submit(player[, opponent] command)──> Turn
                                      ^                                                     │
                                      │                         ┌───────────────────────────┤
                                      │                         v                           v
                              SubmitReplacement()          Finished (Win/Lose/Draw/Run)  AwaitReplacement
                                      ^                                                     │
                                      └─────────────────────────────────────────────────────┘
```

Turn flow (a mirror of `Section_Root_ProcessActions.Execute @0x22c9a10`) [P, structure from pseudocode; see below for individual steps]:

1. **TurnStart** (`Section_TurnStart.Execute @0x2274fa0`): wake all sleeping factors (`WakeAllFactors`), check the event-variable stack, reset Pokémon special priorities to 1.
2. **Collect actions** (`Section_StoreActions`): one action per side; container order is player first, then opponent.
3. **Sort, apply special priorities, sort again** (`sortPokeActionOrder`, `setSpActPriority`, `sortPokeActionOrder`): each sort recalculates all keys and draws a random value for every tie (section 3). A tie therefore consumes **two draws**.
4. **Execute actions** (`ProcessAction`, sections 4–6) in order; actions for fainted or switched-out Pokémon are skipped.
5. If a side is wiped out (`CheckShowdown`), the battle ends immediately (win, loss, or draw).
6. **TurnCheck** (`Section_TurnCheck.turnCheck @0x226fa20`): step 1 weather (duration/end, otherwise weather damage in Speed order), step 4 friendship healing, step 5 event `0x91`, step 8 status conditions (`TurnCheck_Sick`, section 5), step `0xb` side effects, `0xc` field effects, `0xd` event `0x92`, `0x10` event `0x93`. The original checks for showdown and switch requests between groups. Weather and status conditions are implemented.
7. **CoverCheck** (`Section_CoverCheck`): replace fainted Pokémon on the field; the opponent chooses through AI, while the player phase changes to `AwaitReplacement`. Replacement therefore happens **after** end-of-turn effects (weather damage, poison, etc.) [P: order from `ProcessActions.Execute`; whether switch requests inside TurnCheck (steps 3/7/10/15) happen earlier is established only for unimplemented special cases].
8. **TurnEnd** (`Section_TurnEnd.Execute @0x2273cb0`): clear turn flags, remove Isolate factors (`RemoveIsolateFactors`), increment counters.

## 3. Turn order [O/OK]

### 3.1 `ActPri` sort key [O]

`ActPri.Make(dominant, operation, wazaPri, spPri, agility)` [`@0x1bbd360`] = `(dominant & 7) << 25 | (operation & 7) << 22 | (wazaPri & 0x3f) << 16 | (spPri & 7) << 13 | agility & 0x1fff`.
Larger means earlier. All eleven helpers (`ChangeAgility`, `ChangeWazaPriority`, `Get*`, `Set*`, `ToHandlerPri`, `ToWazaOrgPri` = `wazaPri - 7`) are oracle-verified (500 cases, including values beyond the masks).

Consequences: Speed has only **13 bits**. Values ≥8192 wrap (practically irrelevant); during ordering, `10000 - Speed` is formed and then masked
(`9900 → 1708`), so order remains correct as long as Speed does not exceed 1808.

### 3.2 Action key (`Section_CalcActionPriority.Execute @0x22ad570`) [P, table values from pseudocode]

- **Dominance:** 0 (interrupt actions set it higher; not implemented).
- **Action kind** (`operation`): move 1, item 4, switch 5, run 6 (a **wild Pokémon's** run is treated as 1), G-start 2, cheer 3, recording timeout 0. Run outranks switch, which outranks item, which outranks move, regardless of Speed.
- **Move priority stage** (`Event_GetWazaPriority @0x1e178a0`): move priority + 7 from WazaTable, then event 17 (`GET_WAZA_PRI`, variable `WAZA_PRI`); non-moves use 0. Switch/item/run therefore have stage 0 and sort first by action kind.
- **Special priority** (`Event_CheckSpecialActPriority @0x1e1c7f0`, event 15, variable `SP_PRIORITY`): 0 low, 1 normal, 2 high (handler effects such as Prankster/After You); set only for move actions, between the two sorts.
- **Speed** (`Event_CalcAgility @0x1e179a0`, event 19) [OK]: value with stages, handler ratio (starts at `0x1000`, bounds `[0x19a, 0x20000]`), `MulRatio`;
  paralysis halves it (`× 50 / 100`) while event variable `GEN_FLAG` (starts at 1) remains set (handlers such as Quick Feet may clear it); capped at **10000**;
  if `TRICK_FLAG` is set (ordering mode), use `10000 - Speed`.

### 3.3 Sorting (`Section_SortActionOrder.sort @0x22cd470`) [OK]

Selection sort with two loops `i < j`: swap if `pri[i] < pri[j]`; on a **tie, draw `GetRand(2)`**, swapping when the result is nonzero.
There is no further rule (no preference by side, level, etc.). The oracle runs the real function with a Python container and checks order **and**
the next random value (therefore the number of draws) across 700 cases. End-of-turn ordering (`Section_SortByAgility @0x22cd6a0`) uses the same tie rule.

## 4. Action execution

### 4.1 First failure check, `CheckFail_1st` (status conditions) [P, order from pseudocode `@0x227ee20`; counters and random functions [O]]

Order and random draws, **before** PP is deducted:

1. Sleep: counter `+1` (`+2` with Early Bird, ability 48, if active); wake at counter ≥ duration (`CheckNemuriWakeUp`) [O]; otherwise fail cause 2. No draw.
2. Freeze: a move with flag 10 (“thaws user”) or one `IsOccurPer(20)` draw thaws; otherwise fail cause 4.
3. Flinch (turn flag 4) → cause 6. No draw.
4. Confusion: counter `+1`, ends at counter ≥ duration (`CheckKonranWakeUp`) [O]; otherwise draw `IsOccurPer(33)` for self-hit (cause 5).
   Self-hit (`Section_ConfDamage.calcDamage @0x22b56a0`) [OK]: first draw `GetRand(16)`, then `DamageBase(40, Attack, stage, Defense)` (both stats include stages),
   `(Base & 0xffff) * (100 - draw) / 100`, minimum 1.
5. Paralysis: draw `IsOccurPer(25)` → cause 3.
6. Infatuation: draw `IsOccurPer(50)` → cause 8.

Not implemented: disobedience, `Event_CheckWazaExecute` (handler failures, Hustle/Truant), Disable/Taunt/Heal Block/Gravity/Imprison checks, `Event_ExeFailThrew` (Sleep Talk/Snore).

### 4.2 PP and successful-check flow (`Section_WazaExecStart.Execute @0x227b3d0`) [P]

`CheckFail_1st` → targets → **PP −1** (`decrementPP @0x227be60`; Pressure via `Event_DecrementPPVolume` is not connected) → second/third failure checks → execute.
A failure in the first check consumes **no PP**. If all PP are empty, the Pokémon uses **Struggle** (move 165, recoil equal to ¼ max HP, no type effectiveness).
The move's Waza handlers (only those implemented in Slice 3, via `WazaHandlers.Add`) are registered for the duration of the move.

### 4.3 Hit, immunity, damage (random draw order)

No-effect cases (type effectiveness 0, including paralysis moves against Electric types) are checked **before** accuracy (`CheckWazaInvalid` runs before category handling) [P]. Draw order for an attacking move:

1. Hit count (`HitCountStd`, only for “2–5 hits”, type 5) [O] — placement relative to accuracy [P].
2. Accuracy: `Event_CheckHit` through `BuildHitInput`/`AccuracyCalculator` (one `GetRand(100)` draw; accuracy 0 or >100 always hits without a draw; moves targeting the user do not check accuracy) [OK].
3. For each hit: critical check (`CriticalHit.Check`, one draw) → damage (`DamageCalculator.Calc` via `BuildDamageInput`, one draw for the random factor);
   stop the hit loop when the target faints; damage cannot exceed current HP.
4. Additional effects (`Section_WazaAdditionalEffect.Execute @0x2279760`: flinch → drain → target status/stat change → user's stat change) [P, order established]:
   - Drain/recoil: percentage of **total** damage (`damageRecoverRatio` > 0 drain, < 0 recoil), minimum 1.
   - Status condition (category 4): chance `sickPer`; target stat change (category 6) or user's stat change (7): `rankEffPer` per entry. Values 0 and ≥100 are guaranteed (no draw) [P].
   - Flinch only if the target has not acted this turn (turn flag 0); draw only when `shrinkPer` <100 [P].

Categories (`WazaCategory`): 0 damage, 1 status condition, 2 stat changes, 3 healing, 4 damage+status, 5 stat changes+status, 6 damage+stat change, 7 damage+user stat change,
8 drain, 9 one-hit KO (hit chance = accuracy + user's stage − target's stage [P], damage = current HP), 10 field (weather), 11–13 side/special/handler moves (**not implemented**: log `MoveFailed` with `NotImplemented`).

### 4.4 Stat stages, healing, status conditions

- Stages 0..12 (6 neutral), `ChangeRank`: blocked at caps by `StatChangeBlocked`. Values 1 Attack … 7 evasion; critical-hit stage (9) not implemented.
- Healing (category 3): `MaxHP × hpRecoverRatio / 100`, minimum 1; fails at full HP [P].
- Status application (`Section_AddSickCheckFail.checkFail_byBasicRules @0x21dc0a0`, excerpt) [P]: fails if same condition is active; a major status (1–5) already exists; paralysis on Electric, freeze on Ice or in sun, burn on Fire, poison on Poison/Steel; infatuation only between opposite sexes.
- Condition duration (`calc.MakeDefaultPokeSickCont @0x2074d20`): paralysis, freeze, burn, poison last indefinitely (type 1); **sleep** type 2 with `RandRange(2, 4)` turns (one draw);
  confusion type 2 with `RandRange(min, max)` from move data; binding type 4; **bad poison** is a lasting condition with counter capped at 15 (`MakeMoudokuCont`; move data has `sickTurnMin = sickTurnMax = 15`).

### 4.5 Weather (`Section_WazaExec_Category_FieldEffect`, `FieldStatus.TurnCheckWeather @0x19fa950`) [P/O]

Weather moves: Sunny Day 241, Rain Dance 240, Sandstorm 201, Hail 258 (master-data types match: Fire, Water, Rock, Ice [checked locally]). Duration = 5 + extension (items via
`Event_WazaWeatherTurnUp`, not connected). Setting the same weather fails. At turn end, increment counter; when counter ≥ duration, weather ends **without** dealing damage that turn (so duration 5 gives 4 damage ticks). Otherwise weather deals `max(1, MaxHP/16)`
(sand: Rock/Steel/Ground immune; hail: Ice immune) in Speed order. Weather damage modifiers are in Slice 1 [O].

## 5. Status conditions and turn end [O]

### 5.1 Duration, `BTL_SICKCONT` [O]

64-bit value per condition: bits 0–2 type (0 none, 1 permanent, 2 turns, 3 Pokémon, 4 Pokémon+turns), 3–7 source, 8–13 turn count/maximum/Pokémon ID,
from bit 14 parameters (16 bits; for type 4, Pokémon ID is at 14–19 and parameters start at 20), bit 30 flag. `MakeNull` = `0x1f << 3`. All `Make*`/`Get*` methods in `SICKCONT` are oracle-verified (600 cases, 11 constructors). Each condition also has a byte counter (`BTL_POKEPARAM` +`0x50`).

### 5.2 Advancing counters (`WazaSick_TurnCheck @0x20e10f0`) [O]

Applies to all conditions **except sleep (2) and confusion (6)** (those count during the action, section 4.1): inactive condition? type 0 → no.
For turn count 0 (permanent): if maximum is nonzero (bad poison: 15) and counter < maximum, increment counter; condition remains active.
For a timed condition: increment counter; if counter < duration it remains active; otherwise it **expires** (duration to zero, counter to zero, cure message).
Then, only if it has not expired, apply damage (`CalcSickDamage @0x20de0c0`) [O]: burn `max(1, MaxHP/16)`; poison `MaxHP/8`, bad poison `MaxHP/16 × counter`; Nightmare `MaxHP/4` only while asleep (or with ability 213); Curse `MaxHP/4`; binding `MaxHP/8` (`cont_Bind`, factor 8 [P]; Binding Band = 6 is not connected). Bad poison's counter advances **before** damage: 1/16, 2/16, 3/16, …

### 5.3 Status-condition order [O]

The real `tables.GetTurnCheckWazaSickByOrder` table (42 entries from the `.cctor`) begins `36, 21, 18, 5, 4, 9, 10, 8, 43, 11, 12, 23, …`: Aqua Ring, Ingrain, Leech Seed, **poison, burn**, Nightmare, Curse,
binding, Whirlpool, … For each condition, all Pokémon are processed in Speed order (`Section_TurnCheck_Sick.Execute @0x2270720`); Pokémon are sorted once
(`SortByAgility`, one draw on a tie).

## 6. Run, switching, and items

### 6.1 Run formula [OK]

`Section_Escape_Sub.checkEscapeEnableByAgi @0x22b73c0`, using **base Speed without stages** (`GetValue_Base(AGILITY) & 0xffff`) for the fleeing and opposing Pokémon:

- If the user's Speed is **greater** than the opponent's: success, **no random draw**.
- Otherwise draw `GetRand(256)`; `ratio = opponent == 0 ? 0 : (own << 12) / opponent`; success if `(attempts & 0xff) * 0x50 + ((int)(ratio << 7) >> 12) > draw`.

The increment per failed attempt is **0x50 = 80** (not 30 from the classic formula); with equal Speed, the first attempt has a 50% chance `(128 + 0)/256`, the second 81% `(128 + 80)/256`.
Attempts = `ESCAPE_TRIED_COUNT`, incremented after each failure (`onEscapeFailed: IncBattleCount(1)`). The oracle checks 900 cases, including draw count.

Before this (`Section_Escape_Sub.checkForceSucceed @0x22b72a0`): Ghost type (type 7) and handler event `SKIP_NIGERU_CALC` (11) force success without calculation (Smoke Ball, Run Away: handlers not yet implemented).
Afterward (`Section_Escape_Core @0x22b6e80`): `Event_CheckNigeruForbid` (status 22 “run prevented” or binding 8; handlers may extend it, event 12) → failure, **after** the random draw.
Running is disallowed in trainer battles (`EscapeMode` != WILD): `Submit` rejects the command. Run has the highest action kind (6), so it executes before all others.

### 6.2 Switching and replacement

Switch (action kind 5): remove old Pokémon's factors, clear its stages and non-major status conditions, register new Pokémon's factors (`Tokusei.Add`, `Item.Add`), and set opponent records for experience (`Confronted`). Same for replacement after a knockout. Event `MEMBER_IN` (108) and entry effects (Intimidate, hazards) are not connected.

### 6.3 Items

Healing items use master-data value `wk_prm_hp_rcv` (255 = full HP) and are consumed from the bag. Status cures, berries, PP items, and Poké Balls (capture) are missing.

## 7. Knockouts, experience, effort values

- **Faint:** event once per Pokémon; non-permanent conditions expire. Against an opponent, award experience/EV immediately (`Section_CheckExpGet` runs after damage, weather, and status conditions in the original) [P].
- **Experience** [O for formula, P for distribution]: for each able Pokémon on the player's side, `ExpCalculator.Calc` (Slice 1, `Exp.CalcExp @0x19f7d70`); inputs from `calcExp_Poke @0x19f8c10`:
  `deadPokeExp = give_exp` for the species; levels, friendship, `isMatch` = faced the defeated Pokémon (`CONFRONT_REC`), Exp. Share, Lucky Egg (item 231 = `0xe7`), traded Pokémon.
  **There is no ×1.5 trainer-battle bonus in this path**: `competitor` is not read by `Exp.CalcExp` (this answers gap 5 in Specification 1: no bonus).
- **Level-up:** recalculate stats from growth table; increase HP by the change in max HP. Learning moves is handled by the UI, not battle flow.
- **Effort values** (`calcEffortExp_Poke @0x19f9060`) [P]: only for Pokémon that gain experience (`exp != 0`). Yields are in `PersonalTable.exp_value`, two bits each in order
  HP, Attack, Defense, Speed, Sp. Attack, Sp. Defense [checked against real local species data: Pikachu +2 Speed, Mewtwo +3 Sp. Attack, Gyarados +2 Attack]. Macho Brace (item 215 = `0xd7`) doubles gains. Limits 252 per stat, 510 total [P, assumed].
  Not implemented: Power items, Pokérus (table is in `ExpCalculator`'s `.cctor`, not yet extracted).
- Write results back to source data (`BattleMon.WriteBack`): HP, experience, PP, level, stats.

## 8. Event log

`BattleEngine.Log` is a list of structured `LogEvent` values (kind `LogKind`, turn, Pokémon ID, target, ID, two values). Pokémon IDs: player 0–5, opponent 6–11.
Kinds: `BattleStart, SendOut, TurnStart, ActionOrder, MoveUsed, MoveFailed, MoveMissed, NoEffect, Critical, Effectiveness, Damage, HitCount, Recover, Drain, Recoil, StatChange, StatChangeBlocked, SickAdded,
SickFailed, SickCured, SickDamage, ConfusionDamage, WeatherStart, WeatherEnd, WeatherDamage, Faint, ExpGained, LevelUp, EvGained, Switch, ItemUsed, RunAttempt, RunSuccess, RunFailed, TurnEnd, BattleEnd`;
flinch appears as `MoveFailed` with cause 6.
Field meanings are documented on each entry in `FlowTypes.cs`. Output is bit-for-bit reproducible for the same seed (test `IdenticalSeedsGiveIdenticalLogsAndDifferentSeedsDiffer`).

## 9. Verification

### 9.1 Oracle (`scripts/battle_oracle_flow.py`, fixture `unity/Assets/Tests/EditMode/Fixtures/BattleFlow.json`)

| Group | Real function(s) | Cases | Level |
|---|---|---:|---|
| `actpri` | `ActPri.Make/Change*/Get*/Set*/ToHandlerPri/ToWazaOrgPri` | 500 | [O] |
| `sickcont` | `SICKCONT.Make*` (11), `IsNull/IsMoudokuCont/GetPokeID/GetTurnMax/GetParam` | 600 | [O] |
| `sickturn` | `WazaSick_TurnCheck` (700), `CheckNemuriWakeUp`/`CheckKonranWakeUp` (300+300), `CalcSickDamage` (500) on synthetic guest memory (condition/counter arrays) | 1,800 | [O] |
| `escape` | `Section_Escape_Sub.checkEscapeEnableByAgi` | 900 | [OK] |
| `sort` | `Section_SortActionOrder.sort` with Python container | 700 | [OK] |
| `agility` | `Event_CalcAgility` (handler results as inputs) | 900 | [OK] |
| `confdmg` | `Section_ConfDamage.calcDamage` | 500 | [OK] |
| `tables` | `tables..cctor`: end-of-turn status order | 42 | [O] |

For [OK] groups, the tested function runs for real (including real `Xoroshiro128+` and real `calc.GetRand/MulRatio/DamageBase`); neighboring functions (`BTL_POKEPARAM.GetValue*`, event functions, containers) are stubs with test values.
Each random case also stores the **next** random value to verify how many values were drawn. Reproduction:

```
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_flow.py            # regenerate BattleFlow.json (about 1 minute)
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_flow.py --out work/battleflow-oracle --only escape sort
cd work/dotnet-battleflow && dotnet test                                  # 142 tests without Unity Editor
```

### 9.2 Flow tests (`BattleFlowEngineTests`, 30)

Turn order (Speed, priority, tie with two draws); damage = calculator with draw order hit → critical → random factor; type effectiveness/immunity; accuracy; 2–5 multi-hit and Double Kick; drain/recoil/healing; stat-stage limits; burn/poison/bad poison/sleep/freeze/paralysis/confusion (rates and exact duration); type-based condition rules; weather duration and damage; weather modifier; switching (priority, target); run (success without draw, roll, increasing chance, run prevention, trainer battle); knockout with experience/EV/level-up; Exp. Share and Macho Brace; replacement phase and trainer replacement; items; Struggle; PP deduction after first check; reproducibility; 120 randomized battles (invariants, termination).

### 9.3 Local test with real master data (not in repository)

`work/dotnet-battleflow/tests/BattleFlowRealDataLocal.cs` (ignored when `work/masterdata` is missing): weather moves/types, EV yields, Mewtwo/Gyarados, and 60 real trainer teams (from `TrainerPoke`) against a two-Pokémon player team until completion (59 wins; no crash; every battle ends). This test reads local data only, writes nothing, and is not part of Unity tests.

## 10. Verification levels at a glance

| Claim | Level |
|---|---|
| ActPri packing, SICKCONT packing, condition counters, sleep/confusion counters, condition damage, end-of-turn order | [O] |
| Run formula, sorting including tie draws, Speed (paralysis/cap/order), confusion damage | [OK] |
| Action-kind table, move-priority stage, special priority, turn structure, order of failure checks, PP deducted only after first check | [P] (pseudocode, structure cross-checked several times) |
| Hit count/accuracy/critical/damage order, additional effects (draw sequence), replacement after end-of-turn effects | [P] (some evidence; details partly assumed) |
| Master-data interpretation (`sickPer 0` means guaranteed, `hitPer > 100` always hits, weather move IDs, EV bits, EV limits 252/510) | [P], partly checked against local real data |

## 11. Gaps (reported candidly)

1. **Effect API and handlers with effects** (Intimidate, weather abilities, berries, Leftovers, Focus Sash, flinch abilities, events 91–93, `MEMBER_IN`, etc.) are not connected.
   Slice 3 handlers only apply where they change event variables (power, attack, defense, accuracy, Speed, priority, final damage).
2. **Moves:** only WazaTable categories 0–10. Moves with handler logic (categories 11–13: protection, Hidden Power, Curse, special moves, fixed damage, status tables, etc.), sleep-specific rules,
   double-damage conditions, and more log `MoveFailed` (`NotImplemented`). Fixed-damage events 87–89 are missing.
3. **Side, position, and field effects** (barriers, hazards, room effects, terrain): none; `Handler.Side/Pos/Field` are not implemented in Slice 3. Events for Trick Room are wired but have no handlers.
4. **AI:** opponent chooses a random move with PP (`RandomEnemyBrain`); trainers use neither items nor switching. Original AI (`BtlAiExpert`, `AiBit`) is not reconstructed.
5. **Capture** (Poké Balls, `Capture.checkCapureSuccessByRandom`), prize money (`calc.CalcWinMoney`), friendship effects, move learning, post-battle evolution, disobedience, capture bonus, Power items, Pokérus.
6. **Wild generation** (nature, IVs, ability, sex) does not match the original (`Pml.PokePara.InitialSpec`); `PokemonFactory.CreateWild` is only a helper. Real encounter tables are in `Xnu.Data`.
7. **Seed:** the original live seed comes from `UnityEngine.Random`; here it is a parameter (Specification 1, section 4.2).
8. Unresolved: random draw order for multi-hit moves (hit count before or after accuracy), whether a draw occurs when `sickPer` = 100, flinch draw, and ordering of replacement/end-of-turn handlers in special cases (section 2, step 7).

## 12. Remaining effort (estimate)

| Area | Scope | Estimate |
|---|---|---|
| **Double battles** | Targets (`PokePos`, four slots), target selection (move targets 0–13), multi-target damage (`TargetRatio` is prepared), ordering four actions, spread events, replacement selection per side, experience confrontation mapping, command phase with two commands per side | 3–4 days, with oracle for ordering and target selection (`Section_RegisterWazaTargets`) |
| **Trainer AI** | `BtlAiExpert`, AI script interpreter (`AiScriptCommandHandler`, `aiSeqNo` from WazaTable, `AiBit` from `TrainerData`), item/switch decisions | 3–5 days (large but schematic script VM; oracle possible for individual commands) |
| **Effect API** (`Common.*`, 56 `Section_FromEvent_*`) | Prerequisite for almost all handlers with effects | 2–3 days (Slice 3 estimate); flow portion is already in place here |
| **Side/field/position effects** | 37 IDs, 40 functions | 1 day after effect API |
| **Capture, prize money, learning, evolution** | Balls, `Capture`, `CalcWinMoney`, learnsets (`WazaOboeTable`), evolution check | 2 days |
| **Dynamax/additional mechanics** | **None:** BDSP has no Dynamax, Mega Evolution, or Z-Moves. The “G-mode” and Raid remnants (`GMode`, `RaidBoss`, `Section_G_Start`) are from Sword/Shield and are not needed | 0 |
| Handlers over 60 lines, berries/items | See `docs/kampf-spezifikation-3.md` | 3 days |

Overall, completing “all wild and trainer battles in the main story as in the original” was estimated at roughly 2–3 weeks, one third of that oracle work.
