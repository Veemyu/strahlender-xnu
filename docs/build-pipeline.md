# Build Pipeline: Stages, Markers, and Tools

> **Status 2026-10-19:** Unity project stages `assets`, `stubs`, `unity-build`, and `deploy` have been removed from `main`, as have `--shaders-into-unity`, Unity's `--target`, and editor detection. Remaining stages: `tools`, `extract`, `il2cpp`, `recomp`, `masterdata`, `shaders`, `video`, `audio`. Sections about removed stages apply only to branch `unity`. Also removed (only on branch `unity`): `scripts/bundle_retarget.py` and `scripts/ios_deploy.sh`.

Entry point is `scripts/build_all.sh` (bash 3.2 compatible). Helpers: `scripts/build_helpers.py` (decryption, manifest) and `scripts/build_stages.py` (stage selection, markers with input hashes, preflight). User guide “provide NSP/XCI, get app” is `docs/bauen.md`; this document describes implementation.

Stages run in this order: `tools`, `extract`, `il2cpp`, `recomp`, `masterdata`, `shaders`, `video`, `audio` (placeholder). Unity stages `assets`, `stubs`, `unity-build`, `deploy` are removed (branch `unity`). (`recomp` = macOS app from recompilation, main path since decision 3; technical details: `docs/recomp-macapp.md`.) Preflight runs first. All stages are present in script; `audio` reports “not implemented.” Tested: dry run, `extract` (earlier run, see below), `il2cpp`, `masterdata`, `video` (sample), `shaders` (sample), and `recomp`. **Update (2026-10-19):** real player builds using real bundles for macOS and iPad (section “First Player Build Results,” details in `docs/player-build-1.md`); Unity batch driver (Editor closed) was not used; build was made via `Xnu/Build/…` menu items in open Editor. The same update was inadvertently repeated in the source.

## Invocation

```
scripts/build_all.sh all --xci <x.xci> --nsp <update.nsp> --keys <directory> [--target macos|ios|all]
scripts/build_all.sh --dry-run all --xci … --keys …       # plan, marker status, commands; changes nothing
scripts/build_all.sh --from masterdata --to video
scripts/build_all.sh --only shaders,video
scripts/build_all.sh preflight
```

| Option | Meaning |
|---|---|
| `--xci`, `--nsp`, `--keys`, `--prod-keys`, `--title-keys` | Inputs for `extract` (NSP optional; `title.keys` is fallback only). After successful `extract`, `--xci` is no longer needed. |
| `--work` | Work directory; default **`work/`** (formerly `work/build`). Other scripts also expect `exefs/`, `romfs/`, `il2cpp/`, `masterdata/` there. |
| `--target` | `macos`, `ios`, `all` (default), for `recomp`. |
| `--dry-run` | Do not execute, write, or install; show commands with `[dry-run]`. |
| `--from`, `--to`, `--only` | Stage range or exact selection (`--only` cannot combine with `--from/--to`). |
| `--force` | Regenerate selected stages even if marker matches. |
| `--no-preflight`, `--min-free-gb N` | Skip preflight or change minimum free space (default 60). |
| `--keep-nca` | Keep extracted NCAs (several GB). |
| `--video-profile`, `--movie-src` | `h265-crf18` (default) or `h265-crf14`; alternate video source (samples only, no marker). |
| `--shader-only NAME` | One shader only (test, no marker). |
| `--launch` | Launch iOS app after installation (default: do not launch). |
| `--bundle-platform`, `--bundle-subset`, `--texture-format` | Options from removed `assets` stage (branch `unity`). |

Environment variables: `TOOLS_DIR` (default `tools/`), `MIN_FREE_GB` (reserve for `extract`, default 25), `PREFLIGHT_MIN_FREE_GB`, `DEVELOPER_DIR`, `SHADER_USED` (JSON of used keyword sets).

## Preflight

Checks only; never installs and never uses `sudo`. Checks requirements of selected stages:

- **At least 60 GB free** (all stages except `tools`/`audio`; `recomp` alone: **at least 25 GB**, see `docs/bauen.md`). Less space → exit 8 and hint to `--min-free-gb`.
- `recomp`: Homebrew `clang` and Apple `clang`, `pkg-config` with `sdl3`, `libavcodec`, `libavformat`, `libavutil`, `rsync`, `codesign`, `install_name_tool`, `otool`, `iconutil`, `plutil`, `tools/pydeps/{capstone,unicorn}`, vendored LASRecomp components in `scripts/recomp/upstream/` and `scripts/recomp/rt-bdsp/nvn/upstream/` (no clone needed).
- `tools`: git, make, cc. `extract`: `tools/hactool/hactool` (or built by `tools`). `il2cpp`: `dotnet` ≥ 8 and `tools/il2cppdumper-bin/Il2CppDumper.dll`. `masterdata`/`shaders`: `tools/pydeps/UnityPy`; `shaders`: make, cc. `video`: `ffmpeg` with `libx265`.

Missing requirements appear as an **installation list** (commands for user to run). Exit 4 for missing tools, 8 for insufficient space. In dry run, failed preflight does not terminate; it shows the exit code a real run would return.

## Markers and Idempotency

After success, every stage except `tools`, `audio`, and samples writes `work/.stages/<stage>.json`: schema, stage, input hash, timestamp, notes (counts, sizes). Per-stage hash (`build_stages.py stage-hash`) includes:

| Stage | Inputs hashed |
|---|---|
| `il2cpp` | core of `manifest.json`, SHA-256 of `global-metadata.dat` and Il2CppDumper |
| `recomp` | dump modules (SHA-256 of `exefs/main`, `sdk`, `subsdk0`, `rtld`), generator scripts and clone tools, submarkers `recomp-gen` (generated C) and `recomp-obj` (compiled objects), `rt-bdsp/` sources (excluding `test/`, `vulkan/`), clone NVN sources, `shader_translator/`, `scripts/recomp/app/`, `main.npdm`, options (`-O0` threshold, Hardened Runtime, data) |
| `masterdata` | manifest core, `masterdata_export.py` |
| `shaders` | manifest core, all `shader_*.py`/`shader_build.sh`, `shader_translator/` sources, `SHADER_USED` |
| `video` | manifest core, `video_convert.sh`, profile, WebM source paths and sizes |
| `il2cpp` | manifest core, SHA-256 of `global-metadata.dat` and Il2CppDumper |

Stages with matching marker and existing output are skipped; interrupted run resumes where markers end. `extract` uses its own `manifest.json` process (below). Markers, logs, and outputs never contain keys; team ID is never stored in plaintext.

## Individual Stages

### `il2cpp`
`DOTNET_ROLL_FORWARD=Major dotnet tools/il2cppdumper-bin/Il2CppDumper.dll exefs/main global-metadata.dat work/il2cpp.stage`, then rename to `work/il2cpp/` (`dump.cs`, `script.json`, `il2cpp.h`, `DummyDll`, `stringliteral.json`). Dumper raises a harmless exception at end without a terminal (key prompt); success is determined from output. Test: sandbox run (5.7 s) produced `dump.cs` and `script.json` **byte-identical** to earlier manual run. This stage is not needed for the app itself, only analysis and master-data comparison.

### `masterdata`
`masterdata_export.py export --set all --messages` and `counts` with `PYTHONPATH=tools/pydeps` to `work/masterdata/`. Test (sandbox): 9 s, 129 files, 104,649,610 bytes.

### `shaders`
Calls `scripts/shader_build.sh` (`docs/shader-translator.md`). Default output `work/build/shaders/`. Exit 9 (16 variants with subgroup shuffle cannot be packaged) is a warning. Because helper scripts read fixed `work/romfs`, stage creates a symlink there for another `--work` (or aborts if a different real directory exists). Test: sample `Custom/EffectCopyTexture` in 1.3 s. Full run (6,804 variants) not started; without stripping (`SHADER_USED`), import time and file count in Unity project are excessive, so default is outside project.

### `video`
`scripts/video_convert.sh <Movie> work/video <Profile>`: libx265, `hvc1`, no H.264 fallback (`docs/video-umwandlung.md`). Script is idempotent via `video-manifest.json`. Test: 4-s loop in 2.5 s; second run “unchanged, skipped.” Full run of 18 videos not started (about 10 min encoding).

### `audio`
**Not implemented.** Stage says so clearly and exits successfully without a marker. Planned work is offline conversion of Wwise banks to files (vgmstream); pipeline never plays audio, and app is silent by default (`AudioSafety`).

### `assets` (Removed, Branch `unity`; Historical)
Places data for player under gitignored `unity/Assets/StreamingAssets/GameData/` (enforced with `git check-ignore`; otherwise abort, exit 2):

```
GameData/romfs/Data/StreamingAssets/AssetAssistant/   all bundles (APFS clone, otherwise copy)
GameData/romfs/Data/StreamingAssets/Movie/            H.265 videos from work/video
GameData/masterdata/                                  JSON from work/masterdata
```

Structure matches `GameDataPaths` (`Root` = `StreamingAssets/GameData` if `XNU_GAMEDATA` is unset), so `AssetAssistant` and `masterdata` consumers need no code changes. Also `GameData/materials/` (material exports from `work/materials`, if present; required for shader remapping). Audio is not copied. Counts and size are measured and printed. Test (sandbox, real bundles): 14,183 files, 3.9 GB in 4 s without extra disk use (clone).

**Bundle platform identifier (required for player).** Original bundles identify target platform 38 (Switch). Editor loads them; **player does not** (“The file can not be loaded because it was created for another build target…”). Stage therefore runs `scripts/bundle_retarget.py tree … --platform macos|ios`: for each bundle, only platform identifier in Serialized File changes (decompress block with four bytes, patch, repack with LZ4HC, rewrite block info, copy other blocks unchanged; texture formats and contents stay the same). Real-data result: 14,052 bundles, 0 errors; clones become real copies (4.0 GB disk). Total time 42 s (24 s if patched block remains uncompressed, but +0.9 GB). UnityPy opens patched and original bundles with identical objects (28,225 objects in `area001`, same checksum for first 300).
- `--bundle-platform macos|ios|keep`: default from `--target` (`ios` → ios, else macos; `all` means macos, rerun stage with `--target ios` for iOS). `keep` leaves identifier unchanged (tools only; player then cannot load bundles).
- `--bundle-subset FILE`: instead of all bundles, select listed names (relative to `AssetAssistant`, `#` comments) plus all non-bundle files (catalog `Dpr.bin`, etc.). For iPad: `scripts/subsets/ipad-start.txt` (scene `FieldTest2` startup, 5 bundles, 34.6 MB; rationale/measurement in `docs/player-build-1.md`).
- `--texture-format 4x4|6x6|8x8|off`: convert BC textures (BC1/BC3/BC4/BC5/BC7, Crunch) in bundles to ASTC (`scripts/texture_transcode.py tree`, after platform identifier). Default `6x6` for bundle platform `ios` (Apple GPUs do not support BC), otherwise `off`. Mip chains, dimensions, names, PathIDs, ColorSpace, and streaming through `.resS` are preserved; BC4/BC5 always use ASTC 4×4. Idempotent (bundle without BC remains unchanged). Measurement (`ipad-start` subset): 24 s, 34.6 → 47.9 MB on disk, Zone 422 texture memory 46.4 → 25.5 MiB; all bundles: 2,838 contain BC textures (5.2 GB raw), estimated 10–15 min with 4–6 processes. Details: `docs/ios-texturen.md`.
- Stage marker hash includes `bundle_retarget.py`, `texture_transcode.py`, platform, texture format, subset, and material-export list.
- Unity build then copies all data into package (macOS app 4.1 GB, output directory with symbols 5.0 GB; iOS without subset about 4.4 GB plus Xcode Derived Data).

### `unity-build` (Removed, Branch `unity`; Historical)
Batch build per target with `Xnu.Build.Editor.BuildScript` (`BuildMacOS`, `BuildIos`):

- Driver `cli`: `unity --non-interactive --no-banner build unity --target StandaloneOSX|iOS --execute-method … --output-path … --editor-version 6000.3.26f1 --architecture arm64 --allow-dirty-build --log-file …`.
- Driver `editor` (fallback or `XNU_UNITY_DRIVER=editor`): `Unity -batchmode -quit -projectPath unity -buildTarget … -executeMethod … -xnuOutput …`.
- Build script sets before building: IL2CPP scripting backend, **Metal only** graphics API, macOS arm64 architecture (via reflection, otherwise Editor default), iPhone and iPad device types for iOS. Scenes: enabled Build Settings scenes; otherwise `Boot` (selection menu/start), `FieldTest2`, `FieldTest`, `UiTest`, `InputTest`; `-xnuScenes a;b` overrides. Creates Boot scene automatically if needed (`BootSceneBuilder`). **Before build**, syncs generated shaders into `Assets/XnuGenerated/Resources` (`GeneratedShaderSync`; source `-xnuShaders`, `XNU_SHADERS`, `work/build/shaders`, `work/shaders/combined`, each with `variants.json`); Resources are included in player and `Shader.Find` finds shaders there (verified 61 of 61 in macOS player). `unity/Assets/link.xml` prevents stripping engine classes referenced only by bundle contents (iOS: `SkinnedMeshRenderer`). Player can start directly in a scene with `-xnuScene <Name>` or `XNU_START_SCENE`. Output: `-xnuOutput` or `-buildOutput`. Batch exit code 1 on errors. iOS postbuild `IosPostBuild.cs` (Increased Memory Limit entitlement) unchanged; it exists only if iOS is active at compile time: both drivers (`--target iOS` or `-buildTarget iOS`) satisfy this; **with open Editor targeting macOS, entitlement was missing on first call** (repeat after target switch adds it). Script checks `Xnu.entitlements` in Xcode project afterward. `ApplyPlayerSettings` writes `ProjectSettings.asset`: IL2CPP for Standalone and Metal only for macOS/iOS (intended, belongs in repo).
- Output is deleted first (Unity otherwise appends to old Xcode projects).
- **Editor open:** if `build_stages.py editor-open` detects Unity process with `-projectpath unity` (import workers and shader compiler do not count), build is not attempted. Script prints PID and two alternatives, skips `unity-build` and `deploy`, exits **11**.
- Exit 12: Unity build failed (excerpt from Unity log).

### `deploy` (Removed, Branch `unity`; Historical)
- macOS: checks `work/builds/macos/xnu.app` and `codesign --verify` (read-only); app is already in destination directory.
- iOS: without team ID (environment `TEAM_ID` or `work/local.env`), reports “built only.” With team ID, `scripts/ios_deploy.sh work/builds/ios/xnu --no-launch` (`--launch` starts app). No iPad → skip with message; otherwise exit 13.

## `tools` Stage

Checks or builds everything locally; installs nothing system-wide: hactool (clone of github.com/SciresM/hactool, `config.mk`, `make`, log `tools/hactool/build.log`), ffmpeg, python3 ≥ 3.9, Unity Hub CLI and Editor with iOS module, Xcode. Lists all missing items (exit 4).

## `extract` Stage

1. Unpack XCI secure partition and NSP contents into `<work>/nca-base` and `<work>/nca-update`.
2. Read each NCA with `hactool -i`; retain only content type, title ID, Master Key Revision, Rights ID, and size. Base program is largest Program NCA in XCI; update program is NSP Program NCA with matching title ID.
3. Title key: parse ticket (`.tik`) in NSP (signature type determines offsets); for Common Ticket, first 16 bytes of key block are title key; otherwise use `title.keys`.
4. Apply update with `--basenca`; ExeFS and RomFS go to `<work>/exefs` and `<work>/romfs`.
5. Version from CNMT and `control.nacp`, then write `<work>/manifest.json` (title ID, versions, input sizes, SHA-256/SHA-1 of `exefs/main`, SHA-256 of ExeFS files, RomFS file count/size; no key material).
6. Temporary NCAs are deleted even on error unless `--keep-nca`.

**Idempotency:** if `manifest.json` matches input sizes and existing outputs, skip stage. **Key-leak prevention:** hactool prints key values to stdout/stderr; script discards both. Title key exists only in shell variable and is passed to hactool as an argument (briefly visible in same user's process list). **Disk space:** at least `MIN_FREE_GB` must remain after run (need about 2× XCI + NSP, peak about 12 GB).

## Exit Codes

0 success · 2 invocation · 3 input file missing · 4 tool missing or build failed · 5 hactool error · 6 key/title key · 7 matching NCA not found · 8 insufficient space · 9 output validation failed · 10 prerequisite/upstream stage missing · 14 il2cpp/masterdata/shaders/video failed (11–13 were removed with Unity stages).

## Tests

- `python3 -m unittest discover -s scripts/tests` (all passing). New: `test_build_stages.py` (stage selection, markers, hash dependencies, team ID never plaintext, editor detection against sample `ps` output, preflight with simulated tools, installation list without `sudo`) and `test_build_all.py` (dry run without writes, `--from/--to/--only`, invocation errors, audio placeholder, assets stage with synthetic bundles: copy, skip, regenerate, enforce gitignore). `test_build_helpers.py` still covers ticket parser, NCA selection, manifest.
- C# build script first **compiled** without starting Editor against Unity 6000.3.26f1 assemblies (0 errors); since 2026-10-19 runs in open Editor (macOS and iOS, section “First Player Build Results”). New `test_bundle_retarget.py` (8 synthetic UnityFS bundle tests: read/change platform, preserve contents, leave original, uncompressed/big-endian, `tree` and `subset`, missing entries); Python suite 258 passing total. Unity EditMode: 635/635 passing (including `BootOptionsTests`).
- `bash -n scripts/build_all.sh` is clean; `shellcheck` not installed here. New `test_texture_transcode.py` (10 tests: BC→ASTC with synthetic textures and hand-built mini bundle with `.resS`, idempotency, subset/dry run; requires `astc_encoder`, `etcpak`, `texture2ddecoder` in `tools/pydeps`, otherwise skipped).

## `extract` Test Result (Status 2026-10-18, macOS arm64)

Run into a new directory (since deleted): `tools` under 1 s; full `extract` 31 s and 34 s; second run with matching manifest 0.3 s (skipped). Error cases: missing XCI/keys exit 3, missing argument exit 2, empty keys exit 6. Compared with manual result: `exefs/main` and all five ExeFS files identical; RomFS byte-identical except six `.DS_Store` files. Detected version: title version 393216, display version 1.3.0.

## First Player Build Results (Status 2026-10-19, M1 Pro and iPad Pro M2; Unity pipeline, historical)

Details in `docs/player-build-1.md`. Summary:

| Measurement | Value |
|---|---|
| `assets` stage, clone only (platform unchanged) | 4 s, 14,187 files, 3.9 GB (no disk use) |
| `assets` stage with platform identifier (macOS, all bundles) | 42 s, 14,833 files, 4.0 GB (real copies) |
| `assets` stage for iPad (subset) | 7 s, 9 bundle/catalog files (34.6 MB), 179 MB with master data and materials |
| macOS build | first 202 s, then 44 s and 92 s after target switch; 0 errors; app 4.1 GB, output directory 5.0 GB |
| iOS build (Unity) | 19 s incremental, 247 s on first target switch; Xcode project 1,055 MB |
| `ios_deploy.sh` (Xcode Release, sign, install) | 2 min 25 s to 2 min 40 s |
| Zone 422 startup | macOS 1.2 s, iPad 1.1 s; both 30 FPS |

Errors found and fixes:
1. **Player cannot load bundles with platform 38 (Switch)** → `bundle_retarget.py` in `assets` stage (per-bundle platform identifier).
2. **iOS stripped `SkinnedMeshRenderer`** (“Could not produce class with ID 137”) → `unity/Assets/link.xml`.
3. **`IosPostBuild` missing from first iOS build in open Editor** (`#if UNITY_IOS`, active target was macOS) → rebuild after target switch; batch driver unaffected; stage checks `Xnu.entitlements`.
4. **Relative `-logFile` path** creates no file → use absolute path.
5. **Generated player shaders:** no error; synced to `Assets/XnuGenerated/Resources` before each build (`BuildScript`), all 61 found by `Shader.Find`. 237 build warnings come from those shaders (single-iteration loops, unsigned negation), harmless.
6. **Still open:** BC1/BC3/BC7 map textures fail on iOS (1,884 errors in Zone 422); ASTC conversion missing (`docs/player-build-1.md`, section 6).

## Open Items

- (Historical, stage removed) Unity batch driver (Editor closed, `build_all.sh --only unity-build,deploy`) has not been run with real bundles; builds were made from `Xnu/Build/…` menu in open Editor. Boot is now start scene (selection menu).
- BC→ASTC texture conversion is implemented (`scripts/texture_transcode.py`, `docs/ios-texturen.md`; `assets` stage removed), but has not been run on iPad; full bundle set on iPad (installation, space, load time) unmeasured; no visual inspection (Mac: screenshot not possible).
- (Historical) `--target all` created only one `StreamingAssets/GameData` data set (macOS platform).
- Free space on this development machine (≈ 41 GB) is below the 60-GB preflight minimum; a real full run requires `--min-free-gb` or more space.
- `audio` missing; shader stripping (`SHADER_USED`) missing.
