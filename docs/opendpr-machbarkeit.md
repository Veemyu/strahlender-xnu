# opendpr Feasibility Test (Status: 2026-10-18)

> **Historical:** This documents the discontinued Unity path.

This is an original summary. Nothing from `opendpr` or `Lumi_Small_Scripts` was copied into the repository.
Both clones exist only locally, gitignored, under `tools/opendpr` and `tools/Lumi_Small_Scripts`.
Neither repository has a GitHub license (`gh repo view` returns `licenseInfo: null`), so all rights are reserved.
The scripts repository belongs to `SaltContainer/Lumi_Small_Scripts` per README link, not TeamLumi.
AssetRipper source (tag 1.1.8, commit `97e8b07`) is also available locally to inspect its API under `tools/AssetRipper-src-1.1.8`.

## 1. What opendpr Is

- Reconstructed Unity project for BDSP (Editor 2019.4.27f1, Changeset `23dc10685eb4`), not an actual decompilation.
- Repository contains about 3,800 hand-written C# files (about 307,000 lines, 37 MB) under `Assets/Scripts`, Wwise integration (2019.2.4, 139 MB, Mac and Windows plugins), `ProjectSettings`, `Packages` (TextMeshPro 2.1.6, Timeline, uGUI, standard modules), and Wwise project `Dpr_WwiseProject`.
- Game data and assets are **not** in repository. They must be generated from a personal dump.
- Many methods remain placeholders (about 4,300 occurrences of `return default;`). Starting Editor can show at most that scaffold runs, not a playable game.
- No scene is listed in Build Settings. Must open `level0.unity` manually.
- Open issues: #2 (README unclear about directory structure and `TextMesh Pro`), #1 (missing mesh assets). No answer about Windows bundles.
- README says generative AI was not used and advises other projects against it. This is a position, not a license condition.

## 2. Steps to an Openable Project

Status: ✅ done, ⚠️ uncertain, ❌ missing.

| # | Step | From our dump | Status |
|---|---|---|---|
| 0 | Clone repositories | – | ✅ complete |
| 1 | AssetRipper 1.1.8 on RomFS + ExeFS, skip StreamingAssets | `work/exefs/main`, `work/romfs/Data` (including `Managed/Metadata/global-metadata.dat`) | ✅ input complete, export not yet run |
| 2 | Python script `fix_pathids.py` | Export directory `Assets` as `input/` | ⚠️ README does not describe input structure |
| 3 | Manual steps (delete, move, replace assembly name) | result of step 2 | ⚠️ |
| 4 | `AssetBundles/Editor` with Windows bundles `fxparticle` and `shaders` | only Switch versions available | ❌ **Blocker B1** |
| 5 | Copy StreamingAssets from RomFS to `Assets/StreamingAssets` | `work/romfs/Data/StreamingAssets` (4.7 GB) | ✅ |
| 6 | Rename `GeneratedSoundBanks/Switch` to `.../Windows` | present (427 MB) | ✅ |
| 7 | Open Unity 2019.4.27f1, resolve packages, choose scene | – | ⚠️ see section 5 |

### 2a. AssetRipper Automation (Read from 1.1.8 Source)

Start: `tools/AssetRipper-1.1.8/AssetRipper.GUI.Free --port 8765 --launch-browser false --log true --log-path <File>`.
The file is an arm64 Mach-O binary. Server listens only on `127.0.0.1`.

| Purpose | Request (form `application/x-www-form-urlencoded`) |
|---|---|
| Set settings | `POST /Settings/Update` with `ScriptContentLevel=Level2`, `ScriptExportMode=Hybrid`, `ScriptLanguageVersion=AutoSafe`, `SpriteExportMode=Texture2D`, `IgnoreStreamingAssets=` |
| Load input | `POST /LoadFolder` with `Path=<directory with exefs/ and romfs/Data>` |
| Export | `POST /Export/UnityProject` with `Path=<destination>` |
| Reset | `POST /Reset` |
| API docs | `GET /openapi.json` plus Swagger UI (route `/swagger`, default from `UseSwaggerUI`) |

Important behavior from source:

- `/Settings/Update` sets every checkbox to false if its key is absent from form. “Skip StreamingAssets” is checkbox `IgnoreStreamingAssets`; value may be empty, only key matters.
- Defaults are already Level 2, Hybrid, AutoSafe. Only Sprite export (default `Yaml`) and StreamingAssets checkbox need changing.
- Settings can be changed only before anything is loaded.
- Load and export are synchronous. HTTP response arrives after completion as 302 redirect to `/`.
- Middleware swallows errors and also redirects to `/`; check log and output directory to confirm success.
- `Export/UnityProject` runs `Directory.Delete(Path, true)` and recreates directory. Destination must exist; its contents are destroyed.
- Output goes to `<Path>/ExportedProject/{Assets,ProjectSettings}` and `<Path>/AuxiliaryFiles`.
- Switch detection (`SwitchGameStructure`) expects directory with `exefs` (file `main`) and `romfs/Data`. Our `work/` already matches; no copy needed.
- With IL2CPP and Level 2, exported script bodies are empty (comment in `ScriptContentLevel` enum). opendpr apparently does not use ripped scripts because Python script skips `Scripts`, `Plugins`, and `Shader`.
- Unverified: whether Cpp2IL in AssetRipper 1.1.8 reads metadata v24.4 (per our Il2CppDumper run) successfully. opendpr authors claim support for same Unity version. Our bundles also carry `2019.4.27f1` in header.

Prepared `scripts/assetripper_export.py` (standard library only, supports `--dry-run`, not run). Prechecks:

- Ghidra PID (default 4461) is not running,
- input files exist,
- destination is under `work/` and empty,
- at least 5 GB is free.

Then it starts AssetRipper, sets options, loads and exports. Afterwards it checks console log for applied settings and completed export, then stops AssetRipper.
Output: `work/ripper/out/ExportedProject/`; logs: `work/ripper/assetripper*.log`.
Untested, but syntax and dry run checked.
Note: Ghidra (PID 4461) was already stopped when this document was written (`ps -p 4461` had no match).

Size note: besides StreamingAssets, `work/romfs/Data` is only a few MB (`resources.assets` about 1 MB, `.resS` 3 MB, `globalgamemanagers` under 0.5 MB). Export should be small and quick. The 3.9 GB of bundles under `StreamingAssets/AssetAssistant` are not ripped, only copied.

### 2b. Python Script `asset_ripper_resources/fix_pathids.py`

- Pure Python 3 using `os` and `shutil`; no requirements file or version pin. Python 3.14.3 is available here and should work.
- Input: `input/` in current working directory. It contains AssetRipper export subdirectories (as interpreted, contents of `ExportedProject/Assets`; README only says “the directories created by AssetRipper”).
- Output: `output/` with same structure.
- In `.asset` and `.prefab` files, script replaces about 40 pairs of script GUID and FileID with GUIDs used by opendpr. Covers TextMeshPro, DOTween, Wwise, startup settings, and custom game classes. All other files are copied unchanged.
- `input/Scripts`, `input/Plugins`, and `input/Shader` are skipped.
- Script weaknesses (do not modify, just account for): extension determined by `split('.')[1]`. Filename without dot raises `IndexError`; multiple dots select wrong extension. Destination is formed by `replace('input','output')` across full path, so a directory named “input” is also changed.

### 2c. Manual Steps from README (Paraphrased)

1. Delete four files and their `.meta` from `MonoBehaviour`: `AkWwiseInitializationSettings`, `Mac`, `Switch`, `Windows`. They conflict with project Wwise assets.
2. Move TextMeshPro parts from `Resources` (`fonts & materials`, `sprite assets`, `style sheets`, and two `LineBreaking …txt`) to `TextMesh Pro/Resources/…`. README does not say where `TextMesh Pro` comes from (issue #2). Probably TMP Essentials import from Unity package; unverified.
3. Move `Scenes/level0.unity` directly to `Assets`. Everything else goes directly to `Assets/Resources`.
4. In `StartupSettings.asset`, replace assembly reference `AssetAssistant, Version=0.0.0.0,` with `Assembly-CSharp, Version=1.6.28.12450,`. Version matches our dump (Assembly-CSharp 1.6.28.12450; see `docs/extraktion.md`).
5. Create `AssetBundles/Editor` at project root and put Windows bundles `fxparticle` and `shaders` there (blocker B1).
6. Copy contents of `romfs/Data/StreamingAssets` to `Assets/StreamingAssets`, then rename `Audio/GeneratedSoundBanks/Switch` to `Windows`.

## 3. Requirements from Our Dump

| Required | Present | Note |
|---|---|---|
| `exefs/main` (NSO, IL2CPP) | ✅ 37.9 MB | read directly by AssetRipper |
| `romfs/Data` with `globalgamemanagers`, `level0`, `resources.assets`, `sharedassets0.assets`, `Resources`, `Managed/Metadata/global-metadata.dat` | ✅ | |
| StreamingAssets (`AssetAssistant` 3.9 GB, `Audio` 427 MB, `Movie` 456 MB) | ✅ | bundles have `UnityFS` version `2019.4.27f1` |
| Switch bundles `AssetAssistant/Effects/fxparticle` (3.9 MB), `AssetAssistant/Dpr/shaders` (6.7 MB) | ✅ | contain Switch shaders, not Windows/Mac |
| Windows bundles `fxparticle` and `shaders` | ❌ | blocker B1 |
| Windows Wwise banks | ⚠️ | only `Switch` (427 MB) available. Renaming does not change format. Mac Wwise plugin playback unverified. Not needed just to open project. |
| Unity Editor 2019.4.27f1 | ❌ | section 5 |
| Network for first open | – | Package Manager resolves packages from `Packages/manifest.json` |

## 4. Blockers and Risks

**B1 – Windows bundles `fxparticle` and `shaders` (hard blocker, origin unclear).**

- Editor code (`AssetManager.editorPath`) reads bundles in Editor from `<destination>/AssetBundles/Editor`. `EffectManager` requires `fxparticle` and `effect_common`.
- README does not explain where “prepared bundles” come from or how to build them. Issues offer no answer. They are not in repository (only filename `fxparticle` occurs in code).
- Explicitly unverified hypothesis: Switch shader contains only NVN bytecode, no source. Windows shaders would need rebuilding from source or obtaining from third parties (Lumi community). AssetRipper shader export (default `Dummy`, alternative `Yaml`) yields no compilable source.
- Legal: shaders are copyrighted game content. Prebuilt bundles from others would redistribute Nintendo/Game Freak material. Building privately from one's own dump is probably unproblematic. Not legal advice; not verified.
- Mac: Windows bundles contain Direct3D shader blobs. Mac Editor renders through Metal. Without Metal variants, materials would be magenta or invisible. Whether bundles contain Metal variants is unknown (unverified). On Mac, bundles would need to be built from shader source for `StandaloneOSX`.
- Project might open without these bundles (console errors, pink materials). Not established.

**B2 – Unity 2019.4 under Rosetta on macOS 26.** See section 5. Officially unsupported; only trial can establish outcome.

**R1 – Export structure.** README is unclear according to issue #2. Inspect directories after first export, before moving files.

**R2 – Script errors** (section 2b) on unexpected filenames.

**R3 – Cpp2IL and metadata v24.4** (section 2a). If AssetRipper cannot load scripts, log shows “Switching to the 'Unknown' scripting backend.” Then MonoBehaviour types are missing and script GUID mapping will not work.

**R4 – Privacy/copyright.** Nothing from `work/` or built project belongs in Git repository. `work/` and `tools/` are already gitignored.

**R5 – Limited free space** (38 GB free at 91% usage), see below.

### Approximate Space Requirement

| Item | Size |
|---|---:|
| Unity Editor package download | 2.15 GB (measured via HEAD request) |
| Unity Editor installed/unpacked | about 6–8 GB (unverified) |
| AssetRipper export | under 0.2 GB (estimated from input size) |
| opendpr copy without game data | 0.22 GB |
| StreamingAssets in project | 4.7 GB; APFS clone (`cp -c`, same partition) adds about 0 GB |
| Unity `Library` | 2–6 GB (unverified estimate) |
| **Total** | **about 11–16 GB with clone, up to about 21 GB with full copy** |

Installer package can be deleted after installation. It fits within 38 GB, but leaves little margin.

## 5. Mac Feasibility (Unity 2019.4.27f1)

Established:

- Version exists in archive: Changeset **`23dc10685eb4`**, Hub link `unityhub://2019.4.27f1/23dc10685eb4` (https://unity.com/releases/editor/whats-new/2019.4.27f1, https://unity.com/releases/editor/archive).
- Direct links checked with HEAD (HTTP 200):
  - `https://download.unity3d.com/download_unity/23dc10685eb4/MacEditorInstaller/Unity-2019.4.27f1.pkg`, 2,148,927,494 bytes (about 2.0 GiB). Intel (x64) Editor; no Apple Silicon build exists for 2019.4.
  - `.../MacEditorTargetInstaller/UnitySetup-Mac-IL2CPP-Support-for-Editor-2019.4.27f1.pkg`, 142.7 MB.
  - `.../MacEditorTargetInstaller/UnitySetup-Windows-Mono-Support-for-Editor-2019.4.27f1.pkg`, 111.5 MB.
  - Download Assistant `https://download.unity3d.com/download_unity/23dc10685eb4/UnityDownloadAssistant-2019.4.27f1.dmg`, 0.5 MB.
- Modules: no additional modules needed just to open and run in Editor. Project uses Editor with Mono. “Mac IL2CPP Support” and “Windows Build Support” are needed only to build, not for this task.
- Unity 2019.4 manual lists macOS Sierra 10.12.6+, x64 with SSE2, and “Metal-capable Intel and AMD GPUs” as minimum Editor requirements. Editor is “supported … running without emulation, container or compatibility layer” (https://docs.unity3d.com/2019.4/Documentation/Manual/system-requirements.html). Rosetta is therefore not officially covered.
- Rosetta is installed here (process `oahd` running, `/Library/Apple/usr/share/rosetta` exists).
- Unity 6 docs say Apple is deprecating Rosetta (https://docs.unity.com/en-us/engine/6000.0/manual/platform-specific/apple-mac/macos-requirements-and-compatibility). Intel Editor may therefore be at risk on future macOS versions.
- opendpr project already has `metalEditorSupport: 1` (`ProjectSettings/ProjectSettings.asset`). Wwise Mac plugins are x86_64 bundles. Both fit a Rosetta Editor.
- Unity Hub: Homebrew lists `unity-hub` 3.22.3 (not installed).

Unverified (only leads from web search; sources not read):

- Whether Hub 3.22.3 on Apple Silicon reliably installs and starts Intel Editor 2019.4.27f1.
- Whether Editor crashes or displays black windows on macOS 26. A forum thread suggests `metalEditorSupport: 1` as workaround (https://discussions.unity.com/t/unity-editor-crashes-macos/757071, unavailable). It is already set here.
- Installed Editor and Library sizes.

License/login: user must handle this. Hub requires Unity ID and Personal license.
Hub login is not an action for us; no credentials are requested.

Mac conclusion: Editor should start under Rosetta, but this is not officially supported. Experiment costs about 2 GB download. Likely bottleneck is shaders (B1), not Editor.

## 6. Commands for User (No sudo)

All commands are run from repository root `<REPO_ROOT>`.

```sh
# 0) Ghidra must be stopped (no output except header = OK)
ps -p 4461

# 1) Preview export, then run (AssetRipper, a few minutes, low RAM)
python3 scripts/assetripper_export.py --dry-run
python3 scripts/assetripper_export.py
ls work/ripper/out/ExportedProject/Assets

# 2) Create project directories (opendpr copy, APFS clones save space)
mkdir -p work/dpr-prep work/dpr-project
cp -cR tools/opendpr/Assets tools/opendpr/Packages tools/opendpr/ProjectSettings tools/opendpr/Dpr_WwiseProject work/dpr-project/
cp -cR work/ripper/out/ExportedProject/Assets work/dpr-prep/input

# 3) Run unchanged third-party Python script from work/dpr-prep
cd work/dpr-prep && python3 ../../tools/Lumi_Small_Scripts/asset_ripper_resources/fix_pathids.py && cd ../..
ls work/dpr-prep/output

# 4) Manual steps (inspect structure only after step 3)
find work/dpr-prep/output -name StartupSettings.asset
#    then perform deletes/moves from section 2c
#    and replace assembly name in StartupSettings.asset,
#    then put result under work/dpr-project/Assets

# 5) Clone StreamingAssets (no extra disk use) and rename soundbank directory
cp -cR work/romfs/Data/StreamingAssets/. work/dpr-project/Assets/StreamingAssets/
mv work/dpr-project/Assets/StreamingAssets/Audio/GeneratedSoundBanks/Switch work/dpr-project/Assets/StreamingAssets/Audio/GeneratedSoundBanks/Windows

# 6) Install Unity Hub and get Editor via archive link (user signs in)
brew install --cask unity-hub
open "unityhub://2019.4.27f1/23dc10685eb4"

# 7) Open project in Hub using “Add”: work/dpr-project
#    B1 is still missing before first open: work/dpr-project/AssetBundles/Editor
```

Alternative to Hub without sudo (unverified): download package with `curl -L -O` and unpack using `pkgutil --expand-full <pkg> <destination>`. Unpacked contents include `Unity.app`, which could be started from user directory.
Using `installer` requires admin rights.
Note on step 5: `cp -c` works only when source and destination are on the same APFS partition. This is true for `work/`.

## 7. Decision

How far should the test go?

- **A (recommended, low cost):** export and prepare now, then open project without Windows shader bundles. Goal: check whether Rosetta Editor, script scaffold, and resource mapping work. Cost: about 2 GB download, 10–15 GB disk. Shader question remains open.
- **B:** also investigate shader question (B1), rebuilding bundles from source for Mac/Windows. This is the part with real effort and uncertainty.
- **C:** skip Unity and use opendpr only as a name/structure reference. Continue IL2CPP/Ghidra track, save space and time.

Recommendation: A, because AssetRipper work is small relative to input size. Then choose B or C once it is clear whether Editor runs under Rosetta.
