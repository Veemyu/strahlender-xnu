# Build: From Your Own NSP/XCI to an App

> **Status 2026-10-19:** Unity stages `assets`, `stubs`, `unity-build`, and `deploy` have been removed from `main` (branch `unity`). The `scripts/recomp/` path (BDSP.app, iPad via `scripts/recomp/ios/deploy_ios.sh`) is unchanged. Sections below about those stages apply only to branch `unity`. Also removed from `main` (only on `unity`): `scripts/bundle_retarget.py` and `scripts/ios_deploy.sh`. “Data in the Player” describes the Unity path.

This repository contains only original code, scripts, and documentation. All third-party content (textures, models, master data, videos, shader wrappers) is produced locally from **your own** copy of Pokémon Brilliant Diamond. Keys, dumps, and game data never belong in the repository; `work/`, `tools/`, `unity/Assets/StreamingAssets/`, and `unity/Assets/GameData/` are gitignored. Built apps contain your game data and are for personal use only.

## Requirements

- Apple Silicon Mac running macOS, with about **60 GB free** (bundles, copies, Unity library, builds).
- Your files: base game as `.xci`, optional update as `.nsp`, and `prod.keys` (plus `title.keys`) from your own console. You choose where they are stored; they are only read.
- Tools: Xcode, Unity Editor **6000.3.26f1** with “Mac Build Support (IL2CPP)” and “iOS Build Support” modules, `ffmpeg` (with libx265), `dotnet` (8+), Python 3.9 or newer. The script builds `hactool` itself (stage `tools`).
- Nothing is installed with `sudo`. If something is missing, preflight provides an **installation list** for you to follow.

## One Command

```sh
scripts/build_all.sh all --xci <path/to/game.xci> --nsp <path/to/update.nsp> --keys <directory/with/prod.keys> --target all
```

`--target macos`, `ios`, or `all` (default) selects what Unity builds. An iPad is deployed only when a team ID is known (see below).

Inspect first, then run:

```sh
scripts/build_all.sh --dry-run all --xci <…> --nsp <…> --keys <…>
```

Dry run checks prerequisites, shows for each stage whether it would be skipped or run, and prints commands. It changes nothing.

## Stages

| Stage | Function | Result |
|---|---|---|
| `tools` | builds hactool locally, checks ffmpeg and Xcode | `tools/hactool` |
| `extract` | unpacks XCI/NSP, applies update | `work/exefs`, `work/romfs`, `work/manifest.json` |
| `il2cpp` | runs Il2CppDumper on `exefs/main` and `global-metadata.dat` | `work/il2cpp/` |
| `recomp` | **macOS app from recompilation** (main path, see below): generator → C → compile → runtime/Metal → `BDSP.app`, RomFS to Application Support | `work/builds/macos-recomp/BDSP.app` |
| `masterdata` | reads master data and text from bundles | `work/masterdata/` |
| `shaders` | translates Maxwell shaders, creates Unity wrappers | `work/build/shaders/` (default) |
| `video` | converts WebM (VP8) to H.265 (`.mp4`, `hvc1`) | `work/video/` |
| `audio` | **not implemented** (placeholder, never plays anything) | – |

## Partial Runs and Resuming

```sh
scripts/build_all.sh --from masterdata --to video      # range of stages
scripts/build_all.sh --only shaders,video              # exactly these stages
scripts/build_all.sh preflight                         # check prerequisites only
```

After success, each stage writes a marker `work/.stages/<stage>.json` with a hash of its inputs (extraction manifest, scripts, upstream markers, Unity sources). A later invocation skips stages whose inputs are unchanged and resumes where a run stopped. `--force` regenerates selected stages. After the first `extract` run, you can invoke it without `--xci`; existing output is reused.

## macOS App from Recompilation (Stage `recomp`)

Since decision 3 (`docs/architektur-entscheidung.md`), recompilation is the main path: the game is built from **your** dump as a native arm64 app using Metal, currently **without audio** (audio is under investigation) and without network access. The stage runs after `extract` (and `il2cpp`); technical details, controls, save handling, and measurements are in `docs/recomp-macapp.md`.

```sh
scripts/build_all.sh --only recomp                  # after extract; without --xci, reuses existing work/exefs and work/romfs
scripts/build_all.sh --dry-run --only recomp        # plan, preflight, and marker status only
open work/builds/macos-recomp/BDSP.app
```

- **Additional requirements:** Homebrew packages `llvm`, `sdl3`, `ffmpeg`, `pkg-config` (`brew install llvm sdl3 ffmpeg pkg-config`; put `/opt/homebrew/opt/llvm/bin` before `/usr/bin` in `PATH`), Xcode Command Line Tools, Python packages `capstone` and `unicorn` in `tools/pydeps` (`python3 -m pip install --target tools/pydeps capstone unicorn`). Clone `research/LASRecomp` is no longer needed. Vendored components: `scripts/recomp/upstream/` (generator, headers), `scripts/recomp/rt-bdsp/nvn/upstream/` (NVN layer). Preflight names missing items and the relevant command.
- **Disk space:** preflight requires **≥ 25 GB** free (`--min-free-gb N` can deliberately lower it). The stage itself was measured at only about 1.7 GB (C 1.0 GB, objects 0.3 GB, program 0.22 GB, app 0.36 GB, RomFS clone 0 GB; briefly +1 GB temporary data when rerunning generator); the rest is reserve for compiler and swap.
- **Time:** cold (generator + compile + app) measured at **about 27.5 minutes** under load 25–50 (generator 7.2 min, compile 19.8 min; see `docs/recomp-macapp.md`). Later only changed parts rebuild: unchanged inputs 0.4 s, runtime change 13–50 s, generator input change recompiles only changed C files. At most 4 compiler jobs (`--recomp-jobs N)); outlier files (one function, over 300 KB C) compile with `-O0` (`--recomp-o0-kb N`).
- **Idempotency:** substage markers `work/.stages/recomp-gen.json` and `recomp-obj.json`, plus stage marker `recomp.json` (hash over dump modules, generator, runtime sources, options). Second run without changes: “Marker matches, skipped.” `--force` rebuilds everything.
- **Signing:** ad hoc (`codesign -s -`), can launch without developer account; on first Finder launch, right-click → Open may be needed (Gatekeeper). `--hardened` signs with Hardened Runtime (only entitlement is `disable-library-validation` for bundled libraries); no JIT is needed, and there is no sandbox or network entitlement.
- **Data:** app reads RomFS from `~/Library/Application Support/dev.local.xnubdsp/romfs` (stage makes an APFS clone of `work/romfs`, requiring no extra space; `--no-install-data` skips this), save from `…/save`, and stores shader cache and screenshots under `~/Library/Caches/dev.local.xnubdsp`. Paths can be changed in `config.ini` or environment variables; none are in the repository.
- **Import save:** menu *Game → Import Save…*, drag `SaveData.bin` (or its directory) onto window, or `BDSP.app/Contents/MacOS/BDSP --import-save <path>`; save is validated first (979,108 bytes, MD5 as in `scripts/bdsp_save.py`).
- **Errors:** if something is missing, the script explains in German and gives the next step (exit codes: 4 tool/build, 8 disk space, 10 prerequisite/upstream stage). Logs: `work/logs/recomp-compile.log`, `recomp-runtime.log`, `recomp-images.log`; generator: `work/recomp/spike2/gen4_<module>.log`.

## Unity Build (Removed, Branch `unity`)

The Unity path was removed from `main`; stages `assets`, `unity-build`, and `deploy` remain only on branch `unity`. This section is historical.

## iPad / iPadOS

1. Connect iPad over USB, unlock it, enable Developer Mode, trust developer profile.
2. Put `TEAM_ID=<your ID>` in `work/local.env` (gitignored). It is never printed or stored elsewhere (`scripts/recomp/ios/deploy_ios.sh`).
3. Run `scripts/recomp/ios/deploy_ios.sh build`, then once `data` (RomFS to Documents, about 4.7 GB), then `install` and `run [seconds]`. Without a duration, app runs until Ctrl-C; log is written under `work/builds/`. App is currently silent.
4. Transfer save to iPad with `scripts/ios_push_save.sh` (file to `Documents/SaveData.bin`, checksum before and after, imported at next “Continue”; `--pull` retrieves it). Build sets `UIFileSharingEnabled`, exposing Documents in Files app. Procedure, causes, and measurements: `docs/ipad-durchstich-1.md`.

A free Apple team is sufficient; profile expires after 7 days.

**Data on iPad (historical):** bundle subset (`scripts/subsets/ipad-start.txt`, five bundles, 34.6 MB) comes from removed `assets` stage (branch `unity`). For recompilation, use RomFS and launch with `deploy_ios.sh data` and `run`. Start a scene without input: `xcrun devicectl device process launch --device <iPad> --terminate-existing --console --environment-variables '{"XNU_START_SCENE":"FieldTest2"}' dev.local.xnum0`. App starts in Boot scene (test-scene list). **Textures (historical):** BC/DXT-to-ASTC conversion ran in `assets` stage (`scripts/texture_transcode.py`, measurements in `docs/ios-texturen.md`).

## Data in the Player

Player loads bundles only when platform identifier matches its target. Original bundles identify as Switch; `assets` stage changes this per target (`--bundle-platform`, default from `--target`). With `--target all`, only one data set is made (macOS); rerun `assets` with `--target ios` for iOS. Inspect individual bundles with `PYTHONPATH=tools/pydeps python3 scripts/bundle_retarget.py info <file>`.

## Output Structure (All Gitignored)

```
work/
  manifest.json            extraction: title ID, version, hashes, sizes (no keys)
  exefs/  romfs/           decrypted content
  il2cpp/  masterdata/  video/
  build/shaders/           generated .shader wrappers
  builds/macos/xnu.app     macOS app (arm64)
  builds/macos-recomp/BDSP.app   macOS app from recompilation (recomp stage)
  recomp/                  recomp stage intermediates (gen4: generated C, obj4: objects, img_app, bdsp_app)
  builds/ios/xnu/          Xcode project for iOS/iPadOS
  logs/<stage>.log         per-stage logs
  .stages/<stage>.json     markers with input hashes
unity/Assets/StreamingAssets/GameData/   data copied into player
```

The app searches for data first via `XNU_GAMEDATA`, then in `StreamingAssets/GameData` (prepackaged build), and finally in the device application directory.

## Known Gaps

- `audio` is not implemented: built app currently has no audio and is silent; audio is being investigated (Todo `rc-audio`).
- Shader wrappers are written to `work/build/shaders/`.
- Disk space: 60 GB is the preflight minimum. On a smaller drive it can be deliberately lowered with `--min-free-gb N`.
- The first real player build completed on 2026-10-19 in the open Editor (menu `Xnu/Build/…`): macOS 202 s (cold) or 44 s, iOS 19 s, install 2 min 40 s; Zone 422 loads in both apps in about 1 s at 30 FPS (`docs/player-build-1.md`). **Update:** BC-to-ASTC texture conversion (`scripts/texture_transcode.py`, `docs/ios-texturen.md`) implemented and checked on macOS with loaded bundle, **not yet on iPad**. **Open:** run converted textures on iPad, visual inspection, full bundle set on iPad, run batch driver with Editor closed.
