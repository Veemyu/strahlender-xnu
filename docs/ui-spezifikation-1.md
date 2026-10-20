# UI Specification 1: Original UI Structure, Inventory, and Rebuild Plan

As of 2026-10-19, todo `ap-ui` (analysis phase). Structures, class/field names, and numbers only; no game content or text.
Text, format, tags, and fonts are covered in `docs/lokalisierung.md`. All figures come from our own dump (Unity 2019.4.27f1, Switch), read without the Unity Editor using UnityPy and `work/il2cpp/dump.cs`.

## 0. Evidence and acceptance levels
**Evidence levels** used for statements:
- **[D]** measured from data (catalog `Dpr.bin`, UnityPy over the bundles, `resources.assets`, master-data JSON).
- **[S]** from `dump.cs` (classes, fields, offsets, constants, signatures): structure, not logic.
- **[A]** assumption or inference, identified in the text.
- **[T]/[V]** code checked by tests / against real data (section 9 only).
Ghidra pseudocode was **not** analyzed. The window-class logic still needs to be read before rebuilding a screen (included in the estimate in section 7).

**Acceptance levels** for each rebuilt screen (for later implementation):
- **U1 Structure:** prefab/bundle loads, hierarchy is complete, no missing references, sprites resolve.
- **U2 Layout:** positions and sizes match the original at 1280×720 (16:9) and 4:3 (measurements from RectTransform data, spot-checked against user reference images, e.g. from Ryujinx).
- **U3 Behavior:** navigation, input, state, and text follow the original logic (synthetic-data tests, checked against pseudocode).
- **U4 Pixel match:** image comparison against a reference in fixed states (requires the ported UI shaders, section 8).

## 1. Summary
- The UI uses **Unity uGUI** (Canvas, RectTransform, Image, Slider, ScrollRect, LayoutGroups) with **TextMeshPro** and a custom `Dpr.UI.*` layer (325 classes, 4,834 methods); it is not a custom rendering system. [D][S]
  Core types: `UIManager` (singleton), `UIWindow` (window base), `UIWindowID` (74 windows), `UIText` (TMP subclass connected to the message system), `UINavigator`/`Cursor` (button navigation), `UIInputController` (Switch button masks).
- Windows are **prefabs in bundles**: 82 prefab roots in `UIs/ui/*` and `Dpr/fieldui/*`; 53 are in the combined bundle `ui/uiresidentwindow` (8.2 MB). The `UIDatabase.UIWindow` table (74 rows) maps each `UIWindowID` to a bundle and prefab. [D]
- Reference resolution is **1280×720**; 78 of 84 scalers in prefab bundles use `CanvasScaler` “Scale With Screen Size,” matched by width (Match 0). This suits 16:9; at 4:3 (1024×768, iPad), the height changes. [D]
- Total UI assets: 1,994 bundles in project `UIs` plus 11 Message bundles (95.3 MiB total), plus 5 font bundles (24.2 MiB); 7,282 sprites, 2,584 textures, 12,812 GameObjects in prefabs, 499 animation clips, 303 animators. [D]
- Textures are mostly **ASTC** (native on Apple GPUs), with some **DXT5** (BC3, not native on iOS/iPadOS); small icons use RGBA32. [D]
- Core runtime objects (`UIManager`, `MsgWindowManager`, `MessageManager`, `NowloadingController`, `UIModelViewController`) are in `Data/resources.assets` **without a TypeTree**. They can only be read there using field layouts from `dump.cs`; we plan to rebuild them anyway. [D]
- **Recommended approach:** load original prefabs from bundles and drive them with **custom scripts using the same class/field names** (`Dpr.UI.*`, Assembly-CSharp); validate with a spike when an editor is available (section 6). Estimated core scope: **150–230 developer-days** [A]; start with the framework and message window.
- Built and tested in this step: the `Xnu.Text` text reader (section 9).

## 2. Inventory

### 2.1 Catalog (`Dpr.bin`), `UIs` project, and `Message`
| Group (catalog path) | Bundles | Size | Assets (catalog) | Contents |
|---|---:|---:|---|---|
| `UIs/ui` | 34 | 24.5 MiB | 87 prefabs | Window prefabs: 53 in `uiresidentwindow`, one each for contest/trade/UG/Union/team, 2 transitions, 6 Hall of Fame parts |
| `UIs/textures` | 70 | 10.7 MiB | 1,608 PNG, 19 SpriteAtlas | Atlases by area (`common`, `box`, `zukan`, `map`, `menutop`, `report`, `setting`, `trainercard`, `pokemon`, `field/*`, `halloffame/*`) |
| `UIs/textures_mass` | 1,845 | 38.4 MiB | 4,296 PNG, 1 SpriteAtlas | Pokémon icons: `pokemon_dp` 1,302 bundles (7.1 MiB), `pokemon_l` 542 (14.9 MiB), `texturemass` 1 (16.4 MiB) |
| `UIs/shareduiassets` | 19 | 2.0 MiB | 450 PNG, 19 SpriteAtlas | `sharedui` (947 KB) + 9 language variants each of `sharedui_lang.*` and `battle_lang.*` |
| `UIs/gms` | 12 | 4.3 MiB | 4 prefabs, 10 SpriteAtlas, 1 PNG | Minigame UI (localized graphic text `graphictext.*`) |
| `UIs/contestphoto` | 4 | 0.4 MiB | 4 PNG | Frames for contest photos |
| `UIs/masterdatas` | 1 | 0.3 MiB | 6 `.asset` | `UIDatabase` (32 sheets), `PlaceNameTable`, `TownMapTable`, `TownMapGuideTable`, `DistributionTable`, `InputLimitTable` |
| `UIs/searchdatas` | 9 | 0.2 MiB | 9 `.asset` | Pokédex search index, one per language |
| `Message` | 11 | 14.5 MiB | 1,280 `.asset` | Text (see localization) |
| Total | 2,005 | 95.3 MiB | | |
Other UI-related sources [D]: `Dpr/font` (5 font bundles, 24.2 MiB, section 2.4), `Dpr/fieldui` (2 bundles, 0.8 MiB: `fieldcanvas` with 24 GameObjects, `encseqgym`), `Union/unionroom` (1 prefab, 2.9 MiB), `Contest/textures` (10 SpriteAtlas, 2.7 MiB),
`Dpr/scenes/title` (scene bundle, 287 KB), `field` scene (3 canvases with CanvasScaler), `Data/resources.assets` (10 canvases, 130 GameObjects). Not in the catalog but on disk: 81 localized texture bundles `GMS/textures/graphictext/*` (`docs/bundle-katalog.md`).
**Language variants** (suffixes `.en .fr .ge .it .jp .ko .si .sp .tr`): 11 bundle families × 9 = 99 bundles, 11.6 MB total: `common_lang`, `sharedui_lang`, `battle_lang`, `gms/graphictext`, `contestgraphictexture`, `searchdatas/indexdata`, five Hall of Fame logos. Text embedded in images (logos, labels) therefore has separate graphics for each language. [D]

### 2.2 Object types across all 1,994 `UIs` bundles [D]
GameObject 12,812, RectTransform 12,753, MonoBehaviour 12,025, CanvasRenderer 9,598, Sprite 7,282, Texture2D 2,584, MonoScript 706, AnimationClip 499, CanvasGroup 452, Canvas 363, Animator 303, Material 119, AnimatorController 118, SpriteAtlas 55, Font 20, Camera 17, BoxCollider2D 22.
Script classes in prefabs (11,883 MonoBehaviours, 337 classes): `UnityEngine.UI.Image` 6,923, `Dpr.UI.UIText` 1,648, `HorizontalLayoutGroup` 195, `Dpr.UI.UINavigator` 184, `PokemonIcon` 180, `SealIcon` 149, `Capsule2DGridCell` 148, `RawImage` 147, `VerticalLayoutGroup` 145,
`Slider` 90, `RectMask2D` 88, `Dpr.UI.Cursor` 87, `CanvasScaler` 84, `DOTweenAnimation` 75, `GraphicRaycaster` 50, `Dpr.UI.HpBar` 52, `UIWindowStateMachine` 54, `TMP_FontAsset` 49 (embedded font objects). Script assemblies: 240 × `Assembly-CSharp.dll`, 14 × `UnityEngine.UI.dll`, 1 × `Unity.TextMeshPro.dll`. [D]
Materials (119, shader mapping resolved through shader-bundle path IDs): 40 × `TextMeshPro/Mobile/Distance Field`, 9 × `TextMeshPro/Distance Field`, 23 × `UI/Custom`, 2 × `UI/UI-Multiply`, 1 × `UI/UI-SoundWave`,
19 × post-processing (`Custom/Bloom*`, `Fxaa`, `Gaussian7x7`, `DepthOfField`, focus shaders, `Dpr/PostEffect/*`; used by model views, 3.5), and 22 with shaders outside `Dpr/shaders` (probably Unity standard UI shaders, [A]). [D]

### 2.3 Texture formats (sample across all groups; counts are textures) [D]
| Group | Formats | Typical sizes |
|---|---|---|
| `textures` (37 samples) | DXT5 25, ASTC 6×6 12 | 1264×240, 1280×400, 1024², 2048² |
| `shareduiassets` | ASTC 4×4 9, ASTC 6×6 11 | 1024×512, 1024×256, 512², 2048² |
| `gms` | ASTC 6×6 11, ASTC 4×4 1, Alpha8 2, RGBA32 1 | 1024×2048, 2048², 1280×720 |
| `contestphoto` | ASTC 6×6 | 1280×720 |
| `textures_mass` | RGBA32 | 88×88, 256² |
Implication: DXT5 must be decompressed on load or re-encoded at build time on iOS/iPadOS (memory: RGBA32 is 4× the size of BC3); this has not been measured. [A] `Sprite.texture` is `null` for atlas sprites; access them only through the SpriteAtlas object (`docs/m0-bundle-kompatibilitaet.md`).

### 2.4 Fonts and text
Five TextMeshPro font bundles (SDF, static atlases plus dynamic fallback with embedded TTF), one font family per language group: `efigs_font`, `jpn_font`, `kor_font`, `sch_font`, `tch_font`. Counts and license note are in `docs/lokalisierung.md`, section 7.
Message files: 11 bundles, 119 files per language, `MsbtData` format (see `docs/lokalisierung.md`). In game code, `UIText` binds a file and label to a text field.

### 2.5 Animations [D]
UI bundles contain 499 `AnimationClip` and 303 `Animator` (118 `AnimatorController`), 54 `UIWindowStateMachine` behaviors, and 75 `DOTweenAnimation` components (DOTween package required). Windows open/close through Animator states (`UIWindowStateMachine`, parameters `animParamConnectId`, `animParamStateId`);
`UIDatabase.UIWindow.WindowAnimId` (20, 30, … 700) is the connection ID for each window pair. [D][S]

## 3. How the original builds the UI

### 3.1 Canvas and scaling [D]
- `CanvasScaler` in prefab bundles (84): `ScaleWithScreenSize`, reference 1280×720, “Width or Height” match mode, Match 0.0 on 77 (width is primary); 1 with Match 1.0; 3 `ConstantPixelSize` with reference 1280×720 and 3 with reference 800×600 (reference has no effect there). The `title` scene (1 scaler) and `field` scene (3) use `ConstantPixelSize` at 800×600.
- `Canvas`: 357 in prefab bundles (363 across all `UIs` bundles); render mode Overlay (0) for 77, Camera (1) for 5, value 2 (WorldSpace) for 275 (mostly nested sub-canvases with no independent effect, [A]). `overrideSorting` on 69.
- Sorting order (constants in `UIManager`): Poketch 200, window 400 (+100 for each additional window), context menu 9900, transition 16384, error dialog 16484. [S]
- The original renders at 16:9 (Switch 1280×720/1920×1080). The rebuild viewport (`DisplayController`, 16:9 with bars at 4:3, see `docs/eingabe.md`) remains the basis; use a 1280×720 reference canvas matched by width. [A]
- `UIWindow.EnableMainCameraByUiMode` and `UIDatabase.UIWindow.UiCameraMode` (−1 for 5 windows, 0 for 27, 1 for 42) likely control whether the field camera is disabled when a window opens. [S][A]

### 3.2 Management: `UIManager`, `UIWindow` [S][D]
- `UIManager.CreateUIWindow<T>(UIWindowID)` instantiates the prefab from an object pool (`ObjectPool<UIWindowID, UIInstance>`), along with `GetCurrentUIWindow<T>`, `GetExistWindow<T>`, `SetTransitionWindowIds`, and `PlayTransition(TransitionID, FadeType)` (2 transition prefabs, 0.1 s fade).
- Loading: `LoadResidents` / `LoadWindows` read `UIDatabase` (`UIWindow` has 74 entries: 54 resident, 20 load-on-demand, 6 with `Firstload`), then `OpLoadSpriteAtlases` (7 atlases: `SharedUI`, `Common`, `Common_Lang`, `TextureMass`, `SharedUI_Lang`, `Battle_Lang`, `Zukan`; 3 are language-dependent). Atlases are bound through the `SpriteAtlasManager` callback `OnAtlasRequested`. `Reload(langId)` swaps language atlases.
- `UIWindow` is the base for all windows: `OnCreate`, `OnOpen(prevWindowId)`, `OnTransition…`, `PlayOpenWindowAnimation`, Animator states “In/Out”, helpers `OpenMessageWindow`, `CreateContextMenuYesNo`, and queries `IsPushButton/IsRepeatButton/IsOnButton/IsAccelButton`. 74 window IDs: `XMENU 0, ZUKAN 1, POKEMON 2, BAG 3, CARD 4, REPORT 5, MAP 6, GIFT 7, SETTING 8, SEAL 9, POKEMON_STATUS 10, CONTEXTMENU 11, LEVEL_UP 12, KEYGUIDE 13, SELL_ITEM 14, POKEMON_BATTLE 15, BOX 16 …, BATTLE_MATCHING_* 66–69, TVRANKING 71, YUNION 72, UNION_RECODE_MATCHING 73`.
- Database: `UIDatabase` has 32 sheets, including `PokemonIcon` 1,958 (icon bundle and asset per Pokémon/form), `Keyguide` 226, `ContextMenu` 112 (file+label), `ZukanDisplay` 1,958, `ZukanCompareHeight` 1,954, `Wallpaper` 32, `Box` 40, `SealTemplate` 34, `ShopMessage` 26 (9 labels each), `RankingDisplay` 10, `HideWazaName` 101. `MsgWindowData` (Dpr/masterdatas): 2,380 speaker-name rows, 25 window frames, 4 backgrounds, 12 signs, 7 sound tags. [D]
- Bundle `ui/prefab/teammix` is referenced in `UIWindow` (ID `BATTLE_MATCHING_TEAM_MIX`) but missing from the catalog (online feature). [D]

### 3.3 Input [S][D]
- `UIInputController` reads **Switch button masks** (bit values matching `nn::hid::NpadButton`, [A]): `ButtonA/B/X/Y`, `StickLLeft/Right/Up/Down`, `ButtonPlusMinus` (static fields in `UIManager`); `UIWindow.MoveLeftButton` 69632 (0x11000 = left stick + D-pad left), `MoveRight` 278528 (0x44000), `MoveUp` 139264 (0x22000), `MoveDown` 557056 (0x88000).
  Each button mask is queried with `IsPush`, `IsRelease`, `IsRepeat`, `IsOn`, `IsAccel` (accelerated repeat); `SetAutoButton` simulates buttons.
  Implication: `Xnu.Input` needs a small **adapter** to translate `GameInput` into these masks plus push/repeat/acceleration timing logic (timings still need to be read). [A]
- Navigation: `UINavigator` (neighbors `left/right/top/bottom` and stop flags, 184 instances in prefabs, so wired in the editor) plus `Cursor` (Animator states In/Out/Decide/Wait). Prefabs provide all the data; only the logic is missing.
- Touch: `UITouchInputController` (up to 10 touches, 1 s long press, Began/Moved/Stationary/Ended states). iPad touch can map to this. The original uses touch on Switch alongside buttons (Pokédex, box, map). [S][A]

### 3.4 Text, fonts, and message window [S][D]
- `UIText : TextMeshProUGUI` (1,648 instances): fields `_useMessage`, `_messageFile`, `_messageId`, `_useTag`, `_sizeId` (`UIFontSizeID` SSS…XL), `_fontMaterialDataIndex`; text is loaded from the message system at startup and when the language changes. Text sizes/materials are in `TextFontData`/`FontMaterialData` (`resources.assets`, not yet read).
- Message window: `MsgWindowManager` (singleton) → `MsgWindow` (state machine: open, type, wait for input, finish, close) → `WindowMessage` (typewriter, events) → `MsgTextContainer`/`WindowMsgText` (TMP). Variants: normal, **sign** (`OpenBoardMsg`, 12 signs, 5 textures), **item received** (`OpenItemGetMsg`), **battle** (`OpenBtlMsg`, one line). Extras: speaker name (up to 10 characters), continue icon (`UIKeywaitIcon`), loading icon, window frame (25), Yes/No menu (`OpenYesNoMenu`, `OpenCustomMenu`).
  `MsgWindow`, `WindowMessage`, etc. are GameObjects in `resources.assets` (without a TypeTree). Text speed and timing values: `docs/lokalisierung.md`, section 9.

### 3.5 Model views and special rendering [S]
`UIModelViewController`, `PokemonModelView`, `CharacterModelView`, `MultiModelView`, `ModelViewBgCamera`, and `ModelViewReflectionCamera` display **3D models in the UI** (Pokédex, party, map, Pokémon status, Trainer Card) using dedicated cameras and render textures (`modelBgRoot`, reflection). This depends on Pokémon/character models and their shaders (separate workstream). `UIManager` also has a blurred background (`_blurBg`, `UI/Blur` with GrabPass), grayscale (`_id_GrayscaleAmount`, `UI/UI-Gray`), and duplicate materials (`DuplicateImageMaterialParam`).

### 3.6 Custom components outside the window hierarchy
`HpBar`/`BUIHpSlider` (slider with color states: Alert below 50%, Danger below 25%, `HpDead` at 0; duration and easing from DOTween), `PokemonIcon`, `TypePanel`, `PokemonSick` (status marker), `RaderChart` (stat polygon), `Capsule2D/3D*` (sticker capsules), `TownmapSymbol` (75), `Poketch*` (27 classes, 14 mini-apps).

## 4. Screens (mapping and scope)
Scope = GameObjects/images/text fields in the prefab hierarchy ([D], `scripts/ui_inventory.py windows`) and method count for related `Dpr.UI` classes ([S]; approximate count of method signatures per family).

| Screen | `UIWindowID` / Prefab | GameObjects | Images | Text fields | Classes / methods | Notes |
|---|---|---:|---:|---:|---|---|
| **Title** | Scene `Dpr/scenes/title` (not a window) | 210 | 22 | 140 | `Title`, `TitlePlayer`, `MoviePlayer`, `StaffrollRow` (20) | Video + credits (140 `UIText`); fixed 800×600 canvas; video: `ap-cutscenes-video`; no input menus in bundle |
| **Main menu** | `XMENU` / `xmenu` | 131 | 83 | 14 | `XMenuTop` | 8 entries (`XMenuTopItem`); player graphics from `CharacterBag` (28 rows) |
| **Bag** | `BAG` / `bag`; `BAG_UG` / `bagug` | 409; 59 | 208; 26 | 87; 9 | 11 / 187 | pocket categories (`BagCategoryButton` 16), item list, description, quantity selection, TMs (`BagWazaSelectPanel`) |
| **Party / Pokémon** | `POKEMON`, `POKEMON_SELECT`, `ROTOM_SELECT` / `pokemon`, `pokemonselect`, `rotomselect` | 259 each | 128 each | 56 each | 41 / 497 (with status/moves) | 30 `PokemonPartyItem`; model view; context menu |
| **Pokémon status** | `POKEMON_STATUS`, `WAZA_MANAGE` / `pokestatus`, `wazamanage` | 383; 247 | 217; 113 | 69; 52 | included above | tabs (`PokemonStatusTab` 9), radar chart, move list, contest moves, ribbons |
| **Boxes** | `BOX` / `box` | **2,220** | 1,705 | 81 | 22 / 437 | largest prefab; tray (30 `BoxTrayItem`), search, wallpapers (32), multi-select, infinite scrolling |
| **Pokédex** | `ZUKAN`, `ZUKAN_REGISTER`, `_HABITAT`, `_COMPARE`, `_MOVING` / `zukan`, `zukanregister`, `zukanhabitat`, `zukancompare`, `zukanmoving` | 103; 75; 115; 89; 153 | 52; 38; 70; 47; 126 | 15; 10; 1; 9; 2 | 24 / 327 | models (1,958 display parameters), habitat map, size comparison; `zukanmoving` (audio mini-game, Wwise, visuals only without sound) |
| **Battle UI** | Prefab `battleviewuisystem` (no `UIWindowID`) | 638 | 390 | 93 | 24 / 276 (`Dpr.Battle.View.UI`) | command menu `BUIActionList` (battle/bag/Pokémon/run + XY frame), move list `BUIWazaList` (4 buttons, type sprites, PP colors), target selection `BUITargetSelect`, status window `BUIStatusWindow` (name, gender, level, `HpBar`/`BUIHpSlider`, EXP slider, status, ball row), situation display, result, message box via `MsgWindow.OpenBtlMsg` (one line, `controlID` 1) |
| **Shop** | `SHOP_BUY`, `SHOP_EXCHANGE`, `SELL_ITEM` / `shopfriendly` (71), `shopflower` (80), `sellitem` (100); boutique `shopboutique*` (35) | 35–100 | 13–53 | 5–24 | 19 / 286 | buy/sell/exchange, quantity selection, description; `ShopMessage` 26 rows; UG shops (`shopug`, etc.) optional |
| **Dialog / textbox** | `MsgWindow` (resources.assets), `DIALOG`, `CONTEXTMENU(_SCROLL)`, `KEYGUIDE` | 8 / 7 / 14 / 7 | 2 / 2 / 4 / 2 | 1–2 | 14 / 328 + `Dpr.MsgWindow` 23 / 336 + `Dpr.Message` 64 / 666 | see 3.4 and `docs/lokalisierung.md`; Yes/No menu from `ss_box` labels |
| **Settings** | `SETTING` / `setting` | 472 | 93 | 113 | 7 / 105 (with XMenu, Report) | 14 rows (`SettingMenuItem`); `ConfigID` has 14 entries (text speed, battle animation, battle rules, frame style, volume, …) |
| **Map** | `MAP`, `MAP_WALL` / `map`, `mapwall` | 85; 91 | 50; 52 | 6; 7 | 10 / 73 | `TownMapTable` 218, `PlaceNameTable` 774, `TownMapGuideTable` 135 |
| **Trainer Card / report** | `CARD`, `REPORT`, `CERTIFICATE`, `BADGE_GET` | 61 / 35 / 8 / 3 | 10 / 13 / 2 / 1 | 40 / 12 / 3 / 0 | 10 / 152 | model, badges; report = save (`BackUpReport`) |
| **Language/player/start** | `SELECT_LANGUAGE`, `SELECT_PLAYER`, `BACKUP_START`, `NOW_LOADING`, error dialog | 49 / 42 / 51 / 6 / 5 | 34 / 29 / 23 / 3 / 1 | 0 / 0 / 12 / 0 / 1 | 1–2 window classes each | first startup, loading display |
| Pokétch (watch app) | `POKETCH` / `poketch` | 974 | 641 | 2 | 27 / 363 | 14 mini-apps; later |
| Stickers | `SEAL`, `SEAL_TEMPLATE` / `seal` (637), `sealtemplate` | 637; 258 | 354; 137 | 12; 9 | 20 / 367 | 3D stickers; later |
| Contest | `CONTEST_*` / `cont*` | 27–276 | | | 22 / 584 | later |
| Berries/Poffins | `KINOMI`, `POFIN*` | 46–106 | | | 9 / 138 | later |
| Gifts, Union, battle matching, online | `GIFT`, `UNION*`, `BATTLE_MATCHING_*`, `TVRANKING`, `YUNION` | | | | ≈ 50 / ≈ 500 | online/network; out of scope |

Similar windows share a hierarchy (e.g. `pokemon`, `pokemonselect`, `rotomselect` each have 259 GameObjects): same template, only state and scripts differ. This reduces effort. [D]
The “classes/methods” counts cover only the named family; shared helper classes are in the framework (3.2, 3.3: 14 classes/328 methods). [S]

## 5. Dependencies on other workstreams
- **Text** (`Xnu.Text`): reader is complete; grammar is missing (localization section 6).
- **Input** (`Xnu.Input`): adapter for button masks and repeat/acceleration timing (section 3.3).
- **Shaders**: UI needs seven UI shaders and TextMeshPro SDF; 1:1 visual fidelity depends on ported shaders (`docs/shader-translator.md`). Until then, only U1–U3 are achievable.
- **Master data/save**: bag (ItemTable, save), party/boxes/Pokédex (`PokePara`, `Save`), shop (`ShopTable`), map (zones); battle UI connects to battle view (outside this section's scope).
- **Pokémon models** in UI views (3.5) and **video** (title).
- **Audio**: UI sounds (`SoundTag`, `MsgWindowSoundPlayer`, Wwise events in `PokemonVoice`) stay disabled (requirement: no sound, `AudioSafety`).

## 6. Strategy and spike
**S1 spike result: see `docs/ui-spezifikation-2.md` (option A confirmed; binding works only in `Assembly-CSharp`).**
**Option A (recommended): load original prefabs, recreate scripts.** Bundles load in Unity 6 (`docs/m0-bundle-kompatibilitaet.md`: all 14,052 bundles `ok`); uGUI components and TMP fonts are recognized as objects. Prefabs refer to `Dpr.UI.*` in `Assembly-CSharp.dll`.
Hypothesis [A]: if the project defines classes with the **same namespace, class name, and field names** in the standard assembly (`Assembly-CSharp`), Unity automatically binds serialized fields when loading prefabs (as with the missing `XLSXContent` classes for master data; see `docs/masterdata.md`).
Consequences: layouts, wiring (`UINavigator`, animators, sprite/font references) come directly from the data; only logic needs to be written. Risks: (a) Unity 6 vs. 2019.4 script matching for `UnityEngine.UI` (`UnityEngine.UI.dll` vs. package `com.unity.ugui` 2.0.0, with TMP), (b) the Assembly-CSharp requirement conflicts with the `Xnu.*` assembly split (UI scripts would live outside it), (c) `TMP_FontAsset` references to embedded TTFs, (d) original shader assignment (materials must point to our ported shaders).
**S1 spike** (when an editor is free, about 2–3 days): load `ui/uiresidentwindow`, instantiate `bag.prefab`, add skeleton `UIText`/`UINavigator`/`Cursor` classes, count errors (“missing script”, field matching), then decide. Measure: 8.2 MB bundle load time, atlas memory (DXT5 on iOS), language-atlas behavior.
**Option B (fallback): rebuild in C#.** Generate custom prefabs/layouts from RectTransform data (an exporter reads anchors, sizes, sprites) and use only sprites/fonts from the dump. More work (layouts and animations must be ported), but independent of script matching and compatible with `Xnu.*`. An intermediate option is a **prefab converter** in the build: read original prefab (UnityPy) → JSON → Unity Editor script builds prefab with custom components.
Windows that show models (3.5) need the model pipeline with either option.

## 7. Effort per screen and implementation order
Effort in **developer-days** (DD) for a developer familiar with the dump and project, including reading original logic (pseudocode) and tests, **excluding** hardware tests; estimate [A] based on scope (section 4), not measurement. Lower bound assumes option A works (S1 positive); upper bound assumes option B.

| No. | Component / screen | DD | Prerequisite | First acceptance level |
|---:|---|---:|---|---|
| 0 | S1 spike (prefab binding) and font setup (TMP from dump, UI shader placeholders) | 3–5 | free editor | U1 |
| 1 | UI framework: `UIManager` (minimal), `UIWindow`, `UIText`, atlas/sprite loading, 1280×720 canvas setup, `UINavigator`/`Cursor`, input adapter, transitions | 25–40 | 0, `Xnu.Input`, `Xnu.Text` | U1–U3 |
| 2 | Message window: `MsgWindow`, `WindowMessage`, sign, item received, Yes/No/context menu, key guide, dialog | 12–18 | 1; German grammar (3–6 DD extra, localization section 6) | U3 |
| 3 | Title (video + credits) | 3–5 | video path (`ap-cutscenes-video`), 1 | U1–U2 |
| 4 | Language/player/name (`SelectLanguage`, `SelectPlayer`, `SoftwareKeyboard`, loading) | 5–8 | 1, 2 | U3 |
| 5 | Main menu + settings | 8–12 | 1, 2 | U3 |
| 6 | Party and Pokémon status (including move management) | 20–30 | 1, 2, `PokePara`, model view (3.5) | U3 |
| 7 | Bag (+ field item use) | 8–12 | 1, 2, item data | U3 |
| 8 | Shop (buy/sell) | 8–12 | 7, `ShopTable` | U3 |
| 9 | Battle UI (commands, moves, targets, status, HP bars, messages) | 15–25 | 1, 2, battle system + battle view | U3, later U4 |
| 10 | Boxes | 15–25 | 6, save boxes | U3 |
| 11 | Pokédex (list, details, habitat, comparison) | 20–30 | 6, models, map | U3 |
| 12 | Map, Trainer Card, report/save | 9–15 | 1, 2, save | U3 |
| | **Core scope total (1–12)** | **150–230** | | |
| 13 | Pokétch, stickers, contests, berries/Poffins | 60–100 | 1, 2 | as needed |
| 14 | Gifts, Union, online, battle matching | – | networking | out of scope |
Notes: (a) Totals exclude pixel-match goal U4, which depends on the shader port. (b) Main uncertainties are S1 spike (option A/B), grammar, and model views.
**Recommended order:** 0 → 1 → 2 (message window makes dialogue in field scenes usable) → 3/4 (startup) → 5 → 6/7 (party, bag) → 9 (battle UI, alongside battle work) → 8 → 12 → 10 → 11 → 13.
**Parallel work** is possible: input adapter and message window (2) independent of party/bag; coordinate battle UI with the battle agent; text/grammar can proceed alongside the framework.

## 8. Open questions and risks
1. **Option A or B** (S1 spike): determines effort. Both require UI shaders and TMP to work in Unity 6 with original materials (shader port).
2. **Font license:** the fonts (Fontworks/Nintendo proprietary font) are third-party content, used only from the user's own dump in a personal build; an open replacement would change text widths and wrapping (breaking 1:1 fidelity). User decision required.
3. **Texture formats:** DXT5 share on iOS/iPadOS (Unity decompresses on load or build-time re-encoding), memory use of atlases and 1,845 icon bundles (38 MiB) on iPad unmeasured.
4. **`resources.assets` without TypeTree:** `UIManager`, `MsgWindow*`, `MessageManager`, `TextFontData`, `FontMaterialData`, style table. Either read via field layouts from `dump.cs` (precedent: `ui_resources_scan.py`; `MsgWindowConfig` worked) or define anew in C#.
5. **Input timing** (repeat, acceleration, long press) and mapping button masks to `GameInput`: still needs investigation (`UIInputController` pseudocode).
6. **Window camera mode** (`UiCameraMode`) and **window animation** (`WindowAnimId`): meaning unclear, not verified.
7. **iPad touch:** original uses touch alongside buttons (boxes, Pokédex, map); define iPad touch behavior per screen; possible overlay conflict with `Xnu.Input` touch overlay (pointer input in UI).
8. **Languages/atlases:** language atlases (`_lang.*`) and per-language text embedded in images: which languages ship in the first version (suggestion: German/English)? Original `GetLanguageVariant` selection rule has not been read.
9. **3D models in UI:** Pokédex, party, map, Trainer Card depend on model pipeline and shaders.
10. **DOTween** (75 animations, package required; clarify license/source, dump contains references only) and Wwise references in UI (ignore).
11. **Missing bundle:** `ui/prefab/teammix` missing from catalog (online); handle failure when loading all 74 windows.
12. **Unity test run** (`TextTests`, 35 tests) remains pending; additional editor access needed.

## 9. Built in this step
- `unity/Assets/Scripts/Text` (`Xnu.Text`, pure C#): JSON reader for `MsbtData`, file model, language tables, `MessageBank`, `MessageComposer` (sections with events), `TagWordBuffer`/`ITagFormatter` (scaffold), `RichText`, `MessageTimingConfig`, and `MessageTypewriter`.
- `unity/Assets/Tests/EditMode/TextTests.cs`: 35 tests (`dotnet test` in throwaway project `work/dotnet-text`: passing; added `Xnu.Text` reference to `Xnu.Tests.EditMode.asmdef`). Cross-check against real exports [V]: 119 + 119 + 90 files, 0 invalid references.
- Read-only scripts: `scripts/ui_inventory.py` (`catalog`, `bundles`, `deep`, `windows`, `fonts`), `scripts/msg_stats.py`, `scripts/ui_dump_view.py`, `scripts/ui_find_script.py`, `scripts/ui_resources_scan.py`. Outputs under `work/ui` (gitignored): `catalog_stats.json`, `bundle_types.json`, `deep.json`, `windows.json`, `fonts.json`, `msg_stats.json`, `resources_scan.json`, `dump_uimanager.txt`.

## 10. Evidence (reproduction)
```
python3 scripts/ui_inventory.py catalog | bundles | deep | windows | fonts     # catalog, object types, script classes/CanvasScaler, prefab scope, fonts
python3 scripts/msg_stats.py german english                                      # message statistics
python3 scripts/ui_resources_scan.py                                             # resources.assets, MsgWindowConfig
python3 scripts/ui_dump_view.py UIWindowID UIManager UIText --methods            # classes from dump.cs
cd work/dotnet-text && dotnet test                                               # 35 tests (throwaway project)
```
