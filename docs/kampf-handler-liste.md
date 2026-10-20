# Handler List (Battle, Slice 3)

Prioritized list of the battle system's ability, item, and move handlers. All prose is original; the document contains only IDs, internal
handler abbreviations (code identifiers), and numbers, no game text or content. Figures come from `work/masterdata` and
`work/decomp/battle_all` (local, not in the repository) and can be regenerated with the scripts in section 5.

## 1. Method

1. **ID → handler table.** `scripts/battle_handler_map.py` runs the real `.cctor` methods of handler classes in the oracle, reads
   `GET_FUNC_TABLE` (ID → `ADD_*` function), calls each `ADD_*` function, and maps the returned table pointer to the
   static `HandlerTable_*` fields. Results (`work/battleevents/handler_map.json`): Tokusei 241 IDs → 222 tables,
   Item 197 → 193 (one ID has no table), Waza 310 → 262, side 22, field 10 (8 with a table), position 5, default power-up 3, raid boss 1.
   Multiple IDs often share a table (e.g. Tokusei 37 and 74, Items 298–313 each with one type constant).
2. **Frequency.** `scripts/battle_handler_priority.py` counts from master data: abilities per species (`PersonalTable`, slots 1–3, species rows)
   and per trainer team slot (`TrainerTable.TrainerPoke`); items as wild-held items (species rows) and trainer items; moves as
   learnset entries (`WazaOboeTable`, once per species) and trainer moves. The “Usage” column below is `species/trainer`.
3. **Simplicity.** Search each handler's pseudocode (including class helper functions) for external calls. **Pure** means only
   `Common.GetEventVar/MulEventVar/RewriteEventVar`, Pokémon reads (`BTL_POKEPARAM.*`), weather/field/partner checks, and
   calculation helpers. These handlers can be run in the oracle with query stubs only. **Impure** handlers have effects (messages
   `Common.Message`, `RankEffect`, `AddSick`, `Damage`, `UseItem`, `ConsumeItem`, `SetRecallEnable`, etc.).

Results: Tokusei 64 of 241 IDs are pure, Item 80 of 197, Waza 57 of 310. All pure handlers with ≤ 60 lines and some longer Waza handlers
are implemented; remaining work is mainly handlers with effects (sections 3 and 4).

## 2. Implemented (175 IDs)

Evidence level **[OK]**: the real ARM64 function runs in the oracle against the C# function; Pokémon/field queries are stubs (spec 3, section 3).
Line count = handler pseudocode lines.

### 2.1 Abilities (54 IDs, 4 from slice 2)

| ID | Handler | Event | Lines | Usage |
|---|---|---|---|---|
| 1 | Akusyuu | 133 | 38 | 7/7 |
| 4, 75 | KabutoArmor | 67 | 29 | 8/6, 14/1 |
| 8, 81 | Sunagakure, Yukigakure | 64 (155 open) | 56 | 17/9, 6/2 |
| 14 | Fukugan | 64 | 29 | 5/1 |
| 32 | TennoMegumi | 102, 125, 133, 205 | 59 | 9/9 |
| 33, 34 | Suisui, Youryokuso | 19 | 47, 55 | 32/71, 25/9 |
| 37, 74 | Tikaramoti | 74 | 38 | 3/4, 2/25 |
| 47 | AtuiSibou | 74 | 38 | 19/43 |
| 69 | Isiatama | 101 | 29 | 18/76 |
| 77 | Tidoriasi | 64 | 40 | 7/4 |
| 79 | Tousousin | 70 | 55 | 10/0 |
| 86, 126 | Tanjun, Amanojaku | 114 | 39 | 3/3, 2/0 |
| 89 | TetunoKobusi | 70 | 40 | 5/3 |
| 91 | Tekiouryoku | 84 | 38 | 5/2 |
| 92 | SkillLink | 66 | 29 | 4/0 |
| 97 | Sniper | 90 | 38 | 12/8 |
| 98 | MagicGuard | 156 | 29 | 6/9 |
| 101 | Technician | 70 | 37 | 12/11 |
| 105 | Kyouun | 67 | 31 | 6/3 |
| 132 | NakamaIsiki | 90 | 38 | 5/0 |
| 134, 135 | HeavyMetal, LightMetal | 151 | 29 | 5/0 |
| 136, 231 | MultiScale | 90 | 40 | 2/0 |
| 137, 138 | Dokubousou, Netubousou | 70 | 47 | 1/0, 2/3 |
| 146, 202 | Sunakaki (155 open), Yukikaki | 19 | 56, 38 | 2/0 |
| 147 | MilacreSkin | 64 | 44 | 3/0 |
| 162 | GoodLuck | 64 | 31 | 0/0 |
| 169 | FurCoat | 75 | 38 | 0/0 |
| 177, 205 | HayateNoTsubasa, HealingShift | 17 | 48, 43 | 0/0 |
| 181 | KataiTume | 70 | 38 | 0/0 |
| 196 | Hitodenasi | 67 | 43 | 0/0 |
| 198 | Harikomi | 74 | 42 | 0/0 |
| 200 | Haganetukai | 74 | 39 | 0/0 |
| 203, 204 | Enkaku, UruoiVoice | 42 | 29, 40 | 0/0 |
| 212 | Husyoku | 217 | 32 | 0/0 |
| 217, 249, 252 | Battery, PowerSpot, HaganeNoSeisin | 70 | 45, 38, 40 | 0/0 |
| 218 | MohuMohu | 90 | 50 | 0/0 |
| 233, 246 | BrainPrism, KooriNoRinpun | 90 | 38 | 0/0 |
| 247 | Jukusei | 140 | 30 | 0/0 |
| 239, 242 | ScrewObire | 46, 225 | 58 | 0/0 |

Coverage: 21.3% of species ability slots and 20.4% of trainer team slots. Most commonly used abilities have effects
(ID 22: 20/124, ID 39: 22/99, ID 26: 59/62 …, section 3).

### 2.2 Items (73 IDs, 4 from slice 2)

| Family | IDs | Event | Handler |
|---|---|---|---|
| Type boosters (power multiplier based on item value, one type constant each) | 222, 233, 237–244, 246–251, 254, 298–315, 317, 318, 644 (38) | 70 | `common_PowerUpSpecificType` |
| Weather rocks (weather duration = item value) | 282–285 | 152 | `common_WazaWeatherTurnUp` |
| Accuracy modifiers | 213, 255 (factor 100 − item value), 265, 276 | 64 | HikarinoKona, NonkiNoOkou, KoukakuLens, FocusLens |
| Critical-hit stage | 232, 326 (+1), 256, 259 (species-specific, +2) | 67 | PintLens, LuckyPunch, Naganegi |
| Species-specific boosters | 226, 227 (species 366), 258 (species 104/105), 257, 274 (species 132, not transformed), 225 (species 380/381) | 74, 75, 19, 70 | SinkaiNoKiba … KokoroNoSizuku |
| Initiative/Gewicht ×0,5 | 215, 289–294 (19), 539 (151) | 19, 151 | KyouseiGipusu, PowerXXX, Karuisi |
| Other | 266, 267, 268, 296, 543, 640, 1123, 879 | 70, 90, 174, 78, 75, 150, 210 | one handler each |

Coverage: 54.3% of wild-held item entries, 29.7% of trainer items. The most common unsupported trainer items (158, 157, 150 berries; 275; 270 recoil;
234; 217; 273 …) need effect handlers (item consumption).

### 2.3 Moves (48 IDs)

Special effects only; standard effects are in `WazaTable` (section 4).

| ID | Handler | Event | Lines | Usage (learnset/trainer) |
|---|---|---|---|---|
| 89 | Jisin | 189, 90 | 80 | 34/76 |
| 371, 372 | Sippegaesi, Dameosi (power ×2) | 69 | 42 | 35/41, 27/10 |
| 474 | BenomShock | 70 | 42 | 12/28 |
| 74 | Seityou | 113 | 57 | 37/22 |
| 246, 702 | GensiNoTikara | 113 | 38 | 53/17 |
| 23, 34, 407 | Fumituke | 62, 90 | 84 | 23/19, 31/17, 10/6 |
| 86 | Denjiha | 77 | 29 | 34/17 |
| 16, 239 | Tatumaki | 189, 69 | 80 | 27/16, 12/10 |
| 473, 540, 548 | PsycoShock | 72 | 39 | 8/16 |
| 213 | Meromero | 54 | 46 | 12/14 |
| 234–236 | AsaNoHizasi (healing amount by weather) | 177 | 47 | 6/5, 24/10, 12/13 |
| 46, 18 | Hoeru | 203 | 41 | 25/11, 17/4 |
| 57 | Naminori | 189, 90 | 80 | 17/11 |
| 59 | Fubuki | 62 | 38 | 21/9 |
| 101, 69 | TikyuuNage (damage = level) | 88 | 34 | 20/8, 26/2 |
| 162, 717 | IkariNoMaeba (halbe KP des Ziels) | 88 | 44 | 5/6 |
| 512 | Acrobat | 69 | 40 | 8/5 |
| 492 | Ikasama | 71 | 31 | 8/3 |
| 206, 610 | Mineuti | 143 | 38 | 12/2 |
| 573 | FreezDry | 78, 79 | 38 | 3/2 |
| 776 | BodyPress | 73 | 29 | 2/1 |
| 329 | ZettaiReido | 65 | 40 | 11/0 |
| 599, 602, 674 | BenomTrap, ZibaSousa | 113 | 42 | 7/0, 5/0 |
| 744, 781, 782 | DaiMaxHou | 90 | 42 | 0/0 |
| 533, 663 | NasiKuzusi | 63, 72 | 58 | 0/0 |
| 659 | Sunaatume | 177 | 41 | 0/0 |
| 745 | NeraiUti | 46, 225 | 58 | 0/0 |
| 754, 755 | DengekiKutibasi | 69 | 42 | 0/0 |
| 788 | Newton | 70 | 40 | 0/0 |

Coverage: 13.9% of learnset entries, 12.7% of trainer moves.

## 3. Priority of remaining handlers

| Rank | Group | Scope (IDs) | Prerequisite |
|---|---|---|---|
| 1 | Pure handlers with >60 lines: Tokusei 96, 109, 244, 84, 159, 174, 178, 182, 184, 206; Item 112, 135, 136, 278; Waza 87, 167, 210, 283, 542, 560, 751, 783 | Tokusei 10, Item 4 (+ 4 placeholders), Waza 8 | none (queries only) |
| 2 | Effect API: `Common.Message`, `TokuseiWindow_In/Out`, `RankEffect`, `AddSick`, `CureSick`, `Damage`, `RecoverHP` | 58 Tokusei and 74 Waza handlers with messages; 28 with stage effects | section layer (next slice) |
| 3 | Item consumption (`UseItem`, `ConsumeItem`, `SetRecallEnable`): berries, sash, leftovers | about 50 items | item consumption, berry data |
| 4 | Side, field, and position effects | 22 + 10 + 5 | weather/field management |
| 5 | Moves with raid boss/G-Wall checks (`GetRaidBossParam`, `GWall.IsActive`) | about 40 | raid boss, G mode |

Most common unsupported abilities by trainer usage: 22 (124), 39 (99), 26 (62), 51 (48), 38 (43), 9 (40), 5 (37), 68 (37), 28 (33), 41 (27), 114 (27),
109 (27, pure, 103 lines), 62 (25), 61 (25).

## 4. Why many handlers are missing (findings)

- Effect handlers call `Common.Message`/`StrParam` (messages) and `Section_FromEvent_*` descriptions: 58 Tokusei, 74 Waza, and about 70
  item handlers depend on them. Without the section layer, their output cannot be checked against the oracle.
- Moves without handlers (286 of 512 valid moves) use only the table (`WazaTable`): power, accuracy, priority (35 moves with
  priority ≠ 0), stat changes, and conditions (195 moves) are stored there and read by the slice 1 calculators and sections.
  There is no per-move “priority handler”; only `GET_WAZA_PRI` (event 17, e.g. abilities 177/205) changes priority in a handler.

## 5. Reproduction

```
PYTHONPATH=tools/pydeps python3 scripts/battle_handler_map.py        # ID -> table -> handler (work/battleevents/handler_map.json)
python3 scripts/battle_handler_priority.py                          # frequency x simplicity (work/battleevents/handler_priority.json)
python3 scripts/battle_pseudo_view.py Tokusei 0x1a3f7b0             # pseudocode without IL2CPP noise (output only)
```
