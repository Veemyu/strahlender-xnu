# Vertical slice: title → Continue → field → event → battle → save (task `ap-vertical-slice`)

> **Historical (2026-10-20):** Discontinued Unity approach. `scripts/ios_deploy.sh` was removed from `main` and exists only on branch `unity`.

Date: 2026-10-19; measured in the main Editor (Unity 6000.3.26f1, Metal) and macOS Player. Names, numbers, and structure only; no game text, real saves, or images in Git. Images/logs remain under ignored `work/`. Evidence levels follow `docs/spielkern-1.md`: **[A]** assumption, **[P]** supported by evidence. No sound; AudioSafety unchanged.

## 1. Results

An **unattended** run completes in the Editor and macOS Player (input script `work/vslice/run4.txt`, about 100 seconds wall time, 1,215 logic ticks):

| Step | Player result |
|---|---|
| Boot → `Game` scene (`-xnuScene Game`) | Title screen with Continue |
| Continue | Master data in 2.2–2.6 s: 707 trainers, 183 encounter zones, 119 message files + `msg_common`, 856 script files, 12,985 labels, 709 trainer and 659 zone names. Imported local Ryujinx save (979,108 bytes; source read-only). |
| Field | Zone 167 at saved cell (842, 597), party of six, money 45,156, eight badges; field ready in 1.8 s |
| Walking | Player walks four cells (30-Hz grid movement) and enters door: **zone 167 → 168**, Pokémon Center interior, different map bundle, fade |
| Talking | `nearnpc` + A: `GameEvHost` starts `ev_c10pc0101_pcwoman1`; **four text windows** with actual messages and original `sharedui` frame, **Yes/No choice**, then healing animation (five unimplemented host calls, see gaps), event ends (one started, one ended) |
| Encounter | Forced `encounter`; zone 168 table empty, fallback species 396, level 3 → `Battle` |
| Battle | Fight/Bag/Pokémon/Run menu, move selection with PP, nine played log beats, messages with names from `ss_monsname`/`ss_wazaname`, HP bars; victory and return to field |
| Saving | Script `save` (in-game: menu → Save): 979,108 bytes, refreshed hash, backup `Backups/main/<timestamp>/SaveData.bin`. Ryujinx source bytes and timestamp unchanged. |

Local images: `work/visual/vslice/`: Editor `s*.png`/`v*.png`, Player `p*.png`, intermediate `t*.png`. Log: `work/builds/player.log`.

## 2. Structure

New **`Xnu.Game.Unity`** assembly (`unity/Assets/Scripts/Game/Runtime`), Editor portion `Game/Editor` (menu `Xnu/Game/Spielszene erzeugen`, scene `Assets/Scenes/Game.unity`, after `Boot` in `BuildScript.DefaultScenes`; automatically listed by the boot menu).

| File | Responsibility |
|---|---|
| `GameDriver` | MonoBehaviour: title, loading, 30-Hz `LogicStep`, device/script input as `GameInput` data, text bridge, battle view, saving, `IScriptWorld` |
| `FieldHostAdapter` | `IFieldHost`, `IFieldInteractionHandler`, `IFieldFlags` for `FieldController`: MAP_CHANGE → `BeginSwitchZone`, talk/contact → `FieldSignal`, save work/system flags → object visibility, fade, player position |
| `BattleView` | uGUI: HP panels, placeholder boxes instead of models, message window, menus; plays `BattleBeat` and returns commands; automatic replacement after fainting |
| `SaveSlotService`, `SavedPosition` | Own `main` slot under app save root (`-xnuSaveRoot`/`XNU_SAVE_ROOT`, otherwise `persistentDataPath`, slot `Saves/main`); since `docs/ipad-durchstich-1.md`, valid file required, with staging `SaveData.bin` in Documents. Imports source (`XNU_SAVE_SOURCE` or `<GameData>/../Ryujinx/…/0`), backup before every overwrite. |
| `GameDataLoader`, `GameBattleTexts` | Master data, `msg_german` + `msg_common`, name tables; names and original battle messages |
| `GameOptions` | `-xnuInputScript`/`XNU_SCRIPTED_INPUT`, `-xnuSaveSource`, `-xnuSaveRoot`, `-xnuShotDir`, `-xnuAutoContinue` |

Pure `Xnu.Game` logic (no UnityEngine): `BattlePresentation.cs` (`BattleLogPlayer`: event log → `BattleBeat`, tracking HP) and `InputScript.cs` (input-script parser/execution).

Backward-compatible changes: `FieldController` (`Flags`, `ExternalTick`/`LogicTickExternal`, `BeginSwitchZone`, `SetStartCell`, `ZoneChanged`, `RefreshNpcsNow`; interiors show only their own placements), `GameInput.InputOverride`, `DialogModel.ForceFinish`, `ChoiceModel.Force`, `GameLoop.BeginBattle`, `HostCommands` (523), and `scripts/field_zone_names.py` (also exports `TrainerID` names).

**Text:** Host opens `DialogModel`; driver displays it through `TextboxView` (typewriter, pages, Yes/No), reporting completion through `ForceFinish`/`Force`. Confirmation is withheld from the game loop while a textbox/choice is open. `GameEvHost` supplies names/variables through `TagWordBuffer` (Xnu.Text).

**Battle text:** Original messages only where file, label, and placeholders can be mapped **[A]**: encounter (`BTL_STRID_STD_Encount_Wild1`), experience, level-up, escape (`ss_btl_std`). All other messages are locally written placeholders, using names from actual files.

## 3. Input script

One instruction per line: `wait N`, `tap A|B|Plus|Up|Down|Left|Right`, `hold <direction> N`, `mash N`, `mashuntil <state> N`, `waitstate <state> N` (Title, Loading, Field, Transition, Event, Textbox, Choice, Battle…), `fight S`, `starter I`. Driver-specific commands: `goto X Y DIR`, `nearnpc [partial-ID]`, `encounter`, `shot NAME`, `save`, `report`, `state`, `log TEXT`, `quit`. Directions are **screen-relative**; indoors and outdoors (yaw 180), Up means grid gy−1.

Input uses `GameInput.InputOverride`, without focus or mouse. Timed `waitstate` makes runs independent of timing; timeouts are counted (one here for the brief `Transition` state).

Editor reproduction: Open `Game`; through `unity command eval`, set `XNU_GAMEDATA=<Repo>/work`, `XNU_SCRIPTED_INPUT`, `XNU_SHOT_DIR`, `XNU_ENV_HOUR`; then `editor_play`.

Player: `scripts/build_all.sh --only assets --target macos --bundle-subset scripts/subsets/vslice-start.txt --min-free-gb 20` with `ASSETS_DEST=<ignored-directory>` (182 MB, 788 files, 4 s); menu `Xnu/Build/macOS (arm64, IL2CPP)` (93 s, 972 MB); then `xnu -xnuScene Game -logFile <path>` with the same environment (`XNU_GAMEDATA` points to the assets-stage destination). The Player cannot load original Switch bundles; without `bundle_retarget`, the field fails with “LoadFromFile returned null.”

## 4. Measurements

| Metric | Value |
|---|---|
| EditMode tests | **688/688 passed** (previously 645; 24 new `GameUnityTests` covering scripts, options, log player, battle view, field adapter, save slot, EditMode driver; additional tests from other agents) |
| Loading | Data 2.2–2.6 s in Editor; field 1.8 s in Player |
| Player script | 1,215 ticks = 40.5 s logic time; about 100 s wall time including loading/captures |
| Player frame rate | 27–30 FPS (30-Hz logic) |
| Nurse event | Four text windows, one choice, five unimplemented host calls, 497 ticks (16.6 s) |
| Battle | Nine log beats to completion, one player command |
| Save | 979,108 bytes, valid hash (test round trip), backup created |

## 5. Issues found and fixed

- **Saved location is blocked:** `TownMapLocation` (zone 167, (842, 597)) is a map marker outside the Pokémon Center, not a player position **[A]**. Driver selects nearest walkable cell (840, 599). Its own slot writes zone/position to those same fields.
- **Interiors displayed NPC markers from all rooms sharing a map bundle:** `FieldController` now uses only current-zone placements.
- **Textbox absent from captures:** `Awake` created an overlay; driver now attaches it to the game camera.
- **Stale movement:** `GameInput.Move` persisted between frames with multiple logic ticks (`InputOverride.Enabled`).
- **Healing hung:** Missing command 523 (counts Pokémon Center animation balls up to party size) caused an infinite loop; implemented as party size **[A]**.
- **Species names missing:** `ss_monsname` belongs to `msg_common`, not `msg_german`.

## 6. Known gaps

- **Trainer battle and grass encounter** are wired (`HostCommands`, `FieldSignal.Step`) but **not exercised** here; only a forced wild encounter ran. Zone 168 has no encounter table, so fallback species 396 was used.
- **Minimal battle UI:** Placeholder boxes, no models/sprites; no Bag (notice only), no multi-battle; automatic replacement after fainting; mostly custom messages; HP display only bars and player's numeric HP; no animations/status display.
- **Field:** Stationary NPC markers, no models. `SetObjectVisible/Grid`, `AC_*` animation, camera/effect `RunVisual` are counted gaps. Field triggers doors/warps itself, not through `FieldSignal.Warp`. Player uses gray fallback shader in Player.
- **Menu:** Save/Back only; no Bag, party, Pokédex. New Game is disabled at the title.
- **Save position** is assumed as above; direction 0/1 mapping unresolved. `PeriodOfDay` does not come from the clock.
- **Healing animation:** Commands 977/978/765 (balls/nurse) unimplemented; 523 assumed.
- **Three script states are transient** (`Transition`), hence timed `waitstate`.
- **iPad:** Build/install/start succeeded; initial run incomplete (section 7).

## 7. iPad (initially partial)

**Later same-day update:** The unattended slice now completes on iPad. `docs/ipad-durchstich-1.md` records the “no slot” cause (duplicate `Saves` directory and root-owned directories created by devicectl), save transfer (`scripts/ios_push_save.sh`), and measurements: zero texture errors, 30/60/120 FPS, footprint ≤ 861 MiB. The following records the earlier, unfixed state.

- **Expanded subset:** Added `Environments/fields/area008` and `Environments/prefab_map/t02pc0101` to `scripts/subsets/ipad-start.txt` (seven bundles). `scripts/build_all.sh --only assets --target ios --texture-format 6x6 --bundle-subset scripts/subsets/ipad-start.txt`: 789 files, **229 MB** (previously 179 MB), 31 s including ASTC conversion.
- **Built/installed:** iOS menu build (main Editor target switch: 502–505 s, 1,107 MB); `scripts/ios_deploy.sh … --no-launch`: 2 min 8 s.
- **Launched:** App starts with `XNU_START_SCENE=Game` and `XNU_SCRIPTED_INPUT=run5.txt` via devicectl environment variables (arguments after `--` did not arrive). Script loads, but remains at title: **no slot**. Save copied via `devicectl device copy to` into `Documents/Saves/main/SaveData.bin` was absent after reinstall or not recognized. Field was **not loaded**; **texture errors (previously 1,884) and a 60-second run were not measured**. Zero logged errors without a loaded map is inconclusive. Title runs at 60 FPS.
- Pending at that stage: Check `Documents/Saves/main`, copy save after install, repeat run, count texture errors. iPad time ran out after two 8.5-minute builds due to target switching.

## 8. Next steps at the time

1. Measure trainer battle (`TRAINER_BTL_SET`, trainer sight field) and grass encounters with step checks.
2. Export player/NPC materials; use NPC models with walking patterns.
3. Battle: Bag, displayed Pokémon switching, status symbols, bundle models, original `ui_masterdatas` layout.
4. Menu contents (Bag, party, map), New Game (`FIRST_POKE_SELECT`).
5. Establish original save position (`SetPlayerPosData`), then adjust `SavedPosition`.
6. iPad: Build ASTC subset, deploy, count texture errors.
