# Battle Flow, Slice 5: Handler Effects, Side/Field Effects, Special Moves, Prize Money

As of slice 5, building on `docs/kampf-spezifikation-4.md` (flow state machine). Code: `unity/Assets/Scripts/BattleFlow`
(`BattleEngine.Effects.cs`, `BattleEngine.SpecialMoves.cs`, `PrizeFormula.cs` added; `BattleEngine*.cs`, `BattleMon.cs`, `FlowTypes.cs` extended).
Evidence levels **[O]**, **[OK]**, **[P]** as in spec 2 (section 0): **[P]** = read from Ghidra pseudocode, not confirmed by oracle; **[A]** = assumption without evidence.
Important: slice 3 handler tables act only through event variables; the added **section layer** here (messages, state changes, event calls) is recreated in C# and therefore mostly **[P]**.

## 1. Results in numbers

| | |
|---|---|
| Tests (throwaway dotnet project, including 101 existing Unity-suite battle tests) | 157 passing (144 → 157; 13 new in `BattleFlowEffectTests`) |
| Real trainer teams (local, `work/masterdata`) | **706** available; 694 completed without `NotImplemented` (98.3%); the **first 60** teams: **60/60** without `NotImplemented` |
| Teams whose moves are all supported (static analysis) | 667/706 (94.5%); first 60: 58/60 |
| Special moves in categories 10–13 | about 57 move IDs in `ResolveSpecialMove` |
| New oracle fixtures | none (see section 6) |

Missing moves in trainer teams (ID: occurrences across teams): 164 Substitute (6), 102 Mimic (5), 214 Sleep Talk (5), 580 Grassy Terrain (5), 272 Skill Swap (4), 668 (4), 501 Quick Guard (4), 277 Magic Coat (2), 494 (2), 356 Gravity, 513, 118 Metronome, 286 Imprison, 469 Wide Guard, 472, 604 (one each).

## 2. Handler effects (section layer)

The engine merges slice 3 tables (`TokuseiHandlers`, `ItemHandlers`) with custom effect handlers (`RegisterAbility`/`RegisterItem`; only the first entry per event runs for each factor, so `Merge` avoids duplicates).

| Area | Implementation | Level |
|---|---|---|
| Entry (event `MEMBER_IN`) | Called at battle start (only if a lead has an entry effect, preserving slice 4 random sequence), on switch, and on replacement. Intimidate 22 (opponent Attack −1), weather abilities 2/45/70/117 (Drizzle, Sand Stream, Drought, Snow Warning), berries 155/158 on entry | [P] |
| End of turn (order) | Weather → event 145 (0x91) → status → sides → field → event 146 (0x92) → event 147 (0x93); `Section_TurnCheck_Event` first calls global (ID 0x1f), then each Pokémon in speed order | [P] |
| Event 145 | Leftovers 234 (1/16), Black Sludge 281 (Poison type heals 1/16, otherwise takes 1/8 damage), Wish (position effect), Future Sight (position effect, 3 counters) | [P] |
| Event 146 | Flame Orb 272 and Toxic Orb 273 (self-poison/burn), Shed Skin 61 | [P] |
| Event 147 | End-of-turn check for effects following 146 (order wired; no dedicated handlers) | [P] |
| Weather reaction (event 155) | Weather damage runs through `Event_CheckWeatherReaction`: variables POKEID, WEATHER, `FAIL_FLAG` (rewrite-once), VOLUME; abilities 8/159/81/142/98 (protection from sandstorm/hail) set `FAIL_FLAG`; weather healing/damage 115/44/87/94 | [P] |
| Weather speed | 33/34/146/202 double Speed in matching weather (event `CALC_AGILITY`) | [P] |
| Levitation | `IsFloating` (Levitate 26, Magnet Rise): Ground moves do not affect, entry hazards (Spikes, etc.) do not hit | [P] |
| Berries | Sitrus 158 (25% HP), Oran 155 (10 HP) after damage/on entry; consumption (`ConsumeItem`, log `ItemConsumed`) | [P] |
| Choice items | Choice Band/Scarf/Specs (220/297/287): lock to first move (`ChoiceLock`), lock clears on switch | [P] |
| Life Orb 270 | recoil of 1/10 max HP after damage (Magic Guard 98 blocks it) | [P]; divisor 1/10 read from item handler |
| Survival effects | Stamina, Sturdy 5 (only at full HP), Focus Sash 275 (consumed), Focus Band 230 (chance = `HoldPower`) | [P] |
| Contact abilities | 9/38/49 (30% status on attacker), Rock Head 69 (no recoil) | [P] |
| Other | Synchronize 28, Aqua Ring (condition 36, 1/16), protection from stat drops by 29/73/51/52, immunity abilities 15/72/7/17/41/40/20, Safeguard, Mist, Lock-On (condition 29), and sleep/accuracy ability 99 | [P] |

## 3. Side, field, and special moves

Original side-effect IDs (`work/battleevents/handler_map.json`): 0 Reflect, 1 Light Screen, 2 Safeguard, 3 Mist, 4 Tailwind, 5 Crafty Shield (not implemented), 6 Spikes, 7 Toxic Spikes, 8 Stealth Rock, 14 Sticky Web, 17 Aurora Veil.

| Effect | Duration / rule | Level |
|---|---|---|
| Reflect, Light Screen, Aurora Veil | 5 turns; event 90 with factor 0x800 (single battle), only for matching damage category and no critical hit; once per hit (helper variables 100/101) | [P] |
| Safeguard, Mist | 5 turns; Safeguard blocks major status and confusion from opponent's side, Mist blocks stat drops | [P] |
| Tailwind | `MakeTurn(…,4)`, Speed ×2 (factor 0x2000, event 19) | [P] |
| Spikes | Layers 1–3: 1/8, 1/6, 1/4 max HP on entry; does not affect levitating Pokémon | [P] |
| Toxic Spikes | 1 layer poisons, 2 layers badly poison (`MakeMoudokuCont`); Poison types absorb them | [P] |
| Stealth Rock | Divisor from table `{256,256,128,64,32,16,8,4,2,1,1,1,1}` (type effectiveness, read from ELF `DAT_03e59d2c`) | [OK] (table read); application [P] |
| Sticky Web | Speed −1 on entry | [P] |
| Room effects | Trick Room (433): FIELD factor on event 19 sets `TRICK_FLAG`; lasts 5 turns; setting it again ends it **[A]** | [P] |

Special moves (`BattleEngine.SpecialMoves.cs`): Protect 197/182/596/673 (repeat success 1/3ⁿ, **[A]**; fails if used last in turn), Endure 203, Curse 174 (Ghost/non-Ghost), Taunt 269 (3 or 4 turns, turn **[P]**), Focus Energy 116, Rest 156, Aqua Ring 392, Haze 114, trapping moves 212/335, Roar/Whirlwind 46/18 (wild battle: end battle with `RunEnemy`), Future Sight 248, Baton Pass 226; Torment (condition 23, 3 turns **[A]**) and Disable (condition 13, 4 turns **[A]**) block moves in `ExecuteFight`/`CheckFirstFail`, plus moves with IDs 194, 487, 100, 199, 170, 244, 384, 187, 504, 220, 273, 215, 432, 367, 180, 271, 415, 393, 262, 150 (Splash), 227, 50, 383, 254, 502/270/266 (without a partner: `NoTarget`).
Share of move slots in categories 10–13 across the 706 teams is about 11%.

## 4. Prize money and wild encounters

**Prize money (`calc.CalcWinMoney`, 0x2076980 / `calcWinMoney_Sub` 0x2076900) [P]:** only for trainer opponents (`competitor == 1`):
`(Gold & 0xFF) × level of the LAST opposing party member × 4`; in double battles (parties with ≥ 4 slots), add the second opponent's amount. `Gold` is `TrainerData.Gold`.
It is calculated when the battle starts (`MainModule.InitializeCoroutine`), but here on victory (`BattleEngine.PrizeMoney`, log `PrizeMoney`). Not modeled: money-doubling items (Amulet Coin) and payout, which are outside the battle module and could not be verified.

**Loss (`CalcLoseMoney` → `CalcPenaltyMoney`, 0x2076c60) [P]:** highest level in player's party × `Table[Badges]` × 4, capped at current money; badge count outside table (length 9) throws an error in the original.
The table is a statically initialized byte array (`RuntimeHelpers.InitializeArray`, data block not read). **[A]:** `{2,4,6,9,12,16,20,24,36}` from predecessor games — `BattleSetup.PenaltyTable` will override it once actual values are read.

**Wild encounters (gap):** generation (nature, stats, ability, gender, encounter-slot randomization, level) is in `EncountTool`/`Pml.PokePara.InitialSpec`, not in the pseudocode analyzed (`work/decomp/battle_all` contains only `Dpr.Battle.*`).
`PokemonFactory.CreateWild` remains a helper **[A]**. Caller must provide species, form, and level. Estimate: about 1–2 days (decompile encounter classes, oracle for `InitialSpec`).

## 5. Opponent AI (gap, with findings)

Trainer AI is **not bytecode**; it is compiled C# code: `AiScript.CreateScriptBase` (0x1bc08d0) creates one of `BtlAiBasic`, `BtlAiStrong`, `BtlAiExpert`, `BtlAiDouble`, `BtlAiAllowance`, `BtlAiItem`, `BtlAiPokeChange` depending on bits.
Pseudocode size: Basic 541 KB, Expert 996 KB, Double 306 KB, Strong/Item/PokeChange 20–31 KB each; plus `BattleAiCommand` (310 KB) and `AiWazaJudge` (47 KB).
In principle, everything can be derived, but it is not “clear and small”: this is a scoring system (script commands raise/lower each move's score, select highest score with random tie-break) with about a hundred commands and dozens of checks (type effectiveness, damage from `BattleSimulator`, weather, status).
This was **not implemented** in slice 5; see slice 6, `docs/kampf-spezifikation-6.md` (structure, scoring, Basic/Strong/Allowance/Item/PokeChange implemented and oracle-checked; Expert and Double were open). `RandomEnemyBrain` remains the default; `IEnemyBrain` is the interface. Estimate: Basic/Strong about 2 days, Expert + Double about 3–4 days, item/switch AI (`AiItemJudge`, `AiPokeChangeJudge`) about 1 day; oracle is useful only for individual calculation commands.

## 6. Verification

- Oracle: **no** new fixtures for this slice — section-level behavior and prize money are supported only by pseudocode; the arithmetic parts (Stealth Rock table, 1/8·1/6·1/4, prize formula) are simple integer formulas tested in `BattleFlowEffectTests`. Oracle (`scripts/battle_oracle_flow.py`, 5,900 cases) remains green.
- New tests (`BattleFlowEffectTests`, 13): Reflect halves damage (same random sequence), Reflect ends after 5 turns, Stealth Rock on entry, Spikes layers, Protect, Trick Room, Intimidate, Drizzle, Leftovers, Choice lock, prize money (trainer and wild), loss penalty.
- Local (not in repository test, because it needs `work/masterdata`): `BattleFlowPlaythroughLocal` runs all 706 teams, output in `work/battleflow-playthrough.txt`.

## 7. Remaining gaps and estimates

| Area | Status | Estimate |
|---|---|---|
| Substitute 164, Mimic 102, Sleep Talk 214, Skill Swap 272, Magic Coat 277, Imprison 286, Metronome 118, Quick/Wide Guard 501/469, terrain 580/604/472, Gravity 356 | not implemented | 1–2 days |
| Remaining items/abilities (see `work/battleflow-coverage.txt`: e.g. status berries, stat berries, trainer items) | partial | 2 days |
| Opponent AI | section 5 | 6–8 days |
| Wild generation | section 4 | 1–2 days |
| Double battles, capture, learning, evolution | as in spec 4, section 12 | unchanged |
