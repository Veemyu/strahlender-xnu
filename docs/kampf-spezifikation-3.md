# Battle Event System, Slice 3: Handler Coverage

> **Historical report:** This document describes the deprecated Unity rebuild. It is retained as project history; the native static recompilation is the current product.

Status: Slice 3 interim report (ability, item, and move handlers on the event system from Slice 2; no rendering or audio).
The C# implementation (`unity/Assets/Scripts/BattleEvents`, assembly `Xnu.Battle.Events`, pure logic without UnityEngine) was derived from the rules described here; oracle fixtures compare it with the real ARM64 functions. Priorities are listed in `docs/kampf-handler-liste.md`. Evidence conventions and verification levels follow section 0 of `docs/kampf-spezifikation-2.md` (addresses are Ghidra addresses).

## 1. Results

| | Slice 2 | Slice 3 (new) | Total | Goal |
|---|---:|---:|---:|---:|
| Abilities (IDs) | 4 | 50 | 54 | ≥ 40 |
| Items (IDs) | 5 (2 partial) | 69 | 73 (270 not checked in Slice 3) | ≥ 40 |
| Moves (IDs) | 0 | 48 | 48 | about 60 |
| Oracle cases | 720 | 1,755 (1,728 compared with C# handlers) | | |
| Unity/.NET tests | 93 | 8 new | 101 passing | |

IDs share tables; among implemented IDs, distinct handler tables: 50 abilities, 72 items, 31 moves. Move coverage is below target because only 57 of 310 move IDs are handler-only (section 5), and about half of valid moves have no handler.

## 2. Findings

### 2.1 ID-to-handler map [O]

`GET_FUNC_TABLE` in `Tokusei`, `Item`, `Waza`, `Side`, `Field`, `Pos`, `DefaultPowerUp`, and `RaidBoss` is an array of structs (ID at `@0x0`, delegate at `@0x8`, 16 bytes per entry). IDs are the familiar sequence values (ability 22 = Intimidate, item 220 = Choice Band, move 33 = Tackle with no handler). `scripts/battle_handler_map.py` executes the real `.cctor` methods and maps tables through the `ADD_*` functions: 241 / 197 / 310 / 22 / 10 / 5 / 3 / 1 IDs (Tokusei / Item / Waza / Side / Field / Position / Default Power-up / Raid Boss). Item 0 (no item) and two field IDs have no table; for Waza, 259 of the 262 tables reached in Slice 2 resolve to an ID.

**Oracle lesson:** arrays of structs use 16 rather than 8 bytes per element; the default stub for `il2cpp_array_new_specific` allocates only 8 bytes, and `Oracle.make_class` allocates only 0x100 bytes for statics. For 222 tables (about 1,800 bytes of statics), objects overlapped. The handler map therefore allocates 0x2000 bytes of statics and overrides the array stub (32 bytes per element). This does not affect Slice 2's `--tables` results: table names and entries (event, function) in the new map match `handler_tables.json` for every table.

### 2.2 `char` variables in pseudocode [O]

Handlers that store `GetEventVar` in a `char` variable and write `+ 1` use **unsigned 8-bit arithmetic**:
`RewriteEventVar(l, (byte)(v + d))`. For example, the oracle returns 255 for input 254 and 0 for input 255 (not 256 or −1). Equality checks against constants (such as `== '\\t'`) are unaffected. The oracle disproved the initially assumed signed variant.

### 2.3 Handler pattern [OK]

Nearly all pure handlers follow a fixed pattern (`HandlerKit.When`):

1. The owner variable (`POKEID`, `POKEID_ATK`, or `POKEID_DEF`) must match the current Pokémon ID. Some instead check “not me, but an ally” (`IsFriendPokeID`), or perform no owner check (items that only apply the owner factor).
2. Optional conditions: damage type (`DAMAGE_TYPE`), move type (`WAZA_TYPE`), weather, status (`CheckSick`), target turn/duration flags, full HP, species, or item.
3. Effect: `MulEventVar` (fixed-point ratio x/4096, e.g. 0x2000 = ×2, 0x1800 = ×1.5, 0x800 = ×0.5, 0x14CD = ×1.3), `RewriteEventVar` (flag, value), or `MulWazaBasePower` (base power `WAZA_POWER` × n, integer).

Special cases: `Common.GetWeather` (field weather) versus `GetLocalWeather(pokeId)` (including weather setters); weather codes 0 none, 1 sun, 2 rain, 3 snow, 4 sand, 5 heavy rain, 6 harsh sunlight, 7 strong winds; `calc.IsShineWeather` = 1 or 6, `calc.IsRainWeather` = 2 or 5 (from the actual code). Weather-based healing moves (234–236) read a table `{0xAAC, 0x400, 0x400, 0x400, 0x400, 0xAAC}` (weather 1–6, otherwise 0x800; read from the binary data section); Sunaatume (659) uses 0xAAC in sand, otherwise 0x800.

### 2.4 Move handlers versus the move table [P]

Of 827 `WazaTable` rows, 512 are valid; 286 of those have no handler (only 226 appear in `GET_FUNC_TABLE`). Priorities (35 valid moves with priority ≠ 0), stat changes (`rankEffType1..3`), and statuses (`sickID`) are in the table (195 moves have at least one of the latter two) and are read by calculators/sections, not handlers. Handlers cover moves with special rules (conditional power ×2, fixed damage, weather dependence, protection-phase exceptions, type override). Therefore “status effects, stat changes, priorities” are not generally handler responsibilities; handlers cover them only when they override those values (priority: abilities 177/205 through event 17).

## 3. Verification

### 3.1 Harness (`scripts/battle_oracle_handlers.py`)

For each handler entry (ID, event), the oracle runs the **real handler function** in the real event machine (`EventSystem`, `EventVar*`, `Common.GetEventVar/MulEventVar/RewriteEventVar/GetPokeParam`). Random scenarios (seeded, nine per entry) set handler variables (identified from pseudocode and helper functions) to FREE, ONCE, or MUL (with bounds), with variable-specific domains for IDs 0–3 (50% owner), types, damage types, weather, flags, and so on. Four Pokémon receive random values (HP, level, sex, species, item, types, statuses, turn/duration flags, G-mode/transformation), along with weather, move flags (7, 8, 12), field effect 2, and item value. The harness calls `CallEvent`, then records every variable. Stored results include the call trace, occupied variable stack (value, state, bounds), and factors list.

Stubs (Pokémon/field queries): `BTL_POKEPARAM.GetValue/IsHPFull/GetMonsNo/GetItem/IsMatchType/CONTFLAG_Get` (and from Slice 2: `CheckSick`, `TURNFLAG_Get`, `IsGMode`, `HENSIN_Check`), `Common.GetWeather/GetLocalWeather/IsFriendPokeID/CheckFieldEffect`, `WAZADATA.GetFlag`, `calc.ITEM_GetParam`. “Ally” means matching ID parity. Verification level is therefore **[OK]** (real handlers, query results supplied by tests).

Fixture: `unity/Assets/Tests/EditMode/Fixtures/BattleHandlers.json` (2.3 MB, numbers only): 1,755 cases, 1,451 with handler calls; two entries skipped (item 220: events 36 and 192 are effect-layer logic).

### 3.2 C# tests (`BattleEventsSlice3Tests`)

- `HandlersAgreeWithTheRealFunctionsForEveryOracleCase`: runs every case against the C# table and checks equality (call trace, every variable, state, bounds). 1,728 cases compared; cases without a C# handler (155 weather reactions) are counted but not compared. Coverage: 54 abilities, 73 items, 48 moves.
- `ImplementedNumbersAreCoveredByTheOracle`: every implemented ID has at least one oracle case (except item 270 from Slice 2).
- Manual calculations [P]: Rivalry (gender), plates/incenses, move registration (priority), Acrobatics, Morning Sun by weather, Anger Point damage.

### 3.3 Reproduction

```
PYTHONPATH=tools/pydeps python3 scripts/battle_handler_map.py                     # work/battleevents/handler_map.json (2 seconds)
python3 scripts/battle_handler_priority.py                                        # prioritization
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_handlers.py [--cases 9]     # BattleHandlers.json (about 3 minutes)
cd work/dotnet-battlehandlers && dotnet test                                      # 101 tests, no Unity Editor
```

## 4. Changes to Slice 2 code

- `IEventBattleEnv` gains `GetWeather`, `GetLocalWeather(pokeId)`, `WazaHasFlag(waza, flag)`, and `IsFriend(a, b)` (new implementers must provide these; the test environment does).
- `BattlePoke` gains `MonsNo`, `Sex` (value ID 20), `IsHpFull`, and duration flags (`GetContFlag/SetContFlag`, 32 entries).
- `TokuseiHandlers`/`ItemHandlers` are `partial`; Slice 3 tables are in `HandlersSlice3.cs`, moves in `WazaHandlers.cs` (`GetTable`, `IsImplemented`, `Add` = `Waza.Add`: WAZA factor, main priority 1, sub-priority supplied by the caller).
- A Slice 2 test (`TokuseiWithoutHandlerRegistersNothing`) now uses ability 22 (Intimidate, no handler) instead of 1 (now implemented).

## 5. Gaps

- **Incomplete tables:** Sunagakure/Yukigakure/Sunakaki (8, 81, 146) lack weather reactions (event 155, `common_weather_guard`); item 220 (Choice Band) lacks its lock logic; item 270 lacks recoil. Fumituke/Jisin/Tatumaki/Naminori are complete (both entries).
- **Not implemented (effect layer):** Intimidate (22), Soul-Heart (39), Levitate (26), Static (9), Poison Point (38), Water Veil (41), Sturdy (5), and others (messages, stat changes, statuses); all berries, Focus Sash, Leftovers, Life Orb recoil. Pure-logic handlers over 60 lines (Tokusei 109/96/244/84/159/…, Waza 87/167/210/283/542/560/751/783, Item 112/135/136/278) remain open and are next (about 1–2 hours with the oracle).
- **Move goal (about 60) not reached:** 48; with only 57 handler-only move IDs (table in `docs/kampf-handler-liste.md`), the goal cannot be met without the effect layer.
- **Oracle limits:** Pokémon/field queries are stubs (verification level [OK], not [O]); equality of query numeric values with meanings (e.g. Sick IDs 4/5/6 = burn/poison/confusion, turn flags 1/2/0x12, duration flags 3/4/5/8) is evidenced by pseudocode, not oracle; fixture data does not map these values to game concepts.
- No Python tests for `battle_handler_map.py`, `battle_oracle_handlers.py`, or `battle_handler_priority.py`; evidence is their execution only.
- **Not tested in Unity Editor** (two editors were open); new files lack `.meta` (`HandlersSlice3.cs`, `WazaHandlers.cs`, `BattleEventsSlice3Tests.cs`, `Fixtures/BattleHandlers.json`). `Xnu.Tests.EditMode.asmdef` was not changed; tests are in the existing directory.

## 6. Remaining effort (estimates from the measurements)

| Block | Scope | Estimate |
|---|---|---|
| Pure handlers over 60 lines | Tokusei 10, Item 4, Waza 8 | 2 hours with the existing oracle |
| Effect API (`Common.Message/RankEffect/AddSick/Damage/RecoverHP`, `StrParam`, `Section_FromEvent_*`) | 56 section classes; used by about 130 Tokusei, 74 Waza, 70 Item handlers | 2–3 days for section layer, then about 10–20 minutes per handler; oracle needs effect recording (stub writes description objects to a trace) |
| Item consumption/berries | about 50 items (`UseItem`, `ConsumeItem`, `SetRecallEnable`) | 1 day after section layer |
| Side/field/position effects | 37 IDs, 40 functions | 1 day (weather management, barriers, traps) |
| Raid boss/G-mode queries | about 40 Waza | together with G-mode |

The remaining work is pseudocode volume (Tokusei 16,682, Item 13,752, Waza 31,425 lines in open IDs). Without the effect layer it does nothing; with it, most of the work is schematic.
