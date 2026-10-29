# Build pipeline status

## Observed timings (macOS aarch64, 2026-10-26)

| Work | Previous Python generator | Native C generator |
| --- | ---: | ---: |
| Main module emission | 61.92 s | 7.29 s |
| All module generator phase | about 74 s | 9.75–13.81 s |

The observed generator reduction is roughly 60–64 seconds, or about 81–87%.
Main module emission is about 8.5 times as fast. These are observed development
runs, not a controlled same-revision whole-build benchmark. Input extraction,
Clang, runtime, signing and installation are additional work. Do not claim a
matching speedup for the entire build.

One native GUI run compiled all 2,495 objects in 302 s (331.75 s for the phase)
and completed in approximately 6 min 23 s with extraction reused. A later,
successful normal-path incremental run reused generation, compiled objects,
runtime and installed data. From extraction start to package completion it took
about 37 s; packaging alone took 26.69 s. This is not a fresh-input benchmark.

## What still uses Python

The expensive instruction analysis, disassembly/emission and module-image
construction use our native C generator and the Unicorn C API. The active
installer path does not call the historical Python emitter or Unicorn's Python
bindings. Native tool bootstrapping still uses a small Python build wrapper.

Python remains in:

- `scripts/install/driver.py`: JSONL orchestration, preflight, extraction/build
  commands, input/mod metadata and platform installation.
- `scripts/build_stages.py` and `installer/extract` (Rust, `--cli extract`): manifests, input
  identity/checks, stage fingerprints and extraction metadata around hactool.
- `scripts/recomp/native-generator/build.py`: native compiler/Unicorn discovery,
  tool build and dependency fingerprinting.
- `scripts/recomp/parallel_jobs.py`: host CPU/memory/cgroup process-count policy.
- `scripts/recomp/app/game_icons.py`: localized artwork, Pillow image conversion,
  and mod artwork extraction (UnityPy where applicable).
- `scripts/recomp/app/bundle_dylibs.py`: collecting/rewriting macOS dependencies.
- Optional shader inventory/extraction/wrapping utilities, outside the standard
  already-translated game-code emission path.

The installer itself, IPS patching and GUI remain Rust. Actual game compilation,
linking, image conversion and platform tools also execute native libraries and
programs. Python is not responsible for executing Clang compilation serially.
A source-line percentage would not describe build time or runtime cost reliably.

## Parallelism and remaining opportunities

- Native module analysis and function emission use a bounded worker pool.
  Some discovery/coordination remains serial. Modules run sequentially because
  each can use the worker pool; running every module concurrently would compete
  for the same CPUs and additional memory.
- Generated C compilation shares a bounded Clang queue across optimization
  levels. Host CPU/affinity/cgroup and memory capacity determine the process
  count; there is no fixed assumption of eight cores or 32 GB RAM.
- Module export/import binding requires ordered passes. Runtime/NVN build scripts
  still have serial per-file compiler loops. On the measured incremental run,
  images/runtime each took less than one second, so these were not the bottleneck.
- macOS bundle creation/library rewriting/signing still takes about 27 seconds
  even when game code is unchanged. Avoiding redundant packaging with a complete
  dependency fingerprint is a useful next optimization. Profile first rather
  than blindly parallelizing signing or dependent import-binding passes.
- Input hashing/manifest checks and archive extraction still contribute time.
  Sharing verified extraction across source revisions needs a dedicated owned
  game-data library; it is not enabled by automatic successful-workspace cleanup.

## Clean build and retention semantics

Clean build explicitly regenerates the game's C, objects, images and runtime.
Extraction, original inputs, shader caches and toolchain dependencies are kept.
The option applies to native Mac, Linux and Apple-device driver paths. The reset
uses known output names under work and validates every selected input before any
deletion. It does not recursively delete arbitrary development work folders.

Automatic cleanup runs only after successful installation and a successful
backend process exit. Each downloaded workspace receives a new ownership receipt;
only the live in-memory owner can remove that exact tree. It verifies the target
exists outside the workspace and no installed resource link depends on it.
Small compiler/image/runtime diagnostics are retained in fixed bounded files.
For device builds, the IPA is exported before workspace removal. Other selected
files, installed data and saves are unaffected. Errors in cleanup are reported
separately from the successful installation.

Failed/cancelled workspaces and unknown older workspaces are retained. A future
explicit cleanup UI and ownership migration can address those; do not treat their
names alone as permission to delete them. Developer checkouts are never removed
automatically. No host-wide package manager caches or reusable private Python
runtimes are purged. A normal release build starts from a fresh pinned main
snapshot anyway; clean build is most relevant to a retained or development cache.

## Validation limits

Deletion and reset behavior are tested with isolated temporary fixtures, sentinel
inputs/saves, malformed ownership, symlinks and device-package export. Changed
GUI views are checked in English/German dark mode. Full clean build plus cleanup
acceptance on clean macOS/Linux systems remains to be run. Windows cleanup code
is prepared but has no hardware acceptance. No remote host access or CI dispatch
is needed for these local changes.

## Direct iPhone/iPad signing preflight

Missing team configuration is checked with the initial prerequisites. Once input
extraction and optional ExeFS staging determine the final bundle identity, the
installer runs `scripts/recomp/ios/signing_preflight.sh` before native generation
and Clang. Its tiny C application uses the actual development team, device,
bundle ID and app entitlements to exercise Xcode provisioning and signing. It
is not installed. Temporary probe products are removed, while diagnostics and
existing game build outputs are retained. IPA export bypasses personal signing.

### iPhone/iPad shader resources and follow-up verification

Packaging compiles locally recorded MSL sources under `work/recomp/cache/shaders`
with Apple's **iPhoneOS** Metal compiler, pinned to the app's iOS 17 deployment
minimum. Vertex libraries preserve invariance. The source hash, SDK and compiler
version determine incremental reuse. `BDSP_SHADER_CACHE_DIR` can explicitly select
another local cache; it is not an automatic search through other checkouts.
A present source cache makes the Metal toolchain a prerequisite before compilation.
The final bundle only receives libraries matching its current source names and
platform. Rebuilds remove stale bundle shader resources; device and macOS libraries
are never substituted for each other or for simulator libraries.

Recorded shaders are user-generated build data, not distributed repository assets.
A clean checkout without recordings explicitly reports that the device must compile
new shaders. Matching bundled libraries accelerate known variants; new effects and
GPU-specific pipelines can still require compilation. iOS shows a small localized
status independently of the render worker, including bursts of short compilations.
The pipeline warm-up gate reports numerical progress through the same native status. iOS does not compile or display the renderer HUD; the desktop renderer HUD remains a fallback for standalone builds without an app shell. Runtime MSL
recordings live in app-private `Library/Caches/BDSP/shaders` on iOS.

The first verification after import, changed game/mod inventory, or a new expected
manifest hashes every manifest-bound file with SHA-256. Successful checks write a
private binary receipt under `Library/Caches`. Unchanged starts compare the complete
file list, device/inode, size and nanosecond mtime/ctime instead of rereading all file bytes.
Descriptor-relative native directory traversal avoids resolving a URL for each file.
Unchanged launches perform this short check silently. Only full verification publishes
progress through the native banner; it does not open a blocking progress dialog.
An explicit **Check game files again** always performs full verification. A missing
or invalid receipt also hashes again; cache write failure does not block playing.
Receipts do not depend on the app executable's build ID, so code-only app updates
can reuse verified data. Container relocations that preserve every file identity can reuse the receipt; replaced files still trigger a full check. This is a fast
change detector, not cryptographic authentication against deliberately forged
filesystem metadata. Saves are outside the inventory and are never changed.
Manual mods outside the expected manifest are not authenticated by the base-game
manifest; ExeFS/IPS changes still require a new build.


Normal iOS launches start immediately after data verification and save recovery,
without a Play/Backup confirmation. To manage or restore saves before the runtime
starts, enable **Settings → BDSP → Game files & saves → Open tools on next launch**,
then fully close and reopen the app. The switch resets after showing the tools.
Automatic pre-update snapshots and external backup retries still run. Restore/import
remains excluded while the runtime is running.

The UIKit and AppKit shader banners share a coalesced status core: warm-up shows
completed/total pipelines, and new compilations show a preparation count. They are
in-window views and do not request system notification permission. The status timer
updates the view only when the text changes, and suppresses individual fast cache hits.

Save/backup completion messages use the same native banner on Apple platforms.
iOS reports external success only after a configured external export succeeds.
A configured but unavailable destination reports an external backup pending; no
external destination means no unsolicited pending message. macOS currently reports local save/snapshot
results; it does not claim an external export that its shell does not implement.
Messages wait for shader preparation instead of producing overlapping banners.

### Notification preferences

iOS/iPadOS Settings → BDSP → Notifications provides independent, persisted switches
for shader preparation, local save confirmations, external backup confirmations,
save/backup warnings and full-verification progress. All default to enabled. These
switches affect status banners, not the underlying verification, save or backup work.
Explicitly requested operations and errors requiring a decision retain their dialogs.

macOS BDSP → Notifications provides persisted checkmarks for its implemented shader,
local-save and save/backup-warning banners. Menu changes apply immediately. External
backup and verification switches can be added when those services exist in the Mac
shell; the menu does not advertise services it does not perform.

### Optional native firmware import

After Update, the installer offers a compact Firmware view accepting ZIP or NCA
folder selection and drag-and-drop. Skip sits beside Continue. The view explains
that missing original Switch keyboard resources are replaced by alternative input
(native system keyboard on iPhone/iPad). Only the selected source reference is
remembered locally; no firmware or keys are fetched remotely.

The `firmware_import` Rust helper uses hactool, suppressing its raw output because
it can include key material. Before any game C generation it checks the firmware
NCAs, chooses required keyboard/text-font/glyph-font titles, extracts resources and
validates decoded SFNT tables and core Yaz0/SARC layout entries. Optional CJK fonts,
sounds, localized labels and the name-check dictionary are kept when supplied.
Required titles missing or wrong keys cause a firmware-specific failure before
compilation; skipped firmware adds no prerequisite.

ZIP imports reject unsafe paths, links, duplicate names and oversized archives.
Limits are 8,192 entries, 4 GB expanded input and 256 MB extracted resources.
Complete NCA files and registered `.nca/00` directories are supported, not split
NCAs. Successful imports publish an immutable content-derived cache entry after
validation. Reuse checks its file inventory and SHA-256 manifest. Source files and
selected keys remain untouched; temporary import directories are removed on normal
success/failure. Forced process termination can leave staging that needs cleanup.

The cache is under the installer's private application-data directory and remains
reusable across downloaded source revisions. Small validated resources are copied
into signed Mac/iOS app resources (including IPA), or the Linux installed app tree.
No second RomFS is created. Firmware does not enter the save/game identity or trigger
game-code regeneration. App publication already uses staging, so a failed package
does not replace the installed app or its firmware. Manual `Documents/Firmware` on
iOS remains supported as fallback to bundled resources.

Validation includes synthetic ZIP/folder import, cache reuse/tampering, incomplete
dumps, invalid paths/fonts/layouts, navigation and pre-build ordering. Actual
user-firmware/device keyboard acceptance remains pending; no proprietary fixture
is distributed. The helper is included in macOS universal and Linux AppImage
packaging; no CI job or release was dispatched for this change.

Installed firmware discovery reuses the shared emulator-location registry and OS
roots used for key lookup. It checks `bis/system/Contents/registered` for
Ryujinx/Ryubing and `nand/system/Contents/registered` for Yuzu-family profiles,
including Flatpak and historical data roots. Windows uses APPDATA/roaming roots;
Linux respects XDG roots; macOS uses the registry's Application Support/data roots.
An explicitly selected or remembered `system/prod.keys` or `keys/prod.keys` can
also locate a portable installation. No repository directory is a built-in search
location. Discovery accepts installed `.nca/00` blobs without changing them; empty
or unavailable locations produce a hint rather than an error. A remembered manual
firmware choice takes priority. Decryption remains an early build check.

A real registered-directory acceptance run scanned 229 NCAs and produced 58
validated resource files (about 18.2 MB), including optional CJK fonts and the
name-check data. No original NCA, key, RomFS or save was changed. Device keyboard
acceptance is still pending. Progress-state storage derives its length from the
declared stage list, with regression coverage rendering all real build stages.
