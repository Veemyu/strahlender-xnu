# iPhone/iPad delivery and save recovery

## Current implementation and acceptance boundary

The macOS installer offers **Export IPA** (the default mobile delivery mode) and
**Install on device**. Both use the native C generator, ExeFS/IPS staging and the
same universal iPhone/iPad application, original localized artwork and mod icon
overrides. The application currently requires iOS/iPadOS 17 or newer.

The export path has been built locally through generation, 2,478 guest object
files, module images, runtime and Xcode packaging. The regular compilation pass
took approximately 327 seconds on the development Mac; this is not a clean-clone
benchmark. A path containing spaces was deliberately used for all these phases.
The resulting approximately 204 MiB IPA passed ZIP integrity checks, declares
both device families and contains no personal provisioning profile. Its separate
base library contained 18,022 checksum-verified files.

**SideStore import/refresh and LiveContainer gameplay/update acceptance are still
pending.** Native filesystem tests and a valid IPA do not establish compatibility
with either host. The current runtime uses a fixed virtual address window and
requests `com.apple.developer.kernel.increased-memory-limit`; a LiveContainer
guest cannot independently grant capabilities to its host. Test the available
address space, actual memory allowance, Metal, audio, controllers and file-picker
access before advertising LiveContainer support. If the fixed window cannot be
reserved, evaluate the existing translated-address iOS memory model separately.

## Building and installing

IPA export needs macOS and Xcode's iPhoneOS SDK, but no connected device, Apple
account, `TEAM_ID`, or provisioning access. Xcode builds without personal signing;
after artwork generation the exporter applies an ad hoc signature. SideStore or
LiveContainer supplies the appropriate installation signature later. Export does
not load private signing configuration and does not install an application.

The tools stage prepares missing iPhoneOS movie libraries automatically. FFmpeg
9.0.2 source is pinned to SHA-256
`8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`.
The source archive is checked before extraction; downloads use HTTPS. Existing
native libraries are reused. This builds local dependencies without modifying
system packages. See `scripts/recomp/ios/build_ffmpeg_ios.sh` for its minimal
decoder configuration and [FFmpeg's license information](https://ffmpeg.org/legal.html).

Direct installation needs a connected device and an Apple development team.
After device selection, the installer offers available local Apple Development
signing identities, or a manually entered ten-character team ID. It reads the
certificate subject's OU field, not the common-name suffix, and only offers
unexpired certificates matching valid local signing identities. The chosen team
ID is remembered privately; account credentials and private keys stay in Xcode
and Keychain. **Open Xcode** and **Refresh** guide account/certificate setup.
Missing or malformed team IDs stop prerequisites before compilation. After
extraction/mod staging resolves the final app identity, a separate **Check Apple
signing** phase builds and signs a tiny C-only probe with the real bundle ID,
selected team/device and the same entitlements. It validates provisioning and
capabilities before native game generation/compilation. The probe is never
installed and its temporary project/products are removed on success or failure.
A failed probe keeps existing game build outputs and stops the pipeline. The
real macOS/iPad signing probe passed during local validation. Team
selection remains editable from the setup page. IPA export does not need a team.
CLI callers can use `--ios-team TEAM_ID`; explicit GUI/CLI selection overrides
legacy `TEAM_ID` environment or literal `work/local.env` configuration. The GUI lists physical paired iPhones/iPads, including USB and
Finder Wi-Fi connections. A separate device step offers **Refresh** and shows
connection status; the setup page can reopen it before building. Up to three
compact device cards fit without scrollbars; larger lists use page controls
in the refresh row. The window keeps its fixed dimensions. Only a single
connected device is selected automatically on first discovery. With multiple
devices, the user must select one. A refresh preserves that selection even if it
becomes unavailable; installation never falls back to another device. Duplicate
names/models show a short identifier suffix for disambiguation. Device identities
remain session-only. Offline paired devices can be selected to retry their
connection; a connected selection is required before continuing. The backend
revalidates the explicit `--ios-device` before building and attempts to reopen a
stale CoreDevice tunnel. Direct installation uses the existing container-relative data locations. Neither
delivery mode uninstalls the original game to make room for a separate mod app.
New GUI device builds also embed an expected data manifest and check the copied
files before starting; an interrupted transfer leaves saves intact and offers a
retry. Older development bundles without that manifest retain a folder-presence
compatibility check.

The JSONL build driver adds:

```text
--ios-delivery device|ipa     # CLI default: device, preserving old callers
--ios-team TEAM_ID           # development signing team for direct install
--ios-export-dir DIRECTORY   # required for IPA export; outside the source checkout
--ios-export-no-embed        # IPA without game data plus a separate Game Library (default: embed)
--ios-profile-id ID          # reuse the opaque mod identity from an earlier IPA
--ios-profile-game TITLE_ID  # validate its original game
--ios-bundle-id BUNDLE_ID    # preserve that IPA's application identity
```

The GUI passes an installer-managed persistent `exports/ios` destination.
Artifacts are reported as `ipa` and `game_library`; an export is not reported as
an `installed_application`. The IPA filename includes its bundle identifier and
content hash. A different existing file is never replaced. Successful workspace
cleanup preserves both exports; it does not need a second copy of an already
exported IPA. Development checkouts remain outside automatic workspace cleanup.

To use an exported build:

1. Import its IPA into SideStore, iloader or a similar tool, or into a configured
   LiveContainer for an explicit compatibility test. The installer does not
   collect Apple credentials. The default IPA contains your game data and needs
   no further step (see "Game data inside the IPA").
2. Only for an export without game data (`--ios-export-no-embed`, "Export without
   game data" in the build options): transfer the **Game Library** folder to
   Files, keeping game data locally available. Select it in the game; each
   separate app grants its own folder access.
3. After selecting Vanilla or a mod, choose an independent save-backup folder.
   iCloud Drive can be selected through Files without an app-specific cloud service.
4. Update the installed application in place. Do not delete the app or its
   LiveContainer data container as an update procedure.

SideStore handles certificate refresh, not the game's data migration. Its normal
free-account limit includes SideStore itself; LiveContainer offers a different
hosting model rather than a new game package format. See the primary
[SideStore FAQ](https://docs.sidestore.io/docs/faq) and
[LiveContainer repository](https://github.com/LiveContainer/LiveContainer).

## Game data inside the IPA

**Export IPA** embeds the RomFS of the user's own dump in the IPA by default, so
one file runs without a second step. The direct installation on a connected
device never embeds; it keeps copying the data with `devicectl`. The switch
`--ios-export-no-embed` (build option "Export without game data") restores the
earlier export: a small IPA and a separate **Game Library** folder. The default
needs no new argument, so installers that predate the switch export the new way.

Legal note: the project distributes no game data. The embedded data come from
your own dump and stay on your machine. The IPA is for your own devices only; do
not share it.

Transparency, so nothing happens unannounced:

- Before the build and again when the IPA is written, the log (events `log`,
  which installer 0.1.3 already shows) says "Exporting the IPA WITH your game data
  embedded" with the size (about 5.3 GB), the minutes, "for your own devices
  only, do not share it" and how to export without data. An export without data
  logs "WITHOUT game data" and that the IPA alone does not run.
- The write is named in three steps (zip, structure check, hash), with
  `progress` events (`id=install`, bytes) for the zip and the hash. The result
  line gives the IPA path, size and "No Game Library folder is needed or written".
- Installer 0.1.4: the review page, right before the start, shows the warning
  and the visible switch "Export without game data" with its explanation; the
  finished page names path and size and says WITH game data, WITHOUT game data
  (Game Library next to it) or WITHOUT game data and without a Game Library (does
  not run alone, export again).
- Too little space stops the export with the needed and the free space and what
  to do (free space, or export without data on purpose). There is no automatic
  switch to an export without data anywhere in the code; tests check that.

How it works:

- The IPA is built in two steps. `installer_build.sh package` places the data
  below `res/EmbeddedData/<RomFSDirectory>` of the app (an APFS clone, hard links
  or copies; no extra disk space on APFS) before the ad hoc signature, so the
  seal covers the data. A mod adds its `romfs` and `exefs` folders below its
  `ModDirectory`. Data of an earlier export are removed from the reused app
  folder first, so no other build ever carries them.
- The driver (`scripts/install/ipa_pack.py`) writes the IPA once: ZIP64 where the
  4 GiB limits of the format are passed, embedded files stored without
  compression, everything else deflated, modes and links kept. The file name
  carries the SHA-256 of the written bytes (hashed once). It checks the free
  space before the build and reports `progress` events with `bytes_completed`.
- `res/install-data.plist` gets `EmbeddedLibrary = true` next to
  `ExternalLibrary = true`, so the save layout (`Documents/Profiles/...`) is
  the same as for an export with a Game Library and a later switch keeps the
  saves. `res/expected-library.json` is the inventory.
- At launch the app treats `res/EmbeddedData` as a verified library: the first
  launch checks every file against the inventory (SHA-256) and writes a receipt
  to `Library/Caches`; later launches compare only metadata. **Game files...
  > Check game files again** repeats the full check. The runtime only reads the
  data (RomFS and mod folders are opened read-only; saves, shots and caches
  live in `Documents`), so the signed bundle is never written.

Measured on the development Mac (APFS) with the real 4.7 GB RomFS of the game:
IPA 5.30 GB (20,583 files, ZIP64), package step including Xcode link, clone and
signature about 80 to 90 s, writing and hashing the IPA 29 s, `unzip -t` 33 s,
extracting 36 s, `codesign --verify --deep --strict` of the extracted app 10 s,
file tree identical to the RomFS. An app-side full check of the extracted data
took 5.6 s on the Mac; the time on a phone is not measured.

Not verified: any run on a device. Whether SideStore, iloader, Sideloadly or
LiveContainer accept a 5.3 GB ZIP64 IPA and re-sign 20,000 files in acceptable
time and memory, how long the first full check takes on a phone, and the
free-account limits for an app of this size are open.

## An IPA alone does not run

An IPA exported with `--ios-export-no-embed`, or by an installer before this
change, contains no game data and does not run alone. Installed alone, the app does not start the
game: it shows **Choose game library** and explains that the game files are
missing. Choose the **Game Library** folder that the installer exported next to
the IPA, install directly from the installer with a connected device, or export
the IPA again with the data included. The dialogs exist in English, German,
Spanish, Portuguese and Russian and have a Help button that opens this section.

The runtime starts only after the data were verified against the inventory that
is part of the app. Before the slow checksum pass, a quick check names the
problem: folder missing, folder empty, files of length 0, or a number of files
missing. If the data still disappear later, the runtime stops with a message in
its log (`RomFS folder ... holds no files`) instead of starting an empty game.

A crash right at launch without this dialog has another cause (for example a
signing tool that removed the increased-memory-limit entitlement, or an address
range the system does not give to the app); the dialog appears only after the
app has started. For a diagnosis, the crash log (Settings, Privacy and
Security, Analytics and Improvements, Analytics Data; or Xcode, Devices and
Simulators, View Device Logs), device model, iOS version, sideloading tool and
signing type are needed.

## Shared data and stable identities

An IPA contains executable code, module images, icons and localizations. It never
contains production keys or saves. It contains the RomFS only when exported with
the default embedding (see "Game data inside the IPA"); otherwise it does not. The data exporter includes only the
selected mod's `romfs` and `exefs` trees; unrelated files in its outer directory
are not copied. No personal source path appears in the library manifest.

The shared library layout is:

```text
Game Library/
  GameData/<romfs-content-id>/romfs/...
  Mods/<mod-content-id>/<mod-name>/{romfs,exefs}/...
  Manifests/<data-identity-sha256>.json
```

Schema 1 manifests contain the exact app data identity and sorted, relative
per-file paths, sizes and SHA-256 checksums. The data identity includes game title
ID/version, data paths, selected mod and save-profile identity. It excludes app
build revision, timestamp and host paths. Separate manifests allow old and new
data versions to remain usable, including versions with identical RomFS bytes.

The native exporter stages and verifies new trees before publishing them. An
existing content directory is reused only if its inventory matches; an altered
directory is not silently repaired or overwritten. Symbolic links and path
traversal inside a data tree are rejected. The game verifies every file before
using a selected library and shows the checked-file counter.

For an update, select the existing library and use **Import new game files** to
select the newly exported library. Only missing content versions are copied,
checked and activated; existing versions and saves remain intact. A separate mod
app can reuse the already imported base RomFS. Folder access uses document-picker
bookmarks; failed verification does not replace a previously working bookmark.
Missing/revoked access requests a new selection instead of making an empty profile.
Old library versions are not automatically deleted in this iteration.

New IPA bundle IDs are `dev.local.xnubdsp.game.<title-id>.<profile>`:
`vanilla` for the base game, otherwise an opaque 20-character hexadecimal ID.
The installer privately remembers successfully exported mod profiles and their
previous display names. A unique name match reuses the existing identity. For a
renamed mod or a different computer, choose **Update an existing mod app…** and
select the previous IPA; only its identity metadata is read. The extracted game
must match the previous IPA. **New mod app** creates a fresh identity explicitly.
Keep the previous IPA alongside backups. Existing direct-install bundle IDs and
save locations are retained; legacy apps require explicit save export/import.

Exported apps place local saves below `Documents/Profiles/<game>/<build-profile>/Saves`.
Exported installed mods use `mods/<opaque-profile-id>` independently of their display name. Legacy direct installs and locally selected mods retain `mods/<name>`. External
backup identity follows the **actually selected** vanilla/mod profile, so choosing
Vanilla inside a RomFS-mod app cannot mix its backups with the mod's backups.
Changing delivery host, signing identity or bundle ID requires explicit backup
and restore; access to another application's sandbox is not assumed.

## Save guarantees and recovery behavior

- Guest host-file writes handle short writes and report errors. Flush failures
  are no longer acknowledged as successful flushes.
- iOS save commits flush the save tree and create a byte-verified, durable native
  C snapshot while guest save filesystem writes are serialized. No asynchronous
  reader tries to snapshot files while the game is changing them.
- The iOS adapter seals snapshots with game/profile identity, slot, player-ID
  file and a SHA-256 inventory. Only sealed, checksum-valid snapshots are offered
  for restoration or counted for retention. Ten verified local generations per
  slot are retained; external copies are not automatically pruned.
- Before the first game start with a different code/data build identity, an
  existing save receives a protected pre-update checkpoint. These checkpoints
  are offered in local recovery and excluded from ordinary ten-generation
  pruning. A failed checkpoint stops that start without changing the save.
  The build identity survives personal re-signing, so certificate refresh alone
  does not create a new checkpoint. Protected checkpoints are intentionally
  retained until the user removes them; they are save data, not build artifacts.
- An independent, user-selected backup folder receives immutable versioned
  copies while the app runs in the foreground. Missing permissions, offline
  providers and failed copies leave a visible pending status and are retried.
  A successful provider write does not promise completed iCloud server sync.
- A guest directory's sibling inside the same LiveContainer host sandbox is
  rejected as an independent backup destination. Local copies are not protection
  against deleting the whole app/host container.
- The startup menu operates on the selected game/mod profile. It offers local
  backup creation, verified local recovery, external recovery and explicit
  drop-file import. Dropping `SaveData.bin` into Documents no longer overwrites
  a live save automatically. Original import files are retained.
- Restoration requires a stopped game, matching game/profile identity and valid
  archive checksums. A different existing player identity is not silently replaced.
  Copies are verified and flushed before activation. The previous slot remains
  as `restore-old-*`; a durable journal recovers interruptions between directory
  moves. Unknown or malformed journals stop recovery for inspection.
- Game/library updates and installer cleanup never delete saves, backups or the
  user's external library. Existing direct-install save folders are not moved.

Checksums here establish archive integrity, not game-save semantic compatibility.
No claim is made that arbitrary mod save formats or an intentionally deleted last
copy can be recovered. Real save-load and update acceptance must use disposable
test profiles before claiming support.

## Verification and remaining device acceptance

Run the native implementation with synthetic files only:

```sh
bash scripts/tests/run_ios_data_tests.sh host
# Optional, with TEAM_ID supplied through private configuration:
bash scripts/tests/run_ios_data_tests.sh device DEVICE_ID
```

The host suite uses AddressSanitizer and UndefinedBehaviorSanitizer. It checks
corruption, malformed identities, traversal/symlinks, old-version preservation,
mod export filtering, immutable IPA publication, cross-profile/player rejection,
restore-journal recovery and injected ENOSPC failures during snapshot write,
flush and publication. Fault injection is compiled only into test binaries.
The device host is a distinct `dev.local.xnubdsp.datatests` app and never links
the game runtime or opens an installed game's saves.

Device selection was checked against a real USB-connected iPad and a known,
disconnected iPhone. Synthetic tests cover three simultaneous USB/Wi-Fi devices,
selection retention through disconnects/refreshes, pagination and stale results.
Real simultaneous multi-device Wi-Fi acceptance remains to be run.

Dark-mode installer captures cover the changed mobile selection, setup and export
completion views in all five UI languages. The CLI tests cover device-free
export, stable identities across moved/updated mods and cleanup-safe output roots.

Still required before a compatibility claim:

- Native filesystem tests passed on a physical iPad using a separate temporary
  test app; it was removed afterwards. Repeat on iPhone during device acceptance.
- Install the default IPA with embedded game data (5.3 GB, ZIP64) through iloader
  and SideStore on a device: acceptance of the size, re-signing time, the first
  full data check and a game start from the bundle.
- Import, refresh and update the IPA through SideStore without changing its ID;
  compare disposable save hashes and actually load the test save afterwards.
- Repeat under LiveContainer, including container-preserving updates, folder
  bookmark access, memory reservation and runtime behavior.
- Run Vanilla plus a separate Lumi app against the same library; confirm separate
  local save roots and external backup identities without duplicate base RomFS.
- Exercise interrupted on-device data imports, revoked folder permissions and
  unavailable file providers; previous data and saves must remain usable.

The document-picker integration follows
[Apple's directory-access guidance](https://developer.apple.com/documentation/uikit/providing-access-to-directories).
LiveContainer's own
[container operations](https://livecontainer.github.io/docs/guides/containers-and-external-data)
remain host-managed; this implementation does not modify LiveContainer or depend
on its private directory layout for game data.

Local signing-team discovery uses the Team ID in the certificate subject's OU
field as documented in [Apple TN3161](https://developer.apple.com/documentation/technotes/tn3161-inside-code-signing-certificates).
Account and development-certificate setup remains in
[Xcode's signing workflow](https://help.apple.com/xcode/mac/current/en.lproj/dev60b6fbbc7.html).

Device transfers resolve the local RomFS/mod root to its canonical directory
before calling CoreDevice. Directory symlinks used to share extracted input
therefore do not become file transfers (`EISDIR`), and no additional local RomFS
copy is created. Sources/destinations are validated before app installation;
retrying transfer copies only the selected content paths, never save folders.

## Integrity checks and pre-game menus

Current installer-built iOS apps hash every file in the expected RomFS and
build-selected mod trees with SHA-256 at startup and compare relative paths,
sizes and hashes against their build manifest. Missing, changed or extra files
inside those trees block startup. `.DS_Store` is ignored. Older development apps
without a manifest only have the documented presence-check fallback.

A newly added standalone RomFS overlay in Documents/Mods is scanned on the next
launch and does not change the base inventory. It has no reference hash inventory
in an older app's build manifest; that check cannot authenticate arbitrary new
user mods. Updating a manifest-bound mod requires a matching installer export
and data import; ExeFS/IPS changes additionally require a new code build.

The regular pre-game dialog offers Play and Saves & backups. Backup setup and
restoration are separate views, and Back up now is hidden until a save exists.
External-library selection/import is a separate Game files view. German copy
addresses the player with du/dein. This changes navigation only: automatic save
snapshots, pre-update checkpoints, external retries and restore checks remain.

Real UIKit previews with synthetic state can be captured without the game:

```sh
bash scripts/tests/preview_ios_data_ui.sh
# Optional: SIMULATOR_ID for an already booted simulator, or SIMULATOR_RUNTIME.
```

The runner captures only these changed dialogs in dark mode, with the iPhone
11 Pro Max landscape dimensions, and removes its own simulator/build products.
