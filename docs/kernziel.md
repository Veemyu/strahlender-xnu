# Core Goal (User Requirement, 2026-10-18)

**This repository and a personally owned NSP/XCI of Pokémon Brilliant Diamond / Shining Pearl must be enough to build the complete app for iOS, iPadOS, and macOS.** A single command should suffice, and the repository should contain only original code, scripts, and documentation for this purpose.

## Principles
- The repository contains **no** game data, keys, dumps, or derived content. All third-party content is produced locally during the build from files supplied by the user.
- The user supplies locally: the base game as XCI, the update as NSP, and `prod.keys`/`title.keys` from their own console. Keys are never included in the repository or app.
- **Built apps contain the user's content** (textures, models, audio, videos). They are therefore for personal use only and must not be redistributed. Only the repository is shared.
- All conversions (for example, video format conversion) are **additional build steps** and do not modify the source data.

## Build Pipeline (Goal)
Entry point: `scripts/build_all.sh all --xci <file> --nsp <file> --keys <directory> --target macos|ios|all` (guide: `docs/bauen.md`, technical details: `docs/build-pipeline.md`; `--dry-run` previews the plan).

| Step | Contents | Status |
|---|---|---|
| 1 Tools | hactool, Ghidra-free baseline: only what the build needs (hactool from source, ffmpeg, Unity 6.3 LTS, Xcode) | `tools` stage and preflight (installation list without sudo) |
| 2 Decryption | Unpack XCI/NSP, apply update: `work/exefs`, `work/romfs` | `extract` stage (tested) |
| 3 Master data | Read bundles, produce typed data | `il2cpp`, `masterdata` stages (tested) |
| 4 Assets | Integrate bundles into the Unity project, replace shaders with custom ones | `shaders` stage (sample tested), `assets` stage (tested) |
| 5 Video | Convert VP8 WebM to H.265 (`ffmpeg`) | `video` stage (sample tested) |
| 6 Audio | Convert Wwise banks/WEM offline to a Unity-ready format (vgmstream) | Placeholder: “not implemented” (`ap-audio`) |
| 7 Unity build (**deprecated, decision 4**) | IL2CPP player for macOS (arm64) and iOS/iPadOS (Xcode project) | `unity-build` stage: retired, no longer maintained (`unity/DEPRECATED.md`) |
| 7b Recompilation (main path since decision 3) | macOS app from recompilation: generator → C → compile → runtime/Metal → `BDSP.app` | `recomp` stage (tested, cold build 27.5 min; `docs/recomp-macapp.md`) |
| 8 Sign/install | Xcode with a personal team, `scripts/recomp/ios/deploy_ios.sh` | `recomp` stage with `--target ios` (team ID via `TEAM_ID` or `work/local.env`; build only if no ID is available) |

## Videos (Proposed Decision)
- 18 files, VP8 in WebM (`docs/daten-inventar.md`). Whether Unity's VideoPlayer plays VP8 on macOS and iOS is **untested**. If it does not, the build converts them.
- Target format: **H.265 (HEVC, `hvc1`, `.mp4`)**, explicitly with no H.264 fallback (user decision: all target devices hardware-decode HEVC; this is an assumption, not a measurement). Re-encoding an already lossy VP8 source can never be entirely lossless. A true lossless mode would produce very large files. Practical approach: use a very high quality (CRF range), then measure file size and compare images.
- `ffmpeg 9.0.2` is available through Homebrew.

## Distribution Form (User Requirement, 2026-10-18)
- **Primary: prepackaged binary.** Build everything on the development computer with Unity and Xcode. Nothing needs to be imported or selected on the target device (iPad/Mac). The game data (converted bundles, videos, audio) is already in the app. This fits the model “built by oneself, nothing is redistributed.”
- **Optional later: core app plus import** (first-launch assistant that processes an XCI/NSP). This saves build time and app size, but requires more work on the device (decrypting, unpacking, storage).
- **To verify for the prepackaged approach** (not established): app size when installed on iPad via Xcode, bundle loading times from the app package, device storage use, and behavior with a free team (7-day profile). The read paths in code (`GameDataPaths`) remain configurable so both approaches are possible.

## Legal Context
This is not legal advice. The “repository plus personal dump” model avoids us redistributing third-party content. Built binaries are explicitly not intended for redistribution. Clarify the legal position before any public release.
