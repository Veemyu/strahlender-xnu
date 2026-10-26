# strahlender · Installer

Cross-platform Rust/Iced installer. Download the development builds from
[GitHub Releases](https://github.com/Veemyu/strahlender-xnu/releases): one universal
macOS app ZIP for Apple Silicon and Intel, or a Linux AppImage for aarch64 or
x86_64. End users do not need Rust or Python to
open the installer. Building the game requires your own prod.keys, base game,
optional update and the platform tools listed by guided setup. Full native Mac
and Linux GUI builds have passed desktop testing; fresh-system dependency
installation remains under validation. macOS downloads are ad-hoc signed and
not notarized. See [release controls](docs/releases.md) for deliberate nightly
and stable publication.

Flat dark theme by default, manually selectable light
theme, bundled Fira Sans, a compact 440 × 480 desktop window, rounded grayscale surfaces and separate keys → game → update views. All hosts start with target selection. Mac offers Mac and a combined iPad / iPhone target; Windows and Linux additionally offer their native desktop target. Android is visible as a disabled future placeholder. Native Mac → iPhone/iPad build and device deployment are connected; Apple builds from non-Mac hosts remain planned backend work.
A pinned, segmented step strip shows the current phase without tabs. Longer
phases have wider slots and live generator/compiler counters. Simulation is
available explicitly with `--demo`; real builds use backend progress.
Progress uses a damped spring at the display refresh rate; it never runs ahead
of the reported value.
All Cargo files and build artifacts stay in this directory.

The installer icon uses the approved Vee color artwork on a white rounded tile.
Linux AppImages and window icons use its flat rendering; Mac bundles include a
classic ICNS and a native Liquid Glass asset catalog, generated before signing.
All artwork is local and rendered during the build. See [icon sources](assets/brand/README.md).

On macOS, Apple's working `/usr/bin/git` satisfies the Git requirement and is
selected separately from the Homebrew LLVM search path. A Homebrew Git formula
is not required. Public extraction-tool downloads disable credential helpers
for those commands only, so they do not request access to the login keychain.
Source/build workspaces under `~/Library/Application Support/` are supported;
the tilde in diagnostic paths abbreviates the user's home directory.

Details can be expanded on every view, including after failure or completion.
Normal views keep the same window size. Only opening the log extends the window,
to at most 630 logical pixels. On Mac the complete window is additionally capped
at 85% of the usable screen height, excluding the menu bar and Dock. File details and their compact actions share a row. Main actions
stay visible below the content and use compact buttons. Summary and setup
explanation are separate views to avoid overloading a page.
The two mod views are optional; “Skip mods” jumps to the review and removes
both views from the step bar. They open a local mods folder and discover Ryujinx/yuzu-style
`<name>/romfs` and `<name>/exefs` folders. On macOS and Linux, discovery calls
the runtime's `mods_scan()` without activating a mod or touching saves. A
portable scanner follows the same folder rules on Windows. Pure RomFS mods can
be copied with a file manager and need no rebuild. The installer marks ExeFS
mods as needing a code build. IPS/IPS32-only mods can build a separate Mac or
iPhone/iPad app from a Mac, including one additional `subsdk1` module. Unsupported ExeFS files block
advancement. Choose a whole downloaded mod folder, including common wrapper
folders. The compiled app fixes the selected mod and keeps its own save.
On iOS the installer deploys versioned base and mod data to the app's own
container; `Documents/Mods` also accepts pure RomFS mods through Files.
Mod-provided icons and localized names feed directly into the existing game-icon
pipeline before platform icon generation and signing. Embedded artwork is
extracted from the mod's known RomFS title-logo bundles through the existing UnityPy
reader; Lumi's actual localized logos are extracted there. Explicit icon files
take priority. Only mods with no usable artwork get a visible MOD badge on the
base icon, without host fonts or network assets. The existing shader profile is
needed for embedded Unity logos and is checked before compiling.
All language variants ship.


The session log can be copied; it records file checks, automatic key searches,
concrete validation errors and clearly labelled preview phases. Key contents are never logged. Real backend subprocess output can include local
paths; the expandable log reports commands, diagnostics and exit codes.

The file/folder pickers and basic filesystem validation are real. On a local
macOS checkout, the setup view now runs the existing read-only prerequisite
checks through a versioned JSONL backend protocol and streams the output into the
session log. This development connection uses `python3`; it does not install
Python or change files. Native Mac and Linux builds, plus Mac-hosted iPhone/iPad builds, stream real
extract, generator, compile, packaging and installation phases. Other host/target
combinations remain previews until their backend support is added.
Packaged installers use their own verified Python runtime instead of requiring
system Python.
The first private runtime assembly and its tested host matrix are documented
in [runtime/README.md](runtime/README.md). A development build uses that runtime
when `BDSP_INSTALLER_RUNTIME` points to its verified directory. Release builds
require it. Release preparation bundles the complete shader profile; end users
never install Python packages or invoke pip.

## Build and open

Requires Rust 1.88 or later and the platform's development tools. From the repo root:

```sh
cargo run --locked --manifest-path installer/Cargo.toml
```

Use `cargo run --locked --manifest-path installer/Cargo.toml -- --demo` to
explore the UI with clearly labelled synthetic files. Every input step can be
continued without real files, and examples can be restored after removal.
Automatic key discovery is disabled in this demo mode.

Build a locally signed macOS `.app` for visual and startup checks with
`installer/scripts/package_macos_app.sh`. It writes the bundle to
`work/installer-packages/macos/Strahlender Installer.app` and includes both the
GUI, native `ips_patch` helper and the verified private Python runtime for the
current Mac architecture. The bundle finds that runtime beside its executable.
The backend downloads current `main` into an isolated per-build workspace.
For local backend development only, set `BDSP_INSTALLER_DEV_CHECKOUT=1` in a
debug build to use the current checkout. Release builds ignore that switch.

Simulate host-specific target choices locally:

```sh
installer/target/debug/strahlender-xnu-installer --demo --platform mac
installer/target/debug/strahlender-xnu-installer --demo --platform windows
installer/target/debug/strahlender-xnu-installer --demo --platform linux
```

`--platform` is restricted to demo/capture mode. It changes presentation and target
choices, not native OS APIs or actual emulator-key search paths. The demo banner
identifies the simulated host. Apple targets on Windows/Linux explain the need
for a future Mac/Xcode build connection; selecting them does not implement it.

Theme preferences live in the user's application configuration directory. The
app does not follow the system theme. It stores the appearance preference and
the paths to previously selected prod.keys, game, update and mod folders so a
repeat build can reuse still-valid selections. It never stores key contents.
Each saved path is checked again at startup; missing or invalid files need to be
selected again. The keys view searches known emulator directories when no saved
keys file is available. Missing keys produce an informational hint, not an error.

The `rfd` dependency uses Linux desktop portals instead of its GTK dialog backend.
Linux still needs a functioning desktop portal service for file selection and the
usual windowing/graphics system libraries. This is not a dependency-free binary.

## Automatic screenshots

```sh
python3 installer/scripts/capture.py
python3 installer/scripts/capture.py --backend tiny-skia
python3 installer/scripts/capture.py work/installer-ui/windows --platform windows
python3 installer/scripts/capture.py work/installer-ui/target --platform windows --scenes target,target-ios,demo-target-ios
```

Each command builds and opens the real application, captures the requested states in dark mode, writes PNGs plus a linked review report under `work/installer-ui/`, and
exits automatically. Fixtures are synthetic and saved preferences are untouched.
By default only the target view is captured. Use `--scenes` to select the views
actively changed, including their relevant states. Do not routinely re-capture
unaffected pages. The registry includes dark-mode mod-folder, empty, selected,
ExeFS-only and review scenarios; `--scenes all`
is an explicit full-matrix run and should be reserved for a requested broad review.
Actual main-content
overflow is measured from the Iced widget tree; overflow above half a logical
pixel fails the capture run. The intentionally scrollable log is excluded.
The long-name state exercises a long Unicode filename at the same window width. Use `--language de` or `--language en` to select the capture language. The PNGs capture the
application content, not the operating system's window decorations.

The binary also supports `--capture-dir DIRECTORY` for capture without the Python
wrapper. `ICED_BACKEND=tiny-skia` selects software rendering. Screenshot automation
requires a graphical desktop session; it is not a headless rendering test.

## Verification

```sh
cargo test --locked --manifest-path installer/Cargo.toml
cargo clippy --locked --manifest-path installer/Cargo.toml -- -D warnings
cargo fmt --manifest-path installer/Cargo.toml --check
```

The current development GUI can start a native build for macOS ARM64 and Linux
x86_64 from a base XCI, base NSP or NCA folder, with an optional update NSP.
The backend performs prerequisite checks, builds through the existing local
scripts, reports live stages and installs the resulting desktop app. Linux's
launcher and desktop entry use the XDG data directory and keep saves outside
the replaceable app folder. These paths have synthetic tests; an end-to-end
build through the GUI with actual game inputs is still required. Windows,
Linux ARM64 and macOS x86_64 remain planned build ports. Native Mac-hosted
iPhone/iPad builds and deployment are connected, with device evidence below.

For ExeFS development, `cargo run --locked --manifest-path installer/Cargo.toml --bin ips_patch -- inspect <patch.ips> [--nso <original.nso>]` checks IPS/IPS32 framing and the NSO build ID. `apply <original.nso> <staged.nso> <patch.ips>...` decompresses the NSO with native Rust/LZ4 code, applies matching IPS/IPS32 records to backed segments and writes a separate uncompressed NSO for the existing generator. `stage <base-exefs> <mod-exefs> <output>` inventories a mod's top-level IPS/IPS32 files and optional `subsdk1`, matches patches to exactly one NSO and creates a complete isolated ExeFS folder. The Rust helper also validates the extra module's memory slot including BSS and writes cross-module branch entry points for the generator. Unknown entries, mismatched updates, `rtld` patches and records in gaps or BSS are rejected. Source NSOs are never overwritten. For a native Mac or Mac-hosted iPhone/iPad code mod, build the `ips_patch` binary alongside the GUI (`cargo build --locked --manifest-path installer/Cargo.toml --bins`); the GUI stages, compiles and packages a separate signed mod app. It detects a complete downloaded mod folder, including wrapper folders, and gives mod-provided icons and names priority. Linux code builds, more added modules and in-app code switching remain unavailable. A full code-mod playthrough is not validated. The offset rule follows
[Atmosphere's loader](https://github.com/Atmosphere-NX/Atmosphere/blob/master/stratosphere/loader/source/ldr_patcher.cpp)
and its [patch documentation](https://github.com/Atmosphere-NX/Atmosphere/blob/master/docs/components/modules/loader.md#nso-patching).

The local Apple Silicon Mac and a Fedora-based KDE Wayland Linux x86_64 desktop now pass
their native Cargo builds, tests and Clippy checks. The Linux host also assembled and
executed the private Linux x86_64 runtime and captured the native Linux target
view in dark mode without content overflow. Its desktop portal exposes the file
chooser, but real picker interaction and drag-and-drop still need manual
acceptance. Windows, other Linux desktops, X11, OS permission flows and packaged
releases still need their own runs. The prototype does not claim a tested
six-platform release matrix.

On macOS, winit's external file-drop events do not carry pointer coordinates.
A small main-thread AppKit adapter queries the existing content view's pointer
position; hit testing uses actual Iced widget bounds and scroll offset. This does
not introduce native controls or a separate macOS interface. The Linux/Windows
hover-event path must be verified on real desktops before release.

The UI supports German, English, Spanish and Portuguese (system locale, optionally
`BDSP_LANG` for development). All `es-*` variants share the Spanish catalog;
all `pt-*` variants, including `pt-BR`, share the Portuguese catalog. No separate
Latin American UI files are maintained. Unsupported languages fall back to English.
The complete separation of installer language, game preview language and universal
application resources is specified in [docs/localization.md](docs/localization.md).
The GitHub mark in the header opens the project repository in the system browser.
Appearance uses bundled sun/moon SVGs; device choices use bundled monitor, tablet
and phone SVGs alongside their labels. All icons are compiled into the binary,
and Fira Sans is embedded by Iced. No CDN, system icon theme or emoji is required.
See [asset sources and licenses](assets/README.md); `--licenses` prints the bundled
asset license texts offline.

The manual `Installer packages` workflow prepares macOS and Linux packages on
native x86_64 and aarch64 runners. It includes the complete private Python
runtime and does not publish releases. Windows packaging is follow-up work.
See [release preparation and verification](docs/releases.md).

Every build resolves current `main` once, downloads that commit, and keeps the
revision fixed throughout the build. The backend JSONL protocol is checked;
an incompatible backend stops with an explanation. Network failure never silently
selects stale source. Each run owns its generated files; old workspaces are retained.

When built with `BDSP_INSTALLER_UPDATE_PUBLIC_KEY`, the GUI checks stable GitHub
Releases, verifies separately signed update metadata, and offers an update.
Download and restart require confirmation. Updates cannot interrupt a build.
Without a configured key, update checking is disabled. Public macOS updates
require Apple signing/notarization; current packages are development artifacts.

The setup view explains missing tools and offers guided terminal installation
using Homebrew, apt, dnf or pacman, followed by a fresh check. The installer never
reads administrator passwords. `installer_setup` exposes the same Rust dependency
catalog to CLI users; `--install` explicitly opens guided setup. The older shell
installers retain their existing independent checks for compatibility.

End users download packaged installers from GitHub Releases. The manual workflow
builds all four macOS/Linux architectures; a regular branch push publishes
nothing. Initial nightlies remain development builds while fresh-system and
downloaded-package acceptance coverage is completed.

Game region metadata is not wired to the prototype yet. Original icons are
extracted during a real build through `scripts/recomp/app/game_icons.py`, including its existing
locale recommendation. No cartridge region is guessed from a filename or locale.
The shared icon manifest now also retains all original NACP titles and the display
version; Apple builders include every localized display name alongside every icon.
No finished app is filtered by the installer/system language.

The iPadOS backend has passed an isolated signed-device startup test on an M2
iPad Pro with a no-op IPS, separate bundle/container, mod icon and no imported
saves (2026-10-24). It reached language selection and captured frame 600.
This is not yet a real code-mod gameplay test or a complete fresh-input GUI run.
Xcode signing and iOS FFmpeg libraries must already be configured locally;
a GUI device/signing flow remains pending. See `docs/mods.md` for exact limits.

The full Lumi 2.2F combination (155 IPS32 records, `subsdk1`, RomFS and actual
localized Lumi artwork) also passed a 90-second M2 iPad run, reaching the player
house and exiting normally at the test time limit. Lumi and the original BDSP
app remain installed side by side with separate identities and containers.
Battle and extended gameplay validation, plus a fresh-input GUI run, remain open.

### Linux CPU optimization

The review page offers **Optimize for this computer**, enabled by default.
It starts enabled on every app launch. The selection for this run is passed explicitly as
`BDSP_CPU_TARGET=native` (off: `portable`). Native builds use supported CPU
features including AVX/AVX2; AVX2 is not a minimum requirement. Turn this off
when building for other computers. This option currently applies to Linux game
builds; it does not change the distributed installer or Apple build targets.

### Native generator progress and development storage

The build view now distinguishes native module analysis from C emission and
shows module and function counts, with the existing animated progress bar and
expandable diagnostics. Native errors retain their module, phase and concrete
cause. Stage durations are recorded in the build log. English and German dark
mode captures validate these changed views.

Development runs share one canonical extracted RomFS per game/update combination
on each host, using links in isolated test workspaces instead of repeated exports.
Keep different game/update versions separate. Do not mutate the shared original
RomFS for mods: RomFS overlays remain separate, and ExeFS patches use staged inputs.
Finder metadata does not trigger another extraction. Device deployment still
needs its own on-device game data; this rule does not remove those required copies.
After validation, retire unused Cargo deps/incremental/build outputs and obsolete
test packages, keeping the current testable installer and diagnostic reports.
This is development housekeeping, not automatic deletion of user game data.

For an isolated interactive development run, a debug build with
`BDSP_INSTALLER_DEV_CHECKOUT=1` can also set `BDSP_INSTALLER_DEV_INSTALL_ROOT` to
redirect the existing backend installation destination. Both settings are required;
release builds do not compile this override. This leaves the normal Applications
installation and remote-main source policy unchanged.

Successful desktop installations retain the actual destination and offer a folder
reveal action (Show in Finder on macOS). Development destinations are shown as
such rather than being labelled Applications. Function counters update the live
progress display without flooding diagnostics; raw native module logs remain
available. Detailed generator resource profiling is opt-in with
`BDSP_CODEGEN_PROFILE=1`. Compiler inventory from a previous run is ignored until
the current build publishes its inventory.

### Clean builds and automatic housekeeping

Setup offers a compact **Build options** view. Clean build defaults off and
regenerates C, compiled objects, module images and runtime without discarding
extracted game data, icons or mod inputs. It resets only known generated paths
inside this checkout's work folder and refuses selected inputs inside them.

Automatic cleanup defaults on. After a successful installation and backend exit,
the live owner of a downloaded workspace verifies its ownership receipt and the
external installed artifact, retains bounded compiler diagnostics, then retires
that run's source/build tree. Installed game data, saves, mod libraries, original
containers and keys are outside this scope. Symlinks into external game data are
not followed. Installed resource links back into the workspace prevent cleanup.
For device builds, the finished IPA is retained under installer data `exports/`
before removing temporary files. Failed or cancelled runs remain for diagnosis;
disabling cleanup keeps successful workspaces too. No old or unknown directories
are swept. Local development checkouts are never automatically removed.

See [build pipeline status](docs/build-pipeline.md) for measurements, remaining
Python orchestration and parallelism limits. End-to-end release cleanup still
needs clean-system Mac/Linux acceptance; fixture tests are not that acceptance.
