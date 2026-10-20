# Battle Flow, Slice 7: Complete Opponent AI (Double, Expert, Remaining Basic, Strong Double Branch)

As of slice 7, building on `docs/kampf-spezifikation-6.md` (Basic/Strong/Allowance/Item/PokeChange implemented there; open items were Double, Expert, 115 Basic-Seq functions, and the Strong double branch).
Code: `unity/Assets/Scripts/BattleFlow/Ai/` (handwritten: `TrainerAi.cs`, `AiWorld.cs`, `AiScriptBase.cs`, `AiScriptBasic.cs`, `AiScriptsOther.cs`; **generated**: `Generated/AiScriptDouble.cs`, `AiScriptExpert.cs`, `AiScriptBasicGen.cs`, `AiScriptStrongFull.cs`).
Tool: `scripts/ai_translate/` (pseudocode → C#); oracle: `scripts/battle_oracle_ai.py` (Unicorn, real ARM64 functions). Evidence levels as in spec 6 (**[O]** oracle-confirmed, **[P]** read from pseudocode, **[A]** assumption, **[N]** not modeled).

**Repository rule (user decision: original formulation only, no translated game code in the repository):** `Generated/` is mechanically translated from pseudocode and therefore gitignored; it is produced at build time from the user's own dump (planned build stage `ai_translate`, requires Ghidra pseudocode export). The repository contains only the translator, oracle, numeric fixtures, and handwritten parts. `AiGenerated.Create` loads generated classes via reflection (`link.xml` preserves `Assembly-CSharp`; the battle assembly is project code); if they are missing, the game still builds, oracle tests are skipped, and trainers with Expert/Double bits do not get that AI layer.

## 1. Results in numbers

| | Spec 6 | Slice 7 |
|---|---|---|
| Script classes implemented (bits in 706 trainer teams) | Basic, Strong (singles only), Allowance, Item, PokeChange | **all seven**: plus **Double (706 trainers)**, **Expert (83)**, Strong with double and G branches |
| Oracle-confirmed functions (entries) | 66 | **505 functions**: Basic 167 (all 148 reachable Seq functions + 15 helpers + `main_proc`), Double 65, Expert 255, Strong 3, Allowance 1, Item 6, PokeChange 8 |
| Oracle cases compared (pseudo-worlds) | 4,220 | **11,300**, 0 mismatches, 0 skipped |
| Basic: Seq functions implemented | 33 of 148 (7.6% of move slots were no-ops) | **148 of 148**: 119 generated, 33 handwritten; slots with no effect: 0 |
| Script volume as C# | about 60 KB handwritten | +137 KB Double, 361 KB Expert, 92 KB remaining Basic, 15 KB Strong (generated) |
| `UnimplementedScriptBits` (set AI scripts not implemented) | 2 (Expert, Double) | **0** |
| Tests in throwaway dotnet project (all Unity-suite battle tests) | 169 | **174 passing** (4 new oracle tests for Double/Expert/Strong/Basic-Seq, 1 flow test with all scripts) |

Run across all 706 teams (mirror teams, greedy player; measurement helper `BattleAiPlaythroughLocal`, not in repository because `work/masterdata` is required):

| | Opponent wins | Player wins | Draws | Unfinished | Avg. turns | NotImplemented | Items | Switches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Random opponent | 111 | 587 | 8 | 0 | 15.7 | 91 | – | – |
| Slice 6 trainer AI | 143 | 558 | 5 | 0 | 15.2 | 101 | 66 | 49 |
| **Slice 7 trainer AI** | **163** | 537 | 6 | **0** | 15.0 | **83** | 69 | 46 |

First 60 teams: random opponent 8 wins / 22.3 average turns; slice 6 trainer AI: 13 wins / 18.9 average; **slice 7: 16 wins / 18.8**, NotImplemented 4 (previously 8).

`NotImplemented` counts battle-**engine** failures (`FailCause.NotImplemented`: the selected move needs a handler/section that does not yet exist), not AI scripts; all AI scripts themselves have been covered since this slice. Random opponents show nearly the same count at 91 (the AI does not choose unfinished moves more often). There are only **11 distinct moves** (IDs across all 706 teams using trainer AI): 214 (30×), 272 (12×), 118 (10×), 164 (8×), 102 (6×), 286 (6×), 580 (4×), 604 (3×), 277 (2×), 494 (1×), 668 (1×). Fixing them belongs to the engine (`BattleEngine.SpecialMoves`), not AI.

## 2. Method: pseudocode → C# (instead of hand-writing 440 functions)

Hand translation is not feasible or verifiable for another 440 functions (Double 65, Basic 115, Expert 256). The scripts themselves are C# code represented as IL2CPP pseudocode; a tool (`scripts/ai_translate/`: `ghc_parse.py` parser and noise removal, `ghc_emit.py` emitter, `ai_translate.py` class generation) translates it, and the **oracle checks each function individually against the real ARM64 function**. The tool reads only `work/decomp/battle_all` (pseudocode, not in repository) and the oracle (static numeric fields from ELF); generated files contain command sequences, constants, and script control flow, no game data or text.

What the tool does:

- **Parser** for the C subset used here (expressions with casts, pointer access, comma operator; `if/else`, `goto`, labels, `switch`).
- **Noise removal**: class initialization (`DAT_… & 1`, `FUN_00359b58`, accesses to +0x12e/+0xe0), debug output (`PRINTF`, `String.Format`, boxing)—except `CurrentWazaNo` calls inside debug output, which execute as real `AI_CMD`s (without them, call order differs from `BtlAiDouble.main`; oracle found this); argument-array bounds checks (`if (len < 3 || (arr[2] = x, len == 3)) goto ERROR`) become the included assignments; error tails (`thunk_FUN_0035c83c; FUN_003afbc0`) are removed.
- **Array flattening**: `a = new long[n]; a[0] = x; …; r = Call(cmd, a)` → `r = C(cmd, n, x, …)` (length `n` remains part of call order); if it cannot be done unambiguously (array reused across labels), keep a real array `aA`. The oracle reads static numeric fields (`InitializeArray`) from ELF and inserts them as constants; it also supplies the Expert type-check score tables (11 tables with values −1/+1).
- **Type fidelity**: preserve Ghidra variable types (int/uint/long/ulong); `x - 0x68U < 0x3d` stays unsigned; bit-mask idioms `(1L << (x & 0x3f)) & M` become `Bit(x, M)`.
- **Goto-faithful control flow**: C# allows `goto` only into enclosing blocks; an `if` stays structured if all labels visible in it are only targeted from within, otherwise flatten to `if (!c) goto …`. Original jump-table `switch` becomes `switch … goto` with merged cases.
- Entry points (`Run(name)`) and name list (`Functions`) are generated; no reflection (to avoid IL2CPP stripping).

Invocation `PYTHONPATH=tools/pydeps python3 scripts/ai_translate/ai_translate.py` writes to `unity/Assets/Scripts/BattleFlow/Ai/Generated/`. One location could not be read automatically: `DoubleAI_Friend_Main` dispatches AI IDs 0x181–0x189 through a jump table (Ghidra: “indirect jump”); oracle measured the mapping (385, 386→309, 388, 391, 393→309), which is encoded in the tool.

## 3. Double (bit 3, all 706 trainers) — [O]

`BtlAiDouble.main` (0x1d0b560): `IF_MIKATA_ATTACK` (target is partner) → `DoubleAI_Friend_Main`, otherwise `DoubleAI_Enemy_Main`. In **single battles**, `IF_MIKATA_ATTACK` is always 0, so only the Enemy branch runs; the Friend branch is still implemented and tested for doubles.

- `DoubleAI_Enemy_Main`: preamble checks opponent abilities (Lightning Rod 31, Storm Drain 114, Magic Bounce 156, etc.; −10 for matching move types and AI IDs, several random rolls), then dispatch by AI ID (`switch` across ranges) to Enemy Seq functions. 42 AI IDs map to 41 Enemy functions (`BattleAiDispatchDouble.json`, key `BtlAiDouble.Enemy`, measured by oracle); largest: 111 (18 KB), 195 (22 KB with subfunction), 147, 172, 378.
- `DoubleAI_Friend_Main`: 21 AI IDs map to 20 Friend functions (partner support, e.g. healing moves on partner, wind moves).
- Oracle runs all 66 functions in 16 pseudo-worlds each; both dispatchers additionally run with **fixed AI ID** (`DoubleAI_Enemy_Main@62=k` for 44, `DoubleAI_Friend_Main@62=k` for 22 IDs), ensuring every dispatcher branch actually executes: 131 entries, **2,096 cases, 0 mismatches**.

## 4. Remaining Basic and Strong double branch — [O]

The 115 missing Basic Seq functions are generated (`AiScriptBasicGen.cs`, 119 functions including helpers, registered through `partial void RegisterGenerated()`); the 33 handwritten functions remain and are called by generated code (`Seq0NN`). Fixture `BattleAiScriptsBasicSeq.json` (152 Seq functions, 1,824 cases) and the older `BattleAiScripts.json` (48 functions, now with **no** skipped cases, previously 4) match. Largest formerly missing functions (067, 175, 023, 266, 167, 090, 242) are included.

`BtlAiStrong` is now complete (`AiScriptStrongFull`, 3 functions, 192 cases without fixed command responses, therefore **including** double branch `CHECK_BTL_RULE = 1` and G branch). Handwritten `AiScriptStrong` (single battles only) remains as a reference with its old test; `TrainerAi` uses `AiScriptStrongFull`.

## 5. Expert (bit 2, 83 trainers) — [O]

`ExpertAI.main_proc` (0x1d1ab60): long preamble (item, ability, and status checks), dispatch from 294 AI IDs to 223 functions; `ExpertAI_TypeCheck(param)` (25 calls) evaluates 11 score tables per weather/type group. **All 257 functions** are implemented (Seq functions, subfunctions, `…Pokemon` helpers such as `CopyPokemonTokusei`, `MegaShinkaPokemon`); oracle: 255 functions, 3,060 cases, 0 mismatches (`TypeCheck` is checked through its callers). The gap list estimated in spec 6 (46% of Expert move slots without a function) is now obsolete. Bugs found during development (all by oracle): `break` in nested `if` inside `switch`, `byte` argument type for `TypeCheck` (truncation of 0x50e0a09 to 9), length variable also used as move ID (`iVar2 = *(int*)(arr+0x18)` → constant).

## 6. AiWorld (query commands) and damage

**Damage [P]:** `COMP_POWER`, `GET_MAX_WAZA_POWER`, and new `IF_WAZA_HINSHI` use the real `DamageCalculator` (`BattleEngine.EstimateDamageForAi`: `Launcher.BuildDamageInput` with weather, stages, STAB, type effectiveness, burn; **fixed random factor 85, no critical hit**, `DamageInput.FixedRoll`—in the original only the AI simulator sets this flag). The previous approximation is removed. Ability/item handlers outside the effect ID are not included unless the launcher accounts for them **[A]**.

**New commands:** `IF_WAZA_HINSHI`/`IFN_` (damage ≥ opponent HP) [P], `IF_HINSHI`, `IF_HAVE_WAZA`/`IF_HAVE_WAZA_SEQNO` (own side: all moves, opponent: only moves already used—`CheckWazaStored`, from battle log) [P], `IF_COMMONRND_*` (shared random value for the turn) [P/A], `CHECK_AGI_RANK`, `CHECK_MAMORU_COUNT`, `CHECK_LAST_WAZA_KIND`, `CHECK_STATUS`, `IF_DMG_PHYSIC_*` (physical attack vs. Sp. Atk with stages) [P], `IF_DOKUDOKU` (poison with badly-poisoned counter), `IF_BENCH_PPDEC`. Every one of the 100 commands actually called by scripts now has a `case` (several were missing before). Overall 110 of 130 command IDs have a `case` (the 20 without one are never called by scripts; they return 0); **[N]** (intentionally return 0, 16 commands): `IF_CONTFLG`, 18/19 (Perish Song), `IF_BENCH_DAMAGE_MAX`, `CHECK_SLOWSTART_TURN`, `GET_MEZAME_TYPE`, `IF_WAZAHIDE`, `IF_ALREADY_MORAIBI`, `COMP_POWER_WITH_PARTNER`, `CHECK_NEKODAMASI`, `CHECK_RECYCLE_ITEM`, `IF_TOTTEOKI`, `IF_MIGAWARI`, `IF_EXIST_GROUND`, `CHECK_WAZA_NO_EFFECT_BY_TOKUSEI`, `IF_ZIDANDA_POWERUP`.

**Command oracle: not implemented.** `CMDFUNC_*` access `BTL_POKEPARAM` through `GetBppByAISide` (core parameters +0x10 with HP at +0x26, status array +0x48, move list +0x30, rank values +0x18/+0x20 …) and `BattleSimulator`. In the emulator they ran only with a Pokémon and battle environment built in guest memory (`GuestHeap` from `battle_oracle_heap.py` can construct objects from the dump; nested fields in `BTL_POKEPARAM` are not yet consistent). Roughly 1–2 days for about 40 read-only commands (type, ability, HP, rank, status, move list); damage/order also require `BattleSimulator`. Until then the command layer remains the largest source of fidelity errors (unchanged from spec 6).

## 7. Randomness

The AI random generator is the original's Xoroshiro128+ (`Dpr.Battle.Logic.Random`, already `BattleRandom`). **[P]** `BattleAi.ctor` (0x20eb…) creates its **own** `Random` and initializes it from the battle setup's `randSeed` (`Random.Initialize(setup+0x28)`), not by mixing with a constant; `TrainerAi` now seeds with `BattleSetup.Seed` (previously `Seed ^ 0xA1A1A1A1`). The shared value for `IF_COMMONRND_*` comes in the original from `BTL_CLIENT` randomness (+0x90, `GetValue(0x100)`); its seed and exact order of rolls per move/script (order of `wazaScore_DecideBest`, script rolls, ability rates) are **[A]**: decisions match, but not roll-for-roll with the original. Deriving that would require the original battle setup (order of judge calls, `BTL_CLIENT` seed).

## 8. Gaps

| Area | Status |
|---|---|
| Oracle for 130 `CMDFUNC_*` (`AiWorld` command layer) | not implemented (section 6); 16 commands intentionally [N] (return 0) |
| AI random sequence, roll-for-roll | generator and seed [P], roll order and `BTL_CLIENT` randomness [A] |
| Damage: ability/item handlers in `BattleSimulator.CalcDamage` | only those handled by `Launcher.BuildDamageInput` |
| Double battles in `TrainerAi` (target selection, `IF_MIKATA_ATTACK`) | scripts implemented and checked; `AiWorld`/`TrainerAi` model singles only |
| Engine `NotImplemented` (11 moves, section 1) | engine issue, not AI |
| Wild/Safari AI, raid boss | as in spec 6, out of scope |

## 9. Verification

- `BattleAiScriptOracleTests`: Basic (48 functions, 3,072 cases), remaining Basic/Seq (152, 1,824), Double (131, 2,096), Expert (255, 3,060), Strong (3, 96) and full Strong (3, 192), Allowance, Item, PokeChange; dispatch table; every dispatch ID maps to an implemented function.
- `BattleAiFlowTests`: one full battle using all seven scripts (reproducible, `UnimplementedScriptBits == 0`).
- Fixtures (numbers only): `BattleAiScriptsDouble/Expert/StrongFull/BasicSeq.json`, `BattleAiDispatchDouble.json`. Generation instructions are at the top of `scripts/battle_oracle_ai.py` (per-class calls with `--suffix`; include-file entries may be patterns, `name@62=k` fixes the AI ID). Regeneration produces byte-identical files.
- Local: `BattleAiPlaythroughLocal` (60 teams, all 706 teams, random opponent and trainer AI, NotImplemented per move).
