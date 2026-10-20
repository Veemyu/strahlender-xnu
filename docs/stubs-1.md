# Stubs 1: Loading the Original Object Graph (Generated Assembly-CSharp Stub Classes)

> **Historical report (as of 2026-10-20):** The Unity path has been discontinued. These files were removed from `main` (they remain only on branch `unity`): `scripts/stub_gen.py`, `scripts/stub_dump.py`, `scripts/stub_verify.py`, `scripts/stub_probe.cs`, `scripts/stub_bridge/`, and `scripts/tests/test_stub_gen.py`. The commands below no longer run on `main`.

Status: 2026-10-19, todo `ap-stubgen`. Only numbers, methods, and original code; no game content, text, class names, or field names from the game are in the repository.
Measurements: Unity 6000.3.26f1 (Apple Silicon, graphics-free batch mode), Apple M1 Pro; the local dump and scans are under ignored `work/`.
Evidence levels: **[D]** measured, **[S]** from `dump.cs`, **[A]** assumption, **[T]** verified by tests.

## 1. Summary

- **User decision at the time:** Main approach = “stubs + original object graph + logic pipeline.” At build time, generate stub classes for `Assembly-CSharp` from the user's own dump (namespace, class name, base class, serialized fields), so original prefabs/bundles load with intact references. Implement the logic class by class in original wording and verify it with an oracle. Stubs are generated and **not stored in the repository** (ignored); only the generator and its tests are in the repository.
- **Generator output:** `scripts/stub_gen.py` (+ `stub_dump.py`) produces **887 C# files and 4 asmdef files** (1,310 types, 5,777 fields) from the TypeTree and dump in one second; Unity compiles them in about 2 seconds with **zero compiler errors** (interim result 2, section 4.1). [D]
- **Missing Scripts eliminated:** across **13,889 bundles** (all up to 80 MB, 1,112,276 components), missing scripts drop from **34,101 to 0**; `ui/uiresidentwindow` goes 2,650 → 0, and `Environments/fields/area001` (zone 422) goes 38 → 0. [D]
- **Serialized fields bind correctly:** one sample per class checked against the TypeTree: **574 classes**, 42,401 field leaves, **42,399 match (99.995%)**. The two differences are a TextMeshPro base-class field absent from the package version included with Unity 6. Zero console errors from the stubs. [D]
- **TypeTree-only generation:** 357 of 688 classes can be generated exactly (85.8% of instances); 642 (95.3% of instances) bind with compromises; only 12 classes (2,045 instances) require the dump (their base is a UI/TMP class). [D]
- **The Xnu.* ↔ stub bridge is reliable:** Assembly-CSharp may use auto-referenced asmdef assemblies, but not the reverse. Logic lives in `Xnu.*` and sees only interfaces; hand-written `partial` stub files (without an asmdef) implement them. Tested with the original UI bundle (127 components, registration in `Awake`, deregistration in `OnDestroy`). [D]
- **Limits:** scene bundles cannot be opened in batch mode (only their structure was scanned); shaders/materials remain unresolved; gameplay logic itself is missing (section 6).

## 2. Analysis: what the data actually references [D]

`scripts/stub_gen.py scan` reads all 14,057 files (14,052 bundles and 5 player files) with UnityPy in about 3 minutes (5 processes). For each MonoBehaviour it reads only the script PPtr, TypeTree schema, and counters (no instance values). Scripts are resolved through `m_AssemblyName`/`m_Namespace`/`m_ClassName` in MonoScript, including across bundle boundaries (CAB names). Output: `work/stubs/scan.json`.

### 2.1 All script classes and those actually referenced

- `globalgamemanagers.assets` contains **2,761 MonoScripts** (Assembly-CSharp 2,229; remainder: Nintendo SDK `nn` 104, uGUI 85 + 68 tests, Timeline 70, TextMeshPro 59 + 1 test, AssetAssistant 28, TestRunner 110, DOTweenPro 3, DOTween 2, Recorder 3, other 3).
- Instances in bundles/player files reference **727 classes and 54,064 instances**.

| Script assembly | Classes | Instances | On GameObjects |
|---|---:|---:|---:|
| `Assembly-CSharp` | 688 | 44,233 | 34,406 |
| `UnityEngine.UI` | 18 | 8,909 | 8,909 |
| `Unity.Timeline` | 9 | 781 | 0 |
| `Unity.TextMeshPro` | 6 | 127 | 39 |
| `Unity.Polybrush` | 1 | 7 | 7 |
| `AssetAssistant` | 2 | 2 | 0 |
| `DOTweenPro` / `DOTween` | 1 / 1 | 2 / 1 | 2 / 0 |
| unresolved (external reference) | 1 | 2 | 2 |

- Only **30.9%** of Assembly-CSharp classes (688 of 2,229) are referenced by data. The other 1,541 are pure logic and need no stubs to load bundles.
- Of the 688 classes, 170 are ScriptableObjects (9,827 instances: master-data tables, messages, event scripts), and 518 are components; no class is both.
- 647 of 688 classes occur in exactly one bundle group; 41 occur in 2–7.
- Concentration: one class accounts for 36.4% of instances; the top 10 account for 75.6%, top 50 for 95.5%, top 100 for 97.8%. 442 classes have one instance; 35 have at least 100.

### 2.2 By bundle group (top-level folder under AssetAssistant)

Classes are Assembly-CSharp classes with at least one instance in the group (a class is counted in every group where it occurs).

| Group | Files | Classes | Instances | Components | ScriptableObjects |
|---|---:|---:|---:|---:|---:|
| UIs | 1,995 | 332 | 3,866 | 3,778 | 88 |
| Dpr | 141 | 109 | 6,545 | 242 | 6,303 |
| Effects | 2,987 | 8 | 18,360 | 18,359 | 1 |
| Environments | 644 | 29 | 2,653 | 2,653 | 0 |
| Pokemon Database | 5,748 | 6 | 7,851 | 7,851 | 0 |
| Battle | 1,411 | 7 | 1,587 | 348 | 1,239 |
| Characters | 414 | 10 | 825 | 667 | 158 |
| Contest | 579 | 33 | 642 | 78 | 564 |
| Message | 12 | 1 | 1,280 | 0 | 1,280 |
| FureaiHiroba | 14 | 47 | 282 | 207 | 75 |
| Other 8 groups | 107 | 144 | 289 | 183 | 106 |
| Player (`resources.assets`, no TypeTree) | 5 | 41 | 53 | 40 | 13 |

Scene bundles occur only in `Dpr` (9 files). Total: 1,827,593 objects and 51,006 container entries (assets, including prefabs). Per-group counts are in `work/stubs/stats.json` (`container_assets`).

### 2.3 Serialized fields (Assembly-CSharp; dominant TypeTree schema per class, 654 classes with TypeTree)

| Top-level field category | Count |
|---|---:|
| References `PPtr<T>` | 1,657 |
| Primitives (int, float, bool, …) | 823 |
| Lists/arrays | 635 (elements: 345 nested classes, 238 `PPtr`, 27 Unity structures, 23 primitives, 2 strings) |
| Unity structures (`Vector3`, `Color`, `Rect`, …) | 127 |
| Nested `[Serializable]` classes | 97 |
| Strings | 50 |
| `UnityEvent` | 10 |

- 3,399 top-level fields total. `PPtr` targets (including array elements): 1,087 engine classes, **808 game classes**.
- Nested helper types: **308 distinct** `[Serializable]` types with 3,133 leaf fields. Dictionary wrappers appear in the TypeTree as ordinary nested classes (key and value lists), so they cannot be counted separately.
- The dump adds **143 enums** (represented as `int` in the TypeTree), 24 structs, and 8 generic types.
- No `managedReference` (SerializeReference) fields (0), and no interface-typed fields.

### 2.4 Coverage from TypeTree alone (without dump.cs) [D]

Per-class tiers (`stub_gen.py gen --no-dump` compared with a run using the dump):

- **A, exact:** all fields have unambiguous types from the field tree (primitives, strings, Unity structures, `PPtr` to engine classes, arrays, nested classes, events); base is `MonoBehaviour`/`ScriptableObject`. Enums appear as `int`.
- **B, binds with compromises:** also includes `PPtr` to game classes; without the dump, field type falls back to `UnityEngine.Object` (binding and values match, but type information is lost; 855 such fields, 253 target classes).
- **C, dump required:** base class is not derived from `MonoBehaviour` (uGUI/TMP components); without the base-class information, the stub inherits incorrectly.
- **No TypeTree:** classes found only in `resources.assets` (player data without TypeTree); fields come only from the dump.

| Tier | Classes | Share | Instances | Share |
|---|---:|---:|---:|---:|
| A exact | 357 | 51.9% | 37,932 | 85.8% |
| B with compromises | 285 | 41.4% | 4,213 | 9.5% |
| C requires dump | 12 | 1.7% | 2,045 | 4.6% |
| No TypeTree | 34 | 4.9% | 43 | 0.1% |
| Total | 688 | 100% | 44,233 | 100% |

**Answer:** From the field tree alone (A + B), 642 classes (93.3%) with 42,145 instances (95.3%) can be bound. The dump is needed for base classes, target namespaces, enum names/values, generic bases, and the 34 classes without TypeTree. All field names and their order come from the TypeTree, never from the dump.

## 3. Generator method

Files: `scripts/stub_gen.py` (scan, generation, statistics, conflict check), `scripts/stub_dump.py` (dump parser and type index), tests `scripts/tests/test_stub_gen.py` (35 tests using invented names and synthetic fragments, without UnityPy or game data).

1. **Scan** (`stub_gen.py scan`): script classes, instances, components (GameObject ≠ 0), TypeTree schemas (short MD5 hash), CAB names and dependencies per bundle, class list per bundle. Schemas can differ for one class (8 cases); generator uses the most common schema and adds fields missing from the others.
2. **Base chain** from the dump: base classes up to the first class outside stub assemblies (engine, uGUI, TMP, Timeline are considered present). Generic bases (`Foo<T>`), nested types, and outer classes are included.
3. **Assign fields along the chain:** match the flat TypeTree field list (base fields first), from the end, against names declared in each dump class in the chain. Matches go to their declaring class; remaining fields belong to the external base (80 fields, not redeclared). Fields without a dump counterpart (19) go on the leaf class when its base is `MonoBehaviour`.
4. **Types:** compare dump types (namespace, enum, list/array, generic) with TypeTree shapes (enum ↔ `int`, class ↔ structure, object ↔ `PPtr`); TypeTree wins on mismatch (2 cases). For ambiguous short names in the dump (game and engine classes with same name), `PPtr` resolution prefers “derived from `UnityEngine.Object`”; otherwise prefer namespace proximity, then engine over game. Without dump: `PPtr<$Engine>` → engine type, otherwise `UnityEngine.Object`; nested classes → helper types in `Xnu.Stubs.Auto`; enums → `int`.
5. **Output:** one file per class, `<namespace as folder>/<name>.cs` under `Assets/XnuStubs` (no asmdef = Assembly-CSharp), `public partial class`, `[SerializeField] private` or `public` according to dump, fully qualified `global::` types (no `using` conflicts), warning pragmas, no logic. Nested types stay in the outer class file; **types inside generic outer classes** become top-level types (`Outer_Inner`) to avoid compiler error CS7002. Folders with special meaning (`Editor`, `Resources`, `Plugins`, …) get an underscore in the path; otherwise Unity puts the class in the Editor assembly and binding fails (three components in one group initially went missing). Non-ASCII field names are preserved (valid C#; otherwise 28 leaves in a table sample were lost).
6. **External assemblies:** scripts whose MonoScript names another assembly (DOTween, DOTweenPro, AssetAssistant, Polybrush) go under `XnuStubs/_asm/<Assembly>/`, with an `<Assembly>.asmdef` **using the original name** (`autoReferenced: true`, references from type dependencies). Unity binds by assembly name; these classes then bind (9 components: 2 DOTweenPro, 7 Polybrush; in the Contest group, missing went from 2 to 0 with asmdef). Assembly-CSharp stubs may use these assemblies. External types: uGUI, TextMeshPro, and Timeline come from packages (uGUI 2.0 includes TMP); 33 script classes from these packages are not stubbed. DOTween/DOTweenPro/AssetAssistant receive only the types needed for fields and bases (29 types), no logic. Nintendo SDK (`nn`, 104 player scripts) is not referenced by bundle instances and is not generated.
7. **Manifest and report:** `manifest.json` (classes, fields, per-field source `typetree`/`dump`/`typetree+dump`, assembly, file list) in output folder; `work/stubs/report.json` (counts, uncovered types). Idempotent: write only changed files, delete stale files (and their `.meta`); deterministic (sorted, schema hashes). `--dry-run` writes nothing.

Generated in this measurement [D]: 1,310 types = 693 script classes, 46 base classes, 411 data classes/structs (from dump or helper types), 143 enums, 17 reference-only targets (empty shells); 5,777 fields (5,232 TypeTree + dump, 195 TypeTree only, 350 dump only). Gaps: 5 classes with no dump entry (all in external packages, guessed base); 37 classes only in dump (no TypeTree); 1 unresolved base.

## 4. Verification in throwaway project `work/unity-stubs` [D]

Separate project (Unity 6000.3.26f1, uGUI 2.0 and Timeline packages), unrelated to `unity/` and `work/unity-shader-lab`; only one batch editor at a time. Tools: `scripts/stub_verify.py` (plan, before/after, coverage, bridge) and `scripts/stub_probe.cs` (Editor script copied into project). Shader bundles are never loaded (`shaders`, `fxparticle`, `tmpshader` excluded), nothing is rendered (`-nographics`), and only one language variant per family is used (`.ge`).

### 4.1 Compilation

- First attempt: 2 compiler errors (CS7002, nested type in generic outer class) → moved types to top level (section 3, item 5). Then **0 errors, 0 warnings**; compiling 887 files takes about 2 seconds.
- Initial full check missed 3 components in one group: classes in a `….Editor` namespace were placed in an `Editor` folder (Editor assembly) → path sanitized (section 3, item 5).

### 4.2 Missing Script before/after

Measured with `GetComponentsInChildren<Component>` on every loaded prefab; first without `XnuStubs`, then with it.

| Measurement | Components | Missing before | Missing after | Stub components |
|---|---:|---:|---:|---:|
| `ui/uiresidentwindow` (53 prefabs, 21 dependencies) | 25,293 | 2,650 | **0** | 2,650 |
| `Environments/fields/area001` (zone 422) | 21,081 | 38 | **0** | 38 |
| Character prefab (smallest with stubs) | 21 | 3 | **0** | 3 |
| Event scripts `Dpr/ev_script` (ScriptableObjects) | – | – | – | 936 SO loaded |
| Master data (`Dpr/masterdatas`, `Battle/battle_masterdatas`) | – | – | – | 1,122 SO loaded |
| **13,889 bundles** (all up to 80 MB, language variants .ge only; 1,112,276 components) | 1,112,276 | **34,101** | **0** | 34,092 (+9 via asmdef) |
| of which Pokemon Database / Effects / Environments / UIs | | 7,851 / 18,359 / 2,660 / 3,755 | 0 | |

- ScriptableObjects whose script is missing do not load (5,325 SOs loaded in total after stubbing, versus 12 before).
- Not verifiable: scene bundle (`Dpr/scenes/…`) cannot be opened in Editor batch mode (`EditorSceneManager.OpenScene` only knows project scenes); Play Mode test is pending. For the 9 scene bundles, only structure counts from the scan are available.

### 4.3 Serialized-field verifier

`stub_verify.py` reads two instances per class with UnityPy (`read_typetree`), flattens them to paths (`field.Array.data[3].nestedField`), then compares in the Editor with `SerializedObject` on the loaded instance (instance identified by local object ID, numbers with tolerance 1e-5, references only as “set/empty”).

- **Group run** (UI, zone 422, events, master data, character, scene): 469 samples, 435 found (the rest are in the scene bundle that cannot be loaded), 17,483 leaves, 17,480 match.
- **Coverage run** (greedy selection of 97 bundles containing 627 of 654 classes with TypeTree): 780 samples, 711 found, **574 classes checked, 573 fully matching**; 42,401 leaves, **42,399 match (99.995%)**, zero value mismatches, zero unresolved references (set but empty). 53 classes had no discoverable sample (their instances could not be matched by local ID; they still count as zero missing in 4.2); 27 classes do not occur in any loadable bundle ≤80 MB.
- The only two differences are one TMP base-class field (`m_enableWordWrapping`) renamed by the package version bundled with Unity 6. This value is lost for all TMP text (workaround: read it from TypeTree and map to the new property during later material conversion).
- Two initial verifier failures demonstrated sensitivity: a `PPtr<$…>` pointed to a game class sharing a short name with a static engine class (stub chose the wrong one, field missing → now resolved by “derived from `UnityEngine.Object`”), and non-ASCII field names (28 missing leaves → now preserved).

### 4.4 Console, time, memory

- **Console:** zero serialization errors and zero warnings from stubs. The full run shows two messages (`m_PreventLoadingFromFile` assertion, `UnloadAssetBundle failed`), **identical with and without stubs** (not caused by stubs).
- **Full run** (13,889 groups, load all prefabs and ScriptableObjects per bundle, unload): 57 s without stubs, 59 s with; binding costs about 4%.
- **UI group** (22 bundles): open bundles 33 ms; load prefabs/assets 1.1 s without and 1.2–1.4 s with stubs; managed heap +11 MB without / +21 MB with; native memory about 172 MB. Zone 422: 10 ms, 0.27 / 0.29 s, +2 MB heap.
- iPad memory/load time remain unmeasured (Editor, Apple M1 Pro).

## 5. Build-pipeline integration and bridge to `Xnu.*`

### 5.1 `stubs` stage (`scripts/build_all.sh`, `scripts/build_stages.py`)

- The `stubs` stage runs **after `assets` and before `unity-build`** (current order then: tools extract il2cpp masterdata shaders video audio assets stubs unity-build deploy). It requires `work/il2cpp/dump.cs`, bundles under `work/romfs/…/AssetAssistant`, and `tools/pydeps` (UnityPy).
- Flow: `stub_gen.py scan` → `stub_gen.py gen --out unity/Assets/XnuStubs` → `stub_gen.py conflicts` (report only). Marker hash: `stub_gen.py`/`stub_dump.py`, `il2cpp` stage marker, bundle listing; `unity-build` also depends on `stubs` marker.
- Target `unity/Assets/XnuStubs` (overridable with `STUBS_DEST`); `.gitignore` covers `unity/Assets/XnuStubs/` and `unity/Assets/XnuStubs.meta`; stage exits 2 if target is not ignored.
- **Do not disrupt the main Editor:** if an Editor has project `unity/` open, skip the real stage (like `unity-build`), since new scripts trigger recompilation in an open Editor. `--dry-run` displays plan/commands without writing. Only dry-run was performed; `unity/Assets` stayed untouched. [T] (`test_build_all.py`: stage list, order `assets < stubs < unity-build`, stage dry-run).
- Stubs are `partial`: hooks (section 5.3) are hand-written repository files outside the generated directory.

### 5.2 Conflicts with hand-written `Xnu.*` types

`stub_gen.py conflicts --manifest … --scripts unity/Assets/Scripts` compares fully qualified type names only: **464 hand-written types, 1,310 stub types, zero identical full names** (four identical short names in different namespaces, harmless). Examples from the task were not conflicts: stubs are in the global namespace or `Dpr.*`/`SmartPoint.*`, own types are in `Xnu.*`; `EnvironmentSettingsData`/`…Catalog` differ from the stub class name; no `GameInput` stub exists (no bundle instance). Future rules:
- Keep own types under `Xnu.*`. Same name in an auto-referenced assembly and Assembly-CSharp produces only CS0436 warnings (source type wins), **but** CS0433 (error) occurs if two referenced assemblies contain the same fully qualified name. The stage runs `conflicts` and fails on matches.
- Identical short names in different namespaces are fine if stubs use fully qualified names (they do).

### 5.3 How does logic (`Xnu.*`) call into stubs? Options and test

Constraint [D, see `docs/ui-spezifikation-2.md`]: binding uses (`Assembly-CSharp`, namespace, class name); Assembly-CSharp may reference auto-referenced asmdef assemblies, but asmdef assemblies must **not** reference Assembly-CSharp.

| Option | Principle | Assessment |
|---|---|---|
| **A: interfaces in `Xnu.*` + hand-written `partial` in stub** | `Xnu.Core` (or bridge assembly) defines `IBridgeHost`-style interfaces and registration; a hand-written stub `partial` (folder without asmdef, in repo) implements them and registers in `Awake`/`OnEnable`/`OnDestroy`. Logic sees only the interface. | **Robust, tested** |
| B: delegate/factory registration | As A, but stub holds only delegates (`Action`, `Func`) and logic registers at runtime; no interface required | Viable, less strongly typed; useful for small wrappers |
| C: reflection from `Xnu.*` | Logic reads fields by name | Works, but untyped, slow, and needs `link.xml`/`[Preserve]` under IL2CPP; tools/verifiers only |
| D: stubs in `Assembly-CSharp-firstpass` (`Assets/Plugins`) | firstpass compiles before Assembly-CSharp and cannot see it | **Not viable** [A]: MonoScript assembly name is `Assembly-CSharp`, so firstpass does not bind; not independently tested |
| E: logic directly in stubs (Assembly-CSharp) | Game logic as `partial` stub | Undermines testable separation (`Xnu.*` with EditMode tests); useful only for thin Unity callbacks |

**Option A test** (`scripts/stub_bridge/`: `Xnu.Bridge.asmdef`, `BridgeHub.cs`; probe `stub_probe.cs`, run with `stub_verify.py --phase bridge`): in the throwaway project, the script generates a `partial` for a class in the original UI bundle (Assembly-CSharp, separate folder) with `[ExecuteAlways]`; it implements `IBridgeHost` from `Xnu.Bridge` and calls `BridgeHub.Attach/Detach` in `Awake`/`OnDestroy`. Results [D]:
- Found 127 `IBridgeHost` components in 13 bundle prefabs using `GetComponentsInChildren<IBridgeHost>` (logic side does not know stub class).
- Instantiating a prefab: 6 `Attach` calls (`Awake` ran), 18 instance fields read through the interface.
- After `DestroyImmediate`: zero registered hosts; zero console errors.

Remember: the hook folder must **not** be inside the bridge asmdef folder (otherwise it compiles into `Xnu.Bridge`; this happened in the first test and caused CS0436 against the stub).

Recommendation: Option A, convention `unity/Assets/Scripts/DprHooks/<Namespace>/<Class>.Hook.cs` (no asmdef, `partial`), interfaces in `Xnu.Core`; keep hooks thin (forward/register), with logic and tests in `Xnu.*`. Define Unity callbacks (`Awake`, `Update`, `OnDestroy`) only in the hook, never generated code (which has no logic).

## 6. Limits and open questions

1. **Scene bundles** (`Dpr/scenes`, 9 files) and player scenes could not be loaded; need a Play Mode test or player build. The `Dpr` group has 242 components total, some in scenes (only scan structure counts are available).
2. **Package drift:** package base classes (TMP, uGUI) have different fields in Unity 6 than Unity 2019.4. One TMP field found (section 4.3). A package-to-TypeTree field comparison is useful for all 12 tier-C classes and all TMP/uGUI instances (8,909 + 127).
3. **Shaders/materials:** still open (`docs/material-remap.md`); stubs load objects but render nothing. Original-shader materials remain `Hidden/InternalErrorShader` until remapped.
4. **DOTween/DOTweenPro:** only field/base types, no tween logic. `DOTweenAnimation` instances in UI/event prefabs (including 49 in the main UI bundle) contain curves, duration, and ease as data, but nothing plays them. Package versus custom implementation remains undecided (see item 3 in `docs/ui-spezifikation-2.md`).
5. **Classes without TypeTree** (34 classes, 43 instances in `resources.assets`): fields come only from dump (visibility and attributes determine Unity serialization); unverified because no reference values exist.
6. **Interfaces, methods, generic constraints** are intentionally absent; constants are not copied from dump. Enum values come from dump and are not checked against instance values (verifier compares the `int`).
7. **IL2CPP stripping** [A]: classes bound only through bundles need `link.xml` for Assembly-CSharp and asmdef assemblies; player test with built macOS/iPad app remains pending (all measurements were in Editor).
8. **Domain reload in main Editor:** 887 new scripts trigger a larger recompilation while Editor is open (2 s compile in throwaway project, plus reload); stage therefore skips when Editor is open.
9. **Unity.Polybrush** (7 instances, Editor leftovers) and 2 instances with unresolved script references are not covered; no gameplay impact [A].
10. Licensing/legal: generator creates class shells at runtime from user data; repository contains neither stubs nor dump excerpts. This is not legal advice.

## 7. Next steps (prioritizing logic implementation)

Weights (from `stub_gen.py stats`, names only in `work/stubs/stats.json`): instances per class (importance to loaded scenes), dump method count as effort (the 688 referenced classes have 8,769 of roughly 47,800 Assembly-CSharp methods = 18.3%).

1. **Class by class, ranked by “instances per method,” within the vertical slice:** first 20 classes account for 87.6% of instances but have only 187 methods combined (mostly markers/data holders: effects, environment, database objects). They provide most visible progress for little logic, so start there.
2. **Then complete packages by group** (effort = methods including bases; counts assigned by each class's largest instance group): `Effects` 7 classes/18,389 instances/113 methods; `Pokemon Database` 6/7,851/213; `Message` 1/1,280/1; `Battle` 7/2,116/58; `Environments` 28/2,754/1,480; `Dpr` (master-data SOs and systems) 101/6,429/1,048; `Characters` 9/795/660. Then `UIs` with 305 classes/3,965 instances/8,457 methods (largest block, depends on bridge and TMP comparison), followed by `Contest`, `FureaiHiroba`, `UnderGround`, `DigFossil`, and other small groups.
3. **Dependencies** (PPtr graph, 808 references to game classes): implement classes with incoming references before their users. Generator already knows the graph; next small step is an “in-degree” field in `stats` output.
4. **Finalize bridge:** add `IBridgeHost`-style interfaces in `Xnu.Core`, create `DprHooks`, add an oracle test per implemented class (instance field values ↔ logic result), and run `stub_verify.py --coverage` as a regression after every stub generation.
5. **Open measurements:** scene bundles in Play Mode/player, IL2CPP player with `link.xml`, material conversion (shader/TMP), DOTween decision, TMP field comparison, and main-project Editor run of real `stubs` stage (only after closing Editor).
6. Optional `--all-classes` (all 2,229 dump classes as dump-only shells) if hand-written logic later needs types from unreferenced classes; generator supports `dump_only_fields`, but the option is not wired up.

## 8. Reproduction

```
python3 scripts/stub_gen.py scan                                   # work/stubs/scan.json (about 3 min)
python3 scripts/stub_gen.py stats                                  # counts: work/stubs/stats.json
python3 scripts/stub_gen.py gen --out work/unity-stubs/Assets/XnuStubs   # stubs, manifest.json, work/stubs/report.json
python3 scripts/stub_gen.py gen --out … --dry-run                  # write nothing
python3 scripts/stub_gen.py conflicts --manifest …/manifest.json   # check for type-name clashes with hand-written code
python3 scripts/stub_verify.py --phase both                        # Missing Script before/after, field binding (groups)
python3 scripts/stub_verify.py --phase both --bulk "UIs,Battle,Effects,…" --bulk-max-mb 80   # count across all bundles
python3 scripts/stub_verify.py --phase after --coverage --per-class 2                          # one sample per class
python3 scripts/stub_verify.py --phase bridge                      # bridge test
python3 -m unittest scripts.tests.test_stub_gen                    # 35 tests
scripts/build_all.sh --dry-run --only stubs                        # stage in pipeline plan
```

Throwaway-project requirements: `work/unity-stubs/Packages/manifest.json` with uGUI 2.0 (includes TMP), Timeline, and engine modules, plus `ProjectSettings/ProjectVersion.txt` set to `6000.3.26f1`; Unity creates the rest on the first batch start.
