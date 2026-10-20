# Battle Mathematics, Slice 1: Specification

Status: Slice 1 interim results (pure battle mathematics only; no rendering or audio).
This document is a specification written in my own words. The C# implementation (`unity/Assets/Scripts/Battle`, assembly
`Xnu.Battle`) was derived exclusively from this text, not copied from the pseudocode.

## 0. Method and evidence conventions

- **Source:** decompiled functions from the game binary (`work/elf/main.patched.elf`, Ghidra project `work/ghidra/bdsp`,
  exports under `work/decomp/battle1*`), and types/field offsets from `work/il2cpp/dump.cs`.
- **Evidence:** `[Class.Method @0xADDRESS]`; the address is the Ghidra address (Il2CppDumper RVA + `0x100000`).
  Statements about order refer to the call order in the cited function.
- **Verification level for each statement:**
  - **[O]** confirmed by the emulation oracle: the real ARM64 function ran in Unicorn; inputs and outputs are stored
    numerically in `unity/Assets/Tests/EditMode/Fixtures/*.json` and checked against the C# implementation by Unity tests
    (section 9).
  - **[OK]** oracle with substituted state functions (composite oracle): the real function body ran, but game state and
    handlers (abilities, items, moves) were replaced by test inputs.
  - **[P]** read from pseudocode only and checked with hand-calculated examples.
- Internal names of original classes (Japanese abbreviations such as `Seikaku` = nature, `Sakasa` = reversed/Inverse Battle,
  `Koraeru` = Endure, `Migawari` = Substitute) are used only in evidence references.

## 1. Numeric conventions in the original

- All battle calculations use **32-bit integers** (IL2CPP, ARM64). Where a function returns `ushort`/`byte` or masks
  parameters with `& 0xffff`, this is stated explicitly below. Overflow wraps modulo 2^32 (no check).
- **Division always rounds down** (integer division on unsigned values where the original uses `uint`).
- **Fixed point “x/4096”** (ratios): `0x1000` = 1.0; `0x1800` = 1.5; `0x2000` = 2.0; `0x0800` = 0.5; `0x0C00` = 0.75; `0x1333` ≈ 1.2.
  `MulRatio` multiplies and divides by 4096 using **round half down**:
  `p = (a*b) mod 2^32; r = p >> 12; if (p & 0xfff) > 0x800: r += 1` [O, `calc.MulRatio @0x2074b00`]. Thus an exact `0x800` remainder rounds down.
  `MulRatio_OverZero @0x2074b20` does the same but returns at least 1 [O].
  `MulRatioInt @0x2074bb0`: `p = (a*b) mod 2^32; r = p / 100; if p % 100 > 49: r += 1` (percent, “round half up”) [O].
- **Event variables** (handler ratios, section 5) use a different rounding rule: `EVENTVAR_MulValue` computes in 64 bits
  `v = (v * f + 0x800) >> 12` (**round half up**) and clamps the result to `[min, max]` if either bound is nonzero
  [P+OK, `EventSystem.EVENTVAR_MulValue @0x19f5fc0`; hit fixtures use this rule].
- **Type IDs** (`PokeType`): 0 Normal, 1 Fighting, 2 Flying, 3 Poison, 4 Ground, 5 Rock, 6 Bug, 7 Ghost, 8 Steel, 9 Fire,
  10 Water, 11 Grass, 12 Electric, 13 Psychic, 14 Ice, 15 Dragon, 16 Dark, 17 Fairy, 18 = “no type” (`NULL`) [`dump.cs` `PokeType`].

## 2. Type chart and type effectiveness

### 2.1 Chart (in code, not in the bundle)

`Pml.Battle.TypeAffinity.TYPE_AFF_TBL` is a `byte[18][18]`, built by the class constructor
[`TypeAffinity..cctor @0x1c29e00`]. Each row comes from an initializer blob in the metadata; I ran the real `.cctor`
in Unicorn and read out all 18 rows (fixture `BattleTables.json`, `typeChart`) [O]. Rows are attacking types, columns are
defending types. Values: `0` = no effect, `2` = half damage, `4` = normal, `8` = double damage (constants `x0/xH/x1/x2`).
The chart matches the familiar Generation VI chart (including Fairy; Ghost and Dark are neutral against Steel).

Encoding of the 18 rows (columns in type ID order 0..17):

```
Normal : 4 4 4 4 4 2 4 0 2 4 4 4 4 4 4 4 4 4
Fighting: 8 4 2 2 4 8 2 0 8 4 4 4 4 2 8 4 8 2
Flying : 4 8 4 4 4 2 8 4 2 4 4 8 2 4 4 4 4 4
Poison : 4 4 4 2 2 2 4 2 0 4 4 8 4 4 4 4 4 8
Ground : 4 4 0 8 4 8 2 4 8 8 4 2 8 4 4 4 4 4
Rock   : 4 2 8 4 2 4 8 4 2 8 4 4 4 4 8 4 4 4
Bug    : 4 2 2 2 4 4 4 2 2 2 4 8 4 8 4 4 8 2
Ghost  : 0 4 4 4 4 4 4 8 4 4 4 4 4 8 4 4 2 4
Steel  : 4 4 4 4 4 8 4 4 2 2 2 4 2 4 8 4 4 8
Fire   : 4 4 4 4 4 2 8 4 8 2 2 8 4 4 8 2 4 4
Water  : 4 4 4 4 8 8 4 4 4 8 2 2 4 4 4 2 4 4
Grass  : 4 4 2 2 8 8 2 4 2 2 8 2 4 4 4 2 4 4
Electric: 4 4 8 4 0 4 4 4 4 4 8 2 2 4 4 2 4 4
Psychic: 4 8 4 8 4 4 4 4 2 4 4 4 4 2 4 4 0 4
Ice    : 4 4 8 4 8 4 4 4 2 2 2 8 4 4 2 8 4 4
Dragon : 4 4 4 4 4 4 4 4 2 4 4 4 4 4 4 8 4 0
Dark   : 4 2 4 4 4 4 4 8 4 4 4 4 4 8 4 4 2 2
Fairy  : 4 8 4 2 4 4 4 4 2 2 4 4 4 4 4 8 8 4
```

(The rows were read directly from the binary. Cross-checks: Normal→Ghost 0, Ghost→Normal 0, Ground→Flying 0,
Electric→Ground 0, Psychic→Dark 0, Dragon→Fairy 0, Poison→Steel 0.)

### 2.2 Single defending type: `CalcAffinity(wazaTyp, pokeTyp, reversed)` [O, `@0x1c296c0`]

1. If either type is 18 (no type), the result is **ID 7** (= neutral), without reading the chart.
2. Otherwise, chart value `t = TYPE_AFF_TBL[wazaTyp][pokeTyp]`:
   - normal battle: `0 → ID 0`, `2 → ID 6`, `4 → ID 7`, `8 → ID 8`;
   - reversed battle (`isSakasaBattle`, “Inverse Battle”): `0 → ID 8`, `2 → ID 8`, `4 → ID 7`, `8 → ID 6`.
3. Types outside 0..17 (except 18) throw an exception in the original (not modeled here).

**Affinity IDs** (`TypeAffinity.AffinityID`): `0` = ×0, `1` = ×1/64, `2` = ×1/32, `3` = ×1/16, `4` = ×1/8, `5` = ×1/4, `6` = ×1/2,
`7` = ×1, `8` = ×2, `9` = ×4, `10` = ×8, `11` = ×16, `12` = ×32, `13` = ×64, `14` = “no value” (`TYPEAFF_NULL`).
The internal table is `VALUE_TABLE = {0,1,2,4,8,16,32,64,128,256,512,1024,2048,4096}` (ID → 64 × factor) [O, read from the `.cctor`].

### 2.3 Two types: `MulAffinity(a, b)` [O, `@0x1c298c0`]

`MulAffinity` multiplies two IDs: `p = VALUE_TABLE[a] * VALUE_TABLE[b]`.
- If `p < 0x40040`: `v = p >> 6`; if `v == 0` even though both IDs are nonzero (factor below 1/64), set `v = 1` (the original emits an assertion message but continues).
- Otherwise, `v = 0x1000` (saturation at ×64).
- Result: if `a == 0` or `b == 0` → **ID 0**. Otherwise, take the position `k` of the least significant set bit in `v` (zero-based) plus 1;
  thus `v = 64 → ID 7`, `v = 128 → ID 8`, `v = 1 → ID 1`, and `v = 0x1000 → ID 13`.
- Inputs ≥ 14 throw an exception in the original (not modeled here).

The Pml overload `CalcAffinity(wazaTyp, typ1, typ2, reversed)` [`@0x1c29810`] multiplies **both** individual values without checking for duplicates.
Battle code itself uses `calc.TypeAffPair` (next item).

### 2.4 Battle variant: `calc.TypeAffPair(wazaTyp, PokeTypePair)` [P, `@0x2074300`]

`PokeTypePair` is a 16-bit packed value: bits 0–4 type 1, bits 5–9 type 2, bits 10–14 additional type (e.g. from moves such as Halloween,
`PokeTypePair.Split @0x21ce620`). Steps:
1. `aff = CalcAffinity(waza, typ1, reversed)`.
2. If `typ2 != 18` **and** `typ2 != typ1`: `aff = MulAffinity(aff, CalcAffinity(waza, typ2))`.
3. If `additional != 18` **and** `additional != typ1` **and** `additional != typ2`: `aff = MulAffinity(aff, CalcAffinity(waza, additional))`.
The “reversed” flag is `calc.g_SakasaBtlFlag`, set by `calc.InitSys(random, sakasa)` [`@0x2073f40`].
A single-type Pokémon has type 2 equal to type 1 (or 18), so it is not counted twice.

`ConvAboutAffinity(id)` [`@0x1c29b60`] provides a coarse display category: `id > 7 → 2` (effective), `id == 7 → 1`, `id == 0 → 0`,
otherwise `3` (not very effective). `calc.GetResistTypes` [`@0x2074660`] returns all attacking types whose ID against the single type is 0 or 6.

### 2.5 Apply effectiveness to damage: `calc.AffDamage(raw, id)` [O, `@0x2074820`]

- `id = 0 → 0`; `id = 1..6 → raw >> (7 - id)` (arithmetic right shift, so round down: 1 → >>6, 6 → >>1);
- `id = 8..13 → raw << (id - 7)` (32-bit, overflow wraps);
- any other ID (7, ≥ 14) → `raw` unchanged.

## 3. Stats and natures

### 3.1 Nature table [O]

25 natures (`Seikaku` IDs 0..24; enum names GANBARIYA, SAMISHIGARI, YUUKAN, IJIPPARI, YANTYA, ZUBUTOI, SUNAO, NONKI, WANPAKU, NOUTENKI,
OKUBYOU, SEKKATI, MAJIME, YOUKI, MUJYAKI, HIKAEME, OTTORI, REISEI, TEREYA, UKKARIYA, ODAYAKA, OTONASHII, NAMAIKI, SINTYOU, KIMAGURE;
this is the familiar order Hardy, Lonely, Brave, … Quirky). The `Pml.PokePara.CalcTool` table has 25 rows of five `sbyte` values (columns: Attack, Defense, Special Attack, Special Defense,
Speed). `+1` means increased, `-1` decreased, `0` unchanged [`CalcTool..cctor @0x25aec40`, read from the real `.cctor`,
fixture `BattleTables.json`, `natureTable`]. Neutral natures: IDs 0, 6, 12, 18, 24 (all entries zero). Every other nature raises one stat and
lowers one stat, with one `+1` and one `-1` in each row; all rows are in `BattleTables.json`.
Mapping from “power ID” (`powerId`) to column: `1 → Attack`, `2 → Defense`, `3 → Sp. Attack`, `4 → Sp. Defense`, `5 → Speed`
(column = `powerId - 1`); values outside 1..5 mean “no nature effect” [O, `GetPowerTransformBySeikaku @0x25ad6c0`].

### 3.2 Nature adjustment [O, `CalcCorrectedPowerBySeikaku @0x25ad2c0`]

Given `value` (32-bit), nature `n`, and `powerId`:
- If `powerId` is not in 1..5 or the table entry is 0, return `value` unchanged.
- Entry `-1`: `((value * 90) & 0xfffe) / 100`; entry `+1`: `((value * 110) & 0xfffe) / 100`.
Notably, the product is **masked with `0xfffe`** (16-bit, low bit cleared) before division by 100. For real stats (<596) the mask changes nothing
except rounding down an odd product; from value 596 onward (the +10% product reaches 65,536), it wraps. This behavior is reproduced exactly; fixtures
test values through 65,535. The stat functions return `ushort`.

### 3.3 HP and other stats [O]

Inputs are masked: base stat and IV with `& 0xffff`, level with `& 0xff`, EV as `(ev & 0xfffc) >> 2` (that is, `floor(ev/4)` using a
16-bit input).
- **HP** `CalcMaxHp(monsno, level, base, iv, ev)` [`@0x25ad1b0`]: if `monsno == 292` (National Pokédex #292, Shedinja, fixed 1 HP), return **1**.
  Otherwise: `((2*base + iv + ev/4) * level) / 100 + level + 10`.
- **Attack / Defense / Special Attack / Special Defense / Speed** [`CalcAtk @0x25ad200`, `CalcDef @0x25ad3c0`, `CalcSpAtk @0x25ad480`,
  `CalcSpDef @0x25ad540`, `CalcAgi @0x25ad600`]: `raw = ((2*base + iv + ev/4) * level) / 100 + 5`, then apply the nature adjustment (3.2)
  with `powerId` 1, 2, 3, 4, 5. Return `ushort` (lower 16 bits).
- **Level from experience** `CalcLevel(monsno, form, exp)` [`@0x25ad0e0`]: find the greatest `L` in 1..100 where `exps[L] ≤ exp`, with
  `exps` taken from the species' growth-rate row (table `GrowTable`, 101 entries, index = level); `exps[1] = 0`. Result is at least 1 and at most 100.
  `GrowTable.GetMinExp(level)` [`@0x25a0880`] = `exps[min(level, 100)]` (levels >100 emit an assertion in the original and are clamped to 100).

### 3.4 Growth rates [O for data, P for formula]

`work/masterdata/pml_personal/GrowTable.json` contains eight rows of 101 entries. I checked them against the classic formulas
(read-only verification against the master data using `scripts/battle_oracle.py --verify-growth`):
row 0 = medium-fast `n³`; row 1 = erratic; row 2 = fluctuating; row 3 = medium-slow
`6/5·n³ − 15·n² + 100·n − 140`; row 4 = fast `4/5·n³`; row 5 = slow `5/4·n³`; rows 6 and 7 match row 0. All rows match exactly
for levels 2..100 (integer division); level 1 is 0; row 3 is negative there and is clamped to 0. Range boundaries (50/68/98 and 15/35) are
in the C# `GrowthRate` implementation. The bundle table remains authoritative; the formulas are useful for tests without game data.

## 4. Random numbers

### 4.1 Generator [O]

All battle random values come from **Xoroshiro128+** (`Xoroshiro128Plus.Xoroshiro128Plus`), with a 2 × 64-bit state.
- **Seed → state** [`Xoroshiro128Plus..ctor(ulong) @0x18d84e0`]: `mix(x)`: `z = x; z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9; z = (z ^ (z >> 27)) * 0x94D049BB133111EB; z ^ (z >> 31)`.
  `s0 = mix(seed + 0x9E3779B97F4A7C15)`, `s1 = mix(seed + 0x3C6EF372FE94F82A)` (all modulo 2^64). If both are 0, set `s0 = 1`.
- **Step** [`next @0x18d8fd0`, `NextULong @0x18d8ff0`]: `result = s0 + s1`; `t = s1 ^ s0`; `s0' = rotl(s0, 24) ^ t ^ (t << 16)`; `s1' = rotl(t, 37)`.
  `NextULong` returns `result`; `NextUInt` [`@0x18d9010`] returns `result >> 32`.
- **Bounded value** `Random.GetValue(max)` [`Dpr.Battle.Logic.Random.GetValue @0x21d3290`]: `r = NextULong(); max == 0 ? r : r % max` (64-bit modulo,
  range `[0, max)`). The parameterless `GetValue()` [`@0x21d4090`] returns `NextULong`.
- Helpers: `calc.GetRand(n)` [`@0x2074990`] = `GetValue(n)` on battle generator `calc.g_RandSys`; `calc.RandRange(a, b)` [`@0x2074a10`]: order bounds,
  result `min + GetValue(max - min + 1)` [O]; `calc.IsOccurPer(p)` [`@0x2075e20`] = `GetValue(100) < p` [O].
- `calc.GetPublicRand(n)` [`@0x20748b0`] uses a **second** generator `g_PublicRand` (or `UnityEngine.Random` if unavailable) and is intended only
  for non-reproducible presentation effects.

### 4.2 Seed and reproducibility [P]

- `calc.InitSys(random, sakasa)` [`@0x2073f40`] stores the battle generator, creates a second, public generator, and sets the Inverse Battle flag.
  `calc.ResetSys(seed)` [`@0x2074040`] resets the battle generator (`Random.Initialize(seed)` [`@0x21d4000`]).
- `MainModule.SetUpRandSystem` [`@0x213a1b0`]: if replay flag `== 1` in setup (`BattleSetupParam`, byte at +`0x3b`), use the seed from setup field
  `recRandSeed` (+`0xF8`); otherwise, `Random.Initialize()` [`@0x21d3f40`] uses a **Unity random value** from
  `UnityEngine.Random.Range(int.MinValue, int.MaxValue)`, sign-extended to 64 bits (`(ulong)(long)int`), and saves that seed to `recRandSeed`.
  Thus a battle is fully reproducible when its seed is known; a live battle's original seed comes from non-deterministic Unity random. The rebuild accepts the seed as a parameter.
- **Random draw order for damage** (important for reproducibility): hit check (exactly one draw, unless hit is automatic) → critical check (exactly one draw if the move allows a critical check) → damage random factor (exactly one draw, omitted for fixed factor 85). Multi-hit count
  `calc.HitCountStd` [`@0x2075ae0`] draws once only for “2–5 hits” moves (type 5) [O].

## 5. Damage

Damage dealt by a move to a target flows through `Section_CalcDamage.getCalcDamage` [`@0x22addc0`] → `EventLauncher.Event_CalcDamage` [`@0x1e14710`] [OK].
Before the formula, `getCalcDamage` reads weather (`Section_FromEvent_GetWeather`) and passes it in. The critical-hit decision happens **earlier**
in `Section_CalcDamage.Execute` [`@0x22ad8d0`] (`Event_CheckCritical`, section 7), as does type effectiveness in `Section_CheckWazaDamageAffinity`.

### 5.1 Inputs to Event_CalcDamage

Type effectiveness `aff` (ID, section 2), `targetFactor` (fixed point; `0x1000` for one target, lower for multiple targets), critical flag,
“fixed factor” flag (set only by the AI simulator; `getCalcDamage` passes 0), Substitute flag, weather, and move (type, damage category 1 = physical, 2 = special).
State/handlers supply (see 5.3): `power`, `attack`, `defense`, attacker's level, STAB ratio, final factor, and burn-ignore flag.

### 5.2 Calculation order (the order is significant) [OK]

0. **Pre-events** (`0x58`, `0x59`) may provide fixed damage (e.g. fixed-damage moves); when successful, all following steps are skipped. Not part of Slice 1.
1. Determine `power`, `attack`, and `defense` (5.3); level = attacker's level.
2. **Base damage** `DamageBase(power, attack, level, defense)` [O, `calc.DamageBase @0x20747e0`]:
   `u = (attack * power * ((level*2)/5 + 2)) / defense` (32-bit, unsigned division; if `defense == 0`, `u = 0`), result `u/50 + 2`.
3. If `targetFactor != 0x1000`: `s = MulRatio(s, targetFactor)`.
4. **Weather factor** `GetWeatherDmgRatio(weather, moveType)` [O, `@0x2075830`]: sun (1) or harsh sunlight (6): Fire ×1.5 (`0x1800`), Water ×0.5 (`0x800`), otherwise `0x1000`; rain (2) or heavy rain (5): Water `0x1800`, Fire `0x800`, otherwise `0x1000`; all other weather (0, 3 snow/hail, 4 sand, 7, …) uses `0x1000`.
   If factor differs from `0x1000`: `s = MulRatio(s, factor)`.
5. **Critical hit** (if set): `s = (s * 15) / 10` (32-bit, round down; **not** via `MulRatio`).
6. **Random factor** `roll`: for “fixed factor”, **85**; otherwise `100 - GetRand(16)` (85..100, one draw from the battle generator).
   `s = (roll * s) / 100` (32-bit product wraps on overflow, then integer division rounds down). This factor comes **after** weather and critical hit.
7. **STAB**: if move type != 18: `s = MulRatio(s, stab)`, where `stab` comes from `Event_CalcTypeMatchRatio` [`@0x1e15740`]: `0x1800` (×1.5) if the attacker has the type
   (type 1, type 2, or additional type; `BTL_POKEPARAM.IsMatchType @0x20dfad0`; type 18 never matches), otherwise `0x1000`; a handler can modify the ratio
   (ability Adaptability/“Tekiouryoku” writes `0x2000`, `Handler.Tokusei.handler_Tekiouryoku @0x1a41650`).
8. **Type effectiveness**: `s = AffDamage(s, aff)` (2.5).
9. **Burn**: if the move is physical (category 1), the attacker is burned (`GetPokeSick == 4`), and the “ignore burn” flag (from
   `Event_getAttackPower`, event `0x4A`, variable `0x5A`, e.g. an ability that ignores burn) is not set: `s = (s * 50) / 100` (32-bit, round down).
10. **Final factor** (event `0x5A`: handlers for the last damage stage multiply this): variable `0x38` starts at `0x1000` with bounds
    `[0x29, 0x20000]`; handlers multiply it (round-half-up rule, section 1); then `s = MulRatio(s, endFactor)`.
11. (G-mode, Raid Boss wall: Slice 2.)
12. **Minimum damage**: if `s == 0` and fixed damage is not active: `s = 1`. Result is truncated to 16 bits (`ushort`).
    Note: minimum damage also applies at type effectiveness 0; immunity is handled earlier (`Section_CheckTypeAffinity`/`CheckWazaDamageAffinity`).

Then `Section_CalcDamage.Execute` [`@0x22ad8d0`] caps damage: `roundDamage` [`@0x22adf50`] is `min(damage, currentHP)`; for Substitute
(`roundDamage_byMigawari @0x22adf90`) it is `min(damage, Substitute HP)` (HP field +`0x92`). Endure (`Event_CheckKoraeru`) may further alter capped HP [P].

### 5.3 Components from the event system [P, OK with substitutions]

- `power` = `Event_getWazaPower` [`@0x1e14e20`]: starts with base move data; event `0x45` may rewrite it, followed by event `0x46` with a ratio
  (starts at `0x1000`, bounds `[0x29, 0x200000]`); result is `MulRatio(power, ratio)`.
- `attack` = `Event_getAttackPower` [`@0x1e15010`]: physical uses Attack (ValueID 8), special uses Sp. Attack (10); event `0x49` may change the stat kind
  (variable `0x41`), and event `0x47` may change which Pokémon supplies it (variable `0x40`, e.g. the target instead of the attacker). Value is
  `BTL_POKEPARAM.GetValue` (with stages) or `GetValue_Base` (without stages). On a critical hit, **negative stages on the attacker are ignored**
  (stage < 6 in the 0..12 system → base value); otherwise use the staged value. Then event `0x4A` applies a ratio (starts at `0x1000`, bounds
  `[0x19a, 0x20000]`): result `MulRatio(value, ratio)`.
- `defense` = `Event_getDefenderGuard` [`@0x1e153d0`]: physical uses Defense (ValueID 9), special uses Sp. Defense (11); event `0x48` may swap the stat kind
  (variable `0x42`) and force stage-ignore (variable `0x59`). On a critical hit, `GetValue_Critical` ignores **positive** target defense stages
  (stage ≥ 7, i.e. `stage > 6` → base value). In sandstorm, a Rock-type target also gets ×1.5 Sp. Defense (`MulRatio(value, 0x1800))); then event `0x4B` applies ratio bounds `[0x19a, 0x20000]`.
- **Stage-adjusted value** `BTL_POKEPARAM.GetValue(8..12)` [`@0x20dd010`] = `calc.StatusRank(base, stageIndex)` [O]. Stage index 0..12 (6 = neutral):
  `((numerator * base) & 0xffff) / denominator`, with table numerator/denominator `{2/8, 2/7, 2/6, 2/5, 2/4, 2/3, 2/2, 3/2, 4/2, 5/2, 6/2, 7/2, 8/2}`
  (read from the `.cctor`, [O]); index ≥ 13 returns `base` unchanged.
- Accuracy and evasion use the same 0..12 stage system (6 = neutral) [P].

### 5.4 Weather damage after the turn [P]

`calc.RecvWeatherDamage(poke, weather)` [`@0x2075770`]: weather 3 (hail/snow): Ice types are immune; weather 4 (sand): Rock, Steel, and Ground are immune; otherwise
damage is `max(1, maxHP / 16)` (HP via `ValueID 16`, `MAX_HP_BEFORE_G`; the original computes `(x + 15)` for negative x, effectively `x >> 4`). Weather other than 3/4: 0.

## 6. Accuracy

`EventLauncher.Event_CheckHit(attacker, target, move)` [`@0x1e19350`] [OK] returns `hit` and a “friendship dodge” flag:
1. Set flag := 0. Hit automatically (**no random draw**) if any condition applies: `CheckMustHit` (attacker/target in a specific state, e.g. Lock-On effects), battle type “demo capture” (`GetCompetitor == 4`), `Event_IsCalcHitCancel` (move always hits or a handler cancels the check), or target has status `0x21` (`WAZASICK_TELEKINESIS`).
2. `p0` = `Event_getHitPer` [`@0x1e16a30`] = `MulRatio(accuracy, ratio)` (accuracy from move data, event ratio starts at `0x1000`, bounds `[0x19a, 0x20000]`).
3. Event `0x3F` may change accuracy stage `acc` (attacker, 0..12), evasion stage `eva` (target, 0..12), “ignore evasion” flag, and a ratio
   (variable `0x38`, starts `0x1000`, bounds `[0x29, 0x20000]`). If the attacker has turn flag `0xE`, the ratio is multiplied by `0x1333` (≈ ×1.2,
   using `EVENTVAR_MulValue` rounding).
4. Evasion term: if “ignore evasion” is set **or** (target has status `0x11` (`WAZASICK_MIYABURU`, Foresight/Odor Sleuth-like) **and** `eva > 6`),
   use `-6`; otherwise use `-eva`. `idx = clamp(evasionTerm + acc + 6, 0, 12)`.
5. `p1 = HitPer(p0, idx)` [O, `calc.HitPer @0x20750b0`]: numerator/denominator table `{6/18, 6/16, 6/14, 6/12, 6/10, 6/8, 6/6, 8/6, 10/6, 12/6, 14/6, 16/6, 18/6}`; `p1 = (numerator * (p0 & 0xff)) / denominator`,
   capped at 100; index ≥ 13 returns `p0` unchanged. (Equivalent to the classic 3/9 … 9/3 fractions.)
6. `p2 = MulRatio(p1, ratio)`; cap at 100.
7. Friendship: if the **target's** friendship from `SectionUtil.GetFriendship` (active only for player Pokémon in wild/trainer battles, not G-mode; `IsFriendshipActive @0x21378d0`) is **255**:
   `p2 = p2 > 10 ? p2 - 10 : 0` and flag := 1.
8. Draw `x = GetRand(100)`; **hit if `(x & 0xff) < (p2 & 0xff)`**.
Note: `p0 == 0` (moves with no accuracy value) gives `p1 = 0`, hence a miss; such moves must be handled earlier via `IsAlwaysHit`/`IsCalcHitCancel` [P].
Only step 8 consumes a random value.

## 7. Critical hits

`EventLauncher.Event_CheckCritical(attacker, target, move)` [`@0x1e144d0`] [OK]:
1. `moveStage` = `WAZADATA.GetCriticalRank` (0..2, **6 = always critical**). `stage = moveStage == 6 ? 6 : GetCriticalRank(attacker) + moveStage`
   (`BTL_POKEPARAM.GetCriticalRank @0x20e0c10` [P]: stored stage (byte +`0x3f`) plus status-flag bonuses: +2 if bit 1 of the second status field is set,
   +3 for a flag at +`0x168` in the status block; capped at 3).
2. Event `0x43` may change `stage` or **prevent** a critical hit. Then `stage = min(stage, 3)`.
3. If prevented → no critical hit (no random draw).
4. If `moveStage == 6` → critical hit, except in “demo capture” battle type (= 4) (no random draw).
5. Demo capture → no critical hit. Otherwise `friendship = (GetFriendship(attacker) == 255)`; `divisor = friendship ? 2 : 1`.
6. `CheckCritical(stage, divisor)` [O, `calc.CheckCritical @0x2075170`]: `n = CheckCriticalTable[stage] / divisor`, at least 1 (zero becomes 1);
   critical hit if `GetValue(n) == 0`. Table `{24, 8, 2, 1}` (from the `.cctor`) means 1/24, 1/8, 1/2, 1/1.
7. On a critical hit, the function sets the “friendship bonus” flag := `friendship`.
The move-data stage 6 is therefore not a table index; the capped stage indexes the table.

## 8. Experience

Calculated per recipient: `Exp.CalcExp(param, result)` [`Dpr.Battle.Logic.Exp.CalcExp @0x19f7d70`] [O, real function with memory inputs].
Inputs (`Exp.CalcParam`): `levelCap`, `deadPokeExp` (base experience of defeated species, `PersonalTable.give_exp`), `deadPokeLevel`,
`getPokeLevel` (recipient level), `getPokeFriendship`, `playerLanguageId`, `getPokeLanguageId`; flags `isMatch` (participated in battle),
`isGakusyusoutiOn` (Exp. Share present), `haveSiawasetamago` (Lucky Egg), `isEvoCanceledPoke` (stopped level-up evolution/evolution stone),
`isMyPoke` (owned, not traded), and `competitor` (unused).
Steps:
1. If the recipient neither battled nor has Exp. Share, result is 0 (`exp = 0`, flags 0).
2. `L = min(deadPokeLevel, levelCap)`. `basis = L * deadPokeExp`; then `basis = basis < 5 ? 1 : basis / 5` (`CalcBaseExp @0x19f8000`, 32-bit).
3. If the recipient **battled**: `e = basis`. Otherwise (Exp. Share only): `e = max(1, basis >> 1)` (`CalcGakusyusoutiExp @0x19f8030`), set “via Exp. Share” flag = 1.
4. **Level adjustment** (`getexp_calc_adjust_level @0x19f8040`, **single-precision float**):
   `x = 2*L + 10` (float), `y = L + recipientLevel + 10` (float), `f(z) = z*z*sqrt(z)` (float, order `(z*z)*sqrtf(z)`),
   `e = (int)((f(x) / f(y)) * (float)e + 1.0f)` (truncate toward zero, `int`). This corresponds to `((2L+10)/(L+Lr+10))^2.5 · e + 1`.
5. If the Pokémon is not owned (`!isMyPoke`): `e = MulRatio(e, same language ? 0x1800 : 0x1b33)` (×1.5 or ≈×1.7); set “bonus” = 1.
6. Lucky Egg: `e = MulRatio(e, 0x1800)`; set bonus = 1.
7. Evolution bonus: `e = MulRatio(e, 0x1333)`; set bonus = 1.
8. Friendship >219 (`0xDB`): `e = MulRatio(e, 0x1333)`; set bonus = 1.
Return `exp` (32-bit), `viaExpShare`, `hasBonus` (multiplication order 5 → 6 → 7 → 8; each step rounds separately).
The trainer-battle bonus (×1.5) is **not** in this function (`competitor` remains unused); its location is unknown (section 10).
Party distribution (`ExpCalculator.CalcExp @0x19f8460` calls `calcExp_Party`, `calcEffortExp_Party`, `calcGEffort_Party`) and EV awards are Slice 2.

## 9. Oracle method and results

- Tool: `scripts/battle_oracle.py` (Python 3 and `unicorn`, installed under `tools/pydeps`). It loads the ELF LOAD segments at their
  virtual addresses, applies 551,315 relative relocations (needed for IL2CPP to resolve table pointers), and runs functions from entry to return.
  IL2CPP runtime features—array allocation, type checks, barriers, and class initialization—are stubs; static fields are populated by **running the real
  `.cctor`** (`TypeAffinity`, `CalcTool`, `calc`) rather than recreated. Static initializer arrays (`RuntimeHelpers.InitializeArray`) read raw
  bytes from `global-metadata.dat` using field hashes from `dump.cs`.
- Composite oracle (`damage`, `hit`, `crit`): `Event_CalcDamage`, `Event_CheckHit`, and `Event_CheckCritical` run as original; the event system
  (`EVENTVAR_*`, `CallEvent`), `BTL_POKEPARAM` accesses, and handler functions (power, attack, defense, STAB) are Python stubs whose return values
  are fixture inputs. Randomness comes from the real Xoroshiro, so each fixture also records the **next random value after the call** (`nextRand`) to check how
  many values were drawn.
- Fixtures (`unity/Assets/Tests/EditMode/Fixtures`, numeric data only, fixed seeds, reproducible with `PYTHONPATH=tools/pydeps python3 scripts/battle_oracle.py`);
  each function has ≥ 50 inputs.

| Fixture | Functions (real, Unicorn) | Cases |
|---|---|---:|
| `BattleTables.json` | .cctor for `TypeAffinity`, `CalcTool`, `calc` (tables) | 101 entries |
| `BattleStats.json` | `CalcMaxHp`, `CalcAtk/Def/SpAtk/SpDef/Agi`, `CalcCorrectedPowerBySeikaku`, `GetPowerTransformBySeikaku` | 1,635 |
| `BattleTypes.json` | `TypeAffinity.CalcAffinity`, `MulAffinity` | 918 |
| `BattleCalc.json` | `DamageBase`, `AffDamage`, `MulRatio`, `MulRatio_OverZero`, `MulRatioInt`, `GetWeatherDmgRatio`, `StatusRank`, `HitPer`, `RoundValue` | 1,855 |
| `BattleExp.json` | `Exp.CalcExp`, `getexp_calc_adjust_level`, `CalcBaseExp`, `CalcGakusyusoutiExp` | 740 |
| `BattleRng.json` | `Xoroshiro128Plus..ctor`, `NextULong`, `NextUInt`, `Random.GetValue(max)` | 70 streams |
| `BattleRngUse.json` | `IsOccurPer`, `RandRange`, `HitCountStd`, `CheckCritical` with real RNG | 640 |
| `BattleDamage.json` | `Event_CalcDamage` (composite) | 500 |
| `BattleHit.json` | `Event_CheckHit` (composite) | 600 |
| `BattleCrit.json` | `Event_CheckCritical` (composite) | 400 |

## 10. Open questions

1. **Handlers (abilities, items, move-specific cases):** Power, attack, defense, STAB, and final-factor adjustments come from about 2,000 handler methods
   (`Dpr.Battle.Logic.Handler.Tokusei/Item/Waza`). Slice 1 treats them as inputs (ratios). Confirmed example: Adaptability = STAB `0x2000`.
2. **Event IDs** (`0x3E`, `0x3F`, `0x40`, `0x43`, `0x45–0x4B`, `0x53`, `0x54`, `0x58–0x5C`, `0x95`, …) are named here only by their effect; a catalog cross-referenced with handlers is missing.
3. **Fixed damage/pre-events** `0x58`/`0x59` (variables `0x3A–0x3C`) and damage caps from Endure/Substitute/Raid Boss are described only at a high level.
4. **In-battle type effectiveness:** `Section_CheckWazaDamageAffinity`, airborne targets (Ground immunity), abilities (Levitate, absorbers), status (transformed types), and effectiveness rewrites through `rewriteWazaAffinityBy...` have not been reconstructed. Immunity (ID 0) is preserved only if these sections handle it before `Event_CalcDamage`.
5. **Trainer battle experience ×1.5:** absent from `Exp.CalcExp`; probably in `Section_*Exp*`/`BTL_CLIENT`. Experience distribution, EV awards, and level-ups are Slice 2.
6. **Meaning of language/`isMyPoke`:** `playerLanguageId` and `getPokeLanguageId` are language IDs; it is unclear whether the `0x1b33` path can occur in-game (only one language per installation), but it is reproduced.
7. **Friendship effects** (friendship 255): only accuracy (−10) and critical hit (divisor 2) are confirmed; other effects (status healing, survival) are Slice 2.
8. **Growth-rate index in Pokémon:** it is assumed that the species' `grow` field directly indexes `GrowTable` rows (0–5; 6/7 unused).
9. **Live battle seed:** comes from `UnityEngine.Random`; the rebuild can therefore be deterministic only *from* a given seed. Whether online/replay paths
   (`recRandSeed`, `commMode`) use additional random sources is unknown. `g_PublicRand` is intentionally non-reproducible.
10. **Not covered:** `BattleSimulator.CalcDamage` (AI preview), capture (`Capture.checkCapureSuccessByRandom`), prize money (`calc.CalcWinMoney`), effect chances
    (the `calc.IsOccurPer` function is covered, its usage is not), multi-hit sequence, escape formula, speed/priority, status damage (poison, confusion), weather duration.
11. **Oracle limitations:** the emulator stubs class constructors; functions using `PersonalSystem`/master data (`CalcLevel`, `GetGrowTable`) do not run without engine state
    and are covered only by pseudocode plus formula checks against `GrowTable.json` [P]. `RecvWeatherDamage` is [P] only.
