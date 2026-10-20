# Build guide: BDSP recompilation

**Deutsche Fassung: [BUILD.de.md](BUILD.de.md)**

## 1. Overview

BDSP is a recompilation of the original *Pokémon Brilliant Diamond* code. The build turns the game's
machine code into native C, compiles it, and links it with a runtime that provides the console
services and a graphics backend (Metal on macOS, Vulkan on Linux, Metal on iPadOS).

- The repository contains only our own code, scripts, and documentation. It contains no game content,
  no keys, no saves, and no screenshots.
- You need your own dump of the game: the base `.xci` (optional `.nsp` update) and your `prod.keys`
  (plus `title.keys`). Keep them outside the repository. The scripts only read them.
- Everything the scripts produce goes to `work/`, which is git-ignored. Never commit `work/`.
- Targets: macOS app (most complete), iPadOS app (no sound), Linux with Vulkan (work in progress, section 6).

## 2. Common prerequisites

| Item | Needed for | Check |
|---|---|---|
| Xcode (in `/Applications/Xcode.app`), license accepted | macOS and iPadOS builds | `xcodebuild -version` |
| Command Line Tools | Compilers, `codesign`, `otool`, `iconutil` | `xcode-select -p` |
| Python 3.9 or newer | `build_all.sh`, helper scripts | `python3 --version` |
| Homebrew packages `llvm`, `sdl3`, `ffmpeg`, `pkg-config` | macOS app (`recomp` stage) | `pkg-config --exists sdl3 libavcodec libavformat libavutil` |
| Python packages `capstone`, `unicorn` in `tools/pydeps` | Code generator (`recomp` stage) | `ls tools/pydeps` |
| `git`, `make`, `cc` | Stage `tools` (builds `hactool`) | `command -v git make cc` |

Install the Homebrew packages and the Python packages:

```sh
brew install llvm sdl3 ffmpeg pkg-config
python3 -m pip install --target tools/pydeps capstone unicorn
```

The `recomp` stage needs the Homebrew LLVM first in `PATH`, before `/usr/bin`:

```sh
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
```

Nothing is installed with `sudo`. If a check fails, `scripts/build_all.sh preflight` lists what is missing.

## 3. Local configuration (`work/local.env`)

Create `work/local.env`. The file is git-ignored. Do not put these values anywhere else in the repository.

```sh
TEAM_ID=<TEAM_ID>
RZ_HOST=<RZ_HOST>
```

- `TEAM_ID`: your Apple developer team ID. Used only for the iPadOS build (`deploy_ios.sh`). It is passed
  to `xcodebuild` on the command line and is not written to the project.
- `RZ_HOST`: the ssh alias of your Linux build host. Used only by the Linux/Vulkan scripts (section 6).
  Use an alias from `~/.ssh/config`, not an IP address.

Write the file in shell syntax: no spaces around `=`.

## 4. macOS app (stage `recomp`, `--target macos`)

### 4.1 Get the game data (stage `extract`)

The `recomp` stage reads `work/exefs` and `work/romfs`. Create them first:

```sh
scripts/build_all.sh --only tools,extract --xci <path/to/game.xci> --keys <folder/with/prod.keys>
```

Use `--prod-keys <file>` and `--title-keys <file>` instead of `--keys` if your keys are in separate files.
Add `--nsp <update.nsp>` if you have the update.

### 4.2 Build the app

```sh
scripts/build_all.sh --dry-run --only recomp --target macos   # plan only, changes nothing
scripts/build_all.sh --only recomp --target macos
```

Result: `work/builds/macos-recomp/BDSP.app` (arm64, Metal, ad hoc signed).

The first build takes about 28 minutes under load (measured, see `docs/recomp-macapp.md`). Later builds
reuse the markers and are much faster (section 7).

Useful options:

| Option | Meaning |
|---|---|
| `--recomp-jobs N` | number of compiler jobs, 1 to 4 (default 4) |
| `--recomp-o0-kb N` | functions from N KB upward are compiled with `-O0` (default 300) |
| `--force` | rebuild the stage even if the marker matches |
| `--hardened` | sign with the Hardened Runtime (default: ad hoc only) |
| `--no-install-data` | do not install the RomFS under Application Support |

### 4.3 Start the app and set options

Start from the Finder (`open work/builds/macos-recomp/BDSP.app`) or from a terminal. Environment variables
are passed only when you start the binary directly:

```sh
BDSP_FPS=60 work/builds/macos-recomp/BDSP.app/Contents/MacOS/BDSP
```

| Variable | Values | Effect |
|---|---|---|
| `BDSP_FPS` | `30`, `60`, `120` | frame rate. Other values are ignored. Overrides the saved menu setting. |
| `BDSP_PRESENT_AT` | `off`, `min`, `grid`, `lock` | presentation timing. The Mac default is `lock`. `off` restores the old behaviour. |
| `BDSP_EXEC_WORKER` | `0` | `0` turns off the translation worker and uses the synchronous path. On by default. |
| `BDSP_FPS_INTERVAL` | seconds | period of the `fps` log line (default 2). |

From a terminal the log stays on screen. From the Finder it goes to the log folder (`BDSP_LOG_STDOUT=1` forces
terminal output). Configuration file, save data, and cache paths: see `docs/recomp-macapp.md`.

Limits: no sound and no network. The first launch may need right-click → Open (Gatekeeper, ad hoc signature).

## 5. iPadOS app (`scripts/recomp/ios/deploy_ios.sh`)

### 5.1 Prerequisites

- `TEAM_ID` in `work/local.env` (section 3).
- A paired iPad, unlocked, trusted, and connected. The script selects the first connected iPad.
- The iOS build inputs in `work/recomp/obj32` and `work/recomp/img32`. Create them with
  `scripts/recomp/ios/gen32.sh` (see `docs/recomp-ios.md`).
- `work/exefs` with `main.npdm`, from stage `extract`.

### 5.2 Commands

```sh
scripts/recomp/ios/deploy_ios.sh build          # runtime, libgame.a, resources, and the app (xcodebuild)
scripts/recomp/ios/deploy_ios.sh install        # install the app on the iPad
scripts/recomp/ios/deploy_ios.sh data           # copy work/romfs to the app container (once, about 4.7 GB)
scripts/recomp/ios/deploy_ios.sh save           # optional: copy save files from work/recomp/save
scripts/recomp/ios/deploy_ios.sh run 120        # start for 120 seconds; without a number, run until Ctrl-C
scripts/recomp/ios/deploy_ios.sh shots          # copy screenshots to work/visual/ipad-recomp/
scripts/recomp/ios/deploy_ios.sh files [path]   # list files in the app container
```

Environment variables for the script:

- `DEVICE_NAME`: part of the device name, if more than one iPad is connected.
- `BUNDLE_ID`: default `dev.local.xnubdsp`.
- `RUN_ENV`: JSON with environment variables for `run`, for example `{"BDSP_TIMEOUT":"130"}`.

The log of each `run` goes to `work/builds/ipad-recomp-<time>.log`. The build log goes to
`work/builds/ios-recomp-xcodebuild.log`.

### 5.3 Signing

Signing is your job. Select your team and provisioning in Xcode if the build fails. The script passes
`TEAM_ID` and `-allowProvisioningUpdates` to `xcodebuild`. Do not change `project.pbxproj` in the
repository to set the team.

## 6. Linux with Vulkan (work in progress)

Work in progress. Not playable yet. See section 6.4 for the known limits.

### 6.1 Requirements

You run the commands on a Mac. A Linux x86-64 machine builds and runs the game in `~/xnu-recomp`.
Set `RZ_HOST` in `work/local.env` (section 3) to the ssh alias of that machine.

**Linux machine**

- x86-64 CPU with the `x86-64-v3` level (AVX2), because the build uses `-march=x86-64-v3`.
- Vulkan loader and Vulkan driver. Tested GPU: NVIDIA GeForce RTX 2080 Ti with Vulkan 1.4.
- `clang`.
- Runtime libraries (no `-devel` packages needed): `/usr/lib64/libvulkan.so.1`, `/usr/lib64/libSDL3.so.0`,
  `/usr/lib64/libshaderc_shared.so.1`.
- For film playback: `libavformat.so.62`, `libavcodec.so.62`, `libavutil.so.60`. Optional: without them,
  build with `BDSP_NO_MOVIE=1`.

**Mac**

- ssh with key authentication (no password prompt), `rsync`, `curl`.
- Homebrew packages `vulkan-headers`, `sdl3`, `shaderc` (headers only).
- Optional: Homebrew `ffmpeg` for the FFmpeg headers (see step 2 in section 6.2).

### 6.2 Build and run

Run these steps on the Mac, in this order:

1. Copy the headers to the Linux machine (once): `scripts/recomp/ryzen/vk_sync_deps.sh`
   - On the first run, the script downloads `vk_mem_alloc.h` from GitHub, unless it is already in
     `work/recomp/deps-vk/`.
2. Copy the sources and your own data (RomFS, `main.npdm`): `scripts/recomp/ryzen/vk_sync.sh --daten`
   - If `work/recomp/img_gfx` is missing, the script prints the command to create it (`mkimages.sh`).
   - Optional, for film playback: `scripts/recomp/ryzen/sync_deps.sh` copies the FFmpeg headers and the SDL3
     headers from Homebrew to `~/xnu-recomp/deps/include`. Set `FFMPEG_PREFIX` if ffmpeg is not in
     `/opt/homebrew/opt/ffmpeg`.
3. Translate the four modules on the Linux machine into `~/xnu-recomp/work/recomp/obj4-c`:
   `scripts/recomp/ryzen/build.sh` (host prerequisites: `docs/recomp-ryzen.md`).
4. Build the Vulkan runtime: `scripts/recomp/ryzen/vk_build.sh` (result: `work/recomp/bdsp_boot_vk` on the Linux machine).
5. Run without a window (default): `scripts/recomp/ryzen/vk_run.sh --tag=t1 --headless --timeout 40 --screenshot-after 300`
6. Fetch screenshots and logs to `work/recomp/ryzen/` on the Mac: `scripts/recomp/ryzen/vk_fetch.sh`

`--headless` needs no display. It renders into offscreen images. The screenshots are written to
`work/recomp/shots/frame_NNNNN.png` on the Linux machine, and step 6 fetches them.

### 6.3 Run with a window (Wayland)

A window opens on the desktop of the Linux machine. Pass the session variables of the desktop user
with the run. Get the user ID with `id -u` on the Linux machine. Without these variables no window can open.

```sh
scripts/recomp/ryzen/vk_run.sh --tag=win XDG_RUNTIME_DIR=/run/user/<UID> WAYLAND_DISPLAY=wayland-0 \
  SDL_VIDEODRIVER=wayland BDSP_NO_USER_INPUT=1 --window 1280x720 --timeout 22
```

`BDSP_NO_USER_INPUT=1` keeps the window from taking keyboard focus when it opens. Whether it also blocks
the keys below is not verified. Run without it for interactive play.

Settings for window runs only (they have no effect with `--headless`):

- Start size: `--window 1280x720` or `BDSP_WINDOW=1920x1080` (default 1280×720).
- Frame rate: `BDSP_FPS=30`, `BDSP_FPS=60` or `BDSP_FPS=120`. Pass it after the script name, for example
  `scripts/recomp/ryzen/vk_run.sh BDSP_FPS=60 --tag=win ...`.
- MangoHud overlay (fps, frame time, CPU and GPU): `BDSP_MANGOHUD=1`. Needs the `mangohud` package on the
  Linux machine. It is needed only at run time, not for the build. Off by default.
- Run time: `--timeout N` in seconds (default 120).

Keys in the window:

- F1 to F4: window size 960×540, 1280×720, 1920×1080, 2560×1440 (not in full screen).
- F5, F6, F7: frame rate 30, 60, 120.
- F11: toggle full screen. Not verified.

X11 is not tested.

### 6.3a Menu bar (in progress, Qt host)

A menu bar with File, Edit, View, Window and Help is in progress, as part of a Qt host. It is not delivered
yet, and the Qt host is not in the repository. Use the keys in section 6.3 until then.

### 6.4 Known limitations

- **Player character missing, vertex explosions, window fill:** fixed in the last test run (field scene with
  player character, NPCs and water; window fully filled). Not yet verified across sessions.
- **Texture outside the guest window:** the runtime logs `[vk] Textur außerhalb des Gastfensters` and skips
  the upload (guard in `textures.c`). Effect on the picture not verified. Open.
- **Rare hangs on the loading screen:** open. Cause not known.
- **FFmpeg header version:** not matched to the runtime libraries yet. If film playback fails, build with
  `BDSP_NO_MOVIE=1`.
- **Frame rate:** `BDSP_FPS` caps the frame rate (30, 60, 120). Measured in a window only; not verified across sessions.
- No sound. Input state is not reported. Compute workloads are not supported.
- Windows is not supported. X11 and full screen (F11) are not tested.

Details: `docs/recomp-vulkan.md`.

## 7. Build stages overview

Stage order: `tools extract il2cpp recomp masterdata shaders video audio`. Run one part with `--only` or
`--from`/`--to`. Use `--dry-run` first. Each stage writes a marker `work/.stages/<stage>.json` with an input hash.
If the hash matches, the stage is skipped (`--force` rebuilds it).

| Stage | Purpose | Needed for the apps |
|---|---|---|
| `tools` | checks tools, builds `hactool` into `tools/hactool` | yes (for `extract`) |
| `extract` | decrypts the `.xci`/`.nsp` into `work/exefs`, `work/romfs`, `work/manifest.json` | yes |
| `il2cpp`, `masterdata`, `shaders`, `video`, `audio` | Unity-related stages | no: `recomp_build.sh` reads only `work/exefs` and `work/romfs` |
| `recomp` | macOS app from the recompilation | macOS app only |

### 7.1 The `recomp` stage

`scripts/recomp/app/recomp_build.sh` runs six steps:

1. **Generator:** `work/exefs` modules → C in `work/recomp/gen4` (about 1 GB). Marker `recomp-gen`.
2. **Compile:** C → objects in `work/recomp/obj4`, at most 4 jobs. Functions above `--recomp-o0-kb` use `-O0`.
   Marker `recomp-obj`.
3. **Module images:** `mkimages.sh` with `hle_nvn.txt` → `work/recomp/img_app`.
4. **Runtime:** `rt-bdsp/build.sh` with `BDSP_APP=1` → `work/recomp/bdsp_app`.
5. **App:** bundle, `Info.plist`, icon, libraries, ad hoc signature.
6. **Data:** APFS clone of `work/romfs` into Application Support.

### 7.2 The NVN stamp (`prepare.sh`)

`scripts/recomp/rt-bdsp/nvn/prepare.sh` prepares the Metal copy of the NVN layer in `work/recomp/nvn-src`.

- The stamp is a SHA-256 over `scripts/recomp/rt-bdsp/nvn/src` (all files, sorted), `shader_translator/translate.c`,
  `shader_translator/shader.h`, and `prepare.sh` itself. The hash is written to `work/recomp/nvn-src/.stamp`.
- The script copies the sources only when the stamp differs. It does not patch them.
- `prepare.sh --check` copies nothing and exits 0 if the stamp matches, 1 if not.
- `prepare.sh --print` prints the source hash. The `recomp` stage uses it in its own hash.
- Normal builds (`build_nvn.sh`, `build.sh`) call `prepare.sh` for you. They skip it only if `NVN_KEEP=1` is set.

### 7.3 Compiler flags (`flags.inc.sh`)

`scripts/recomp/rt-bdsp/nvn/flags.inc.sh` defines the flags shared by the NVN builds:
`BDSP_OPT="-O1 -g"`, `BDSP_NOWARN="-w"`, `BDSP_WARN_GLUE="-Wall -Wextra -Wno-unused-parameter"`.
The scripts `build_nvn.sh`, `vulkan/build_vk.sh`, and `ios/build_rt32.sh` source it. Platform defines stay in each script.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `NVN-Stempel passt nicht` (from `prepare.sh --check`) | The copy in `work/recomp/nvn-src` is out of date. Run `scripts/recomp/rt-bdsp/nvn/prepare.sh`. Normal builds do this automatically. |
| Build uses old NVN code | `NVN_KEEP=1` is set, so `prepare.sh` was skipped. Unset it or run `prepare.sh`. |
| `Marker passt, übersprungen` / stage skipped | Inputs did not change. Use `--force` to rebuild. |
| `work/exefs/main fehlt` (exit 10) | Run stage `extract` first. |
| Not enough disk space (exit 8) | Free space or lower the requirement with `--min-free-gb N`. The macOS build needs tens of GB. |
| Compile fails (exit 4), memory error | Use `--recomp-jobs 2`. Check `work/logs/recomp-compile.log`. |
| `RZ_HOST fehlt` | Add `RZ_HOST=<RZ_HOST>` to `work/local.env`, or export it. |
| `… ist über den ssh-Alias … nicht erreichbar` | Test with `ssh <RZ_HOST> true`. The host must be on, and key authentication must work. |
| `Kein verbundenes, entsperrtes iPad gefunden.` | Connect the iPad, unlock it, and trust the Mac. Check with `xcrun devicectl list devices`. |
| Build fails in `xcodebuild` (signing) | Read `work/builds/ios-recomp-xcodebuild.log`. Set `TEAM_ID` and sign in with your account in Xcode. |
| macOS app blocked on first start | Right-click the app, then Open. |

## 9. More documentation

- `docs/recomp-macapp.md`: macOS app, data locations, save import, measurements.
- `docs/recomp-ios.md`: iPadOS build steps.
- `docs/recomp-vulkan.md`: Vulkan path and its status.
- `docs/build-pipeline.md`: stages, markers, preflight.
