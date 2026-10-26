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
- `scripts/build_stages.py` and `scripts/build_helpers.py`: manifests, input
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
