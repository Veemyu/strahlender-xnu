# Battle Flow, Slice 6: Trainer AI (BtlAi*, AIBit, scoring, items, switching)

> **Update:** The Double and Expert scripts, the remaining Basic functions, and the Strong double-battle branch listed as gaps in section 8 were implemented and oracle-verified in Slice 7: `docs/kampf-spezifikation-7.md`.

> **Historical report:** This document describes the deprecated Unity rebuild. It is retained as project history; the native static recompilation is the current product.

Status: Slice 6, building on `docs/kampf-spezifikation-5.md` (section 5 identified AI as a gap). Code: `unity/Assets/Scripts/BattleFlow/Ai/` (`TrainerAi.cs`, `AiWorld.cs`, `AiScriptBase.cs`, `AiScriptBasic.cs`, `AiScriptsOther.cs`); interface in `BattleEngine.cs` (`BattleSetup.EnemyAi`, `EnemyItems`). Oracle: `scripts/battle_oracle_ai.py` (Unicorn, real ARM64 functions from `work/elf/main.patched.elf`); fixtures `unity/Assets/Tests/EditMode/Fixtures/BattleAi*.json` (numbers only).

Verification levels follow specifications 2/5, with an extra level for the script layer:

- **[O]** Given the same state, the C# function issues the same `AI_CMD` calls with the same arguments and in the same order, and changes the score exactly as the **real ARM64 function** does (oracle, section 6).
- **[P]** Reconstructed from Ghidra pseudocode; not confirmed by the oracle.
- **[A]** Assumption without evidence. **[N]** Not modeled (returns 0 or has no effect).

## 1. Results

| | |
|---|---|
| Original AI classes | 7 (`BtlAiBasic`, `Strong`, `Expert`, `Double`, `Allowance`, `Item`, `PokeChange`) + `BattleAi`/`AiWazaJudge`/`AiItemJudge`/`AiPokeChangeJudge`/`BattleAiCommand` (130 commands) |
| Script pseudocode volume | Basic 541 KB (168 functions), Expert 996 KB (256), Double 306 KB (65), Strong 31 KB (3), PokeChange 30 KB (11), Item 20 KB (6), Allowance 5 KB (1) |
| Script functions confirmed by oracle | **66** (Basic 48, Strong 3, Allowance 1, Item 6, PokeChange 8); **4,220 cases compared** (64 pseudo-worlds each; four more Basic cases skipped), zero mismatches |
| Basic: move slots across 706 teams fully covered | **5,623 of 6,085 (92.4%)**: 3,990 slots have no dedicated sequence function (common checks only), 1,633 use an implemented function; 462 (7.6%) reach a missing sequence function |
| Basic: implemented sequence functions | 33 of 148 reachable (`BaciAI_Seq_001, 007, 010–013, 016, 018–020, 028, 032, 033, 035, 037, 047, 049, 065, 084, 092, 106, 109, 115, 132, 136, 148, 158, 160, 188, 211, 212, 225, 251`) |
| Tests (throwaway .NET project `work/dotnet-battleai`, including all Battle* tests from the Unity suite) | **169 passing** (6 new oracle tests and 8 flow tests) |
| First 60 teams (mirror team, greedy player) | Random opponent: opponent wins 8, player 51, draws 1, mean 22.3 turns, 2 NotImplemented. **Trainer AI:** opponent wins 13, player 46, draws 1, **mean 18.9 turns** (1,136 total), **8 NotImplemented**, none unfinished |
| All 706 teams with trainer AI | Opponent wins 143, player 558, draws 5, none unfinished, mean 15.2 turns, 101 NotImplemented, 66 healing items used, 49 voluntary switches |

Measurements are local (`work/battleai-playthrough.txt`; the test `BattleAiPlaythroughLocal` in the throwaway project) and are not in the repository because `work/masterdata` is required. The mirror team and greedy player are test aids, not original behavior. The first 60 teams use only Basic+Double (59) or Basic+Double+Allowance (1); they do not use items or switching.

## 2. Structure: AIBit and script classes

Trainer AI is **not bytecode**; it is code translated from a scripting language into C#. `AiScript.CreateScriptBase` (0x1bc08d0) creates a class for each script number. `TrainerData.AIBit` is a bitmask over those numbers **[P]** (`BtlAiscriptBit` in the dump).

| Bit | Value | Class | Role | Trainers (707 total, 706 with a team) |
|---:|---:|---|---|---:|
| 0 | 1 | `BtlAiBasic` | Base move scoring | 706 |
| 1 | 2 | `BtlAiStrong` | Additional scoring (effectiveness, berries, bonuses) | 92 |
| 2 | 4 | `BtlAiExpert` | Advanced move scoring | 83 |
| 3 | 8 | `BtlAiDouble` | Partner/double-battle scoring | **707** |
| 4 | 16 | `BtlAiAllowance` | Small scoring adjustment | 1 |
| 5 | 32 | `BtlAiItem` | Item use | 89 |
| 6 | 64 | `BtlAiPokeChange` | Switching decision | 89 |

AIBit distribution across 707 trainers: `9` (Basic+Double) 613; `111` (Basic, Strong, Expert, Double, Item, PokeChange) 83; `107` (without Expert) 6; `11` (Basic, Strong, Double) 3; `8` (Double only; trainer has no team) 1; `25` (Basic, Double, Allowance) 1.
Every trainer has the Double bit set. Double scripts also run in single battles (`AISide` 2/3 map to the same Pokémon as 0/1 there **[P]**, `AiScriptCommandHandler.AISideToPokePos`). This was the largest open gap in section 8: `DoubleAI_Enemy_Main` (30 KB) and 36 Enemy sequence functions were missing.

Trainer items: 46 trainers have `UseItem1..4` (among 40 of them, 23 Full Restores, 25 Hyper Potions, 26 Super Potions, 17 Potions); 33 have the Item bit and 13 do not. 56 trainers have the Item bit but no items. `HpRecoverFlag` is 0 for all 707 trainers.

### Script interface

A script interacts with battle only through `BattleAiCommand.AI_CMD(clientId, cmd, long[] args)` (130 commands, `AICmd` enum) and changes its `p_Score` field (+0x14) through `ScoreCtrl`; `SetPokeChangeEnable` sets `p_PokeChangeEnable`.
Commands are mostly queries (type, ability, HP ratio, status, side effect, weather, move effectiveness against the opponent). **AI side** (`ai_side`) [P]: 0 defender (opponent), 1 attacker (own Pokémon), 2/3 their partners, 4 replacement Pokémon (switch/bench commands only).
The script's move index is `WAZADATA.AISeqNo` (`MoveRecord.AiSeqNo`, 252 distinct values among trainer moves); `Calc_BasicAll` and `Expert.main_proc` dispatch to `BaciAI_Seq_NNN` / `ExpertAI_Seq_NNN`.
The oracle measured the AI-number-to-function table (Basic: 196 IDs → 148 functions; Expert: 294 → 223) and embedded it in `AiScriptBasic.SeqDispatch`; a test compares it with `BattleAiDispatch.json`.

## 3. Decision flow (BattleAi, AiWazaJudge) — [P]

`BattleAi.StartActionSelect/UpdateActionSelect` (0x20eb8a0/0x20ebaf0) chooses among five actions: **move, item, switch, run, Struggle** (`AiAction`). Each has a scoring mode (SCORE / PROHIBIT / FORCE) and score, initially PROHIBIT, **100**.

1. `CheckSpecialAction`: setup flags 0x100/0x400 (special battles) force running; these are not set for trainers.
2. **Item** (only if `AIItem_CheckUse` offers one): `AiItemJudge` gives **100 + item-script result** (bit 5; without the bit the score remains 100).
3. **Switch** (non-wild battle, switching allowed, a usable replacement and an opponent): `AiPokeChangeJudge` scores the best approved replacement.
4. **Move**: `AiWazaJudge` uses a target × move matrix, initially **100**, status DISABLE. For each enabled Waza script (bits 0..4, in that order), each selectable move, and each target, it runs the script with `p_Score = 0`; the result is **added** and status becomes NORMAL (`wazaScore_Add`).
   With no selectable moves, choose Struggle (score 100). `wazaScore_DecideBest` selects the highest score among NORMAL entries and **chooses randomly (`Random.GetValue(n)`) among ties**; in double battles, discard ally targets scoring below 100.
5. `DecideAction`: first `GetForcedAction` (priority move, run, item, switch, Struggle = table `{0,3,1,2,4}` from `.cctor`, read from ELF; only run can be FORCE); otherwise `storeBestScoredActions` chooses **randomly among actions tied for the highest score**.

Consequences: Basic mostly applies **penalties** (−1 to −12) to 100. An unaffected move stays at 100, with ties decided randomly. An item or switch scoring 100 ties with a move (an item without the Item bit ties randomly if it is offered at all).
After a Pokémon faints, its replacement is the first able Pokémon **[A]** (`BTL_CLIENT` chooses without a script).
The original AI random sequence (`Random` seeded from battle `randSeed`) comes from battle setup; here AI uses its own generator from the battle seed **[A]**. Decisions follow the same rules, but draws do not match the original.

### Item offers (`BTL_CLIENT.AIItem_CheckUse`, 0x2050060) — [P], priority [A]

For each trainer item (up to four slots), no offer is made with status 0x13 (item lock, WAZASICK 19). Slot *i* counts only if the number of living Pokémon is ≤ `{6,4,2,1}[i]` (blob from ELF). Healing items (`wk_prm_hp_rcv > 0`) are offered only at HP ≤ ¼ maximum HP (`QuotMaxHP_Zero(poke, 4)); status/healing-stat items use `check_cure_sick_item`/`check_status_up_item` (**not implemented**).
If several candidates exist, the one with the highest `tables.GetAIItemPriority` (position in a static table, not extracted) wins. The fallback here is healing amount **[A]**. The selected item is consumed.

## 4. Scripts in detail

### Basic (bit 0) — [O] for 48 functions

`main_proc` (0x198b240): (1) end for double battles and ally targets. (2) Five special checks apply −10 and stop when matched: `Basic_ConaHoushi` (powder against Grass/Heatproof 142), `Basic_Itazuragokoro` (Prankster 158 against Dark), `Basic_Sensei` (priority moves), `Basic_Hayatenotubasa` (Gale Wings 177), `Basic_DaimaxNG` (G moves; ineffective in BDSP, `IF_G` = 0).
(3) For damaging moves, `Calc_BasicDamage`: if the move is **ineffective by type** (`CHECK_WAZA_AISYOU` = factor 0), apply −10 and stop (except Ground versus Levitate with the Mold Breaker group, AI IDs 0x87/0xad/0xde); otherwise check the opponent's defensive abilities: Volt Absorb/Lightning Rod/Motor Drive (−12 for Electric), Water Absorb/Dry Skin/Storm Drain (−12 for Water), Flash Fire (Fire), Wonder Guard 25 (−10 unless super effective), Levitate 26 (−10 for Ground without Gravity), Sap Sipper 157 (Grass).
(4) `Calc_BasicAll`: `Bouon_Check` (Soundproof 43 against sound moves, −10), `Boudan_Check` (Bulletproof 171, −10), then dispatch by `AISeqNo`.
Sequence functions check move-specific effects: stat decreases/increases (Seq 10–13, 16, 18–20, 211, 212: penalize if a stat is already capped or an ability, Mist, or Substitute blocks it); status moves (001, 033, 049, 084, 106, 109: existing status, Safeguard, Grass type versus powder, Insomnia/Leaf Guard, Poison/Steel type); weather (115, 136); Explosion (007: penalty if no replacement Pokémon), and others.

### Strong (bit 1) — [O] for single battles without G mode (3 functions)

`main_proc` (0x1e05e60), `Strong_exception`, `Strong_KinomiCheck`. For moves considered “fatal” (`IF_WAZA_HINSHI`), bonuses depend on AI ID (+3 on random roll 0x80/0xe6; +5/+4 for IDs 0x168/0x67/0x155); apply −1 if another own move would deal more damage (`COMP_POWER`) and no exception/berry applies. An opponent's resistance berry (18 types → item table) makes the move “ineffective”; Ground versus Levitate gets −3; **very effective moves (effectiveness ID > 8, i.e. ≥ 4×) get +2 on random roll 0xb4**.
Not implemented: double-battle branch (`CHECK_BTL_RULE = 1`) and G branch (`IF_GWAZA_USE_TURN`). The oracle test fixes these two command responses for `main_proc` (fixture field `override`).

### Allowance (bit 4) — [O]

For a damaging move: +1 if the opponent lacks `CHECK_NEKODAMASI`; otherwise −1 at low opponent HP (<20% / <40%) with random rolls (220/150 out of 256).

### Item (bit 5) — [O] for `main` and `itemAI_001/023/027/057/059`

Dispatch by item ID (`GET_CURRENT_ITEMNO`): Potions 17/24/25/26 → `itemAI_001`, Full Restore 23, Full Heal 27, X items 57/58/61/62/59. Example Potion: own HP <20% → +10 (with bench Pokémon, first random rolls 0x80/0xaa: +10 / +2); <40% → random rolls 0x80/0x46: +10 or +1; otherwise **−20**.

### PokeChange (bit 6) — [O] for 8 functions (+ indirect `IsAisyou0Bai`)

For each usable replacement (side 4), `main` checks in order: Perish Song ending, opponent's Wonder Guard, type immunity, Choice item with poor type matchup (score `Base + 20`), opponent ability makes the current Pokémon ineffective, Natural Cure, better type matchup. Matches set `PokeChangeEnable` and score `CalcBaseScore + 1` or `+ 20` (random roll 220 or 180). `CalcBaseScore`: 0 or −30 (scenario trainer, switching not allowed), plus a tier based on the replacement's strongest move (+0/+2/+3/`|4`).
Among enabled replacements, choose the highest score (random on ties); score = 100 + script result.

### Double (bit 3) and Expert (bit 2) — originally missing (section 8)

`BtlAiDouble.main` branches through `IF_MIKATA_ATTACK` to `DoubleAI_Enemy_Main`/`DoubleAI_Friend_Main`; `Enemy_Main` checks, among other things, Lightning Rod 31 / Storm Drain 114 / Magic Bounce 156 on the opponent's “partner” (the opponent itself in single battles) and calls 36 Enemy sequence functions. `Expert.main_proc` has a long preamble (item, ability, status checks) and dispatches 294 AI IDs to 223 functions. Of the Expert trainers' 1,427 move slots, 654 (46%) have no dedicated function; the most common (`ExpertAI_Seq_043`) covers 61 slots (4%).

## 5. Script state (`AiWorld`, AI_CMD commands)

`AiWorld` implements commands against `BattleEngine` (single battles). **Evidence [P]** (read from `CMDFUNC_*`), including: type command (`CHECK_TYPE`: selectors 0/1 = type 1 of opponent/self, 2/3 = type 2, 4 = move type), `CHECK_WAZA_AISYOU` (move effectiveness ID against target; expected 9 = “≥ 2×”, 5 = “≤ ½”, 0xe = not applicable), `IF_HP_*` (HP ratio in 1/4096, `IF_HP_EQUAL` rounded up), side effects, weather, `IF_PARA_*` (stat/status stages), replacement count.
**Important:** `CHECK_TOKUSEI` does **not** reveal the opponent's ability except for capture abilities (23, 42, 71) or an already revealed ability (`BattleAiSystem.IsTokuseiOpened`). Otherwise the AI chooses randomly among the species' possible abilities (`PERSONAL` abilities 1–3). The four consecutive queries in `Strong_exception` reveal whether the ability is fixed **[P]**. Here, revelation is inferred from `AbilityActivated` log entries **[A]**.
**[A]/[N]:** Damage for `COMP_POWER`/`GET_MAX_WAZA_POWER` is approximate (level, base power, attack/defense, STAB, effectiveness; no stat modifiers, weather, or abilities) instead of `BattleSimulator.CalcDamage`. Not modeled (returns 0): Substitute, Curse/Perish Song counters, terrain, replacement status checks, G mode (not present in BDSP), Mega Evolution.
The world-command layer itself is **not oracle-verified** (only the script logic above it is); it is the largest source of fidelity risk.

## 6. Oracle (script layer)

`scripts/battle_oracle_ai.py` loads `work/elf/main.patched.elf` in Unicorn and runs the real functions (`main_proc`, `Basic_*`, `BaciAI_Seq_*`, Strong, Item, PokeChange, …). `AI_CMD` (0x20ecdb0) is replaced with a **deterministic pseudo-world**:
response = `f(seed, call number, command)` using SplitMix64; 62.5% small values 0..13, 18.75% a constant from all values ≤1000 in the function text (to exercise ability/move lists too), 9.4% 1, 9.4% 0.
Measurements compare call sequence (command, argument array length and contents; FNV hash), return value, final `p_Score`, and `p_PokeChangeEnable`. Dispatch functions also record which sequence function the real flow entered; cases reaching an unimplemented function are skipped (4 of 3,072 for Basic).
The real `.cctor` fills static fields (side list in `BtlAiPokeChange`). Run:
`PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_ai.py --cases 64 --include scripts/battle_oracle_ai_functions.json`
(The include list names implemented functions; `name@57=0,128=0` fixes command responses; `--trace Class.Function:Seed` shows real calls.)
Fixtures: `BattleAiScripts.json` (163 KB, 66 functions × 64 cases: seed, return, score, call count, hash), `BattleAiDispatch.json` (AI ID → sequence function for Basic and Expert), `BattleAiCmdUsage.json` (command frequency per class in pseudo-runs: Basic uses 47 commands, Expert 53, Double 28, PokeChange 14, Strong 15, Item 4, Allowance 5).
Oracle runs caught, among other things: empty static argument arrays (`CHECK_WORKWAZA_*` use `Empty`), a double read of `CurrentWazaNo`, different sides in `IF_PARA_EQUAL` (side 0 for Seq 18, side 1 for Seq 19/20), and a command called even after a short circuit (`Type(2)` in the Grass check)—details pseudocode alone did not reveal reliably.

## 7. Integration (backward-compatible)

```
BattleSetup.EnemyAi   : IBattleAi   (optional; null = existing RandomEnemyBrain)
BattleSetup.EnemyItems: int[]       (TrainerData.UseItem1..4; AI only)
IBattleAi.Decide(engine, side) -> AiResult {Action, MoveSlot, ItemId, ChangeIndex, Scores[]}
BattleAiBrain : IEnemyBrain          (bridge; the engine creates it when EnemyAi != null)
TrainerAi(aiBits, seed, useItems)    (default implementation; TrainerAi.ForTrainer(0, …) = null)
```

`EnemyBrain` still takes precedence over `EnemyAi`. The engine now permits the opponent's `Item` command (healing items from `EnemyItems` only); `Run` remains forbidden. `Change` was already allowed. All existing battle tests still pass (169 in the .NET project; the 645 Unity tests were not run in the Editor).

## 8. Gaps and effort

| Block | Status | Estimate |
|---|---|---|
| `BtlAiDouble` (bit 3, set for **all** trainers; also affects single battles) | originally missing | 2 days: `DoubleAI_Enemy_Main` (30 KB) + 36 Enemy sequence functions, with oracle |
| `BtlAiExpert` (83 trainers, 256 functions, 996 KB) | originally missing | 4–5 days; about 2–3 days with semi-automatic translation (Ghidra C → C#, oracle as checker) |
| Basic: 115 additional sequence functions (7.6% of move slots; largest: 067, 175, 023, 266, 167, 090, 242) | partial | 1–1.5 days |
| Strong: double-battle and G branches | originally missing | 0.5 day (irrelevant to single battles) |
| AI_CMD: exact damage (`BattleSimulator.CalcDamage`), Substitute, Perish Song, terrain, bench status checks, berry checks, `GetAIItemPriority` table | approximate/[N] | 1–2 days; also needs an oracle for commands, not just scripts |
| AI random sequence matching original (`randSeed`, `Random` per judge) | [A] | 0.5 day; needs real battle setup |
| Wild/Safari AI, raid boss (`wazaScore_DecideRaidBoss`), double-battle targets | missing | outside single-battle scope |

## 9. Tests

- `BattleAiScriptOracleTests` (6): Basic, Strong, Allowance, Item, PokeChange against oracle; dispatch table matches fixture; every implemented sequence function is reachable.
- `BattleAiFlowTests` (8): avoids type immunity (score 90 vs. 100), random tie-breaking, determinism, healing item at low HP, no item at full HP, complete AI battle, trainer without bits → no AI, random opponent remains default without `EnemyAi`.
- Local: `BattleAiPlaythroughLocal` (60 teams × random opponent/trainer AI; all 706 teams with AI).
