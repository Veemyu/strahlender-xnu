# Build guide: BDSP recompilation

German version: [BUILD.de.md](BUILD.de.md).

## 1. Overview

BDSP is a recompilation of the original *Pokémon Brilliant Diamond* code. The build turns the game's
machine code into native C, compiles it, and links it with a runtime that provides the console
services and a graphics backend (Metal on macOS, Vulkan on Linux, Metal on iPadOS).

- The repository contains only our own code, scripts, and documentation. It contains no game content,
  no keys, no saves, and no screenshots.
- You need your own dump of the game: the base `.xci` (optional `.nsp` update) and your `prod.keys`
  (plus `title.keys`). Keep them outside the repository. The scripts only read them.
- Everything the scripts produce goes to `work/`, which is git-ignored. Never commit `work/`.
- Targets: macOS app (most complete), iPadOS app, Linux with Vulkan (work in progress, section 6).

## Quick start (guided)

Two guided installers do everything in this guide for you. Run `--dry-run` first if you want to see what they would do.

- **macOS:** double-click `install.command` in the Finder or run `./install.command`. It checks Xcode, Homebrew (and offers
  the official Homebrew installer if it is missing), the Homebrew packages, Python, and a private Python environment
  `work/venv` (Pillow, capstone, unicorn). Then you drag your `.xci`, optionally the update `.nsp`, and your `prod.keys`
  into the window, and it runs the stages `tools`, `extract` and `recomp` of `scripts/build_all.sh` (section 4).
  About an hour and 60 GB of free space.
- **Linux:** run `./install-linux.sh`. It detects `apt`, `dnf` or `pacman`, lists the missing development packages and installs
  them after you agree (the package manager asks for your administrator password through `sudo`; the script never sees it).
  The Vulkan Memory Allocator is not in the official Arch packages: the script asks you to install it from the AUR yourself.
  It then sets up `work/venv`, asks for your files, and runs the build of section 6.2. Several hours; the Linux port is
  work in progress (section 6.4).

Both scripts speak English, German, Spanish and Portuguese (system language, or `BDSP_LANG=de|en|es|pt`). The texts are in
`scripts/install/lang/<code>.sh`; to add a language, copy `en.sh`, translate the values and add the code in
`scripts/install/common.sh`. If a script stops, run it again: finished stages are skipped. The sections below describe the
same steps by hand.

## 2. Common prerequisites

| Item | Needed for | Check |
|---|---|---|
| Xcode 26 or newer (in `/Applications/Xcode.app`), including Icon Composer, license accepted | macOS and iPadOS builds and native Liquid Glass icon compilation | `xcodebuild -version` |
| Command Line Tools | Compilers, `codesign`, `otool`, `iconutil` | `xcode-select -p` |
| Python 3.9 or newer | `build_all.sh`, helper scripts | `python3 --version` |
| Pillow in the selected Python environment | Deterministic original-icon conversion | `python3 -c 'from PIL import Image'` |
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
```

- `TEAM_ID`: your Apple developer team ID. Used only for the iPadOS build (`deploy_ios.sh`). It is passed
  to `xcodebuild` on the command line and is not written to the project.

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

Original icons and their language variants are generated only from user-provided
game data. Artwork and generated assets remain under ignored `work/`.
See [recomp-icons.md](recomp-icons.md) for extraction, selection, and platform styling.

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

Limits: no network. The first launch may need right-click → Open (Gatekeeper, ad hoc signature).

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

Use a Linux x86-64-v3 (AVX2) machine for the build, with a Vulkan-capable GPU and its driver.

`./install-linux.sh` (see "Quick start") installs the packages below for you after you confirm; by hand, install
them yourself. The build and check scripts (`deps.sh` and the scripts in `scripts/recomp/linux/local/`) only check and do not
install packages or download/copy third-party headers. Qt, SDL3, Vulkan, shaderc,
and FFmpeg use installed system headers/libraries through pkg-config. No copied
include-vk/ or deps/include/ fallback is used. Runtime-only packages are not enough.

| Dependency | Debian/current Ubuntu | Fedora | Arch Linux |
|---|---|---|---|
| Qt 6 Widgets development | qt6-base-dev | qt6-qtbase-devel | qt6-base |
| C/C++ tools, CMake, pkg-config | clang, build-essential, cmake, pkg-config | clang, gcc-c++, cmake, pkgconf-pkg-config | clang, base-devel, cmake, pkgconf |
| Vulkan headers and loader development | libvulkan-dev | vulkan-headers, vulkan-loader-devel | vulkan-headers, vulkan-icd-loader |
| SDL3 development | libsdl3-dev | SDL3-devel | sdl3 |
| shaderc development | libshaderc-dev | libshaderc-devel | shaderc |
| Vulkan Memory Allocator headers | libvulkan-memory-allocator-dev | VulkanMemoryAllocator-devel | vulkan-memory-allocator (AUR, not official) |
| FFmpeg development | libavcodec-dev, libavformat-dev, libavutil-dev | libavcodec-free-devel, libavformat-free-devel, libavutil-free-devel | ffmpeg |
| Icon conversion | python3-pil | python3-pillow | python-pillow |
| GNU time (`/usr/bin/time`) | time | time | time |

These are user-run commands; use your normal administrator workflow:

```sh
# Fedora
dnf install clang gcc-c++ cmake pkgconf-pkg-config qt6-qtbase-devel vulkan-headers vulkan-loader-devel SDL3-devel libshaderc-devel VulkanMemoryAllocator-devel libavcodec-free-devel libavformat-free-devel libavutil-free-devel python3-pillow time

# Debian / sufficiently recent Ubuntu
apt install clang build-essential cmake pkg-config qt6-base-dev libvulkan-dev libsdl3-dev libshaderc-dev libvulkan-memory-allocator-dev libavcodec-dev libavformat-dev libavutil-dev python3-pil time

# Arch official packages; VMA must be installed separately after reviewing its AUR package
pacman -S --needed clang base-devel cmake pkgconf qt6-base vulkan-headers vulkan-icd-loader sdl3 shaderc ffmpeg python-pillow time
```

SDL3/VMA availability depends on the Debian/Ubuntu release. Do not replace missing
packages with automatic repository downloads. On Fedora-derived distributions,
use development packages matching the FFmpeg provider already installed; do not
blindly replace or mix providers. BDSP_NO_MOVIE=1 explicitly omits movie support
and its FFmpeg requirement, but the intro path is then unsupported.

Native Wayland also needs the Qt platform plugin (Debian qt6-wayland; Fedora
qt6-qtwayland). X11 uses the xcb plugin and may need its distribution's cursor
support package. No Qt private-devel headers, PySide6, or vendored Qt is required.

Verified primary package references:
[Fedora Qt](https://packages.fedoraproject.org/pkgs/qt6-qtbase/qt6-qtbase-devel/),
[Vulkan loader](https://packages.fedoraproject.org/pkgs/vulkan-loader/vulkan-loader-devel/),
[SDL3](https://packages.fedoraproject.org/pkgs/SDL3/SDL3-devel/),
[shaderc](https://packages.fedoraproject.org/pkgs/shaderc/libshaderc-devel/),
[VMA](https://packages.fedoraproject.org/pkgs/VulkanMemoryAllocator/VulkanMemoryAllocator-devel/),
[FFmpeg](https://packages.fedoraproject.org/pkgs/ffmpeg/).
Debian lists [SDL3](https://packages.debian.org/forky/libsdl3-dev) and
[VMA](https://packages.debian.org/sid/armhf/libvulkan-memory-allocator-dev).
The Arch official package search does not list VMA; its AUR recipe is not an
official Arch binary package and is never installed by these scripts.

### 6.2 Build and run locally

The Linux build runs directly on the Linux machine, from the repository root; its scripts are in `scripts/recomp/linux/local/` (the dependency checks are in `scripts/recomp/linux/deps.sh`).

1. Install the Linux development packages above and the Python generator
   dependencies `lz4`, `capstone`, and `unicorn`.
2. Check the installed packages (no copying, downloads, or installation):
   `bash -c 'source scripts/recomp/linux/deps.sh && linux_require_runtime && linux_require_qt'`.
   Leave out `linux_require_qt` if you do not build the Qt frontend.
3. Provide the inputs `work/exefs/`, `work/romfs/`, and `work/recomp/icons/source/`. Extract your own legally
   obtained game dump on this machine with the command in section 4.1 (the
   extract stage also writes the icon source), or copy existing folders into the same layout. The Linux build
   scripts do not read keys or the `.xci`.
   Optional: `scripts/recomp/linux/local/setup.sh` compares the inputs with `work/exefs.sha256` if that file
   exists; without it, the script only prints a note. Create the manifest from the repository root with
   `sha256sum work/exefs/rtld work/exefs/main work/exefs/sdk work/exefs/subsdk0 > work/exefs.sha256`.
4. Generate and compile guest modules: `bash scripts/recomp/linux/local/build_all.sh`.
5. Build Vulkan and the in-process Qt frontend:
   `bash scripts/recomp/linux/local/vk_build.sh --qt`. Output:
   `work/recomp/bdsp_boot_vk_qt`. Icon variants are converted from extracted
   source data into Linux assets under `work/recomp/icons/` during this build.
6. Launch locally with `bash scripts/recomp/linux/local/vk_qt.sh` and the
   desktop-session environment below.

For the separate-process X11 host, build with
scripts/recomp/linux/local/vk_qt_build.sh and launch using BDSP_QT_PROCESS=1.
That fallback embeds the SDL X11 window; it needs Xwayland on a Wayland desktop.
The in-process host creates its own Vulkan surface and supports native Wayland
or X11 without embedding a foreign window.

For headless renderer checks use `bash scripts/recomp/linux/local/vk_build.sh`,
then `bash scripts/recomp/linux/local/vk_run.sh --headless --timeout 40 --screenshot-after 300`.
Captures are written to `work/recomp/shots/`; the run prints its log to the terminal. The runtime reads its
module images from `work/recomp/img_gfx` (`BDSP_IMG` changes the folder; `vk_qt.sh` uses the same folder). Create them
once, with the inputs in place: `IMG=work/recomp/img_gfx HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt bash scripts/recomp/rt-bdsp/mkimages.sh`.
The `HLE_LIST` binding matches the macOS app build (`scripts/recomp/app/recomp_build.sh`).
No display is required for headless rendering. Generated code/data remain under work/.

### 6.3 Run with a window (Wayland)

A window opens on the desktop of the Linux machine. Pass the session variables of the desktop user
with the run. Get the user ID with `id -u` on the Linux machine. Without these variables no window can open.

```sh
scripts/recomp/linux/local/vk_run.sh XDG_RUNTIME_DIR=/run/user/<UID> WAYLAND_DISPLAY=wayland-0 \
  SDL_VIDEODRIVER=wayland BDSP_NO_USER_INPUT=1 --window 1280x720 --timeout 22
```

`BDSP_NO_USER_INPUT=1` keeps the window from taking keyboard focus when it opens. Whether it also blocks
the keys below is not verified. Run without it for interactive play.

Settings for window runs only (they have no effect with `--headless`):

- Start size: `--window 1280x720` or `BDSP_WINDOW=1920x1080` (default 1280×720).
- Frame rate: `BDSP_FPS=30`, `BDSP_FPS=60` or `BDSP_FPS=120`. Pass it after the script name, for example
  `scripts/recomp/linux/local/vk_run.sh BDSP_FPS=60 ...`.
- MangoHud overlay (fps, frame time, CPU and GPU): `BDSP_MANGOHUD=1`. Needs the `mangohud` package on the
  Linux machine. It is needed only at run time, not for the build. Off by default.
- Run time: `--timeout N` in seconds (default 120).

Keys in the window:

- F1 to F4: window size 960×540, 1280×720, 1920×1080, 2560×1440 (not in full screen).
- F5, F6, F7: frame rate 30, 60, 120.
- F11: toggle full screen. Not verified.

X11 is not tested.

### 6.3a Qt menu bar and native Wayland

The in-process Qt host supplies menus, keyboard input, pause, window sizes,
frame-rate choices, and original-icon language selection. For native Wayland:

```sh
scripts/recomp/linux/local/vk_qt.sh XDG_RUNTIME_DIR=/run/user/<UID> WAYLAND_DISPLAY=wayland-0 QT_QPA_PLATFORM=wayland
```

Use QT_QPA_PLATFORM=xcb with a valid DISPLAY/XAUTHORITY for X11.
Never commit concrete session IDs or authentication paths.

### 6.4 Known limitations

- **Player character missing, vertex explosions, window fill:** fixed in the last test run (field scene with
  player character, NPCs and water; window fully filled). Not yet verified across sessions.
- **Texture outside the guest window:** the runtime logs `[vk] texture outside the guest window`
  and skips the upload (guard in `textures.c`). Effect on the picture not verified. Open.
- **Rare hangs on the loading screen:** open. Cause not known.
- FFmpeg headers/libraries now come from matching installed development packages.
  A new package-only full build must still be verified after the prerequisites are installed.
- **Frame rate:** `BDSP_FPS` caps the frame rate (30, 60, 120). Measured in a window only; not verified across sessions.
- No sound. Input state is not reported. Compute workloads are not supported.
- Windows is not supported. X11 and full screen (F11) are not tested.

Details: `docs/recomp-linux.md`.

## 7. Build stages overview

Stage order: `tools extract recomp shaders`. Run one part with `--only` or
`--from`/`--to`. Use `--dry-run` first. Each stage writes a marker `work/.stages/<stage>.json` with an input hash.
If the hash matches, the stage is skipped (`--force` rebuilds it).

| Stage | Purpose | Needed for the apps |
|---|---|---|
| `tools` | checks tools, builds `hactool` into `tools/hactool` | yes (for `extract`) |
| `extract` | decrypts the `.xci`/`.nsp` into `work/exefs`, `work/romfs`, `work/manifest.json` | yes |
| `recomp` | macOS app from the recompilation | macOS app only |
| `shaders` | converts cached game shaders for the Unity-era shader tools (needs UnityPy in `tools/pydeps`) | no: `recomp_build.sh` reads only `work/exefs` and `work/romfs` |

The Unity-era stages `il2cpp`, `masterdata`, `video` and `audio` were removed (they remain on the branch `unity`).

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
| `NVN stamp does not match` (from `prepare.sh --check`) | The copy in `work/recomp/nvn-src` is out of date. Run `scripts/recomp/rt-bdsp/nvn/prepare.sh`. Normal builds do this automatically. |
| Build uses old NVN code | `NVN_KEEP=1` is set, so `prepare.sh` was skipped. Unset it or run `prepare.sh`. |
| `marker matches` … `skipped` / stage skipped | Inputs did not change. Use `--force` to rebuild. |
| `work/exefs/main missing` (exit 10) | Run stage `extract` first. |
| Not enough disk space (exit 8) | Free space or lower the requirement with `--min-free-gb N`. The macOS build needs tens of GB. |
| Compile fails (exit 4), memory error | Use `--recomp-jobs 2`. Check `work/logs/recomp-compile.log`. |
| `No connected, unlocked iPad found.` | Connect the iPad, unlock it, and trust the Mac. Check with `xcrun devicectl list devices`. |
| Build fails in `xcodebuild` (signing) | Read `work/builds/ios-recomp-xcodebuild.log`. Set `TEAM_ID` and sign in with your account in Xcode. |
| macOS app blocked on first start | Right-click the app, then Open. |

## 9. More documentation

- `docs/architecture.md`: how the recompilation works.
- `docs/development.md`: working rules, commands, tests, what lives in `work/`.
- `docs/recomp-macapp.md`: macOS app, data locations, save import, measurements.
- `docs/recomp-ios.md`: iPadOS build steps, memory model and entitlements.
- `docs/recomp-linux.md`: Linux build host and Vulkan backend.
- `docs/rendering.md`: Metal renderer debugging, performance, frame rate, water.
- `docs/shaders.md`: shader translator and harness.
- `docs/saves.md`: save format, validator, locations.
