# Battle Event System, Slice 2: Specification

Status: Slice 2 interim results (the battle backbone: events, factors, handlers; no rendering or audio). This specification is written in my own words. The C# implementation (`unity/Assets/Scripts/BattleEvents`, assembly `Xnu.Battle.Events`, pure logic without UnityEngine) was derived from this text, not copied from pseudocode. It builds on Slice 1 (`docs/kampf-spezifikation-1.md`, assembly `Xnu.Battle`), whose calculators previously took handler results as inputs; the event system now supplies those inputs.

## 0. Method and evidence conventions

- **Sources (read-only):** pseudocode export `work/decomp/battle_all/` (one file per class, header `// 0xADDRESS Name`), types/fields/offsets in `work/il2cpp/dump.cs`, binary `work/elf/main.patched.elf`. No new Ghidra run.
- **Evidence:** `[Class.Method @0xADDRESS]`; address is the Ghidra address (Il2CppDumper RVA + `0x100000`). Fields use `Field @Offset` (hex object offset from `dump.cs`; object header 0x10 bytes, array length at +0x18, elements from +0x20).
- **Verification level per statement** (as in Slice 1):
  - **[O]** confirmed by the emulation oracle: the real ARM64 function ran in Unicorn on synthetic guest memory; numeric results are in `unity/Assets/Tests/EditMode/Fixtures/BattleEvents*.json` and checked against the C# implementation by Unity tests (section 9).
  - **[OK]** oracle with neighboring functions replaced (e.g. Pokémon queries supplied as test values); the tested function itself is real.
  - **[P]** read from pseudocode only and checked with hand-calculated examples.
- Internal names of original classes (Japanese abbreviations such as `Tokusei` = ability, `Waza` = move, `Kodawari` = Choice item, `Tikaramoti` = Huge Power, `Fukugan` = Compound Eyes) appear only in evidence references.
- **Oracle finding:** pseudocode drops stack arguments from wrapper functions. It shows `EventSystem.AddFactor` with one argument; only disassembly (`ldr w9,[x0,#0x58]; strh w9,[sp]`) reveals that current call depth is passed as a ninth argument (section 4.3). The oracle exposed the initially incorrect assumption that the level was always 0.

## 1. Overview

```
  Battle flow (Sections, EventLauncher)                  Handlers (Tokusei, Item, Waza, Side, Field, Pos, ...)
        |  Event_xyz(...)                                       ^ registered on switch-in, item change, move start
        |  1. EVENTVAR_Push (new variable frame)                 |
        |  2. EVENTVAR_Set* (inputs as variables)           EventSystem.AddFactor -> EventFactorContainer
        |  3. CallEvent(id) -----------------------------> factors ordered by priority
        |       each factor: matching id? -> Handler(args, dependID) (reads/changes variables)
        |  4. EVENTVAR_GetValue (read result)
        |  5. EVENTVAR_Pop
        v
   Slice 1 calculators (damage, accuracy, critical hits, experience)
```

Core idea: battle flow does not know individual abilities or items. At fixed points it calls an **event** (`EventID`, 229 values). All **factors** (registered handler entries) are visited in order; each one with a handler for that event may read and change **event variables**. The caller then reads the result from those variables.

## 2. Event variables (EventVar)

### 2.1 Identifiers

- `EventID` [`dump.cs EventID`]: 229 values, 0 = invalid. Events used in this slice include `ACTPROC_START` 1, `WAZA_HIT_RANK` 63, `WAZA_HIT_RATIO` 64, `WAZA_POWER_BASE` 69, `WAZA_POWER` 70, `ATTACKER_POWER_PREV` 71, `DEFENDER_GUARD_PREV` 72, `ATTACKER_POWER_VID` 73, `ATTACKER_POWER` 74, `DEFENDER_GUARD` 75, `TYPEMATCH_CHECK` 83, `TYPEMATCH_RATIO` 84, `WAZA_DMG_PROC1/2/3` 88/89/90, `USE_ITEM_TMP` 142, `MEMBER_IN` 108, `TURN_END` 223 (full list in `EventIds.cs`).
- `EventVar.Label` [`dump.cs EventVar.Label`]: 124 variables plus `NUM`; 0 (`INVALID`) means “free slot”, 1 (`SYS_SEPARATE`) is a frame separator. Used in this slice: `POKEID_ATK` 3, `POKEID_DEF` 4, `WAZAID` 18, `WAZA_TYPE` 22, `DAMAGE_TYPE` 27 (0 none, 1 physical, 2 special), `HIT_RANK` 42, `AVOID_RANK` 43, `HIT_PER` 46, `WAZA_POWER` 51, `WAZA_POWER_RATIO` 52, `DAMAGE` 53, `POWER` 54, `GUARD` 55, `RATIO` 56, `TYPEAFF` 61, `SWAP_POKEID` 64, `VID` 65, `VID_SWAP_CNT` 66, `CRITICAL_FLAG` 76, `FLAT_FLAG` 82, `GEN_FLAG` 89, `WAZA_TOUCH_FLAG` 99.
- Each variable is a 32-bit integer (`EventVar @0x14 m_value)), plus state (`@0x12`), bounds (`@0x18/0x1C`), and an optional object reference (`@0x20`).

### 2.2 States and operations [O]

`EventVar.RewriteState` [`dump.cs`]: `FREE` 0, `ONCE` 1, `END` 2, `MUL` 3, `LOCK` 4. Each operation resets value, bounds, reference, and state (only freeing leaves contents as-is; see 2.3):

| Operation (EventSystem) | Effect | Evidence |
|---|---|---|
| `SetValue(l, v)` | value `v`, zero bounds, no reference, FREE (rewritable any number of times) | `EVENTVAR_SetValue @0x19f5950`, `EventVar.SetValue @0x19f5a90` |
| `SetConstValue(l, v)` | as above, state LOCK (never writable) | `@0x19f5b60`, `EventVar.SetConstValue @0x19f5c20` |
| `SetRewriteOnceValue(l, v)` | ONCE: one rewrite allowed | `@0x19f5c60`, `@0x19f5d20` |
| `SetMulValue(l, v, min, max)` | MUL with bounds; only `MulValue` may change it | `@0x19f5e10`, `@0x19f5ed0` |
| `RewriteValue(l, v)` | only FREE or ONCE (`state < 2`): set value; ONCE becomes END; returns success | `@0x19f5f10`, `EventVar.RewriteValue @0x19f5f90` |
| `RecoveryRewriteOncePermission(l)` | restore ONCE (including from END/LOCK/MUL) | `@0x19f5d60`, `@0x19f5e00` |
| `MulValue(l, f)` | only in MUL: `v = (int)((long)v * f + 0x800 >> 12)`; then clamp to `[min, max]` if either bound is nonzero | `@0x19f5fc0`, `EventVar.MulValue @0x19f6050` |
| `GetValue(l)` | value; missing variable returns 0 | `@0x19f60a0` |
| `GetValueIfExist(l, out v)` | success + value; otherwise `false` and value 0 | `@0x19f6100` |
| `SetWorkAddress(l, obj)` / `GetWorkAddress(l)` | variable holds object reference, not a number (value 0) | `@0x19f6170`, `@0x19f6270`, `EventVar.SetAddress @0x19f6230` |

`MulValue` arithmetic [O]: truncate the 64-bit intermediate to 32 bits **before** clamping. On overflow (e.g. `int.MaxValue` × 4915), the lower bound therefore wins; Slice 1 (`BattleMath.EventVarMul`) clamps before truncation. This affects overflow only and is not used in Slice 1; the new `EventVar` class follows the original. A handler ratio (fixed point x/4096) is multiplied into a variable using this rule; the usual starting value is `0x1000` (=1.0), with bounds such as `[0x29, 0x20000]`.

### 2.3 Stack and frames [O]

- `EventVarStack` [`dump.cs`, `m_variables @0x10`, `m_sp @0x18`]: pool of **96** variables (`EVENTVAL_STACK_DEPTH`). Label 0 is free. `Push` [`@0x19f5590`]: from `m_sp`, skip occupied slots, put separator (label 1) in first free slot, and set `m_sp` after it; last slot (95) is never a separator, and a full pool does nothing. `Pop` [`@0x19f57b0`]: from `m_sp`, free occupied slots in the frame (only label becomes 0; value/state remain), free preceding separator, and move `m_sp` after previous separator (or to 0). `GetNewPoint` [`@0x19f5a10`] returns first free or same-label slot from `m_sp`, so `SetValue` overwrites the same variable in the same frame. `ToEmpty` [`@0x19f46d0`] frees everything.
- `EventVarSet` [`@0x10 m_pVariables`, 124 slots]: variables indexed by label. `SetVariable` [`@0x19f5ad0`] stores it (label ≥124 is not indexed, but still occupies its stack slot); `GetVariable` [`@0x19f5db0`] reads it.
- `EventVarSetStack` [`@0x10 m_varSets`, `@0x18 m_stackPointer`]: **32** variable sets, one per frame. `Push` [`@0x19f5630`] increments pointer to at most 31; `Pop` [`@0x19f5700`] clears current set and decrements pointer.
- `EventSystem.EVENTVAR_Push` [`@0x19f5510`]: push variable stack, push set stack, current set = `m_varSets[m_stackPointer]`. `EVENTVAR_Pop` [`@0x19f56a0`]: pop set stack, select new current set, pop variable stack. `EVENTVAR_CheckStackCleared` [`@0x19f5880`]: if stack is not empty, reset everything.
- **Visibility:** reads and writes always target the **current** set. Inner frames cannot see outer variables (they start empty); popping restores outer variables. A handler that calls its own event must first push a frame and set the variables it needs.
- Before the first `Push`, no current set exists (`m_pCurrentEventVarSet @0x50` is 0); the original would crash, while C# throws `InvalidOperationException`.

## 3. Factors and their management

### 3.1 Factor (`EventFactor`, `EventFactor.Data`) [O]

A factor is a handler entry with metadata. `EventFactor` [`@0x10 m_instanceID`, `@0x18 m_prevFactor`, `@0x20 m_nextFactor`, `@0x28 m_data`], `EventFactor.Data` offsets:

| Offset | Field | Meaning |
|---|---|---|
| 0x10 | `handlerTable` | `EventHandlerTable[]` (`eventID @0x10`, `eventHandler @0x18`) |
| 0x18 | `skipCheckHandler` | optional skip-check handler (section 5.3) |
| 0x20 | `factorType` | `EventFactorType` (3.2) |
| 0x24 | `priority` | 32-bit sort key (3.3) |
| 0x28 | `subID` | ability, item, move, side-effect ID, etc. |
| 0x2A | `dependID` | Pokémon ID (Waza/Tokusei/Item), side, or parameter |
| 0x2B | `pokeID` | Pokémon ID for sleep/wake and skip checks; 0x1F = none |
| 0x2C | `eventLevel` | call depth at registration (4.3) |
| 0x30 | `numHandlers` | number of table entries (byte) |
| 0x34–0x39 | `callingFlag`, `recallEnableFlag`, `rmReserveFlag`, `sleepFlag`, `tmpItemFlag`, `existFlag` | runtime flags (section 5) |
| 0x40 | `work` | `int[7]`, handler scratch values (`EVENT_HANDLER_WORK_ELEMS = 7`) |

`Clear` [`EventFactor.Clear @0x1e124c0`] zeros all fields and work values. Scratch accessors: `GetWorkValue @0x1e09d60`, `SetWorkValue @0x1e09de0` (index ≥7 throws). Registration conventions: nonzero work value 6 protects Item and Waza factors from default removal (`Item.Remove`, `Waza.Remove`); work value 4 protects Tokusei factors (`Tokusei.Remove`).

### 3.2 Types and main priorities [O]

`EventFactorType` [`dump.cs`]: `WAZA` 0, `POS` 1, `SIDE` 2, `FIELD` 3, `TOKUSEI` 4, `ITEM` 5, `DEFAULT_POWERUP` 6, `RAIDBOSS` 7, `ISOLATE` 8, `NUM` 9 (call “all types”). **There is no separate factor type for status conditions (“Sick”) or weather**: weather is a `FIELD` factor (`Handler.Field.ADD_Fld_Weather`); status conditions live in each Pokémon's sick container (section 7) and are affected by Tokusei/Item/Waza handlers through events such as `ADD_SICK`, `WAZASICK_*`, `POKESICK_FIXED`.

`EventPriority` [`dump.cs`]: `DEFAULT_POWERUP` 0, `WAZA` 1, `POS` 2, `SIDE` 3, `FIELD` 4, `RAIDBOSS` 5, `TOKUSEI_dokusyu` 6, `TOKUSEI` 7, `ITEM` 8, `TOKUSEI_atodasi` 9. **Lower means earlier.** Only three abilities differ from default 7 (their `ADD_*` function passes `ref prio`): `Dokusyu` and `HorobiNoSango` use 6 (before other abilities and items, but after move/side/field); `Atodasi` uses 9 (after items).

### 3.3 Sort key, ties, insertion [O]

- `EventFactorContainer.calcFactorPriority` [`@0x1e13230`]: `priority = ((9 - mainPri) << 24) | subPri` (32-bit; sub-priority occupies lower 24 bits, `SUBPRI_MAX = 0xFFFFFF`). A **lower main priority produces a larger key**.
- Running list (`m_pRunningFactor @0x18`) is sorted in **descending key** order. `addRunningFactor` [`@0x1e13860`]: if new key is larger than head, insert at head; otherwise continue while `new <= current` and insert **before** the first factor with a smaller key (append if none is smaller). On a tie, a later registration follows an earlier one (registration order). **Ties are not randomized.**
- For abilities, items, default power-ups, and Raid Boss factors, sub-priority is the Pokémon's **base Speed** (`BTL_POKEPARAM.GetValue_Base(AGILITY)`, no stages; `Tokusei.Add @0x1a3e920`, `Item.addHandler @0x1a05870`). Side/position/field effects use 0; moves use a caller-supplied value (`Waza.Add @0x18f9610`, called from `ServerCommandExecutor`/`-Putter`). Faster Pokémon therefore act first within each group. **Order is set only at registration:** `SetPriority` is never called, so later Speed changes do not reorder factors.
- Overall order: Default Power-Up, move, position, side, field, Raid Boss, abilities at priority 6, regular abilities, items, ability at priority 9 (“atodasi”); within each group, descending Speed, then registration order.

### 3.4 Pool, registration, removal [O]

- `EventFactorContainer` [`m_factors @0x10`, `m_pRunningFactor @0x18`, `m_pStoredFactor @0x20`]: **172 factors** (`FACTOR_REGISTER_MAX`; constants: 12 per Pokémon = 72, 44 side effects, 30 position effects, 10 field effects, 16 reserve) are allocated once in the constructor [`@0x1e13270`, `createFactors @0x1e13390`] and placed in order in the stored list (`storeFactor @0x1e13520`: unlink factor, `Clear`, put at the **head** of stored list). Instance IDs are therefore allocated **from high to low**: first #171, second #170, …; a released factor is reused next.
- `AddFactor` [`@0x1e13ab0`, parameters: type, subID, main priority, sub-priority, dependID, table, count, event depth]: takes the stored-list head (**empty: returns null; nothing is registered**), sets all fields, `existFlag = 1`, and `pokeID = dependID` only for WAZA/TOKUSEI/ITEM (`isDependPokeFactorType @0x1e13240`), otherwise `0x1F`, then inserts it.
- `RemoveFactor` [container `@0x1e13c40`]: advance running-list head and call `storeFactor`. `EventSystem.RemoveFactor` [`@0x19f4780`] removes **only existing** factors; a running factor (`callingFlag`) is marked for **deferred removal** (`rmReserveFlag`) and removed after its handler (section 5.2). `RemoveIsolateFactors` [`@0x19f4800`] removes all ISOLATE factors (`ConvertForIsolate @0x1e0a490` sets the type; called by ability/move handlers; cleaned up in `Section_TurnEnd`).
- Lookup: `SeekFactor(type)` [`@0x1e13c90`] / `SeekFactor(type, dependID)` [`@0x1e13cd0`]: first **existing** factor without pending removal. `GetNextFactor(f, anyDependID)` [`@0x1e13d20`]: next factor of same type without pending removal (same dependID unless “any”). `SwapFactorsSideEffect` [`@0x1e13db0`] swaps the two sides for all SIDE factors with a given side-effect ID. `Clear`/`CopyFrom`/`storeAllRunningFactor` (`@0x1e139f0/0x1e135f0/0x1e13a50`) copy state for simulations (`BattleEnv`); not implemented.
- Sleep: `SleepFactors(pokeID, type)` [`@0x19f48c0`] sets `sleepFlag` on all factors for that Pokémon and type; `WakeFactors` [`@0x19f4940`] clears it; `WakeAllFactors` [`@0x19f49c0`] clears all. Sleeping factors are not called.

### 3.5 Who registers what [P, parameters from Add functions]

| Handler class | Factor type | Main priority | subID | dependID | Notes | Evidence |
|---|---|---:|---|---|---|---|
| `Handler.Tokusei` | TOKUSEI | 7 (6/9 for 3 abilities) | ability ID | Pokémon ID | `Remove`: while work value 4 = 0; `Swap` removes and re-registers | `Add @0x1a3e920`, `Remove @0x1a3ea40`, `Swap @0x1a3eae0` |
| `Handler.Item` | ITEM | 8 | item ID | Pokémon ID | direct container call with event depth; `Remove`: work value 6 = 0 | `addHandler @0x1a05870`, `Remove @0x1a05a10` |
| `Handler.Waza` | WAZA | 1 | move ID | Pokémon ID | rejects duplicates; checks at most 8 move factors per Pokémon | `Add @0x18f9610`, `Remove @0x18f9840` |
| `Handler.Side` | SIDE | 3 | side-effect ID | side | no duplicates per side; work values 5/6 = duration (`SICKCONT.Split32bit`) | `Add @0x1a386c0`, `Remove @0x1a38a90` |
| `Handler.Pos` | POS | 2 | position-effect ID | position | only if `isRegistable`; work values from parameter field, work value 6 = parameter | `Add @0x1a35980`, `Remove @0x1a35d50` |
| `Handler.Field` | FIELD | 4 | field-effect ID (`EffectType`, including weather) | parameter | direct container call with event depth | `Add @0x1a01e60`, `Remove @0x1a021e0` |
| `Handler.DefaultPowerUp` | DEFAULT_POWERUP | 0 | boost reason | Pokémon ID | direct container call with event depth; sub-priority = Speed | `Add @0x1a01620`, `Remove @0x1a01970` |
| `Handler.RaidBoss` | RAIDBOSS | 5 | as passed | Pokémon ID | sub-priority = Speed; checks `canAdd` first | `Add @0x1a37a90`, `Remove @0x1a37f00` |

Each class has a `GET_FUNC_TABLE` (ID → `HandlerGetFunc`) and a static `HandlerTable_*` for each handler entry (event → handler method). The `ADD_*` functions return only this table (Tokusei/Waza may also return a changed main priority).

## 4. Dispatch loop

### 4.1 Call variants [O]

- `CallEvent(id)` [`EventSystem.CallEvent @0x19f4a00`] calls **all** types with skip checks. `CallEvent_Force(id)` [`@0x19f4ba0`] does the same **without** skip checks. `CallEvent_TargetType(id, type)` [`@0x19f4c70`] calls only that factor type, with checks. `callEventCore @0x19f4ad0` and `notifyHandlers @0x19f4d40` are variants of the same loop.
- Flow: increment call depth `m_eventLevel @0x58`; walk the running list from its head (5.2); decrement depth. If it reaches 0, reset event level to 0 on **all** factors (`SetEventLevel(0)`).
- Before invoking a handler, the loop saves the factor's successor. If that successor has since been removed, it uses the factor's **current** successor. This lets handlers remove arbitrary factors without breaking iteration.

### 4.2 Per-factor checks (`nofityHandler @0x19f4dd0`) [O]

Skip a factor (return its successor) on the first applicable condition:

1. it is already running (`callingFlag`) and has no re-entry permission (`recallEnableFlag`);
2. it is asleep (`sleepFlag`);
3. call is restricted to a type and the factor has a different type;
4. its event level is nonzero and current call depth is **less than or equal to** that level (4.3);
5. it does not exist (`existFlag == 0`);
6. event is `USE_ITEM_TMP` (142) and the factor lacks `tmpItemFlag` (`SetTmpItemFlag @0x1e12840`);
7. `numHandlers == 0`.

Then scan the table: **only the first matching event ID is executed**; later entries for that ID in this factor are ignored. No match means the factor is done. Checked calls then run `checkHandlerSkip` (5.3).

Set `callingFlag`, construct `EventHandlerArgs` (EventSystem reference, current variable set `pEventVar`, factor, battle environment), and call `handler(args, dependID)`. **Afterward:** if the handler called `SetRecallEnable` (`@0x1e0a400`, active only while running), revoke that permission and leave `callingFlag` set; otherwise clear `callingFlag`. If `rmReserveFlag` is set, call `RemoveFactor` if the factor still exists and is no longer running (otherwise leave it pending). Advance the returned successor to the next **existing** factor.

### 4.3 Recursion and event level [O]

- **Recursion:** if a handler calls the same event again (or another event that includes it), its factor is skipped (rule 1), unless it first calls `SetRecallEnable`; then it runs once nested, and permission expires after the inner invocation.
- **Event level:** `EventSystem.AddFactor` [`@0x19f4740`] passes the **current call depth** to the container as the new factor's event level (from disassembly); `Handler.Item`/`Handler.Field` container calls do likewise. A factor registered during a call at depth *t* does not respond to that call or nested calls through depth *t* (rule 4), but does respond at greater depth. When the outermost call ends, all levels return to 0. Outside calls (depth 0), it responds immediately.

### 4.4 Skip logic (`checkHandlerSkip @0x19f5140`) [OK]

Determine before each handler whether it is suppressed (only for `CallEvent`/`CallEvent_TargetType`):

1. **Tokusei factors** (with a Pokémon): skip if Pokémon has `WAZASICK_IEKI` (16, ability disabled), ability is disabled by Neutralizing Gas (`IsTokuseiDisabledByKagakuHenkaGas`), ability is in `tables.CheckOmmitAfterHensin @0x2079980` while transformed, or G-mode is active and `CheckOmmitOnG @0x2079a30` says to omit it.
2. **Item factors** (except event `MEMBER_IN_EVO` 208): skip during field effect 5 (Magic Room), status `WAZASICK_SASIOSAE` (19, item suppression), or turn flag 9 (`TURNFLG_ITEM_CANT_USE`).
3. **Skip handlers on other factors:** each awake factor with `skipCheckHandler` (disabled abilities are excluded) receives the tested factor's event, type, subID, and dependID. If any answers yes, skip the factor (this is how abilities can suppress other handlers). `Attach/DetachSkipCheckHandler @0x1e0a0b0/0x1e0a0e0`.

## 5. Handler types and examples

Handlers have signature `Handler(args, dependID)`. Helpers in `Common` (188 functions in the export) read variables (`GetEventVar @0x1e09be0` = `EVENTVAR_GetValue`, `MulEventVar @0x1e09cc0`, `RewriteEventVar @0x1e09c90`), access Pokémon (`GetPokeParam @0x1e09e40` through `BattleEnv.m_pokecon`), and trigger effects (`Damage`, `RankEffect`, `AddSick`, `ChangeWeather`, etc. through 56 `Section_FromEvent_*` classes). The effect layer is outside this slice; here the focus is reading and changing variables.

| Handler type (factor type) | Original count (section 10) | Typical events (most common) |
|---|---|---|
| Ability (`Handler.Tokusei`) | 222 tables / 383 handler functions | 172 `CHANGE_TOKUSEI_AFTER`, 108 `MEMBER_IN`, 70 `WAZA_POWER`, 95 `WAZA_DMG_REACTION`, 74 `ATTACKER_POWER` |
| Item (`Handler.Item`) | 193 / 285 | 70 `WAZA_POWER`, 142 `USE_ITEM_TMP`, 141 `USE_ITEM`, 180 `CHECK_ITEM_REACTION`, 95, 108 |
| Move (`Handler.Waza`) | 262 / 412 | 34 `WAZA_EXECUTE_CHECK_3RD`, 196 `UNCATEGORIZE_WAZA`, 69 `WAZA_POWER_BASE`, 33, 197 |
| Side (`Handler.Side`, barriers, hazards, Tailwind) | 22 / 29 | 108 `MEMBER_IN`, 51, 90, 145 `TURNCHECK_BEGIN` |
| Field (`Handler.Field`, weather, rooms, Gravity) | 13 (5 placeholders with event 0) / 12 | 0, 33, 78, 79 |
| Position (`Handler.Pos`, Wish, Healing Wish, Future Sight) | 5 / 5 | 108, 145, 200 |
| Default Power-Up / Raid Boss | 1 / 1 and 1 / 2 | 106; 3, 4 |
| Status/Sick | no factor type (3.2) | events 121–130 are handled by ability/item/move factors |

Examples from pseudocode (all implemented as a minimal set, section 8):

- **Huge Power**, `handler_Tikaramoti @0x1a3f7b0`, event 74: if `POKEID_ATK` is the owner and `DAMAGE_TYPE` = 1 (physical), `RATIO *= 0x2000`.
- **Thick Fat**, `handler_AtuiSibou @0x1a3f640`, event 74: if `POKEID_DEF` is the owner and `WAZA_TYPE` is Fire (9) or Ice (14), `RATIO *= 0x800`.
- **Compound Eyes**, `handler_Fukugan @0x1a40a00`, event 64: if `POKEID_ATK` is the owner, `RATIO *= 0x14CD`.
- **Technician**, `handler_Technician @0x1a43500`, event 70: if `POKEID_ATK` is the owner and `WAZA_POWER` < `0x3D` (61), `WAZA_POWER_RATIO *= 0x1800`.
- **Items** use their in-game “attack value”: `Item.item_AttackValue_to_Ratio @0x1a05d30`: `ratio = (int)((float)(w + 100) * 4096 + 0.5) / 100` (subtract 0.5 if `w + 100 < 1`), e.g. 10 → 4505 (`0x1199`), 30 → 5324 (`0x14CC`). Used by `KoukakuLens` (event 64), `MonosiriMegane` (70, only `DAMAGE_TYPE` 2, variable `WAZA_POWER_RATIO`), `TatsujinNoObi` (90, only `TYPEAFF > 7`), and `InochiNoTama_Damage` (90). `KodawariHachimaki_Pow @0x1a12600`, event 74: owner is attacker, not G-mode, physical → `RATIO *= 0x1800`.

## 6. Pokémon in battle (`BTL_POKEPARAM`) [P, as needed by the event system]

`BTL_POKEPARAM` [`dump.cs`, 0x10-byte object headers]: `m_coreParam @0x10` (core), `m_baseParam @0x18`, `m_varyParam @0x20` (stages), `m_doryokuParam @0x28`, `m_waza @0x30`, `m_tokusei @0x38`, `m_turnFlag @0x58`, `m_contFlag @0x60`, `m_permFlag @0x68`, `m_counter @0x70`, `m_migawariHP @0x92`, `m_fldSim @0xA0` (field state for Wonder Room/Gas checks).

- **Core** (`CORE_PARAM`): `hpMax @0x24`, `hp @0x26`, `item @0x28`, `level @0x2E`, `myID @0x2F`, `sickCont @0x48` (array `BTL_SICKCONT`; `CheckSick(id) = (sickCont[id] & 7) != 0` [`@0x20d8b30`]), `fHensin @0x3C` (transformed, `HENSIN_Check @0x20dd470`), `gParam @0x88` (G-mode, `IsGMode @0x20db9a0`).
- **Base stats** (`BASE_PARAM`): `attack @0x14`, `defence @0x16`, `sp_attack @0x18`, `sp_defence @0x1A`, `agility @0x1C`; types `type1 @0x1E`, `type2 @0x1F`, `type_ex @0x20` (18 = no type). `IsMatchType @0x20dfad0`: type 18 never matches; otherwise checks type 1, 2, or additional type.
- **Stages** (`VARIABLE_PARAM`, `sbyte`, actual range 0..12, 6 neutral): Attack, Defense, Sp. Attack, Sp. Defense, Speed, accuracy, evasion (`@0x10..0x16`). `GetValue(id)` [`@0x20dd010`]: IDs 1–7 return the stage; 8–12 call `calc.StatusRank(base, stage)` (Slice 1, section 5.3). `GetValue_Base(id)` [`@0x20dd9e0`] returns values without stages (accuracy/evasion → 6); `GetValue_Critical` [`@0x20dfc50`] ignores attacker stages below 6 and target Defense stages above 6 on a critical hit (uses base value). Wonder Room's Defense swap is **not** implemented (open).
- **Flags:** `TURNFLAG_Get(f)` [`@0x20dfe70`] reads bit `f & 7` in byte `f >> 3` of `m_turnFlag` (27 flags, e.g. 9 `ITEM_CANT_USE`, 14 `HITRATIO_UP`); duration/permanent flags work similarly.
- **ValueID** (`BTL_POKEPARAM.ValueID`): 1–5 stages, 6/7 accuracy/evasion, 8–12 battle stats, 13 HP, 15 MaxHP, 17 level, 18 ability, 19 effective ability (0 when disabled by `IEKI`/Gas), 20 sex.

C# counterpart: `BattlePoke` (Id, Level, Hp/MaxHp, Item, Tokusei, types, base stats, seven stages, sick container (64 duration types), turn flags, G-mode, transformation, Gas flag), with `GetValue`, `GetValueBase`, `GetValueCritical`, `CheckSick`, `GetTurnFlag`, `IsMatchType`. The battle environment (`IEventBattleEnv`) provides `GetPoke(id)`, `IsFieldEffectActive(effect)`, both omission tables, and item attack value.

## 7. Battle call sites (`EventLauncher`) and connection to Slice 1 [P]

`EventLauncher` (176 functions in export) wraps each calculation: `Push`, set inputs as variables, `CallEvent`, read result, `Pop`. Calls feeding Slice 1 calculators:

| Step (function) | Frame and events | Result |
|---|---|---|
| Power (`Event_getWazaPower @0x1e14e20`) | const `POKEID_ATK/DEF`, `WAZAID`, `WAZA_TYPE`, `DAMAGE_TYPE`, `WAZA_TOUCH_FLAG`; `WAZA_POWER` = base power, writable once; event 69; `WAZA_POWER_RATIO` (`0x1000`, `[0x29, 0x200000]`); event 70 | `MulRatio(power, ratio)` |
| Attack (`Event_getAttackPower @0x1e15010`) | frame 1: event 71 (may set `SWAP_POKEID` and `GEN_FLAG` = ignore stages); nested frame: event 73 (may change stat kind `VID`); back in frame 1: `POWER` = value (on critical hit, stage <6 → base), `RATIO` (`0x1000`, `[0x19A, 0x20000]`), event 74 | `MulRatio(value, ratio)` + “ignore burn” flag |
| Defense (`Event_getDefenderGuard @0x1e153d0`) | frame: `VID` = default stat, event 72 (swap stat kind, ignore stages); `GUARD`, `RATIO`, event 75; in sandstorm, Rock target gets ×`0x1800` Sp. Defense | `MulRatio(value, ratio)` |
| STAB (`Event_CalcTypeMatchRatio @0x1e15740`) | `GEN_FLAG` = matching?, event 83, `RATIO` = `0x1800/0x1000`, event 84 | ratio |
| Accuracy chance (`Event_getHitPer @0x1e16a30`, from `Event_CheckHit @0x1e19350`, event 64) | `HIT_PER` = accuracy, writable once; `RATIO` (`0x1000`, `[0x19A, 0x20000]`) | `MulRatio(accuracy, ratio)` = `HitInput.HitPercent` |
| Accuracy stages (`Event_CheckHit`) | `FLAT_FLAG`, `HIT_RANK` = attacker stage, `AVOID_RANK` = target stage, `RATIO` (`0x1000`, `[0x29, 0x20000]`); event 63 | stages, flag, ratio = `HitInput` |
| Final factor (`Event_CalcDamage @0x1e14710`, event 90) | `TYPEAFF`, `CRITICAL_FLAG`, `WAZA_TYPE`, …; `RATIO` (`0x1000`, `[0x29, 0x20000]`), `DAMAGE` = current damage; event 90 | ratio = `DamageInput.FinalRatio` |

C#: `BattleEventLauncher` (`GetWazaPower`, `GetAttackPower`, `GetDefenderGuard`, `CalcTypeMatchRatio`, `GetHitPer`, `BuildHitInput`, `GetFinalDamageRatio`, `BuildDamageInput`) reproduces these calls in `EventSystem` and supplies completed `HitInput`/`DamageInput` to Slice 1 calculators. **Only change to Slice 1 code:** optional `DamageInput.FinalRatioFunc` (takes precedence over `FinalRatio`) because final factor needs damage before the last stage (`DamageCalculator.Calc` calls it with the intermediate value). All Slice 1 tests remain green. Not implemented: fixed-damage events 87–89 and G-mode/Raid events 91/92 inside `Event_CalcDamage`.

## 8. Minimal real-handler set (proof of concept)

| Handler | ID | Event | Effect | Evidence | Level | Coverage |
|---|---:|---:|---|---|---|---|
| Huge Power | ability 37 | 74 | physical attack ×2 | `handler_Tikaramoti @0x1a3f7b0` | [O] | complete |
| Thick Fat | ability 47 | 74 | Fire/Ice against owner ×0.5 | `handler_AtuiSibou @0x1a3f640` | [O] | complete |
| Compound Eyes | ability 14 | 64 | accuracy ×`0x14CD` | `handler_Fukugan @0x1a40a00` | [O] | complete |
| Technician | ability 101 | 70 | power <61 ×1.5 | `handler_Technician @0x1a43500` | [O] | complete |
| Choice Band | item 220 | 74 | physical attack ×1.5 (not in G-mode) | `handler_KodawariHachimaki_Pow @0x1a12600` | [O] | only event 74 entry; lock logic (36/192/222) missing |
| Wide Lens | item 265 | 64 | accuracy based on item value | `handler_KoukakuLens @0x1a10d30` | [O] | complete |
| Wise Glasses | item 267 | 70 | special power based on item value | `handler_MonosiriMegane @0x1a11a80` | [O] | complete |
| Expert Belt | item 268 | 90 | final damage on super-effective hit, based on item value | `handler_TatsujinNoObi @0x1a13910` | [O] | complete |
| Life Orb | item 270 | 90 | final damage based on item value | `handler_InochiNoTama_Damage @0x1a13cf0` | [O] | damage only; recoil (event 164) missing |

Registration: `TokuseiHandlers.Add/Remove/Swap`, `ItemHandlers.Add/AddHandler/Remove` implement `Tokusei.Add`/`Item.addHandler`/`Item.Remove` (3.5).

## 9. Verification (oracle)

### 9.1 Setup

`scripts/battle_oracle_heap.py` (run as `PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_heap.py`) extends the Slice 1 oracle:

- **Guest heap helpers:** `DumpTypes`/`GuestHeap` read field names and offsets from `dump.cs` and allocate objects (container, `EventSystem`, `BattleEnv`, `FieldStatus`, Pokémon placeholders, handler tables) as zeroed blocks in guest memory; heap resets between scenarios.
- **IL2CPP stubs:** class initialization (`FUN_00364fe0`), write barriers, object/array allocation (`FUN_00366700`, `FUN_003afb00`), type checks on array assignment; exceptions (`FUN_0035c83c/0035cda0/003afbc0`) stop emulation with an error rather than silently continuing.
- **Delegate calls:** `EventHandler.Invoke @0x1e12b80` and `SkipCheckHandler.Invoke @0x1e12f40` are “yield” stubs: emulation pauses while the handler runs as Python or as a **real guest function** (nested execution on its own stack), then resumes. This lets handlers remove/add factors and make nested calls using real `EventSystem` functions.
- **Pokémon queries** (`POKECON.GetPokeParam`, `CheckSick`, `TURNFLAG_Get`, `IsGMode`, `HENSIN_Check`, omission tables, `ITEM_GetParam`) are stubs with test values (hence [OK] for `checkHandlerSkip` and handlers that query Pokémon).
- **Method-pointer slots:** each metadata method slot (24,020) points to a record containing the method address. This allows running the **real handler-class `.cctor` methods**, missing from the export due to decompiler timeout for `Tokusei`/`Item`/`Waza`; event-to-handler tables are read from guest memory (`--tables`).

### 9.2 Fixtures (`unity/Assets/Tests/EditMode/Fixtures/`, numeric only, seed-based)

| File | Contents | Coverage |
|---|---|---|
| `BattleEventsVar.json` | randomized operation sequences against real `EVENTVAR_*` functions: returns, both stack pointers, final slot contents | 70 cases, 3,329 operations |
| `BattleEventsOrder.json` | `AddFactor`/`RemoveFactor` with priorities/ties, instance IDs, pool, `Seek`/`GetNext` | 61 cases, 1,113 factors, 240 lookups, pool exhaustion (172) |
| `BattleEventsCall.json` | `CallEvent`/`Force`/`TargetType`; handlers remove themselves/others, add factors, recurse, change variables, enable re-entry, sleep, trigger skip rules; records all handler calls (event, instance, dependID, depth) and final state | 160 cases, 1,729 handler calls |
| `BattleEventsHandlers.json` | nine real handlers (section 8) in the real event system with randomized variables; also `item_AttackValue_to_Ratio` (real floating-point code) | 720 cases (627 with calls), 1,050 ratio values |

Unity tests (`BattleEvents*Tests.cs`) run the same scenarios against C# and compare every log, factor list, slot, and stack pointer. They also include hand calculations (priority key, order, recursion/recall, event level, skip rules, hit/damage wiring). Python tests: `scripts/tests/test_battle_oracle_heap.py` (parser, heap, summary; with Unicorn, real emulation probes too).

### 9.3 What is not covered (and how it is checked)

- **`EventLauncher` functions** (`Event_getHitPer`, `getWazaPower`, `getAttackPower`, `getDefenderGuard`, `CalcTypeMatchRatio`) and **`BTL_POKEPARAM.GetValue`** do not run in the oracle: they depend on `BTL_POKEPARAM`, `WAZADATA`, `Section*`, and `MainModule`, whose object graphs cannot reasonably be synthesized without stubbing large parts of the game (making results merely test inputs). Instead: pseudocode analysis (section 7) plus hand-calculated tests, e.g. Compound Eyes: 70 × `0x14CD` → 91; Wide Lens (value 10) → 77; both → 100; Huge Power: Attack 100 → 200; stages −3/+3 → 40/250; sandstorm: Sp. Defense 100 → 150.
- **`checkHandlerSkip`** is [OK], not [O]: Pokémon queries are stubs; decision logic is real.
- **Handlers with effects** (damage, stat changes, messages) require the Section layer and are outside this slice.

## 10. Open work and estimates

### 10.1 Handler-class counts (from real `.cctor` methods, `--tables`; handler functions = distinct functions in tables)

| Type | Tables (≈ abilities/items/moves/effects) | Table entries | Handler functions | Pseudocode lines (handler functions) | Functions ≤30 / 31–60 / 61–120 / >120 lines |
|---|---:|---:|---:|---:|---|
| Tokusei | 222 | 461 | 383 | 13,666 | 184 / 160 / 36 / 3 |
| Item | 193 | 437 | 285 | 9,139 | 156 / 92 / 37 / 0 |
| Waza | 262 | 542 | 412 | 18,278 | 124 / 206 / 75 / 7 |
| Side | 22 | 32 | 29 | 1,492 | 9 / 9 / 11 / 0 |
| Field | 13 | 18 | 12 | 282 | 8 / 4 / 0 / 0 |
| Pos | 5 | 7 | 5 | 366 | 0 / 3 / 2 / 0 |
| DefaultPowerUp | 1 | 1 | 1 | 4 | 1 / 0 / 0 / 0 |
| RaidBoss | 1 | 2 | 2 | 69 | 0 / 2 / 0 / 0 |
| **Total** | **719** | **1,500** | **1,129** | **43,296** | |

Number of `ADD_*` functions in the export (= tables with handlers): Tokusei 222, Item 193, Waza 262, Side 22, Field 11, Pos 5. The export contains 670 (Tokusei), 532 (Item), 744 (Waza), 62 (Side), 39 (Field), 21 (Pos), 7 (DefaultPowerUp), and 8 (RaidBoss) functions in handler classes (including helpers). At least one handler exists for 194 of 229 events. Most common across all types: 70 (98 entries), 34 (85), 196 (81), 108 (70), 142 (56), 95 (55), 141 (51), 172 (42), 90 (42), 180 (31).

**Implemented:** 4/222 abilities, 5/193 items (2 partial), 0/262 moves, 0 side/field/position effects.

### 10.2 Remaining effort (estimated from counts)

- Handlers up to 60 pseudocode lines (Tokusei 344, Item 248, Waza 330, Side 18, Field 12) mostly “read variable, compare, `MulEventVar`/`RewriteEventVar`”. Following sections 5/8, they should take minutes each and can be oracle-checked (the oracle runs the same function without extra work if it uses only `GetEventVar`/`MulEventVar`/`RewriteEventVar`/Pokémon reads).
- Handlers with **effects** (damage, stats, status conditions, weather, item use, messages) also need the `Common.*` effect API and 56 `Section_FromEvent_*` classes; this is the main work for later slices (flow/sections).
- Largest handlers (>120 lines): 3 Tokusei (largest 339 lines), 7 Waza (largest 171), 0 Item, 0 Side.

### 10.3 Recommended priority

1. **Effect API + Sections** (`Common.*`, `Section_FromEvent_*`) — without them, handlers have no effect.
2. **Damage/accuracy handlers** (events 63/64/69/70/74/75/83/84/90): abilities and items that directly affect power, attack, defense, accuracy, STAB, final damage (about 98 entries for event 70, 24 for 74, etc.); completes the Slice 1 calculation path.
3. **Switch-in/end-of-turn handlers** (108 `MEMBER_IN`, 145 `TURNCHECK_BEGIN`, 223 `TURN_END`, 172 `CHANGE_TOKUSEI_AFTER`): abilities such as Intimidate/weather setters, item healing; plus side/field/position effects (weather, barriers, hazards: only 40 functions total).
4. **Items 141/142/180** (consumption, berries): after item consumption/`UseItem`.
5. **Move handlers** (262 tables, mostly events 34/196/69): last, largest set, dependent on all of the above.

### 10.4 Other open points

- `BTL_POKEPARAM`: Wonder Room stat swap, transformation, G-mode values, other status-based evasion/accuracy flags, sick container duration/counter details (only duration type for `CheckSick`).
- `EventFactorContainer.CopyFrom/Clear` (state copy for AI simulation) and source of move sub-priority (`Waza.Add` parameter 4 from server commands).
- Behavior of `Handler.Pos.isRegistable`, work-value conventions per handler (indices 0–6), and role of ISOLATE factor type at turn end.
- `EventSystem` results passed to `BattleEnv` (e.g. Section propagation through `EventHandlerArgs`): C# argument class carries only battle environment, EventSystem, variable set, and factor.

## 11. Reproduction

```
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_heap.py              # regenerate fixtures (about 2 minutes)
PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_heap.py --tables      # handler tables (work/battleevents/handler_tables.json)
PYTHONPATH=tools/pydeps python3 -m unittest scripts.tests.test_battle_oracle_heap
cd work/dotnet-battleevents && dotnet test                                  # C# tests without Unity Editor (throwaway project)
```
