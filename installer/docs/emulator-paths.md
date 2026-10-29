# Automatic key discovery

The keys view searches automatically on startup. Missing or unreadable candidates
produce an informational hint; users can always drop/select their own file.
The lookup opens candidates only to check readability and size. It never logs key
contents, changes emulator data or recursively searches a home directory/drive.
Decryption compatibility belongs to the shared game-inspection backend.

The shared declarative registry is [`../assets/emulator-paths.json`](../assets/emulator-paths.json).
Rust embeds it; the future Python CLI must consume the same definitions.
All profiles target the ordinary lowercase `prod.keys` file. The researched
loaders also understand `title.keys`; the installation backend should use an
included update ticket first and request title keys only when necessary.

## Standard paths

Append `/prod.keys` to each directory. `APPDATA` means Windows roaming app data;
the Windows known folder is the fallback. `DATA` means absolute `XDG_DATA_HOME`
or `~/.local/share`. `CONFIG` means absolute `XDG_CONFIG_HOME` or `~/.config`.

| Emulator/profile | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Ryujinx / Ryubing | `APPDATA/Ryujinx/system` | `~/Library/Application Support/Ryujinx/system` | `CONFIG/Ryujinx/system` |
| Yuzu | `APPDATA/yuzu/keys` | `DATA/yuzu/keys` | `DATA/yuzu/keys` |
| suyu | `APPDATA/suyu/keys` | `DATA/suyu/keys` | `DATA/suyu/keys` |
| Sudachi | `APPDATA/sudachi/keys` | `DATA/sudachi/keys` | `DATA/sudachi/keys` |
| Eden | `APPDATA/eden/keys` | `DATA/eden/keys` | `DATA/eden/keys` |
| Citron NEO | `APPDATA/citron/keys` | `DATA/citron/keys` | `DATA/citron/keys` |

Ryubing's official guide retains the `Ryujinx` directory name. Do not invent a
`Ryubing/system` default. The Yuzu-lineage keys directories use the data root;
their separate XDG config directory is not the keys root.

Historical Flatpak candidates are also included:

- Yuzu: `~/.var/app/org.yuzu_emu.yuzu/data/yuzu/keys`.
- Ryujinx: `~/.var/app/org.ryujinx.Ryujinx/config/Ryujinx/system`.

These combine verified archived Flathub IDs, source path selection, and Flatpak's
[documented XDG mapping](https://docs.flatpak.org/en/latest/conventions.html#xdg-base-directories).
They establish historical candidates, not a current Ryubing Flatpak release.
Other forks' desktop/AppStream IDs are not treated as proven Flatpak IDs.

Compatibility probes from the existing installers remain separately labelled:
`~/.switch`, macOS `~/Library/Application Support/yuzu/keys`, the old macOS
`~/.config/Ryujinx/system` location, and `yuzu-emu/keys` in the Unix data directory.
They are not claims about every current upstream release.

## Limits and precedence

Registry order is deterministic: Ryujinx/Ryubing, Yuzu, researched forks, historical
Flatpaks and legacy locations. The first readable nonempty candidate is offered.
This is not a claim that it contains the newest key generation. Manual selection
wins over a late automatic result. Once the shared backend is connected, it must
validate the chosen file against the actual game/update and allow replacement.

Portable installations can use `portable/system` (Ryujinx) or `user/keys`
(Yuzu-family). Their roots depend on the emulator executable, launch working
directory or a user override. The helper cannot discover arbitrary portable/custom
installations from its own working directory. These remain manually selectable;
the helper does not search `./user` next to itself and pretend it belongs to an
emulator. A future explicit emulator-location input can expand those exact roots.

The helper ignores relative XDG overrides and uses the standard default instead.
Some researched emulator snapshots accept relative values; reproducing that
behavior would make lookup depend on the helper's unrelated working directory.

## Source evidence and provenance

Each fork was researched independently with a user-requested GPT-6-luna agent.
Source checkouts and detailed notes are in gitignored `work/installer-research/`.
No downloaded emulator code is built, executed or included in this project.
The parent agent rechecked the data/config distinction against actual source
before integrating the registry.

- **Ryubing:** [official setup guide](https://docs.ryujinx.app/guides/setup-guide/)
  documents the `Ryujinx` root, `system/prod.keys`, portable and custom modes.
  The official source server timed out. Platform details use archived Ryujinx
  lineage at `ea07328aea4b6d70f5d5aa2c3c3874a748854ba1`,
  `src/Ryujinx.Common/Configuration/AppDataManager.cs`; this is not proof that all
  current Ryubing internals are identical.
- **Yuzu:** archived source mirror [`yuzu-emu-mirror/yuzu-mainline`](https://github.com/yuzu-emu-mirror/yuzu-mainline)
  at `7ffac53c9e67fa18d067114a8eb3e77c74bba68f`,
  `src/common/fs/path_util.cpp:86–134,303–340`, `fs_paths.h:8–18`,
  `src/core/crypto/key_manager.cpp:641–662`. Original upstream is removed.
- **suyu:** [original FAQ](https://git.suyu.dev/suyu/suyu/wiki/FAQ/) confirms
  Windows/Linux defaults. The original Git host could not resolve. macOS/XDG
  and additional source details use the explicitly identified continuation
  [`suyu-emu/suyu-main`](https://github.com/suyu-emu/suyu-main) at
  `347fcf91d95cd39cb5c3db50f1b6d827ad699311`, `src/common/fs/path_util.cpp:114–159,329–390`
  and `src/core/crypto/key_manager.cpp:460–477`. Continuation evidence is not
  represented as verified original suyu source.
- **Sudachi:** original source URLs were unavailable. Candidate mirror
  [`Synoptikon/Sudachi`](https://github.com/Synoptikon/Sudachi) at
  `f627a085d363bba569adc43a84f35dbd7cf6bb95`,
  `src/common/fs/path_util.cpp:90–124,303–318`, `fs_paths.h:6–27`,
  `src/core/crypto/key_manager.cpp:641–658`. This is an identified historical
  snapshot, not a verified current official release.
- **Eden:** inspected mirror [`eden-emulator/mirror`](https://github.com/eden-emulator/mirror)
  at `989768aa46720e3fcab9e2111e3ddd70819c382b`,
  `src/common/fs/path_util.cpp:114–158` and `fs_paths.h:11–20`.
  See the detailed independent report for upstream access and packaging limits.
- **Citron NEO:** [`citron-neo/emulator`](https://github.com/citron-neo/emulator)
  at `f942c356798800fbe17949fd5e563cc9eec3a7a6`,
  `src/common/fs/path_util.cpp:90–121,260–314`, `fs_paths.h:7–18`,
  `src/core/crypto/key_manager.cpp:699–718`. This describes that NEO revision,
  not every older Citron build.
- **Flatpaks:** archived official Flathub manifests
  [`org.yuzu_emu.yuzu`](https://github.com/flathub/org.yuzu_emu.yuzu/blob/4abf1d239aba843180abfed58fa8541432fece5b/org.yuzu_emu.yuzu.json)
  and [`org.ryujinx.Ryujinx`](https://github.com/flathub/org.ryujinx.Ryujinx/blob/5b8509c6751502eae5955f767bbf51f1f77c95f4/org.ryujinx.Ryujinx.yml).

Path generation and registry coverage are unit-tested for all three operating
systems. Actual desktop/package validation is currently local macOS only;
these source findings do not substitute for Windows/Linux acceptance tests.

## Installed firmware discovery

The firmware step derives installed-resource candidates from the same platform
roots in the registry. This is independent of whether a prod.keys file currently
exists there. Ryujinx/Ryubing replace the key directory `system` with
`bis/system/Contents/registered`; Yuzu-family profiles replace `keys` with
`nand/system/Contents/registered`. Historical Yuzu and Flatpak profiles retain
their corresponding roots. The standalone `.switch` key directory does not imply
an installed firmware location.

An explicitly selected or remembered `prod.keys` in a portable emulator's
`system` or `keys` directory can add that installation's sibling firmware path.
The installer does not guess a portable application's executable location or scan
repositories. Mixed-case key-directory names are accepted for Windows inputs.
A readable nonempty NCA inventory (including `.nca/00` registered blobs) is offered
without modifying it. No result is a hint, not a prerequisite failure. Full title,
key and extracted-resource validation runs before game compilation. A remembered
manual firmware choice takes priority over discovery.

Platform path resolution and registered-blob discovery have synthetic tests. A
real Ryujinx-format registered-directory import also passed on macOS aarch64.
Windows-native and Linux-native firmware-import acceptance remain open.
