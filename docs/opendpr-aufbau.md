# Assembling the opendpr Project from a Personal Dump (2026-10-18)

> **Historical (status 2026-10-20):** Unity path, discontinued. `scripts/opendpr_build.sh` has been removed from `main` (only on branch `unity`). The steps below no longer apply to `main`.

Original summary. Nothing from `opendpr` or `Lumi_Small_Scripts` is in the tracked repository.
The project is under `work/opendpr-project/` (gitignored). Originals in `tools/` were left unchanged.
All steps are repeatable with `scripts/opendpr_build.sh` (custom script; aborts if destination already exists).
The Editor was not opened.

## Log

Free space on <DATA_VOLUME> before run: 38 GiB (threshold: 15 GiB). After run, also 38 GiB (measurement fluctuates within ±1 GiB; APFS clones cost practically nothing). Entire run took about 6 seconds.

| # | Step | Command / result | Space |
|---|---|---|---|
| 1 | Copy repository | `cp -c -R tools/opendpr work/opendpr-project`, then removed copied `.git`. 221 MB, including 139 MB Wwise | about 0 (clone) |
| 2a | Prepare input | Copied all directories from `work/ripper/out/ExportedProject/Assets` to `work/opendpr-stage/input` using `cp -c -R`, **excluding** `StreamingAssets`; removed `.DS_Store` | about 0 |
| 2b | Script | Ran `python3 …/asset_ripper_resources/fix_pathids.py` in stage directory. No errors. Log (96 lines) contains only “Ignoring …” for `Scripts` and `Plugins`. Output: 29 MB (stage) | 29 MB, deleted afterward |
| 3a | Delete | `AkWwiseInitializationSettings`, `Mac`, `Switch`, `Windows` (each `.asset` + `.meta`) from `MonoBehaviour` | – |
| 3b | TextMeshPro | Moved `fonts & materials`, `sprite assets`, `style sheets`, and both `LineBreaking …txt` files (with `.meta`) to `Assets/TextMesh Pro/Resources/` | 1 MB |
| 3c | Scene | Moved `level0.unity` + `.meta` to `Assets/` | – |
| 3d | Remainder | Other contents of `Resources` and directories `AnimationClip`, `AnimatorController`, `Font`, `Material`, `MonoBehaviour`, `PrefabInstance`, `Texture2D` are now under `Assets/Resources/` | 3.2 MB |
| 3e | Assembly name | Ran `sed` on `Assets/Resources/StartupSettings.asset`: 21 replacements, 0 remaining instances of “AssetAssistant, Version=0.0.0.0,” | – |
| 4 | Bundle directory | Created `AssetBundles/Editor/`, left empty (blocker B1) | 0 |
| 5 | StreamingAssets | `cp -c -R work/romfs/Data/StreamingAssets/. Assets/StreamingAssets/` (merged into existing `AK` directory). 18,019 files rather than 18,014 in RomFS (5 extra files are `AK` and `desc.txt` plus `.meta`). Sample checked with `cmp`, identical | about 0 (clone, 4.7 GB logical) |
| 6 | Soundbanks | Renamed `Audio/GeneratedSoundBanks/Switch` → `Windows` | 0 |

Cleanup: deleted `work/opendpr-stage` (intermediate only).

## Observations

- Despite “skip StreamingAssets” setting, AssetRipper export contained a `StreamingAssets` directory of 4.9 GB. It was deliberately excluded from input; otherwise script would copy it with `shutil.copy` (not a clone). Data came from RomFS (step 5). Cause unknown.
- Script weakness (file extension via `split('.')[1]`) was not triggered: there are no files without a dot and no binary `.asset`/`.prefab` files.
- Export directories `Scripts`, `Plugins`, `Shader` are excluded (as the script intends). `.unity` is not replaced.
- A harmless `.DS_Store` from the clone is in project root.

## Static Checks

- **GUIDs:** Compared GUIDs defined in 4,503 `.meta` files with all references in `.asset`, `.prefab`, `.unity`, `.mat` (excluding Scripts, Wwise, Plugins, StreamingAssets). 35 unresolved GUIDs:
  - TextMeshPro scripts and shaders (e.g. TMP_FontAsset, TMP_Settings, TMP_SDF material shader) and UnityEngine.UI (`EventSystem`, `StandaloneInputModule`): supplied by `textmeshpro` and `ugui` packages; expected after package import.
  - Scene GUIDs in `SceneDatabase.asset`: other scenes are not in project (only `level0`).
  - `0000…e000…`/`f000…`: Unity internal resources.
  - `level0.unity` itself has no missing project GUIDs.
  All game GUIDs replaced by script (GameManager, StartupSettings, etc.) resolve, which supports the mapping.
- **Packages:** `Packages/manifest.json` lists 6 registry packages not bundled in Editor: `textmeshpro` 2.1.6, `timeline` 1.2.18, `test-framework` 1.1.24, `ide.rider` 1.2.1, `ide.vscode` 1.2.3, and (via lock file) `ext.nunit` 1.0.6. All module packages and `ugui` are bundled in Editor (`BuiltInPackages`). Offline alone is therefore **not** enough: first open needs network (`packages.unity.com` responded to HEAD, HTTP 200). Local package cache was not checked to avoid searching outside the repository.
- Static compilation could not be checked (about 3,800 scripts, many placeholders).

## Known Gaps

1. **B1:** `AssetBundles/Editor` is empty. Editor path of `AssetManager` and `EffectManager` looks there for `fxparticle`/`shaders`. Expect console errors loading effects/materials and pink or missing shaders. Project should still open (not established).
2. Wwise soundbanks are Switch format (renamed only). Audio probably will not play; irrelevant for opening project.
3. TextMeshPro: TMP Essentials material set arrives only with package import. On first open, Unity may ask to “Import TMP Essentials” (note: this adds files under `Assets/TextMesh Pro`, possibly conflicting with moved files).
4. `StreamingAssets` has 18,000 files. On open, Unity creates `.meta` files and imports items such as videos. This can greatly lengthen first launch and enlarge `Library`. These `.meta` files are created in clone target and do not alter RomFS.
5. Mac rather than Windows: Windows Wwise plugins are in project, but Mac Editor uses macOS plugins.

## Opening (For User to Run)

```
open -n <UNITY_APP> --args -projectPath <REPO_ROOT>/work/opendpr-project
```

Then open `Assets/level0.unity` manually (no scene in Build Settings).

## Unity Editor Test Result (2019.4.27f1, Rosetta, 2026-10-18)
- Project opens, compiles without errors (`Assembly-CSharp.dll` in about 12 s), and resolves packages.
- At startup, `level0.unity` shows only black. Log shows two boot failures:
  1. `NullReferenceException` in `GameManager.OnetimeInitializeOperation` (`GameManager.cs:249`): `UIManager.Instance` is `null`. Cause unknown.
  2. Bundle `shaders` is missing from `AssetBundles/Editor` (blocker B1): `AssetBundle.LoadFromFile` returns `null`, followed by `NullReferenceException` in `AssetManager.LoadAssetBundle`.
- Open questions: whether Switch bundles from dump can be loaded in Mac Editor, and why `UIManager.Instance` is missing.
- Assessment: opendpr is useful as a reference (classes, boot sequence), but does not run on Mac without further work.
