German version: [README.de.md](README.de.md).

# strahlender-xnu

Pokémon Brilliant Diamond as a native app on iPad, iPhone, Mac, Linux and Windows. You bring your own legally obtained copy of the game and your own keys. The installer turns them into an app on your device.

This is not an emulator. The game's own ARM64 code is translated into native code ahead of time, and a small runtime replaces the Switch operating system and its graphics API. Graphics go through Metal on Apple devices and Vulkan on Linux and Windows.

The repository contains **no game data**, no keys, no save files and no generated code. Pokémon is a trademark of Nintendo, Game Freak and Creatures; this project is not affiliated with any of these companies.

## Why "strahlender-xnu"

- **strahlender** is German for "brilliant", the word in the German title *Pokémon Strahlender Diamant* (Brilliant Diamond).
- **xnu** is the kernel underneath macOS, iOS and iPadOS. The project started on Apple platforms, Linux and Windows came later, and the name stayed.

## Where it runs

**Supported:** iPad, iPhone (iPhone 11 family and newer, A13 chip with 4 GB RAM or more), Mac (Apple Silicon), Linux x86-64, Windows 10 22H2 and 11 (x86-64).<br>
**Experimental:** Linux aarch64 (needs Vulkan 1.3). The installer and the build tools work on a real aarch64 machine, a full game build and rendering are not verified yet, testers are welcome (see [docs/BUILD.md](docs/BUILD.md), section 6.5).<br>
**Planned:** Apple TV.

The iPhone is tested on an iPhone 11 Pro Max.

## Getting started

- **Installer (easiest):** download the [latest installer](https://github.com/Veemyu/strahlender-xnu/releases/latest) for your system. It guides you through keys, game files and the build. Python is included. See [installer details](installer/README.md).
- **Command line:** `./install.command` on macOS (double-click it in the Finder) or `./install-linux.sh` on Linux checks your tools, asks for your game files and builds.
- **Build guide:** [docs/BUILD.md](docs/BUILD.md) (German: [docs/BUILD.de.md](docs/BUILD.de.md)).

What you need: your own copy of the game (XCI, optionally the update NSP) and your `prod.keys`. Apps for iPhone and iPad are built on a Mac with Xcode and signed with your own Apple ID.

An exported IPA runs only together with its game data: install directly from the installer, or choose the exported **Game Library** folder in the app ([details](installer/docs/ios-delivery.md#an-ipa-alone-does-not-run)).

## What is in it

- A GUI installer for macOS, Linux and Windows.
- App icons generated from your own game data, in every language of the game.
- Mod support: file mods (RomFS) can be swapped without reinstalling, code mods (ExeFS) are built into the app. See [docs/mods.md](docs/mods.md).
- The Switch's own system keyboard (Horizon OS) for text entry. It needs your Switch firmware during the build. See [docs/input.md](docs/input.md).

## Documentation

All documents are in [docs/](docs/); start with [docs/README.md](docs/README.md). Good entry points are `docs/architecture.md` for how it works, `docs/recomp-macapp.md`, `docs/recomp-ios.md` and `docs/recomp-linux.md` for the platforms, and `docs/changelog.md` for recent changes.

The Unity reimplementation has been discontinued. It lives on the branch `unity` (see `unity/DEPRECATED.md` there). `main` no longer contains it.

### Related projects

If you prefer the route through the original Unity project, the work is available elsewhere:

- [uDPR](https://github.com/shatter9652/uDPR) by shatter9652, a Unity reimplementation based on [opendpr](https://github.com/TeamLumi/opendpr).
- [opendpr](https://github.com/TeamLumi/opendpr) by TeamLumi, the original project.

## Third-party code and attribution

This project adopts and modifies parts of **LASRecomp** (https://github.com/peiikai/LASRecomp, commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`), Copyright (c) 2026 Peiikai, MIT License. Affected are:

- `shader_translator/`: Maxwell-to-MSL/GLSL translator, derived from the original and modified (`shader_translator/NOTICE.md`, license `shader_translator/LICENSE-LASRecomp`).
- `scripts/recomp/runtime/`: runtime based on the original's design, contains parts of it verbatim (`scripts/recomp/runtime/NOTICE.md`, license `scripts/recomp/runtime/LICENSE-LASRecomp`).
- Headers `cpu.h`, `simd.h`, `simd_fp.h`: unchanged, in `scripts/recomp/upstream/runtime/` (license `scripts/recomp/upstream/LICENSE`).
- NVN graphics layer (Metal and Vulkan): modified relative to LASRecomp; sources under `scripts/recomp/runtime/nvn/src/`; the unmodified originals are in the git history (commits `e43b466`, `2d01ade`, `d1c40e7`) and in LASRecomp commit `09f8e5e`.

Complete list, third-party components, and what was not adopted: `THIRD_PARTY_NOTICES.md`.

The user of this repository has explicitly approved the adoption and further development of the MIT-licensed code. The original's license explicitly excludes Nintendo property and the third-party components in its `third_party/`; none of these are included here.

## License of this project's own code

The project's own code is licensed under the MIT License (`LICENSE`, Copyright (c) 2026 Veemyu). The third-party parts above are excluded: they keep their own licenses (`scripts/recomp/runtime/LICENSE-LASRecomp`, `scripts/recomp/upstream/LICENSE`, `shader_translator/LICENSE-LASRecomp`). Game data, keys, and dumps are not part of the repository and are not covered by this license.
