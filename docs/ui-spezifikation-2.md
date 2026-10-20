# UI Specification 2: S1 Spike (Original UI Prefabs Without Scripts) and Message Window

> **Historical (as of 2026-10-20):** Unity approach discontinued. `scripts/ui_s1_probe.cs` has been removed from `main` (only on branch `unity`). `scripts/ui_s1_scan.py` remains.

As of 2026-10-19, todo `ap-ui`, slice 1. Numbers, class/field names, and original code only; no game content, text, or images in the repository.
Measurements: Unity 6000.3.26f1 (main editor `unity/`, Built-in RP, Metal), Apple M1 Pro, own dump under `work/` (gitignored).
Evidence levels follow `docs/ui-spezifikation-1.md`: **[D]** measured, **[S]** from `dump.cs`, **[A]** assumption, **[T]** verified by tests.

## 1. Summary
- **S1 succeeded:** Original UI prefabs load in Unity 6 without the game scripts. uGUI components (`Image`, `Slider`, layout groups, `CanvasScaler` …) bind automatically; only the 240 `Assembly-CSharp` classes are missing (Missing Script). Layout (RectTransform), wiring, and sprites are all present. [D]
- **Custom classes with matching names bind** the serialized fields, but **only when they are in `Assembly-CSharp`**. The same class in a separate assembly (asmdef) does not bind (0 of 1,103). [D]
- **Decision:** use option A (load original prefabs, provide custom `Dpr.UI.*` classes in a folder without an asmdef) for windows that have prefabs; option B (export with UnityPy and rebuild) remains the fallback. The original has no message-window prefab in the bundles (it is in `resources.assets` without a TypeTree), so that window will always be built **in custom C#** (section 4).
- Original shaders are never loaded: all 263 `Image` and 1,052 TMP materials use `Hidden/InternalErrorShader` during the spike; none were rendered. [D]
- Delivered: `Xnu.UI` with `TextboxView`/`TextboxFlow`, scene `UiTest.unity`, and 34 new EditMode tests (481 passing total, including 447 existing tests).

## 2. S1 spike: measurements [D]
Setup: `BundleProvider` with a filter (no shader bundle, exactly one variant per language family), `ui/uiresidentwindow` (8.2 MB, 53 prefabs) and 19 dependencies, inspected with an eval script (`scripts/ui_s1_probe.cs`); offline script-binding counts from `scripts/ui_s1_scan.py` (UnityPy).

### 2.1 Script binding
| Measurement | Value |
|---|---|
| Objects in bundle / MonoBehaviours / script classes | 35,988 / 8,619 / 255 |
| Script assemblies | `UnityEngine.UI.dll` 5,906 (14 classes), `Assembly-CSharp.dll` 2,710 (240 classes), `Unity.TextMeshPro.dll` 3 (1 class) |
| Classes in `Assembly-CSharp` | 230 in `Dpr.UI`; others: `DG.Tweening.DOTweenAnimation` (49 instances, 55 fields), `SmartPoint.Rendering.{Fxaa,Bloom,PostProcessFilter}`, classes without a namespace (`KeyguideItem`, `XMenuTopItem`, `RaycastTarget`, `EnvironmentSettings`, `EnvironmentController`, `CameraSortTragroups`) |
| Components across all 53 prefabs (assets loaded) | 25,293, of which **2,650 Missing Script** (all from `Assembly-CSharp`; difference from 2,710 is mainly `UIWindowStateMachine`, which is in Animator controllers [A]) |
| `UnityEngine.UI.*` and TMP | bind automatically; `CanvasScaler` in instantiated prefab = scale with screen size, 1280×720, Match 0 (width) |
| Prefab loading | `bag.prefab` 409 GameObjects in 98 ms (first prefab), `dialog` 8 GO in 2 ms, `xmenu` 131 GO in 15 ms; instantiation 2–11 ms; opening bundle plus 20 bundles 31 ms; managed heap +17.8 MB; **0 console errors** (no Missing Script spam) |

### 2.2 Reuse through custom classes (binding test) [D]
Four stub classes with the same namespace, class, and `[SerializeField]` field names (`Dpr.UI.UINavigator`, `Cursor`, `HpBar`, `UIText : TextMeshProUGUI`) in a folder **without** an asmdef (= `Assembly-CSharp`):

| Class | Instances | Result |
|---|---:|---|
| `UINavigator` | 184 | bound; `_left` resolved on 182, `_isStop*` flags correct (28 with `_isStopRight`) |
| `Cursor` | 44 | bound; image and sprite arrays present, all 90 of 90 sprite references resolved (external bundles) |
| `HpBar` | 30 | bound; `Slider` 30/30, 90 sprites |
| `UIText` (TMP subclass, 78 original fields) | 1,103 | bound; font resolved on 1,052, `_useMessage` on 1,032, `_sizeId ≠ 0` on 1,083 |
Missing Script count afterward: 2,650 → 2,392 (Cursor, Navigator, HpBar) → 1,289 (with `UIText`). The same classes in asmdef `Xnu.S1Spike`: **0 bound**, 2,650 missing. Binding therefore uses (assembly `Assembly-CSharp`, namespace, class name); Unity matches fields by name using the bundle TypeTree, discards unknown fields, and leaves missing fields at their default values. A misspelled field name is **silently** lost (a validation tool is needed, section 5).

### 2.3 Sprites, fonts, and materials
- There are 5,171 `Image` components (Python counts 5,181; the 10 missing ones are on unloadable objects [A]); sprites resolved on **4,368** (Python: 4,378 with sprites). Without language variants, only 4,226 resolve: language atlases (`common_lang`, `sharedui_lang`, `battle_lang`) must be loaded before the prefab.
- Language variants (`.en .fr .ge .it .jp .ko .si .sp .tr`) contain **the same filenames**: loading two variants makes `AssetBundle.LoadFromFile` return `null` (“same files already loaded”). The catalog lists `.jp`/`.si` at random as dependencies. Prefab references also resolve against another variant (`.ge` instead of `.jp`: still 4,368). **To switch language, load another variant; prefabs stay the same.** `DependencyFilter` must therefore allow exactly one variant per language family.
- Materials: 263 `Image` materials (those with their own material only) and 1,052 TMP font materials use `Hidden/InternalErrorShader`; reading their names and shader names is safe while the shader bundle is absent. Remapping follows `docs/material-remap.md` (copy material, set `shader` to ours; properties retain their names); for TMP, use TextMeshPro's standard shader pair.
- Texture formats (ASTC/DXT5, memory use on iPadOS) have not yet been measured.

### 2.4 What is lost compared with the original
**Preserved** in the data: hierarchy, RectTransform (anchors, sizes), sprites including 9-slice borders, colors, `CanvasScaler`, layout groups, Animator references, and wiring between scripts (after binding). **Lost** without custom classes: all behavior (navigation, window control, `DOTweenAnimation` curves), script references for the 2,650 components; original materials/shaders (need replacements); Animator state behavior (`UIWindowStateMachine`).

## 3. Decision and rationale
| Criterion | A: Load prefabs + recreate `Dpr.UI.*` | B: Export (UnityPy) + rebuild |
|---|---|---|
| Layout, sprites, wiring | 1:1 from data, verified | must be exported and rebuilt (anchors, layout groups, masks, animators) |
| Effort per screen | logic only (declare fields, write behavior) | exporter, builder, and animations in addition |
| Fidelity (U1/U2) | structure and layout match from day one | likely differences, needs per-screen checks |
| Technical cost | classes must be in `Assembly-CSharp`; field names must match; IL2CPP stripping [A] | no binding needed; fits `Xnu.*` |
| Legal considerations | repository contains only custom classes with matching names; data stays local | same as A (export remains under `work/`) |
**Choice: A**, because measurements show the critical parts (binding, sprites, fonts, language variants) work, while B would require the same data path plus additional work. B will not be built; it remains a fallback for individual prefabs whose field layout cannot be bound. The estimate in `docs/ui-spezifikation-1.md` (150–230 developer-days) stands; use the **lower bound** as long as the items in section 5 are manageable.
Binding and `Xnu.*` assemblies: the folder for `Dpr.UI.*` classes (e.g. `Assets/Scripts/DprUi/`, without an asmdef) can use all `autoReferenced` assemblies (`Xnu.Core`, `Xnu.Text`, `Xnu.UI` …); the reverse dependency is not possible. Game logic therefore belongs in `Xnu.*`, while `Dpr.UI.*` classes remain thin shells containing serialized fields.

## 4. Message window (`Xnu.UI`)
Files (`unity/Assets/Scripts/UI`, assembly `Xnu.UI`, editor component `Xnu.UI.Editor`):
| File | Contents |
|---|---|
| `Logic/TextboxFlow.cs` | Flow without Unity types: open → typewriter per section → events → wait for input → close; `Held` state for questions |
| `Logic/ChoiceMenuModel.cs` | Yes/No choice: wrapping cursor, confirm selects, cancel selects the cancel entry |
| `Logic/UiInput.cs`, `PlainMessage.cs` | `UiInputState` (confirm/cancel/hold/up-down), `ManualUiInput`, `MergedUiInput`; plain string → `ComposedMessage` |
| `Runtime/TextboxView.cs` | Builds its own canvas, frame, masked TMP text, continue icon, and choice field; `Show`, `Ask`, `Tick` |
| `Runtime/UiCanvasFactory.cs` | Canvas matches original: scale with screen size, 1280×720 reference, match width (Match 0); with camera = Screen Space Camera (follows the `DisplayController` 16:9 viewport) |
| `Runtime/TextboxSkin.cs` | Frame/continue icon: from local dump (`sharedui`, runtime only, sprites `cmn_wd_message_01_NN_l`, `cmn_ico_messagenext_01`), otherwise custom pixel placeholders |
| `Runtime/GameInputUiSource.cs` | `Xnu.Input` → `UiInputState`: A confirms, B cancels, D-pad/stick navigate |
| `Runtime/UiTestDriver.cs`, `Editor/UiSceneBuilder.cs` | Scene `unity/Assets/Scenes/UiTest.unity` (menu `Xnu/UI/Create UiTest Scene`): camera, `DisplayController` (16:9), `GameInput`, `TextboxView`, driver with invented text |

**Behavior** (values from `MsgWindowConfig`, `docs/lokalisierung.md` section 9; other details [A]):
- Typewriter: 0.06 / 0.03 / 0.01 s per character (Slow/Normal/Fast); rich text is preserved (markup does not count as a character); holding a button = 5× speed; a single press does not skip anything.
- Events: `NewLine` continues; `Wait` delays for a number of seconds; `ScrollLine` waits for input, then scrolls the line up over 0.15 s (text remains, mask clips it); `ScrollPage` waits for input and clears the page; `CallBack` calls back with an ID; `End` waits for input, then closes.
- Input is ignored for 4 frames after the text ends (`waitAfterFinishMsgFrame`); both confirm **and** cancel advance.
- Continue icon: 8 px bob, 210°/s (`iconMoveDist`, `addAngleSec`).
- Window: 144 px high (sprite height), 40 px left/right margins, 24 px above bottom edge, 100 px text margin, font size 36 [A]; open/close duration 0.1 s each [A]. Question flow: show message, keep window open, show choice to the right above it, close window after selection; B selects “No” (last entry) [A].
- Frame: 24 styles `cmn_wd_message_01_01…24_l` (124×144, 9-slice borders e.g. 60/30/60/30, ppu 100); `Sprite.texture` is `null`, but `SpriteAtlas.GetSprite` returns sprites that render normally as `Image` (Sliced). Release bundle handle with `Unload(false)` after retrieval. Render with Unity's standard UI material, no original shader.
- Font: TextMeshPro with Unity's bundled LiberationSans (placeholder). Imported “TMP Essential Resources” for this (`Assets/TextMesh Pro`, shaders, font with OFL text, settings; removed ShaderGraph files and emoji sprites, about 3 MB). The original font (`efigs_font`, material remapping to the TMP shader pair) is **not** connected.

**Tests** [T]: `Assets/Tests/EditMode/UiTextboxTests.cs`, 34 tests with invented text: typewriter timings for all three speeds, hold/single press, rich text, input wait with grace period, cancel, line break, delay, callback, page/line scrolling, open/close progress, `Held`, choice menu (wraparound, cancel, invalid arguments), input sources, canvas values (1280×720, Match 0), placeholder skin, view (text, close, Ask, label via `MessageComposer`). Main editor run: **481/481 passing** (447 existing + 34 new).

**Game View observation** (captures `work/ui/shots/ui_a.png … ui_e.png`, not in repo; game window 1814×934, capture scaled to 1280×720 and therefore slightly compressed, side bars from `DisplayController`): The original frame renders correctly with its 9-slice borders (gray edge, light fill, decorative side strips). Text appears character by character; rich text (`<color>`, `<size>`) renders correctly; line scrolling reveals the second and third lines; the continue icon appears only while waiting for input (small triangle with diagonal line, probably part of original sprite; cause unverified [A]); “Yes/No” choice appears above the window on the right, cursor `>` follows input, “No” was selected with confirm, and the window closed. Runtime warning: `SpriteAtlasManager.atlasRequested wasn't listened to while SharedUI requested` (harmless, atlas is loaded; address when connecting `UIManager` atlas logic). Window position/width do not come from original data; image comparison (U2/U4) remains pending.

## 5. Gaps and next steps
1. **Field-binding validation:** tool to compare bundle field names per class (`ui_s1_scan.py` currently only counts them) against custom `[SerializeField]` fields; otherwise typos are invisible.
2. **IL2CPP stripping** [A]: classes bound only through bundles need `link.xml`/`[Preserve]`; macOS/iPad player test remains pending (spike ran only in Editor).
3. **DOTween** (49 `DOTweenAnimation` in main bundle): package or custom replacement with same namespace/field layout; license/source unresolved.
4. **Material remapping** for the 263 + 1,052 materials in the prefab loading path (copy + set `shader`) and original TMP fonts; language variants in `DependencyFilter` and `SpriteAtlasManager` integration.
5. **Textbox:** frame style from `MsgWindowData` (25 frames; currently fixed to style 1), speaker name, signs, item acquisition, one-line battle message, original dimensions (`resources.assets`), original font and line widths (`strWidth`), touch/pointer input, cursor repeat, grammar (`docs/lokalisierung.md` section 6), image comparison.
6. Texture memory (DXT5 on iOS/iPadOS) and device load times have not been measured.

## 6. Reproduction
```
python3 scripts/ui_s1_scan.py ui/uiresidentwindow --json work/ui/s1_scan.json        # offline script binding
unity command --project-path unity --result-only eval_file $PWD/scripts/ui_s1_probe.cs  # loading, Missing Script, sprites (main editor)
unity command --project-path unity --result-only run_tests editor Xnu.Tests.EditMode assembly
# Scene: menu Xnu/UI/Create UiTest Scene, Play; A/L/Enter confirms, B/K cancels
```
