# Native macOS application

Updated: 2026-10-20. BDSP.app statically recompiles the original ARM64 guest code
and uses a native arm64 shell with Metal. The Unity rebuild is deprecated.
Only implementation code, scripts, and documentation belong in Git; game data,
generated code, saves, images, and app bundles stay under ignored work/.

## Build and bundle

```sh
scripts/build_all.sh --only recomp --target macos
```

After extraction/generation prerequisites, this produces
`work/builds/macos-recomp/BDSP.app`, bundle ID dev.local.xnubdsp.
See [BUILD.md](BUILD.md) for prerequisites and options.

The stage generates guest C, compiles chunks, creates relocated module images,
builds the runtime/NVN/Metal layer, packages dependencies and icons, signs, verifies,
and optionally installs a local RomFS clone. Guest generation and object markers
are separate from packaging inputs. Source icons and icon scripts invalidate
packaging without forcing a guest rebuild.

Contents include MacOS/BDSP, Resources/img, main.npdm, BDSP.icns, AppIcons,
shader caches, and bundled SDL3/FFmpeg dependencies. RomFS is not inside the app.
The bundle contains the user's game code and is not a redistributable artifact.

Original language icons come from the user's dump, English by default.
BDSP → App icon changes the Dock icon and persists the choice. Finder retains
the embedded default. All variants use the approved full-bleed composition,
without our earlier inset frame. The embedded default uses native layered assets;
manual Dock variants use native-compiled compatibility ICNS. See [icons](recomp-icons.md).

Guest PCM16 plays through Audio Queue Services. The user confirmed clean Mac
audio. Renderer/Opus services remain stubs; no network functionality is provided.
See [audio](recomp-audio.md) for measurements and limitations.

## Controls

| Action | Shortcut |
|---|---|
| Open save folder | Cmd+O |
| Import save | Cmd+I |
| Pause | Cmd+P |
| Restart | Cmd+R |
| Reset with backup | Cmd+Shift+R |
| Full screen | Cmd+F; Esc exits |
| Window sizes 960×540, 1280×720, 1920×1080, 2560×1440 | Cmd+1 through Cmd+4 |

The Help menu opens configuration, cache/log folders, and key mappings.
Pause on focus loss is optional, off by default.

Keyboard: Z/X/C/V = A/B/X/Y; Return or Space also A; Backspace also B.
E/U = L/R, Q/O = ZL/ZR, equals or Tab = plus, minus = minus.
Arrow keys = D-pad; WASD = left stick; IJKL = right stick; F/H = stick clicks.

GameController.framework supports compatible controllers. Default Nintendo
layout follows physical button positions; xbox layout follows labels. Stick
dead zone is 12%. Real controller hardware has not been validated.
The view preserves 16:9 with letterboxing, default 1280×720, minimum 640×360.
MetalFX is not implemented.

In the historical controller mapping, Menu/Start meant +, View/Options meant
−, shoulder buttons meant L/R, triggers meant ZL/ZR, and multiple connected
controllers all affected player 1. The historical window setting used
`window = BxH`; the game rendered at 1280×720 and stretched to the window,
adding black bars when its aspect ratio differed from 16:9.

## Local paths and configuration

| Data | Default | Override |
|---|---|---|
| Home | ~/Library/Application Support/dev.local.xnubdsp | BDSP_HOME |
| Configuration | <home>/config.ini | BDSP_CONFIG |
| RomFS | <home>/romfs | romfs / BDSP_ROMFS |
| Saves | <home>/save | save / BDSP_SAVE / --save |
| Cache/captures | ~/Library/Caches/dev.local.xnubdsp | cache / BDSP_CACHE |
| Logs | ~/Library/Logs/dev.local.xnubdsp | logs / BDSP_LOG_DIR |

Precedence: environment, configuration, defaults. Relative paths are resolved
against the invoking directory before startup. Configuration also supports
language, window, fullscreen, pause_on_focus_loss, pad_layout, and backups
(default ten startup backups). Icon choice is separate from game language.

Finder launches log to bdsp.log, with bdsp.prev.log for the previous run.
Terminal launches retain stdout; BDSP_LOG_STDOUT=1 forces it.
A cache working-directory link keeps NVN's relative shader outputs inside the
user cache instead of changing NVN sources.

The original Help → Show configuration file action created a commented
`config.ini` template if none existed. The game's requested console language
was `language` (for example `de` or `en-US`).

## Saves

The app uses the original SaveData.bin and Backup.bin in save_1. Version 0x34
files are 979,108 bytes, with MD5 at 0xE9818. Imports accept versions 0x25–0x34,
checking exact version-specific size and checksum. Valid neighboring Backup.bin
is retained. Ryujinx ExtraData0 supplies user ID bytes 8–23 when present.

Menu, drag/drop, and --import-save share validation. Imports and resets back up
the previous state and restart because the guest keeps state in memory.
Host import writes are atomic (.tmp, fsync, rename). Startup backups occur only
when contents changed, retaining the latest configured count.
The guest delete-to-rename safety path has not been verified live; quitting
mid-save is not guaranteed safe.

The original import troubleshooting note pointed to
`scripts/bdsp_save.py check/fix-hash` for inspecting or repairing a bad
checksum. The Ryujinx source path was `bis/user/save/<ID>/0/`.

## Signing and diagnostics

Default signing is ad hoc. --hardened enables hardened runtime and
disable-library-validation for bundled ad-hoc libraries. A 40-second runtime
check passed. No JIT, MAP_JIT, or unsigned-executable-memory entitlement is needed.
No App Sandbox or notarization workflow is configured.

Useful opt-in test hooks: BDSP_KEY_SCRIPT, BDSP_UI_SELFTEST,
BDSP_PAUSE_SELFTEST, BDSP_MENU_DUMP, BDSP_NO_ALERT, and BDSP_LOG_STDOUT.
Use an isolated save directory for scripted tests.

For crashes, inspect the log's guest/host traces and recent-function rings.
Generate names using `python3 -I scripts/recomp/il2sym.py`, then run
`scripts/recomp/app/crashsym.sh <log>`. Its --atos option resolves host addresses.

Historical testing reached the field and Pokécenter interior. Pause/restart were
tested, but real drag/drop, controller hardware, and full-screen appearance still
need manual verification. Interior floors/walls and known water/title rendering
differences belong to the NVN/shader layer, not the shell.

An October 19 cold build under heavy load took about 27.5 minutes; unchanged
inputs took 0.4 seconds, runtime-only changes about 13–50 seconds. These are
historical measurements, not guarantees. Complete older benchmark tables and
investigation notes (the former German report) are in the git history.

## Historical implementation report (2026-10-19)

This section preserves the original implementation snapshot and its measured
methods. Details below describe that test state, including findings and
limitations that may have changed since then; they are not build instructions
for the maintained app. Measurements were made on an M1 Pro with 16 GB RAM
under competing system load of roughly 25–50, so timings and frame rates were
pessimistic unless noted. Only scripts, runtime sources, and documentation are
kept in Git; generated code, saves, screenshots, and RomFS stayed outside it.

### Original bundle and implementation snapshot

The original report described `BDSP.app` as arm64/Metal, high-resolution and
ad-hoc signed, with the German menus Spiel / Ansicht / Fenster / Hilfe. Its executable
contained the runtime, about 220 MB of translated guest modules, the NVN/Metal
layer, and the app shell. `Resources/img` held relocated module images from the
user's dump, with `hle.txt` for HLE slots; `main.npdm` held program metadata.
`Info.plist` declared bundle ID `dev.local.xnubdsp`, high-resolution support,
and `SaveData.bin`/folder document types for drops.
The report's embedded English icon was a dark rounded tile with an inset frame,
and language variants and generated Dock icons were local bundle contents.
SDL3 and FFmpeg (libavcodec, libavformat, libavutil) plus dependencies made up
16 bundled libraries. The 4.7 GB RomFS was deliberately kept outside the app.
The bundle contains user-owned game code and was for personal use.

At that time audio was initially specified as absent. In the October 20 update,
`audout` was changed to play guest-mixed PCM16 through Audio Queue Services;
the user confirmed clean Mac playback. `audren` and `hwopus` remained stubs,
`BDSP_AUDIO=0` muted output, and `BDSP_AUDIO_GAIN=0.10` set app gain to 10%.
There was no network implementation: `services_net.c` only reported success,
and the app had no network entitlement. Audio measurements and limits are in
[recomp-audio.md](recomp-audio.md).

The historical build path was `scripts/build_all.sh --only recomp` after
`extract`/`il2cpp`, via `scripts/recomp/app/recomp_build.sh`. The six stages
were: `scripts/recomp/gen_all.sh`/`eh_gen.py` generated about 1 GB and 2,495 C
files in `work/recomp/gen4`; `scripts/recomp/build_all.sh` used clang `-O1`,
with `-O0` for individual functions at least 300 KB and at most four jobs into
`work/recomp/obj4`; `mkimages.sh` with `hle_nvn.txt` created
`work/recomp/img_app`; `rt-bdsp/build.sh` with `BDSP_APP=1` ran `prepare.sh` /
`build_nvn.sh` and Apple clang for Objective-C, linking `libgame` into
`work/recomp/bdsp_app`; `make_app.sh` assembled, bundled dylibs, ad-hoc signed,
verified with `codesign --verify --deep --strict`, and checked for Homebrew
paths; then an APFS clone installed `work/romfs` under the user's home directory.
`--no-install-data` skipped that final data step.
The `recomp` stage also had a dry-run mode and a preflight disk-space check
(25 GB by default); its diagnostics were localized in German at that time.

The generator partial marker hashed the four guest modules, generator scripts,
and clone tools. If C already existed, generation still ran and `rsync -c`
copied only content changes, preserving timestamps. Chunk timestamps and the
`recomp-obj` partial marker controlled object compilation; changing the `-O0`
threshold invalidated only affected objects. Module images were always rebuilt
(about two seconds), runtime sources were timestamp checked, and app packaging
always ran (about 20 seconds). `romfs.stamp` used the main-file hash and file
count. `work/.stages/recomp.json` summarized module, generator, runtime, cloned
NVN, shader translator, app-script, and option inputs; matching inputs produced
“Marker matches, skipped.”

The original integration kept shared runtime edits small during parallel iOS
work: `main.c` called `bdsp_app_init` under `#ifdef BDSP_APP`; `nvn/nvn_glue.c`
mapped shell buttons/sticks (`g_ext_buttons` / `g_ext_stick`) into
`buttons_now` / `npad_fill` and provided weak `menu_handle_event` and
`menu_apply_window_requests` stubs; `services_gfx.c` paused the Vsync event via
`g_bdsp_paused`; `build.sh` added `BDSP_APP=1` and `NVN_RT`; and
`recomp/build_all.sh` added `O0_BYTES`. New areas were `rt-bdsp/app/`
(`app.h`, `app_config.c`, `app_save.c`, `app_ui.m`) and
`scripts/recomp/app/`.

### Historical signing, build measurements, and tests

Ad-hoc signing (`codesign -s -`) ran locally without a developer account; the
original report noted Finder might require right-click → Open on first launch.
It attributed `com.apple.quarantine` to downloaded files, not local builds.
With `--hardened`, `--options runtime` passed a 40-second run including Metal,
an FFmpeg movie, and guest code. The only needed entitlement was
`com.apple.security.cs.disable-library-validation`, because bundled libraries
were ad-hoc signed under different identities. XML comments in
`scripts/recomp/app/BDSP.entitlements` caused AMFI to reject the entitlement
file. JIT was not used: guest code was precompiled to ordinary machine code,
with no `MAP_JIT`, `allow-jit`, or `allow-unsigned-executable-memory`; guest
memory used `mach_vm_allocate` as read/write data. App Sandbox and notarization
were not configured or attempted; sandboxed file access would need additional
entitlements, and distribution/notarization was outside scope without a
developer account.

The fresh-directory cold build on 2026-10-19 had no generated C or objects and
used four compiler jobs:

| Stage | Measured time | Historical size or note |
|---|---:|---|
| Generator, four modules | 7.2 min (main 357 s, sdk 46 s, subsdk0 26 s); up to 2.6 GB RSS | 2,495 C files, 995 MB; byte-identical to prior C (`diff -rq`), hence deterministic in this comparison. CPU total was only about 1.5 min, with the rest spent waiting under load. An earlier unloaded figure was about 75 s ([architecture](architecture.md)). |
| Compile | 19.8 min / 1,186 s | 2,430 `-O1` files, 65 `-O0`; objects 303 MB. Largest file took 95 s and 1.7 GB RSS at `-O1`; prior unloaded run was 11.7 min ([architecture](architecture.md)). |
| Module images | 1 s | 104 MB |
| Runtime, NVN/Metal, link | 7 s | `bdsp_app`: 225 MB |
| App, libraries, signing | 10 s | 361–363 MB total (MacOS 223, Resources 104, Frameworks 35) |
| **Cold total** | **about 27.5 min** | Stage used about 1.7 GB of disk, temporarily up to 2.7 GB with `gen4.new` during a repeat. |

Unchanged follow-up inputs took 0.4 s. Runtime/app-only changes took about
13–50 s; generator reruns took 1–7 minutes depending on load, after which the
compiler rebuilt only content-changed files. The 25 GB preflight was tested on
a machine with 14 GB free: it was deliberately overridden with
`--min-free-gb 10`, while the default check exited 8. The cold build used the
stage logic in a separate work directory with `--no-install-data`; its app
started for 70 seconds without crashing. The historical target of under 30
minutes from [architecture.md](architecture.md) was met under load.

Test hooks were opt-in environment variables, and the default test remained a
headless run (`--headless --screenshot-after N`, images in `BDSP_SHOT_DIR`).
`BDSP_KEY_SCRIPT="second:KEY:duration,…"` or `@file` sent SDL key events
through normal mapping (example `62:Z:0.4,108:W:2.5`; key names followed
`SDL_GetScancodeFromName`). `BDSP_UI_SELFTEST="second:action,…"` ran menu
actions without confirmation (`fs`, `w960`…`w2560`, `pause`, `restart`);
external keyboard shortcuts could not be sent because Accessibility access was
not allowed. `BDSP_PAUSE_SELFTEST="start:duration"` scheduled pause,
`BDSP_MENU_DUMP=1` logged menu structure, and `BDSP_LOG_STDOUT=1` /
`BDSP_NO_ALERT=1` selected console logging / suppressed alerts. The older
`--input-script` from the early graphics bring-up remained available and
set buttons directly at Npad level. Scripted tests used isolated save paths.

Observed test results under load 25–50:

- A hidden-window run used
  `BDSP_KEY_SCRIPT="62:Z:0.4,72:Z:0.4,82:Z:0.4,92:Z:0.4,106:D:0.5,108:W:2.5"`
  and captured every 300 frames. Z/A advanced from title through Continue to
  the town field at frame 2,400: paved road, blue-roofed house, red-capped
  player, NPC, and conifers. D then W moved right and up to the Pokécenter door.
  Frames 2,700–4,200 showed the interior and Nurse Joy (pink hair/hat) behind
  the red counter, flower baskets, an NPC and trash bin on the left, a
  temporarily visible NPC with brown braid and pink top on the right, and the
  player at bottom with a yellow light circle. The floor and walls were flat
  blue with a brown wedge instead of tile; dark vertical marks ran along the
  right edge. Characters, counter, and furniture rendered correctly. Cause was
  uninvestigated; missing interior shader texture/lightmap binding was only a
  hypothesis related to the gate 2 water/texture issue.
- `BDSP_PAUSE_SELFTEST=40:6` showed 40.3 s at frame 385, pause from 40–46 s,
  frame 405 at 46.9 s (5,996 ms gap in the Metal counter), then 39 fps again.
- `BDSP_MENU_DUMP` checked the app menu plus Game, View, Window, Help (20
  entries). A visible Finder launch via `open -n`, with default paths and no
  save, showed the BDSP window/menu, blue diamond Dock icon, language choice
  screen with two columns, pale blue crystal background, and the text “Select
  the language you would like to play in.” It created
  `~/Library/Logs/dev.local.xnubdsp/bdsp.log`; 960×540 was seen. Fullscreen was
  triggered but its screenshot was obscured by another program's screen
  recording permission dialog, so the fullscreen appearance was not observed.
- `BDSP_UI_SELFTEST=12:restart` confirmed the old process ended and `open -n`
  started a new PID after one second. Initially, `open` inherited the caller's
  test-hook environment, creating a repeated restart loop (stopped by moving
  the bundle). The fix removed `BDSP_UI_SELFTEST`, `BDSP_KEY_SCRIPT`,
  `BDSP_PAUSE_SELFTEST`, `BDSP_INPUT_SCRIPT`, and `BDSP_SCREENSHOT_*` from the
  restarted environment; the next restart ran once.
- `--import-save work/recomp/save/save_1` installed a 979,108-byte save and
  `Backup.bin`; its SHA-256 began `0396a4a62735…`, matching the test save. A
  one-byte-corrupted copy failed checksum validation (exit 1, no writes).
  Synthetic C tests passed valid/invalid saves, wrong sizes/versions, Ryujinx
  `ExtraData0` user ID, file instead of folder, new/unchanged startup backups,
  trimming to three backups, and reset behavior.
- Hardened signature was `flags=0x10002(adhoc,runtime)` and ran 40 seconds
  without error. `python3 -m unittest scripts.tests.test_build_stages
  scripts.tests.test_build_all` passed 57 tests, including stage order,
  preflight limits, hash dependencies, and dry-run.

### Historical crash investigation and limits

For a Finder launch, the log was `~/Library/Logs/dev.local.xnubdsp/bdsp.log`;
for Terminal, use the invoking command's output. Guest crashes logged
`*** Signal N at Host address …`, host backtrace entries (`f_70xxxxxxxx` for
translated guest functions), and per-thread rings of recent guest functions;
runtime aborts appeared as `FATAL: …`. `python3 -I scripts/recomp/il2sym.py`
generated `work/recomp/il2sym.tsv` once (68,183 IL2CPP method names only).
`scripts/recomp/app/crashsym.sh <log>` added method names to guest addresses
and function rings via `symres.py`; `BDSP_IL2SYM=work/recomp/il2sym.tsv` made
the runtime log each game method on its first call. For host addresses,
`scripts/recomp/app/crashsym.sh --atos <load-address> <address>…` invoked
`atos -o BDSP -arch arm64 -l <load-address>`. The load address came from
`usedImages` in `~/Library/Logs/DiagnosticReports/BDSP-*.ips`; the binary
included runtime symbols and debug information (`-g`). One earlier launch
failed after 0.1 s with signal 11 in `f_70002c1d90`, traced to missing
`hle.txt` in the bundle and therefore missing HLE module-image slots.

Other limits recorded at the time:

- MetalFX was optional and absent: `output_scale` was fixed at 1:1 with
  letterboxing. `g_settings.upscaler` hooks existed, but `renderer.m` did not
  receive a scaler.
- Controller mapping had only code/diagram review, no hardware test. The
  Switch Pro `buttonA` position (bottom/right) was assumed to map positionally.
- Drag/drop on window or Dock icon routed `SDL_EVENT_DROP_FILE` to the same
  importer as the menu, but was not tried with a real mouse.
- Restart via bundle `open -n` was measured; the no-bundle `exec` variant was
  untested. Window size/fullscreen were restored from `config.ini` after restart.
- Fullscreen appearance was not seen, only triggered by self-test. Focus-loss
  pause used the same Vsync event as menu pause; only menu/scheduled pause was
  measured.
- The persistent `work/recomp/obj4` came from the earlier 1 MB `-O0` threshold,
  so files from 300 KB to 1 MB remained `-O1` there. The cold build used 300 KB;
  performance impact was not measured.
- Interior floor/wall artifacts and gate 2 water/title-red differences belonged
  to NVN/shaders, not the app shell. Cause of the interior issue was unverified.
- Cmd+Q terminated immediately; an in-progress guest save write had no safety
  protection. Only host-side import writes were atomic.
- Default game language was `en-US`, the runtime value, and `language` could
  change it. Other languages were not measured.
