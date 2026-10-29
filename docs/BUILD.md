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
  `work/venv` (Pillow, LZ4, Unicorn native assets). Then you drag your `.xci`, optionally the update `.nsp`, and your `prod.keys`
  into the window, and it runs the stages `tools`, `extract` and `recomp` of `scripts/build_all.sh` (section 4).
  Plan for at least 40 GB of free space; a measured run on a prepared 8-thread Mac took about 8 minutes (section 4.2).
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
| Unicorn 2.1.4 C headers/library in `tools/pydeps` or `BDSP_UNICORN_ROOT` | Code generator (`recomp` stage) | `ls tools/pydeps` |
| `git`, `make`, `cc` | Stage `tools` (builds `hactool`) | `command -v git make cc` |

Install the Homebrew packages and the Python packages:

```sh
brew install llvm sdl3 ffmpeg pkg-config
python3 -m pip install --target tools/pydeps unicorn==2.1.4
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
The base source may instead be `--base-nsp <base.nsp>` or `--base-nca-dir <folder>`.
Use exactly one base source. The NCA folder must contain the original `.nca` files
and, when required, its `.tik` tickets. Extraction identifies the base Program NCA
and applies the optional update to that base. The cache records content hashes of
the selected sources; editing a file without changing its size still invalidates it.

The development GUI now sends these three source forms through the same extraction
stage, then builds the native macOS or Linux desktop target and installs it. On macOS,
the default destination is `/Applications/BDSP.app`; the installer updates only
an app identified by its own receipt and unchanged executable. A different app
at that path is left untouched and reported as a conflict. On Linux, the package lives under
`$XDG_DATA_HOME/strahlender-xnu/app` (or `~/.local/share/strahlender-xnu/app`),
with a launcher at `~/.local/bin/strahlender-xnu` and a desktop entry under the
user's `applications/` directory. Saves live beside the Linux package in `saves/`,
outside its replaceable `app/` folder. Runtime libraries still come from the
documented system packages. The GUI connection is under development and has only
been exercised with synthetic installation fixtures, not an end-to-end game build.

### 4.2 Build the app

```sh
scripts/build_all.sh --dry-run --only recomp --target macos   # plan only, changes nothing
scripts/build_all.sh --only recomp --target macos
```

Result: `work/builds/macos-recomp/BDSP.app` (arm64, Metal, ad hoc signed).

C generation uses the native C17 tool in `scripts/recomp/native-generator/`.
It chooses a thread count from the host CPU/RAM budget. Modules run sequentially;
classification, independent large scans and emission use bounded pthread/Win32
workers. Stateful Unicorn jump-table discovery stays in address order.
`BDSP_GEN_JOBS=1` selects serial C execution; `BDSP_GEN_JOBS=N` or
`bash scripts/recomp/codegen.sh gen ... --jobs N` overrides the generator threads
independently of `--recomp-jobs` (Clang). Scheduling does not change file contents.
Unicorn is called through its existing C API; the generator uses neither Capstone nor
Unicorn's Python bindings, and new installer runtimes exclude them. Python remains for build orchestration and asset tools such as Pillow,
LZ4 and UnityPy. See [the native generator README](../scripts/recomp/native-generator/README.md).

Original icons and their language variants are generated only from user-provided
game data. Artwork and generated assets remain under ignored `work/`.
See [recomp-icons.md](recomp-icons.md) for extraction, selection, and platform styling.

On 2026-10-23, a clean GitHub clone plus the current local source changes took **7 min 42 s**
from the start of `scripts/build_all.sh --only tools,extract,recomp --target macos` to a signed
`BDSP.app` on an 8-thread/16-GiB Apple Silicon Mac. This used a base XCI without an update NSP,
8 parallel Clang jobs, and fresh project `work/` and app-data directories. The GitHub clone took
1 s; creating a Python venv and installing four packages took another 3 s with locally cached
package downloads. Xcode 27.1 and the Homebrew libraries were already installed. The measured
build stages were: hactool setup 5 s, XCI extraction 23 s, C generation 68 s, C compilation
about 5 min 25 s (312 s reported inside the compile script), then module images, runtime/Metal,
app assembly, signing and RomFS setup. The result was a 361-MiB arm64 app whose signature passed
`codesign --verify --deep --strict`. Historical slower runs under load are in
`docs/recomp-macapp.md`. Later builds reuse the markers and are much faster (section 7).

Useful options:

| Option | Meaning |
|---|---|
| `--recomp-jobs N` | override the CPU/RAM-based number of parallel compiler jobs |
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

The log of each `run` goes to `work/builds/logs/ipad-recomp-<time>.log`. The build log goes to
`work/builds/logs/ios-recomp-xcodebuild.log`.

### 5.3 Signing

Signing is your job. Select your team and provisioning in Xcode if the build fails. The script passes
`TEAM_ID` and `-allowProvisioningUpdates` to `xcodebuild`. Do not change `project.pbxproj` in the
repository to set the team.

## 6. Linux with Vulkan (work in progress)

Work in progress. Not playable yet. See section 6.4 for the known limits.

### 6.1 Requirements

Use a Linux x86-64 machine with a Vulkan-capable GPU and its driver. AVX2 is optional.
Local game builds default to `BDSP_CPU_TARGET=native`: the compiler enables the build CPU's
supported instructions, including AVX/AVX2 where available. An older CPU builds without
unsupported extensions. This does not guarantee compatibility with a different, older CPU.
Set `BDSP_CPU_TARGET=portable` for the x86-64 baseline (AArch64: ARMv8-A).
Changing CPU profiles or moving native builds between hosts invalidates generated-code and
Vulkan object caches. Distributed installer binaries keep their portable compiler defaults.

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

1. Install the Linux development packages above, asset dependency `lz4` and
   `unicorn==2.1.4` (provides the native C headers/library; no Python code generation).
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

On 2026-10-23, a fresh Fedora Linux x86_64 clone was built with only a base XCI
and update NSP supplied as game files, using the installed Fedora development
packages. `eh_gen` took 52.9 s; 12 parallel Clang processes compiled all
2,369 generated C files in 351.3 s (57 with `-O0`, 2,312 with `-O1`). The
initial guided run exposed macOS-only includes and a QoS call in the runtime;
after platform guards were added, `install-linux.sh` completed and the Qt/Vulkan
binary ran for 10 seconds on native Wayland, presenting 306 frames. A warm
rerun of the guided script regenerated C and linked the guest library in 68 s;
no source objects needed recompilation. The executable dynamically uses the
installed system libraries. More detail: [clang-optimierungsstufen.md](../todo/clang-optimierungsstufen.md).

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
- FFmpeg headers/libraries come from matching installed development packages;
  the Fedora Linux package-only build and short native Wayland run passed on 2026-10-23.
- **Frame rate:** `BDSP_FPS` caps the frame rate (30, 60, 120). Measured in a window only; not verified across sessions.
- SDL audio output now shares its bounded queue/lifecycle implementation with Windows;
  actual device playback is not accepted yet. Input state is not reported. Compute workloads are not supported.
- Windows is not supported. X11 and full screen (F11) are not tested.

Details: `docs/recomp-linux.md`.

## Windows preparation (not yet a playable release)

The minimum target is **Windows 10 22H2 amd64 (build 19045)** and Windows 11.
ARM64 has a separate host/target/ABI profile, not an acceptance claim. The first
playable Windows build must use the existing graphical Rust/iced installer;
the developer CLI below is not a substitute for that requirement.

`installer/assets/windows-dependencies.json` is the shared requirements contract.
It specifies LLVM-MinGW **UCRT**, portable SIMD C, amd64 baseline/CX16, an ARM64
baseline, the OS minimum and release blockers. It references the existing private
CPython 3.13.15 and Unicorn 2.1.4 wheel locks rather than introducing system Python.
Windows inspection never reads `/etc/os-release`, offers Unix package managers,
or silently starts a Linux build. The GUI shows pending qualification instead of
an actionable download/install button for unqualified packages.

| Requirement | Qualification still needed |
|---|---|
| Portable LLVM-MinGW UCRT: Clang, LLD, PE tools, headers/import libraries, compiler-rt, winpthreads | 20261020 archive/hash pinned and privately exercised; full host-tool DLL inventory, notices and Windows 10 execution still needed |
| Private CPython and Unicorn 2.1.4 native headers/library | Execute the existing pinned amd64 runtime/generator on Windows 10; native ARM64 Unicorn is not locked |
| Microsoft VC runtime for the locked Unicorn amd64 wheel | App-local `vcruntime140.dll` is required by this build-time DLL; qualify an authorized, versioned redistribution source, not System32 |
| SDL3 with HIDAPI Nintendo/Sony and Xbox backends | Matching UCRT headers/import library/DLL closure and real USB/Bluetooth acceptance |
| Vulkan-Headers, VMA and shaderc | Separate pins/source notices, toolchain-compatible libraries and required GPU feature checks |
| FFmpeg avcodec/avformat/avutil | Configure flags, enabled codecs, matching sources/redistribution obligations and recursive DLL inventory |
| Native hactool and asset helpers | Version/hash, native Windows extraction and dependency/license inventory |
| Existing graphical installer release | Built by release maintainers with Rust/Cargo >= 1.88; private runtime included, no Rust/SDK required by users |

There are **no GUI-enabled Windows dependency downloads**: LLVM-MinGW's archive
and hash are pinned, but its distribution inventory and the other native development
packages are not qualified. Consented, hash-verified private LLVM-MinGW/Unicorn
downloads were used for developer probes. Preparation must eventually use approved,
hash-verified per-user tools or the same verified offline cache, with no global
PATH changes or administrator requirement. Git, gh, Bash/MSYS2, Visual Studio,
CMake, Make and Ninja are not intended end-user build prerequisites.

The direct developer pipeline in `scripts/recomp/portable_build.py` now provides
native generator invocation, optional `subsdk1` entries, portable Vulkan source
overlay, two-pass images with explicit NVN HLE binding, RAM-bounded compilation,
hot-O2/O0-outlier selection and explicit-inventory LLD linking/package helpers.
Windows compiler processes enter an owned Job Object while suspended, so cancellation
also terminates descendants. Response files handle Unicode, spaces and quoting.
Caches separate host, target, CRT/SIMD, compiler bytes/triple, headers and flags.
PE normal/delay imports are resolved only from explicit candidate DLLs; system DLLs
and the GPU-vendor Vulkan loader are not copied. The package helper excludes
build tools/Python/Unicorn and requires notices, but is not a legal audit or a
complete game-data installer.

Read-only developer inspection, from PowerShell in the checkout:

```powershell
python -B scripts\recomp\portable_build.py inspect --target x86_64
python -B scripts\install\driver.py preflight --root . --work work --tools-dir tools --target windows
```

The second command intentionally reports the current release blockers and fails.
With an explicitly selected LLVM-MinGW UCRT compiler and private Unicorn package,
developers can run `generator`, `generate`, `images` and `compile` using explicit
`--host-cc`/`--cc` paths and `--unicorn-root`; these stages are not an end-to-end
game build and must not be advertised as one.

Verified on the current Windows host with privately prepared LLVM-MinGW UCRT
20261020 and Unicorn 2.1.4: native deterministic generation/image relocations,
amd64 generated-C compilation, moved-generator DLL closure without developer PATH,
paired Windows setjmp/longjmp execution, Job Object descendant cancellation and
the fake-device SDL lifecycle probe (also checked with the existing MSVC).
Generated C and the Win32 host/image-loader/entrypoint sources cross-compile
separately for ARM64; this does not establish ARM64 execution.

The active entrypoint reserves a Win32 guest window. Its data pages commit on
access; explicit commit, read-only/no-access protection, decommit/zero-on-reuse,
monotonic time, memory reporting and Unicode/binary image loading have isolated
native coverage. Guard, write-protected and non-executable pages still fault.
The loader commits file-I/O destinations explicitly rather than relying on
user-mode access faults. This is not the complete runtime or GC port.

The active Win32 kernel uses the monotonic clock, stack/working-set queries and
cryptographic system randomness. Its native probe emits a synthetic ARM64
function through the real C generator and runs four workers through 32
stop-the-world cycles (128 suspends/resumes per build) at `-O1`, `-O2` and `-O3`.
It checks all exported GPRs, 32 SIMD register pairs loaded from guest stacks,
stack roots, changing register-only root candidates, frozen repeat snapshots,
idempotent pause/resume and thread completion. A reproduced defect in context
export is fixed: NZCV, FPCR and FPSR now come from `Cpu`, rather than zero.
This tests the SVC/context and root-storage boundary, not a collecting guest GC.
`Cpu` fields are ordinary C storage; arbitrary optimized host temporaries are
not reconstructed from the captured Windows `CONTEXT` or host stacks. The
reported guest PC remains the saved guest LR, not a translated host instruction
address. No whole-game GC/root completeness or ARM64 execution is claimed.
An additional compiler inspection of an emitted pure EOR/SUB/CBNZ loop confirms
the limitation: at `-O1`, Clang 23.1.4 keeps x19 in a host GPR and writes it back
only after the loop; at `-O2`, the loop also uses host SIMD temporaries.
The passing LDAR-based probe therefore does not establish consistent guest
register snapshots inside arbitrary optimized arithmetic loops. This is
concrete deferred-writeback evidence, not proof of a collected live object.

The native `test_optimized_sole_root_is_missing_from_guest_context` now also
reproduces a live-root omission during real Windows suspension at `-O1`/`-O2`,
not just in assembly listings. Its emitted guest function loads an encoded
pointer to a committed 16-byte guest object, erases the source, reveals/hides
the pointer in a finite arithmetic loop, and uses it after resumption.
Three workers per optimization must each yield eight captured host-context
roots while neither `Cpu`, the exported SVC context nor the worker guest stack
contains any pointer into that object. Sampling is bounded to 256 attempts per
worker with 1/2/3 ms delays. Context and stack positive controls include an
interior pointer. This is an executable characterization of the still-unfixed
root-export gap, not an actual collector/freeing test: no guest Boehm scanner
is available in the source-only synthetic fixture. Host stack roots are not
exported either; this fixture demonstrates the host-context case.

A correct production remedy cannot simply overwrite guest context registers
with unrelated host register values. Publishing additional conservative host
root ranges requires the actual guest collector's scanning/marking contract;
cooperative stopping or compiler root maps require their own contracts and
coverage. None is implemented or qualified by this fixture.
Checkout integration audit found no registered GC push/mark callback.
`hle_register`, image forced-import slots and generator `--hle` are generic
dispatch/replacement mechanisms, not collector contracts. Upstream
`rt_unwind_point` abandons frames for reboot via longjmp; it cannot park and
resume a collecting thread. A collector bridge requires an identified,
version-bound guest hook/signature, verified scan-range and stop/mark lifetime
rules, and proof the hook is reached. None is available in the permitted
source-only fixture; alternatively, a new resumable cooperative-stop contract
must be explicitly chosen rather than inferred from the reboot mechanism.

The later authorized local artifact audit also checked dynamic symbols and
generated symbol inventories for the actual four-module MVP, bound to their
NSO build IDs. No `GC_`, `il2cpp_gc`, `GarbageCollect` or `Boehm` entry was
identified; generated metadata also provides no named collector/root callback.
This does not prove that the private binary lacks a collector: internal/stripped
functions need not have exported names. The generated SDK contains SVC0x32/0x33
sites and public thread-context/suspend wrappers, not a verified collector
push/mark ABI. Actual collector entry address/signature, root-range semantics,
scan phase/lifetime, locks and native-frame reentrancy remain unidentified.
No production root-preservation patch was justified or applied.

The complete **non-graphics diagnostic** runtime now compiles and links directly
with LLVM-MinGW on amd64 and cross-links for ARM64. A synthetic guest-table
fixture boots the active loader/dispatcher/kernel from a moved Unicode package
without developer PATH, then tests a real unhandled Windows exception and its
original exit status. This is not a Vulkan game link or a game run. The iOS-only
snapshot publisher is not compiled into this Windows diagnostic.

The Windows `wmain` converts arguments and inherited `BDSP_*` settings strictly
to UTF-8. Read-only defaults (`img/`, `romfs/`, `exefs/main.npdm`) resolve beside
the executable, independently of the starting directory. Saves default to
`%APPDATA%\StrahlenderXnu\save` (Windows RoamingAppData known folder).
Cache, shots, logs and mods stay under `%LOCALAPPDATA%\StrahlenderXnu`.
An explicit `BDSP_DATA_DIR` keeps all writable defaults, including saves,
under that root for portable/isolated runs; explicit `BDSP_SAVE` wins.
Existing LocalAppData saves are not read, moved or merged automatically; select
that old directory with `BDSP_SAVE` to continue an existing save, or migrate it
manually only while the game is closed. Runtime abort messages and unhandled host exception code/PC/SP are
appended to `logs/crash.log` through a pre-opened native handle; complete
symbolized crash reporting remains open. Shared filesystem/mod logic remains common: only the
Windows file boundary converts UTF-8 to UTF-16 and supplies binary, 64-bit
positional I/O. Native probes include offsets above 4 GiB, unchanged descriptor
positions, fresh guest-page read destinations and atomic backup replacement.
The Vulkan pipeline/SPIR-V cache now uses the common `BDSP_CACHE_DIR` helper;
the full graphics build still needs qualified dependencies.

Linux and Windows share the SDL3 PCM16 output backend and the existing serialized
output lifecycle; macOS keeps AudioQueue. Its input queue is limited to 200 ms.
Stub-device probes cover stop, application suspension/resume, bounded writes,
failed enqueue/open and balanced subsystem lifetime, not audible playback.
The specifically approved SDL 3.4.18 source and maintainer-only CMake 4.1.2 archives
were privately downloaded and hash-verified. The offline `sdl` recipe now builds
separate amd64 and ARM64 UCRT development bundles, including headers, import library,
DLL closure checks, collected notices, generated configuration and per-file SHA256
receipts. C/C++/RC compilers are target-explicit; typed CMake paths prevent Windows
backslash escaping failures. No CMake/Ninja requirement was added to end-user builds.
Neither bundle is qualified for public installation; further downloads still need consent.

Maintainers can reproduce the recipe using those already approved private archives
and an existing Ninja executable; it performs no downloads and refuses existing outputs:

```powershell
$tools = Join-Path (Get-Location) 'work\windows-tools'
$llvm = Join-Path $tools 'llvm\llvm-mingw-20261020-ucrt-x86_64'
python scripts\recomp\portable_build.py sdl --host x86_64 --target x86_64 `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe" `
  --cmake "$tools\cmake\cmake-4.1.2-windows-x86_64\bin\cmake.exe" `
  --ninja (Get-Command ninja -ErrorAction Stop).Source `
  --sdl-archive "$tools\archives\SDL3-3.4.18.tar.gz" `
  --sdl-prefix "$tools\SDL3-3.4.18-x86_64"
```

For the separate ARM64 bundle keep `--host x86_64`, choose `--target aarch64`,
the `aarch64-w64-mingw32-clang.exe` compiler and a new ARM64 prefix. This is a
cross-build, not native ARM64 execution. Real amd64 SDL integration now exercises
the production UTF-8 entrypoint, virtual-controller hotplug/buttons/sticks/focus,
paired/single initialization and worker-thread dummy audio without developer PATH.
These tests do not validate physical controllers, audible output or Vulkan.
Set `BDSP_WINDOWS_SDL_ROOT` and optionally `BDSP_WINDOWS_SDL_ARM64_ROOT` alongside
the existing native-test compiler variables to enable these opt-in checks.

The eight privately approved source archives are pinned by revision, measured
SHA256 and size in `installer/assets/windows-sources.json`. The offline Vulkan
recipe builds Vulkan-Headers/VMA/shaderc with the existing maintainer CMake/Ninja
and explicit target C/C++ tools. Shaderc's and SPIRV-Tools' VCS version probes are
replaced with the locked revisions in temporary sources, with patch hashes recorded.
There is no Git invocation or dependency download during preparation.

FFmpeg is **not built from source**. After separate binary-download consent,
the BtbN `n8.1.3-24-g92611900bb` amd64 LGPL-shared archive was hash-verified.
Unlike a CLI-only winget installation, this actual archive includes the matching
headers, GNU/MSVC import libraries and DLLs. Its offline import retains development
files and documentation but only the measured runtime closure: `avcodec-62.dll`,
`avformat-62.dll`, `avutil-60.dll` and `swresample-6.dll`; no `ffmpeg.exe` is needed
to build or play the game. Keep the exact archive cached: this daily producer
release has limited retention, and the recipe never substitutes `latest`.

Maintainer preparation, using only existing approved archives and tools:

```powershell
python scripts\recomp\dependency_build.py vulkan `
  --archives "$tools\archives" --prefix "$tools\vulkan-x86_64" `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe" `
  --cmake "$tools\cmake\cmake-4.1.2-windows-x86_64\bin\cmake.exe" `
  --ninja (Get-Command ninja -ErrorAction Stop).Source --jobs 4
python scripts\recomp\dependency_build.py ffmpeg --target x86_64 `
  --archive "$tools\archives\ffmpeg-n8.1.3-24-g92611900bb-win64-lgpl-shared-8.1.zip" `
  --prefix "$tools\ffmpeg-x86_64"
python scripts\recomp\portable_build.py runtime --backend vulkan --frontend sdl `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe" `
  --sdl-prefix "$tools\SDL3-3.4.18-x86_64" `
  --vulkan-prefix "$tools\vulkan-x86_64" --ffmpeg-prefix "$tools\ffmpeg-x86_64"
```

The shared compile/cache queue now selects C17 or target C++17 per source,
includes both driver identities and source-specific flags, and prioritizes overlay
headers. The complete active amd64 Vulkan/VMA/SDL/movie runtime compiles and links
against synthetic guest tables, then boots and reports host crashes from a moved
Unicode package without developer PATH. This is **not gameplay or GPU acceptance**.
Actual shaderc generates SPIR-V and returns diagnostics for invalid GLSL. Actual
FFmpeg headers match the loaded C ABI; VP8 is encoded, muxed/demuxed through a
Unicode WebM path and decoded, and VP8/VP9/H264 decoders are present.

Set `BDSP_WINDOWS_VULKAN_ROOT` and `BDSP_WINDOWS_FFMPEG_ROOT` alongside the existing
native/SDL variables to enable these probes. Optional
`BDSP_WINDOWS_DEPENDENCY_REPORT` records the exact configure flags, reported license,
compiler, bundle/probe hashes and runtime closure as JSON. Run
`python -m unittest scripts.tests.test_dependency_build scripts.tests.test_windows_native_generator scripts.tests.test_windows_build scripts.tests.test_recomp_parallel_jobs`.
The observed FFmpeg license is **LGPL version 3 or later**, with no enabled
GPL/nonfree configure switch. This is not a redistribution approval: exact
corresponding FFmpeg/transitive sources, producer recipe identity, notices, CPU
baseline and Windows 10 execution still need qualification. The previously approved
FFmpeg 8.0.1 source does not correspond to this 8.1 binary. No prebuilt ARM64 FFmpeg
is locked; no make download, source build or global winget/PATH change is required.

**Private local installer pipeline (experimental, not release acceptance).** The
GUI backend now connects selected XCI/NSP/NCA inputs to shell-free extraction,
native C generation, full Vulkan/movie linking, data/DLL packaging and per-user
installation. Maintainer preparation of hactool uses the already approved source
and bundled mbedTLS crypto directly, without Make:

```powershell
python scripts\recomp\dependency_build.py hactool --target x86_64 `
  --archives "$tools\archives" --prefix "$tools\hactool-x86_64" `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe"
python -m scripts.install.windows_pipeline `
  --output "$tools\private-catalog.json" `
  --cc "$llvm\bin\x86_64-w64-mingw32-clang.exe" `
  --generator "work\native-generator\windows-x86_64\bdsp_codegen.exe" `
  --sdl "$tools\SDL3-3.4.18-x86_64" --vulkan "$tools\vulkan-x86_64" `
  --ffmpeg "$tools\ffmpeg-x86_64" --hactool "$tools\hactool-x86_64"
$env:BDSP_INSTALLER_DEV_CHECKOUT = "1"
$env:BDSP_WINDOWS_PRIVATE_CATALOG = (Resolve-Path "$tools\private-catalog.json").Path
```

The two explicit environment settings enable **only a debug installer using this
existing checkout**; release builds still refuse unqualified preparation. Catalog
registration never downloads anything or replaces an existing catalog. It records
the whole private toolchain and generator DLL closure, plus verified per-target
dependency inventories. Missing or changed inputs fail rather than falling back to
system tools. The production installer still needs qualified, bundled private
Python/tools; the debug build may use an existing developer Python.

Container copying validates bounds, Windows-safe filenames, HFS0 hashes and the
XCI root header. hactool receives only explicit selected key files, with default
key lookup isolated to a fresh temporary home; raw extraction output is never sent
to the GUI. The existing metadata/content cache and Control/Meta title-family
selection are shared with other tooling. File copying, verified inventories,
rollback-safe Linux/Windows publication and generator progress parsing are common
installer helpers, not separate platform implementations.
Generation and image publication are transactional too: removed optional modules
cannot leave stale C chunks/images, and failed rebuilds retain the prior inventory.
Shared copies also reject existing destination links/reparse points and nested
source/destination trees; unreadable subtrees fail rather than disappearing from
the copy or inventory. Bounded process capture cancels the owned tool on overflow
or progress-callback failure instead of waiting indefinitely for it.

Packages contain `BDSP.exe`, its measured runtime DLL closure, `img`, `romfs`,
`exefs/main.npdm` and notices, without generator/Python/Unicorn/build tools. The
default install is `%LOCALAPPDATA%\StrahlenderXnu\app`; writable saves/cache remain
outside it. Replacement refuses modified/unowned package files and preserves old
files if rollback fails. Clean rebuild preserves previous target outputs.
Mod packaging is explicitly rejected for now rather than silently ignored.

Native synthetic probes exercise the real generator/compiler/image/runtime/link/
package/install chain **after substituting synthetic extraction**, then relocate
the installation and reach its deliberately missing game-entry diagnostic without
developer PATH. A separate isolated-Python JSONL probe invokes the actual native
extractor on an invalid synthetic NCA and verifies failure/redaction. These do not
prove genuine NCA extraction, GUI-click-through with real game data or gameplay.
Use `BDSP_WINDOWS_HACTOOL_ROOT` and `BDSP_WINDOWS_PRIVATE_CATALOG` for these probes;
shared regression suites include the Rust tests of `installer/extract`, `test_windows_pipeline`, `test_installer_filesystem` and `test_installer_driver`.

NVN uses the same HLE lookup and input logic on all platforms, with a small COFF
linker-boundary alternative to Mach-O/ELF. Optimized multi-object HLE registration,
UTF-8 committed-text routing and keyboard focus reset have native probes; the same
glue cross-links against the ARM64 SDL bundle without execution. Focus loss clears
both the shared keyboard source and its accumulated key mask, preventing stuck keys.
Full IME composition and game-facing text acceptance remain open.

The installer compiles and its targeted GUI/prerequisite/backend tests run with
privately prepared Rust/Cargo 1.88.0 and Cargo.lock-pinned crates. Existing Visual
Studio was used only to link this maintainer build, not made an end-user requirement.
The real Windows GUI also renders through tiny-skia without Vulkan in English and
German. Its pending-build view groups tools with readable spacing; technical
output remains available in the expandable log.
The pending Windows preparation page now also exposes its dependency/qualification
details in a spaced, scrollable area; it offers no download/install action.
Packaged Windows Python is located beside the executable under
`resources/runtime/<host>/python/python.exe`. Windows runtime assembly records a
full file hash inventory, including extensions and notices; backend discovery
rejects changed, extra, missing or linked files. This is integrity checking inside
the trusted release bundle, not a substitute for authenticating its download.

Maintainers can inspect the closed public gate completely offline:
`python installer\scripts\release.py windows-readiness`.
The command emits JSON and exits **1** because Windows packaging/signing is not
enabled. Release collection and publication explicitly reject
`installer-windows-*` assets before staging or external commands; they must never
silently promote or discard an unqualified private package. Exact FFmpeg matching
sources/transitive notices/producer recipe, authorized VC-runtime redistribution
and complete toolchain notices remain blockers independently of native probes.
The local notice audit found the target-specific MinGW `COPYING*` files under
`<LLVM>/<target>-w64-mingw32/share/mingw32`; private game packages now preserve all
five files, including runtime and winpthreads notices. The complete compiler
archive also contains separately licensed host tools (including Make/BusyBox,
Python, gendef and widl); its root LLVM license is not an audit of those tools.
The offline evidence audit checked all **30** compiler archive notice files against
their extracted counterparts and preserved copies in
`work\windows-tools\license-audit\llvm-notices`. BusyBox includes GPLv2;
Make/gendef include GPLv3; widl has mixed notices; embedded Python/libffi have
their own terms. Matching copyleft host-tool source/build evidence is not supplied
locally. Do not equate including these tools in the maintainer archive with needing
them for the direct end-user build, or with an approved redistribution.

The shared notice collector now retains complete `LICENSES` directories and
authorship files, without copying unrelated source trees. hactool additionally
retains its unmodified cJSON, Unicode ConvertUTF and LZ4 source notice carriers;
its root ISC notice and mbedTLS license alone were incomplete. Separate
`*-license-audit` private bundles preserve the original binaries and receipts,
adding 13 Vulkan notices, one SDL authorship file per architecture, five hactool
notice carriers, and two generic FFmpeg license texts. Their receipts remain
`qualified:false`; the original bundles/catalog were not changed.
`work\windows-tools\license-audit\audit.json` records hashes and evidence gaps;
`private-catalog-license-audit.json` selects the new amd64 variants for private
debug GUI tests only.

Reproduce the source-notice repair **offline into a fresh output directory**:

```powershell
python scripts\recomp\dependency_build.py notices --bundle work\windows-tools\vulkan-x86_64 --archives work\windows-tools\archives --prefix work\windows-tools\vulkan-x86_64-new-notices
```

The same command supports pinned source-built SDL/hactool bundles; use
`--target aarch64` for the ARM64 SDL bundle. It rejects changed/untracked inputs,
unknown source provenance, missing or mismatched archives and existing outputs.
To import the approved FFmpeg binary into a fresh bundle, supplying `--archives`
also copies the full generic GPLv3/LGPLv3 texts from the pinned **8.0.1** source
archive; it neither builds FFmpeg nor identifies that archive as the **8.1**
binary's corresponding source:

```powershell
python scripts\recomp\dependency_build.py ffmpeg --archive work\windows-tools\archives\ffmpeg-n8.1.3-24-g92611900bb-win64-lgpl-shared-8.1.zip --archives work\windows-tools\archives --prefix work\windows-tools\ffmpeg-x86_64-new-notices
```

Matching FFmpeg/transitive sources, producer recipes and component applicability
remain unqualified. The local Unicorn wheel has **no full license/notice files**:
its metadata says BSD while its embedded README says GPLv2. Native-engine license
and source obligations are not removed by stripping Python bindings. The locked
installer CPython **3.13.15** archive/runtime is not present locally; the compiler's
Python **3.14** notices do not qualify it. Those are missing evidence/artifacts,
not findings that a public distribution has violated a license. No public
Windows release has been qualified.

The real-SDL probe additionally attaches virtual left/right single Joy-Cons with
explicit SDL types and horizontal mappings matching the pinned SDL mini-mode
contract. It exercises each face button, Start, stick click, SL/SR shoulders,
left-stick directions, focus clearing/recovery, detach and reconnect. It does not
emulate Bluetooth/HID reports or prove physical pairing.

Controller configuration belongs to the **game runtime, never the installer**:
there are no controller controls, preferences or build parameters in the installer,
and packages do not contain a selected controller mode. On Windows the runtime
reads `%LOCALAPPDATA%\StrahlenderXnu\controller-mode.txt` (or
`BDSP_CONTROLLER_CONFIG`) containing `pair` or `single`; absence defaults to pair.
`BDSP_JOYCONS=pair|single` explicitly overrides the file. Invalid/unreadable
configuration is diagnosed, not silently replaced. A runtime settings UI is not
implemented yet.
**Shared game frontend:** Qt was selected for Linux with Windows portability in
mind; simplifying the end-user build did not authorize replacing it with a new
SDL application UI. The existing in-process `app/linux/qt_ui.cpp` is now the shared
source for both platforms (its directory name is historical). The separate
`bdsp_qt_host.cpp`/CMake X11 embedding fallback remains Linux-only. AppKit is
unchanged. SDL remains the controller/audio layer; the iced installer is separate.
No new SDL settings menu was added.

The Qt host no longer uses `/proc`/`execv` for restart: the runtime hands it the
original UTF-8 argument vector, and Qt launches the same application with those
arguments/current directory, reporting launch failures before exiting the old
process. Cache/log actions use initialized runtime user paths. Qt's platform
plugin supplies Vulkan surface extensions rather than a hardcoded platform list.
Linux Xauthority/KDE-capture/MangoHud initialization stays Linux-specific.
Windows gamepad initialization, 8 ms polling, focus and shutdown use the existing
SDL main-thread functions; no second gamepad thread or native HID backend is added.

Direct `runtime`/`link` CLI stages select `--frontend qt` by default, requiring an
explicit `--qt-prefix`. The old SDL frontend is available explicitly as
`--frontend sdl` for synthetic diagnostics; `--backend none` is non-graphical.
Qt/SDL object inventories are separated. A Qt bundle must have the existing exact
`build.json` inventory/profile and an additional `qt` record declaring exact
`version` (`6.x.y`), `linkage:"shared"`, `cxx_runtime:"libc++"`,
`minimum_windows_build` at most 19045 and `cxx_compiler_sha256` matching the actual
target LLVM-MinGW C++ driver. Required files include Core/Gui/Widgets headers,
MinGW import libraries/DLLs, `plugins/platforms/qwindows.dll` and notices.
Architecture and transitive plugin/DLL closure are checked; a random MSVC/GCC
Qt SDK is not ABI-compatible evidence.

Private catalog creation optionally accepts `--qt <bundle>` and then uses that
same host for compile/link, packages plugin dependencies, an app-relative
`qt.conf`, `plugins/platforms/qwindows.dll`, menu translations and Qt notices.
Old catalogs are explicitly diagnostic SDL catalogs, not Qt acceptance. Missing
Qt fails before runtime compilation/source-overlay work; no automatic download,
system-Qt lookup or end-user CMake is introduced.
**The local MVP now uses the specifically approved existing archives** in the
isolated `work/windows-tools/qt-mvp-6.12.0` tree, without replacing the existing
compiler or installing a package manager. The actual shared Qt Windows runtime
compiled successfully (44 objects) with Qt 6.12.0 and its paired Clang 22.1.7.
The real user-selected game/update also linked and launched through Qt's Windows
plugin and Vulkan on an RTX 2080 Ti; the opening scene now renders Rowan.
This is not whole-game or Windows 10 acceptance; Linux has not been
revalidated. Redistribution review remains separate.

The Windows Qt game menu now offers **Controllers > Paired Joy-Cons / Individual
Joy-Cons (mini mode)**. It is not an installer option. Selection reinitializes only
the owned SDL gamepad subsystem on the Qt/SDL main thread, clears controller
state, reopens devices through the normal hotplug path and preserves focus and
audio ownership. This intentionally causes a brief interruption of controller
input, not a lossless device switch. Another SDL joystick owner blocks the
startup-only hint change; the old mode is reacquired without changing hints.
Hint/init failures attempt rollback; failed rollback disables mode actions while
keyboard input remains available. Disconnected/open-failed devices are retried
by normal polling rather than silently treated as connected.

Successful selection atomically writes `pair` or `single` to
`%LOCALAPPDATA%\StrahlenderXnu\controller-mode.txt`, flushing before replacement.
Write/publish errors restore the previous runtime mode where possible and show
a Qt error. An explicit `BDSP_JOYCONS` or nonstandard `BDSP_CONTROLLER_CONFIG`
override disables the menu actions instead of writing preferences elsewhere.
The isolated currently running MVP therefore stays unchanged. Linux's existing
poller is unchanged; runtime switching is enabled only on Windows.
Mini-mode stick-click layers retain stick-to-D-pad hysteresis, Plus-to-Minus,
L/R-to-ZL/ZR and release/centering suppression. All pads still merge into player1.
The menu's Mini Controls explanation is localized with the existing EN/DE/ES/PT
tables. Synthetic rollback tests and real SDL virtual Joy-Con tests are not
physical USB/Bluetooth/controller acceptance.

Non-invasive follow-up of the original live MVP confirmed `Responding=True`,
~60fps at145s. Physical keyboard interaction in that live game remains unconfirmed; no input,
focus or save contents were touched. RSS was6544.54MiB, private commit2356.12MiB,
plus fixed6400MiB section commitment. Their sum estimates attributed system
commit, not a directly measured total-process commit peak.

The separate Windows offscreen Qt fixture now verifies synthetic `QKeyEvent`s
through the **actual KeyForwarder -> SDL event adapter (`input_handle_event`) ->
`input.c` mixer -> COFF-registered `nn::hid::GetNpadState`**. It checks all20
mapped keys, combined buttons, press/release, auto-repeat and delayed
release/press repeat pairs, modifier/unknown-key rejection, popup/inactive
window gates, focus loss and application/window deactivation. This exposed and
fixed stuck guest buttons on Qt focus loss: pending release timers and held keys
are cleared immediately through the existing SDL focus-loss handler. The same
active-window gate now applies to the software-keyboard text branch.
Synthetic Unicode key text reaches the existing UTF-8 software-keyboard callback
without setting HID buttons; releasing a held game key while a prompt is open
also clears it. That callback is stubbed for this fixture: native Windows
IME/preedit, the full guest software-keyboard service and physical keyboard
delivery are not qualified by it.

The fixture uses real Qt6.12.0/SDL3 and production C input/HID code, but no game,
GPU surface, controller hardware, save/file menu actions or real preferences.
All45 targeted tests passed; the separate full
`work\tests\qt-controller-mode\BDSP.exe` was relinked with the focus fix, **not
started or deployed**. The detached original game remains on its older binary.
The user subsequently confirmed that Rowan renders and keyboard input works in
the game. This is user-reported runtime evidence, without independently recorded
PID/build/layout details, not native IME or controller acceptance.
The host fix is shared with Linux, but Linux/native Wayland execution was not
retested here. Windows10 hardware, ARM64 execution, GC and release/license gates
remain open.

The existing software keyboard is linked, not stubbed, in the Windows Vulkan
build. Its display gate requires user-supplied firmware fonts and an absolute
`BDSP_FIRMWARE_DATA` path; the initial MVP launcher omitted this path. The
user-supplied firmware resources are now prepared locally at
`work\windows-firmware-20.1.1`, and the existing private MVP launch helper sets
that variable. No new keyboard code, deployment or game restart was needed.
Existing native glyph-atlas and layout-reader tests passed with those resources;
the later isolated game run reached the real applet and the user confirmed
visible keyboard rendering. In-game text commit/submit/cancel remain unverified. The
test was closed normally and no BDSP test instance remains; future runs must
check that no other BDSP instance is running. See
[`input.md`](input.md#windows-vulkan-build-configuration); do not ship firmware
or force scripted automatic text as a substitute for interactive input.

The native `test_real_swkbd_applet_submit_cancel` now checks actual existing
UI/backend callbacks without a game: UTF-8/UTF-16 result serialization,
minimum-length rejection, Cancel, and interactive checker reject/accept.
Kernel/storage transport is synthetic; no full guest IPC or game-level text
acceptance is claimed. Three focused applet/Qt-input/SDL-text tests passed.
The earlier real run's Exitcode0 remains distinct from its recorded
`VK_ERROR_SURFACE_LOST_KHR`; diagnostic timing does not establish whether surface
loss preceded or followed closing. A prior offscreen characterization reproduced
the missing close/keepalive fence, not that GPU error.

The shared Windows/Linux Qt host now calls idempotent `vk_host_shutdown()` before
accepting close and after any other event-loop quit. An armed application-level
surface event filter also runs **before object filters**, including Qt's native
Vulkan cleanup, on `SurfaceAboutToBeDestroyed`. Native Qt surface destruction is
terminal; ordinary Vulkan swapchain recreation does not close admission.
`host_shutdown.c` closes admission to Present/Represent/Clear, requests a terminal
keepalive stop with no future wakes, joins it without holding renderer/worker
locks, drains admitted CPU work, then waits for GPU idle. Queue submit/present/
device-idle share external queue synchronization. The worker sleeps while the
keyboard is hidden and remains joinable until terminal stop.

Acquire uses a one-second timeout with an explicit diagnostic rather than
`UINT64_MAX`. The entire host stop/drain/GPU wait has a three-second deadline.
Vulkan has no cancellable device-idle operation: it runs in a waiter thread.
Timeout or driver/stop/join failure is logged and terminates with exit1 **before
close acceptance or surface destruction**, without attempting unsafe cleanup.
A stuck driver is not declared recovered. Outside terminal shutdown, capability
query/acquire/present surface-loss errors remain fatal; no cached-size fallback
or blanket surface-error suppression is used. Guest threads are not globally
joined: after successful surface shutdown, the existing `_Exit(0)` ends them
without destroying shared runtime resources underneath them.

`test_real_qt_close_drains_keepalive` replaces the gap characterization. It uses
real Qt Host/RenderWindow and real production shutdown/keepalive C code with a
barrier-controlled synthetic present callback and GPU-idle callback. It checks
close acceptance and direct native surface destruction independently, drainage
before object-level surface observers, join/no future wake and idempotence.
Three separate negative processes hold keepalive, CPU ownership or GPU idle
past a short test deadline; each must log timeout and exit1 before teardown.
These are native offscreen ordering tests, **not real GPU/game/hardware
acceptance**. Physical close/driver/controller/IME validation remains with the
user; no new game instance was started.

Focused command (set the existing verified `BDSP_WINDOWS_NATIVE_BINARY`,
`BDSP_WINDOWS_NATIVE_CC`, `BDSP_WINDOWS_SDL_ROOT`, `BDSP_WINDOWS_QT_ROOT` and
`BDSP_WINDOWS_VULKAN_ROOT` first):

```powershell
$tests = @(
  'test_real_qt_close_drains_keepalive'
  'test_real_swkbd_applet_submit_cancel'
  'test_real_qt_keyboard_to_guest_hid'
  'test_real_qt_controller_menu_with_synthetic_backend'
  'test_nvn_coff_hle_registration_focus_reset_and_text'
)
python -X utf8 -m unittest -q ($tests | ForEach-Object {
  "scripts.tests.test_windows_native_generator.WindowsNativeGeneratorTests.$_"
})
```

Compile/link uses `portable_build.compile_runtime(..., frontend="qt")` and
`link_executable` with the existing verified bundles and existing guest object
inventory, solely into `work\tests\qt-controller-mode` (45 runtime objects);
the executable is not started or deployed.

Windows game icons reuse `scripts\recomp\app\game_icons.py`: the `windows`
command produces the existing Qt language-variant manifest/PNGs plus a default
ICO (16/24/32/48/64/128/256 pixels) and RC file. `link_executable(..., icon=...)`
uses the paired LLVM-MinGW windres and records the resource inputs in its link
receipt. The Windows installer prepares icons through the existing authorized
Control-NCA extractor during the images stage and packages `icons/windows`.
Qt discovers that directory automatically and reuses the existing App icon menu,
application/window icon and language preferences; the EXE's embedded Explorer
icon stays the build-time default. No separate artwork pipeline or downloaded
icon is used. Original artwork remains local user-derived data, not a public
release asset. The private MVP was relinked with seven RT_ICON images and one
RT_GROUP_ICON resource. Offscreen tests verify discovery and QWindow icon
inheritance; Explorer/taskbar display and pinned-icon caching need user visual
acceptance, without another agent-started game.

The repeated offline license audit of existing local bundles is at
`work\windows-tools\license-audit-final-20261027\audit.json`; no downloads or
live-package changes. It rechecks inventories/notices for SDL, Vulkan, FFmpeg,
hactool and the original toolchain, plus all four approved Qt archive pins and
the Qt receipt. Qt's38 top-level license files match the source archive; its
source also contains93 third-party notice/attribution candidates needing
applicability review (not93 confirmed shipped dependencies). The paired
toolchain retains34 notice texts; libc++/libunwind match the runtime reference.
The receipt does not itself bind the source/toolchain archive pins or producer
recipe. Complete applicable Qt/runtime attributions and corresponding-source
evidence, FFmpeg8.1/transitive build/source correspondence, host-tool copyleft
sources and authorized VC-runtime provenance remain gates. The original audit
is preserved; neither hashes nor copied generic license texts qualify a release.

Read-only official metadata research subsequently identified an actual prebuilt
candidate: Qt **6.12.0**, kit `6.12.0-0-202609280346`, paired with
**LLVM-MinGW 22.1.7**, not our existing 23.1.4 compiler. The private qualification candidate
in `windows-dependencies.json` records upstream URL/SHA256/byte size for QtBase
(20,746,701), paired compiler (104,242,456), the kit's runtime reference (738,036)
and matching QtBase source for notices/correspondence audit only (51,220,268):
176,947,461 bytes total, about 168.8 MiB. After specific user approval, all four
archives were downloaded into `work/windows-tools/archives/qt-6.12.0-candidate`
and their exact sizes/SHA256 verified. Subsequent explicit approval authorized
isolated extraction and execution for the local MVP, not public redistribution.
Native archive listings confirm Core/Gui/Widgets DLLs, official `libQt6*.a`
filenames, `qwindows.dll` and SBOMs. This is not a successful link/GUI test.
The preparatory receipt validator and link inputs now require
`libQt6Core.a`, `libQt6Gui.a` and `libQt6Widgets.a`, matching those lists
rather than the earlier synthetic `.dll.a` convention. The `.a` suffix alone
does not imply static Qt: shared-linkage/compiler identity, runtime DLLs,
platform plugin and dependency closure remain required. Synthetic positive
and wrong-name rejection tests do not validate the actual archive contents.
The user prioritized the game-launch MVP and deferred the managed-package
decision; no handwritten dependency manager or package-manager integration was added.
Qt 6.11.3's LLVM kit instead declares 17.0.6; the generic Windows support table
alone does not identify a kit's compiler.
The [official Qt 6.12 baseline](https://doc.qt.io/qt-6.12/supported-platforms.html)
includes Windows 10 1809+, but also states 6.12 is the last Windows 10 series;
this is not our physical Windows 10 acceptance of the LLVM kit.
Use the paired compiler in a separate private qualification tree rather than
silently swapping the current compiler/runtime. Existing C++ shaderc/runtime
artifacts need compatible rebuilding/requalification from already approved
sources. The existing shaderc/FFmpeg compile/link/codec/relocation probe also
passes using the paired compiler/runtime; that is not complete ABI qualification.
The private Qt receipt verifies actual headers/import libraries, DLL closure,
platform plugin and matching source license texts. Qt's runtime-reference DLLs
match the paired compiler's DLLs byte-for-byte; only the compiler copy is used
to avoid ambiguous providers. Windows system dependencies include authz, mpr,
netapi32, uxtheme, d3d9, mscms and shcore; these are not bundled from the SDK.
Matching source version is not by itself proof of the binary's build options or
complete corresponding sources. No SDK source build, QtCreator/QML/WebEngine,
docs/examples or public redistribution has been authorized by this metadata pin.

Native extraction keeps metadata capture bounded, but drains and discards unused
ExeFS/RomFS/control extraction output instead of retaining one line per file.
Large real games therefore do not trip the metadata capture limit; extractor
exit failures remain errors and private output is never forwarded to the log.

The first real Windows run exposed an invisible Rowan: GPU import of the guest
alias heap failed, so shader global reads returned zero. On the local NVIDIA
driver, a controlled 64-MiB probe rejects `MEM_PRIVATE` and `SEC_RESERVE`
allocations even after commit/touch, but accepts a `SEC_COMMIT` pagefile section.
The graphical Windows runtime therefore backs its alias range with that section,
keeping other guest ranges private and demand-committed. The current amd64 alias
window charges **6.25 GiB of system commit**, not necessarily resident RAM;
insufficient commit fails explicitly at startup. Section-backed discard zeroes
the range without decommitting GPU-imported backing. Native tests cover guards,
private/section boundaries, protections, zeroing and release/re-reservation.
Vulkan import intersects host/buffer memory types, requires coherent memory and
checks allocation/bind results. A subsequent real 60-second run imported the
5,069-MiB heap successfully and screenshots show Rowan's model and dialogue.
This is a local renderer regression result, not general GPU or GC acceptance.

**Package-manager direction remains undecided.** The user explicitly rejected
MSYS2/pacman; do not install it or hide it inside a new bootstrap. Conan 2 provides
native dependency graphs, compiler profiles, revision lockfiles, binary caches
and `--build=never`; it can consume prebuilt vendor packages without imposing a
new project build system. This does not imply matching ConanCenter binaries:
read-only enumeration of `qt/6.12.0#b0bc6faf97edf4e1e479f9169db772a0`
found ten packages, four Windows variants, all MSVC 194 with `with_vulkan=False`,
and zero Windows Clang/libc++ variants. FFmpeg 8.1.2 binary enumeration returned
HTTP 403, so its binary coverage is unknown. Its source recipe explicitly
requires Windows Bash/MSYS2 and Make when built. vcpkg has native manifests,
version baselines and binary caching, but MinGW triplets are community/untested,
most ports build from source without a matching cache, and its actual Windows
FFmpeg port calls `vcpkg_acquire_msys`. Neither manager is therefore approved as
an automatic source-build fallback. Conan could manage the already selected
vendor binaries through small standard packaging recipes/private cache, rather
than a custom resolver; that is still a proposed integration, not implemented.
Qt-specific `aqtinstall` can manage official prebuilt Qt/LLVM kits without MSYS2,
but does not by itself manage the whole SDL/Vulkan/FFmpeg graph. No package
manager or additional package was installed during this comparison.

The SDL event frontend now synchronizes text input on its own window on every
event/timeout, including focus changes and guest reboot. SDL start/stop failures
are reported and stop the runtime rather than recording a successful toggle.
It does not stop another window's text input. The event loop no longer waits for
an idle event queue before checking text-mode changes or reboot requests; window
shortcuts are suppressed while the guest keyboard owns input. Focus loss also
cancels a held touch key. SDL preedit/candidate events never enter committed guest
text, and reported composition owns editing/confirmation keys until commit or
cancellation. Native OS IME UI remains the SDL default; no new overlay/menu was
added. Real-SDL dummy-window tests cover focus ownership, start/stop/restart,
wrong-thread rejection and synthetic Unicode/preedit event routing; ARM64
cross-linking passes. This does **not** establish physical IME/fullscreen candidate
placement or in-game text acceptance.

The user-approved single-Joy-Con layer holds the **stick click** as a modifier:
Start becomes guest Minus, SL/SR become ZL/ZR and stick directions become D-pad.
Face buttons stay positional. Releasing the modifier clears the layer immediately;
held shifted buttons and movement stay blocked until released/centered, avoiding
an unintended normal action. Direction thresholds use hysteresis rather than a
toggle. Focus loss and hotplug clear transient state; paired/standard controllers
and keyboard input retain their existing mappings. Synthetic real-SDL tests cover
both single halves, repeated polls, both release orders, direction hysteresis,
focus and reconnect. Right-stick and guest stick-click actions remain unavailable
on a single half; the keyboard remains available.
Whole-game GC/thread contexts, complete crash reporting, genuine NCA extraction,
full Vulkan/audio/movie/text hardware integration, persistent single-Joy-Con controls,
real-dump GUI end-to-end acceptance and tool-free gameplay remain unfinished.
Windows 10/11, real controllers and native ARM64 require separate hardware
acceptance. No game was run.

## 7. Build stages overview

Stage order: `tools extract recomp`. Run one part with `--only` or
`--from`/`--to`. Use `--dry-run` first. Each stage writes a marker `work/.stages/<stage>.json` with an input hash.
If the hash matches, the stage is skipped (`--force` rebuilds it).

| Stage | Purpose | Needed for the apps |
|---|---|---|
| `tools` | checks tools, builds `hactool` into `tools/hactool` | yes (for `extract`) |
| `extract` | decrypts the `.xci`/`.nsp` into `work/exefs`, `work/romfs`, `work/manifest.json` | yes |
| `recomp` | macOS app from the recompilation | macOS app only |

The Unity-era stages `il2cpp`, `masterdata`, `video`, `audio` and `shaders` were removed (they remain on the branch `unity`).

### 7.1 The `recomp` stage

`scripts/recomp/app/recomp_build.sh` runs six steps:

1. **Generator:** `work/exefs` modules → C in `work/recomp/gen4` (about 1 GB). Marker `recomp-gen`.
2. **Compile:** C → objects in `work/recomp/obj4`. The default number of parallel Clang processes is based on available CPUs and total RAM (2 GiB system reserve, about 1.5 GiB per compiler); `--recomp-jobs N` overrides it. Functions above `--recomp-o0-kb` use `-O0`.
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
| Not enough disk space (exit 8) | Free space or deliberately lower the requirement with `--min-free-gb N`. The macOS build needs tens of GB. |
| Compile fails (exit 4), memory error | Use `--recomp-jobs 2`. Check `work/logs/recomp-compile.log`. |
| `No connected, unlocked iPad found.` | Connect the iPad, unlock it, and trust the Mac. Check with `xcrun devicectl list devices`. |
| Build fails in `xcodebuild` (signing) | Read `work/builds/logs/ios-recomp-xcodebuild.log`. Set `TEAM_ID` and sign in with your account in Xcode. |
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
