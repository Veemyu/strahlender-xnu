# Installer release preparation

The first downloads are macOS apps (ZIP/tar.gz) and Linux AppImages/portable
archives, each on x86_64 and aarch64. Windows installers and Android remain
follow-up work. CI never processes game files or keys.

## Deliberate builds and publication

Ordinary branch pushes and pull requests never publish or start this packaging
workflow. Publication is triggered only through its explicit manual channel or
an `installer-v*` tag. No scheduled nightly publication is configured.

| Action | Result |
| --- | --- |
| Push development commits to `main` | Source changes only; no installer release |
| Manual channel `artifacts` (default) | Four native builds, tests and downloadable Actions artifacts; no release |
| Manual channel `nightly` | Four native builds and a public prerelease with its own immutable tag |
| Manual channel `release` | Stable release matching `installer/Cargo.toml` |
| Push `installer-v0.1.0` | Stable release, only if the Cargo version is exactly `0.1.0` |

The tag namespace separates installer publication from unrelated repository
tags. Every release requires all four native jobs to pass. Packaging hashes are
verified before collection; the final downloads include a combined
`SHA256SUMS` and `installer-build.json` with the exact installer source commit.
Uploads are staged in a draft before publication. Existing release tags are
never moved or silently overwritten. Nightlies do not replace stable `latest`.

From the repository's Actions page choose **Installer packages → Run workflow**
and select the channel, or use the GitHub CLI:

```sh
# Test packaging without publishing anything.
gh workflow run installer-ci.yml --ref main -f channel=artifacts

# Deliberately publish a development prerelease.
gh workflow run installer-ci.yml --ref main -f channel=nightly

# Deliberately publish the version currently in installer/Cargo.toml.
gh workflow run installer-ci.yml --ref main -f channel=release

# Equivalent stable trigger from Git, after committing the matching version.
git tag -a installer-v0.1.0 -m "Installer 0.1.0"
git push origin installer-v0.1.0
```

Do not run both stable triggers for the same version. A failed publication can
leave a draft for inspection; it never advances an existing stable tag. Initial
nightly downloads are development builds, not a completed fresh-system
compatibility matrix. The macOS packages are ad-hoc signed and not notarized.
Gatekeeper acceptance remains a manual user action. Unconfigured signed update
metadata does not prevent manual downloads or game builds; automatic installer
replacement is disabled until that separate setup is completed.

### Release messages and draft review

Each installer version has an editable English release message at
`installer/releases/<version>.md`. Commit that message with the version change;
publication checks for it before starting the native jobs. The workflow adds
the exact installer commit and channel automatically. Release text remains
editable on GitHub after publication and changing it does not require rebuilding
the downloads.

For a build whose downloads should remain unpublished until the message is
reviewed, select **draft** in the workflow form or pass `-f draft=true`:

```sh
gh workflow run installer-ci.yml --ref main -f channel=release -f draft=true

# After the build: edit the prepared draft, then deliberately publish it.
gh release edit installer-v0.1.0 --notes-file installer/releases/0.1.0.md
gh release edit installer-v0.1.0 --draft=false --latest=true
```

Nightly drafts can be published the same way, with `--latest=false` so they do
not replace the stable latest release. An explicit `installer-v*` Git tag still
requests direct stable publication; use the manual draft route for a review step.

## Private Python

`runtime/manifest.json` pins CPython archives. `wheels.lock.json` pins base wheels;
`shader-wheels.lock.json` adds the complete transitive shader/icon profile. The
assembler verifies archive/wheel hashes, installs offline into private Python,
checks package consistency, and exercises native engines and image decoding.
There is no dependency on system Python in the installed app.

`tpk_ar` has no published wheel and is built from the pinned source archive on
each runner. Linux ARM64 additionally builds UnityPy in the pinned ARM64
Manylinux container and repairs it with auditwheel. Source-built wheel hashes
are recorded together with the locked source hash in `runtime.json`; wheel bytes
may differ between native builds. These provenance records are accepted only
through the explicit release-preparation `--source-builds` argument.

Local macOS preparation:

```sh
python3 installer/scripts/build_source_wheel.py tpk_ar --fetch-source \
  --output work/installer-runtime-release/macos-aarch64/wheels
bash installer/scripts/prepare_runtime.sh macos-aarch64
BDSP_INSTALLER_RUNTIME="$PWD/work/installer-runtime-release/macos-aarch64/runtime" \
  bash installer/scripts/package_macos_app.sh
```

Linux uses `package_linux.sh` with its native full runtime. The output is an
AppImage and a portable AppDir archive. The latter also works where mounting an
AppImage is unavailable. Packaging tools are hash checked. Build paths are
remapped in Rust release binaries and pip's local wheel URL metadata is removed.

The initial Linux GUI build baseline is Ubuntu 22.04 (glibc 2.35). Runtime wheels
target manylinux 2.28, but that does not lower the GUI's own glibc requirement.
Desktop acceptance targets supported Ubuntu/Debian releases, Fedora/Nobara and
Arch; older distributions are not implicitly covered by the wheel tags.

## System tools and permissions

The shared Rust catalog lists component purposes and package mappings. The GUI
first checks, explains the plan, and only launches installation on an explicit
click. The terminal owns sudo/Homebrew authentication. Return to the installer
and choose **Check again** after it finishes. Cancellation or unavailable
packages leave setup incomplete and never start the game build.

Package availability depends on distribution version and enabled repositories.
No PPA, AUR helper, foreign repository or graphics driver is enabled automatically.
In particular, Arch's VMA headers currently require the community AUR package
`vulkan-memory-allocator`; this remains a manual setup gap. Ubuntu releases
without SDL3 development packages also need a supported dependency source before
the game build can proceed. Do not advertise these cases as unattended setup.

Apple device builds still require Xcode account/device pairing, a signing team
and iOS FFmpeg preparation. Their fully guided onboarding remains an explicit
release acceptance item. Existing local developer settings are not copied into
downloaded main workspaces.

## Signed installer updates

Source updates and installer updates are independent. Builds always resolve
latest main; installer updates use stable `vMAJOR.MINOR.PATCH` GitHub Releases.
Set repository variable `INSTALLER_UPDATE_PUBLIC_KEY` to a base64 Ed25519 public
key before building updater-enabled packages. Keep the 32-byte seed private,
outside the repository. The updater is disabled when no key is configured.

Collect final artifacts in one directory, then sign the manifest offline:

```sh
cargo run --locked --manifest-path installer/Cargo.toml --bin installer_release -- \
  0.2.0 work/release-assets /secure/location/update-seed.base64
```

Upload `installer-update.json`, `installer-update.json.sig` and its named assets
to the matching stable release only after approval. macOS updates use `.tar.gz`;
Linux updates use `.AppImage`. ZIPs/portable archives are also available for
manual installation. The public key printed by the signing tool must match the
one embedded in the installer. The workflow does not store or use the private key.

Update metadata signatures and downloaded bytes are verified before replacement.
The user confirms download/restart. The replacement helper waits for the GUI to
exit, keeps a backup, and restores it if replacement or launch fails. Read-only
installation folders retain a verified download for manual installation. A build
and an installer update cannot run together. macOS additionally requires a valid
signature and Gatekeeper assessment; ad-hoc development bundles are rejected.

Developer-ID signing/notarization is not configured. Initial macOS downloads use
ad-hoc signatures and require Gatekeeper acceptance by the user. They can be
published independently of paid Apple signing. Automatic macOS replacement
still rejects these bundles; this is separate from manual distribution.

## Acceptance

- Run Rust formatting, tests and Clippy, runtime-source tests and wheel-lock checks.
- Execute `--check-runtime` from outside the checkout with a minimal PATH.
- Execute `--check-source` to verify current-main acquisition without building a game.
- Inspect only changed dark-mode scenes: `setup-dependencies`, `update-available`.
- Test guided dependency installation on a fresh Mac and Ubuntu/Debian, Fedora/Nobara
  and Arch desktops. Missing package, denied authentication and interrupted network
  cases must leave a usable retry path.
- Complete a real game build from the packaged installer on Mac and Nobara, using
  only user-selected keys/game/update. Keep saves and existing installed games intact.
- Test signed update replacement on Linux and notarized replacement on Mac before
  enabling public updates. Unit tests cover signature tampering and failed-launch rollback.

Native full-runtime assembly passed on macOS ARM64, headless Fedora ARM64 and
Nobara x86_64. A native Nobara AppImage (approximately 74 MiB) passed its bundled
runtime check outside the checkout; Wayland captures of changed setup/update and
log-expansion views were inspected. The user confirmed complete GUI builds on
Mac and Nobara. The dependency probe reported no missing components, so actual
host package installation was not exercised. Nobara source fetching passed after
an initial network outage; no system network settings were changed.

The macOS development bundle passed its runtime smoke check outside the checkout.
Downloaded CI packages still need fresh-system compatibility testing across the
full host matrix. These deferred tests are recorded locally in
`todo/installer-cleanroom-testing.md`; that directory intentionally stays ignored.

## Window runtime patch

`installer/vendor/iced_winit` contains iced_winit 0.14.1 with the small
synchronous-resize fix described in its `PATCHES.md`. Package builds use this
local dependency through Cargo's patch table. Keep the vendor directory and
license in source archives; a normal registry-only build loses the Wayland log
expansion fix. The SBOM includes the patched component and its source location.

