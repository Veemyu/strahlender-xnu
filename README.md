German version: [README.de.md](README.de.md).

# strahlender-xnu

Static recompilation of the ARM64 code of Pokémon Brilliant Diamond (BDSP) for macOS and iPadOS, with a Vulkan path for Linux (work in progress). The runtime (kernel SVCs, IPC services, file system, graphics via Metal or Vulkan) lives in `scripts/recomp/rt-bdsp/`; it contains parts of LASRecomp (see below).

The repository contains **no game data**, no keys, no save files, and no generated code. Building requires your own dump of the game. Pokémon is a trademark of Nintendo, Game Freak and Creatures; this project is not affiliated with any of these companies.

## Building and documentation

- GUI installer: [macOS apps and Linux AppImages](https://github.com/Veemyu/strahlender-xnu/releases) guide you through keys, game files and building. Python is included. Initial downloads are development builds; see [installer details](installer/README.md).
- CLI quick start: `./install.command` (macOS, double-click in the Finder) or `./install-linux.sh` (Linux) checks the tools, asks for your game files and builds.
- Build guide: [docs/BUILD.md](docs/BUILD.md) (German version: [docs/BUILD.de.md](docs/BUILD.de.md))
- More documents are in [docs/](docs/): start with [docs/README.md](docs/README.md), for example `docs/architecture.md`, `docs/recomp-macapp.md`, `docs/recomp-linux.md` and `docs/changelog.md`.

The Unity reimplementation has been discontinued. It lives entirely on the branch `unity` (see `unity/DEPRECATED.md` there). `main` no longer contains it.

### Related projects

The route through the original Unity project and a reimplementation in modern Unity was deliberately dropped. If you want to follow that route, the work is available elsewhere:

- [uDPR](https://github.com/shatter9652/uDPR) by shatter9652, a Unity reimplementation based on [opendpr](https://github.com/TeamLumi/opendpr).
- [opendpr](https://github.com/TeamLumi/opendpr) by TeamLumi, the original project.

## Third-party code and attribution

This project adopts and modifies parts of **LASRecomp** (https://github.com/peiikai/LASRecomp, commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5`), Copyright (c) 2026 Peiikai, MIT License. Affected are:

- `shader_translator/`: Maxwell-to-MSL/GLSL translator, derived from the original and modified (`shader_translator/NOTICE.md`, license `shader_translator/LICENSE-LASRecomp`).
- `scripts/recomp/rt-bdsp/`: runtime based on the original's design, contains parts of it verbatim (`scripts/recomp/rt-bdsp/NOTICE.md`, license `scripts/recomp/rt-bdsp/LICENSE-LASRecomp`).
- Headers `cpu.h`, `simd.h`, `simd_fp.h`: unchanged, in `scripts/recomp/upstream/runtime/` (license `scripts/recomp/upstream/LICENSE`).
- NVN graphics layer (Metal and Vulkan): modified relative to LASRecomp; sources under `scripts/recomp/rt-bdsp/nvn/src/`; the original for comparison is in `scripts/recomp/upstream/runtime/`.

Complete list, third-party components, and what was not adopted: `THIRD_PARTY_NOTICES.md`.

The user of this repository has explicitly approved the adoption and further development of the MIT-licensed code. The original's license explicitly excludes Nintendo property and the third-party components in its `third_party/`; none of these are included here.

## License of this project's own code

The project's own code is licensed under the MIT License (`LICENSE`, Copyright (c) 2026 Veemyu). The third-party parts above are excluded: they keep their own licenses (`scripts/recomp/rt-bdsp/LICENSE-LASRecomp`, `scripts/recomp/upstream/LICENSE`, `shader_translator/LICENSE-LASRecomp`). Game data, keys, and dumps are not part of the repository and are not covered by this license.

