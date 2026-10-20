# UI Specification 3: Stubs in the Main Project, Original Windows In-Game, Battle UI

> **Historical (as of 2026-10-20):** Unity approach discontinued. `scripts/stub_gen.py` has been removed from `main` (it remains only on branch `unity`); the `stubs` stage no longer exists on `main`.

As of 2026-10-19, todo `ap-ui`, slice 2. Numbers, methods, and original code only; no game content, text, or images in the repository (captures and dumps under `work/`, gitignored). The logic was written by hand in original wording, not mechanically translated from pseudocode.
Measurement: main editor Unity 6000.3.26f1 (Metal), local save and data, game mode in the editor with an input script. No audio.

## 1. Summary of results
- **Stubs run in the main project:** `stub_gen.py gen` into `unity/Assets/XnuStubs` (gitignored, 887 files, 5 MB), 0 compiler errors, existing tests still passing (696/696 before the new tests). Conflicts with `Xnu.*`: 0 identical fully qualified names.
- **Switch:** `XNU_STUBS` via `unity/Assets/csc.rsp` (gitignored, applies only to Assembly-CSharp). Without this file, the hooks are absent (`Assets/Scripts/DprHooks`, all under `#if XNU_STUBS`), and the project builds without stubs.
- **Original UI in-game (Editor):** main menu (8 grid entries), party (6 Pokémon: name, level, HP bar, gender, icon), bag (8 pockets, items and quantities from the save, description, money), choice window (Yes/No from the original context menu), and battle status window/move list from the original prefabs. All text comes from local text files, sprites from bundles; original shaders were never loaded.
- **Tests:** `UiScreensTests` (cursor, menu/party/bag models, bundle filter, text binding, save data binding), 54 new tests.

## 2. Build order
`tools extract il2cpp masterdata shaders video audio assets stubs unity-build deploy`. The `stubs` stage writes both `XnuStubs` **and** `csc.rsp`; the `unity-build` stage deletes `csc.rsp` if `XnuStubs/manifest.json` is missing. If an editor has the project open, `stubs` is skipped (new files trigger recompilation). Without a dump, skip the stage; the project builds without original prefabs, and windows fall back to the custom textbox menu and placeholder battle view (`UiWindowManager.IsAvailable`). `link.xml` preserves Assembly-CSharp and the stub assemblies (IL2CPP stripping; untested in the player).

## 3. Structure
| Part | Contents |
|---|---|
| `Xnu.UI/Logic/ListCursor.cs`, `ScreenModels.cs` | `ListCursor`, `GridCursor`, `MainMenuModel`, `PartyScreenModel`, `BagScreenModel`, `HpStages`, row models without Unity types |
| `Xnu.UI/Runtime/UiBridge.cs` | Interfaces to stubs (textbox, menu, party, bag, context menu, battle UI) |
| `Scripts/DprHooks/UiBridgeHooks.cs` | Partial stub implementations (Assembly-CSharp, `XNU_STUBS` only): pass through serialized fields, no logic |
| `UiBundles` | UI bundle provider: no shader bundles, only `.ge` language variant, atlas fallback (`SpriteAtlasManager.atlasRequested`), Pokémon icons (`textures_mass/pokemon_dp`) |
| `OriginalWindowFactory`, `UiMaterialFixer`, `UiTextBinder` | Instantiate prefabs, set canvas to 1280×720/match width, replace materials without shaders with custom shaders (`XnuUiAdd`, `XnuUiGray`) or standard material, use TMP default font, fill labels from file+label |
| `OriginalViews`, `UiWindowManager`, `BattleUiSkin` | Views and window stack (menu → party/bag → choice/notice), battle skin |
| `Game.Unity/GameUiData`, `GameDriver`, `BattleView` | Data from save and text; menu button opens main menu, Plus in menu prompts “Save”; battle view uses the skin |

## 4. Observations and gaps
- **Message window:** the original has no prefab (`resources.assets`); the custom `TextboxView` with the original frame remains.
- **Animator states** for windows cannot be identified in bundles (no editor controller); window animators are disabled, so there is no open/close effect. DOTween animations do not run (party HP bars remain still).
- **Battle:** status window and move list are original; the **command list** (`BUIActionList`) is at the prefab's hidden position (position is set only in code), so the custom text menu is used until then. No original target/bag/Pokémon-switch windows; messages still use the custom box. Move type graphic assumes the type index from master data [A]. Battle Pokémon models: **not implemented** (placeholder boxes).
- **Runtime sprites verified:** the bag icon in the main menu, pocket header image, and party gender graphic are empty in the prefab and are hidden or only tinted; item icons are missing (source not found in bundles). Status conditions (poisoning, etc.) are not displayed.
- **Font:** TMP default (LiberationSans); Japanese strings left in prefabs appear as boxes (warnings “Unicode … not found”); original font is not connected.
- **Party/bag subpages:** selecting in party/bag does nothing (context menu, item use, and status are missing). Pokédex, Trainer Card, map, capsule decoration, settings, and Mystery Gift: frame only, not selectable.
- **Labels:** unsupported placeholders `{n:m}` are cleared; in the bag, static text (“Battle”) still overlaps the description.
- **Player test (macOS) and iPad:** **not performed** (time). Player bundles: `UIs/ui/uiresidentwindow` 8.15 MB, `UIs/ui/prefab/battleviewuisystem` 1.05 MB, plus their dependencies (atlases, `.ge` variants); listed in `scripts/subsets/vslice-start.txt`, total dependency size not measured. Whether the `assets` stage copies dependencies and whether `bundle_retarget` leaves UI bundles unchanged is unverified.
- **New save (town):** the scenarios above still used the old save (zone 167); switching to the save's storage zone remains pending.

## 5. Next screens
1. Battle command list (position, show/hide), target and bag windows; then Pokémon models (catalog `Pokemon Database/pokemons/battle/pmNNNN_FF_00`, 1,304 prefabs) using `MaterialRemapper`.
2. Party context menu, Pokémon status (`pokestatus`), item use, status display.
3. Original font and line widths, window animation (DOTween replacement), player/iPad run with subset and size measurement.

## 6. Reproduction
```
python3 scripts/stub_gen.py gen --out unity/Assets/XnuStubs          # or scripts/build_all.sh --only stubs
unity command … recompile ; scripts/unity_safe.sh test               # tests
# game mode: Game scene, environment variables XNU_GAMEDATA/XNU_SCRIPTED_INPUT/XNU_SHOT_DIR, input script (Plus, A, B, arrows; shot NAME)
```
