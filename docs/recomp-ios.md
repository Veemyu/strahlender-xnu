# Native recompilation on iPadOS

Updated: 2026-10-22. Native ARM64 static recompilation, UIKit and Metal; no JIT.
The Unity rebuild is deprecated and out of scope.

## Current state

The iPad app reaches the intro, title, imported save, and 3D field. The user has
accepted the startup gate: only the shader-compilation counter appears at the
upper left. Do not change this start path without agreement.

Xcode 27.1 (iOS 27.1 SDK) builds the iPad app and the iPhone compile target
(`TARGETED_DEVICE_FAMILY=1`, minimum iOS 17.0). Two findings on 2026-10-22:

- Fixed: shader libraries need `-target air64-apple-ios26.0` (`shader_bin.sh`).
  Without it Xcode 27 emits AIR v29 for iOS 27.1, which iPadOS 26 does not load,
  so every draw was skipped (0 draws). The runtime now logs library load errors.
- Render-worker race: the asynchronous worker runs concurrently with the guest.
  Without any setting, 4 of 10 starts crashed or stalled. Lockstep
  (`BDSP_EXEC_SYNC=1`) avoids that but serializes guest and renderer: about 69
  presentations/s, which was a performance regression. The iOS default is now
  the asynchronous worker with `BDSP_XW_DRAIN_DESTROY=1` (texture release waits
  for the worker): 120 presentations/s in 2 of 2 runs. `BDSP_XW_SNAP=1` stays
  off: it produces empty command lists (0 draws). Details: section 4.5 of the
  German document.

Mac reference runs before this date used module images without HLE bindings
(`work/recomp/img`); their crashes were not code regressions. Regenerate images
with `HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt`. Details: section 4.5 of the
German document.

PCM16 output through Audio Queue Services and AVAudioSession is implemented.
The user confirmed clean sound in one targeted 60-second run ending at 60 fps.
See [audio](recomp-audio.md) for evidence and remaining tests.

Original icons are generated from the user's dump, with English as the default.
Available language variants are selectable in Settings → Apps → BDSP → App icon.
All variants now use the user-approved full-bleed Icon Composer design: 1024px,
100% scale, zero translation, no custom border. iPadOS provides the outer shape
and glass effects from compiled layered assets. See [icons](recomp-icons.md).

## Build and deployment

Requirements: Xcode, paired/unlocked device, extracted modules and main.npdm in
work/exefs, generated model-B guest objects, and TEAM_ID in ignored work/local.env.
Do not commit personal signing settings in project.pbxproj or workspace user data.

```sh
scripts/recomp/ios/gen32.sh all 3
scripts/recomp/ios/build_ffmpeg_ios.sh
scripts/recomp/shader_bin.sh iphoneos
scripts/recomp/ios/deploy_ios.sh build
scripts/recomp/ios/deploy_ios.sh install
```

The deploy helper supports:

| Command | Purpose |
|---|---|
| build | Build static runtime/game libraries, Xcode app, icons, shader resources, then sign and verify |
| install | Install the app and ensure the RomFS manifest matches |
| data | Explicitly replace the device RomFS with work/romfs |
| save | Copy local save import files into Documents; the app validates/imports them |
| run [seconds] | Launch with console log; an optional duration terminates the process |
| files [path] | List container files, default Documents |
| shots | Copy device captures into ignored work/visual/ipad-recomp |

RUN_ENV supplies launch environment as JSON. Logs go to
work/builds/ipad-recomp-<timestamp>.log. Do not use repeated iPad launch loops.
Back up device saves before installation. Recent in-place installs preserved
saves and RomFS; verify rather than assuming preservation or blindly overwriting
them. Data/save commands can replace user state and are not routine test steps.

Output bundle:
`work/builds/ios-recomp-derived/Build/Products/Release-iphoneos/BDSP.app`.
The final bundle is signed after resource modifications and checked with
`codesign --verify --deep --strict`.

## Memory model and architecture

Model B reserves a 4-GiB guest window, translates addresses as
g_base + (uint32_t)ea, and places guest modules below 4 GiB. Static game and runtime
archives are force-loaded. UIKit hosts CAMetalLayer; the runtime runs on its own
thread, not the UI main thread.

Main: 0x01000000; SDK: 0x07000000; subsdk0: 0x08000000; rtld: 0x09000000;
HLE slots: 0x0A000000. Thread stacks occupy 252 MiB from 0x10400000.
The alias region starts at 0x20000000. SDK allocation constraints leave about
1.98 GiB of application memory versus 3.14 GiB in model A.

nvn_rebase32.py rewrites guest-address uses in copied NVN sources under work/,
preserving host pointers. Rules must match or generation aborts.
build_rt32.sh supports Mac validation and iPhoneOS static-library builds.
FFmpeg provides software VP8/VP9 decoding and Matroska/WebM demuxing; the guest
shader converts YUV. The source movies have no audio streams.

The tested device is an M2 iPad Pro with 8 GB RAM. BC compression is supported;
maxBufferLength is 4 GiB. The increased-memory-limit entitlement is signed and
verified. Early field runs reached about 2.1 GiB footprint and thermalState 0.
These historical figures and the earlier 50–52 fps measurements are not current
performance guarantees.

## Memory model A-low, iPhone target and the thermal limit (2026-10-23)

**Model A-low** is the compact layout of model B shifted to a fixed host address (`0x8_0000_0000`, free on iPad and iPhone), so guest address == host address again
(see [architecture.md](architecture.md)). Build: `MODEL=a scripts/recomp/ios/gen32.sh all` (folders `gen4i`, `img4i`, `obj4i`, about 15 minutes cold),
`IOS_MODEL=a scripts/recomp/ios/deploy_ios.sh build` and `install` (own runtime folder `ios-rt-a`, own build output). Model B stays the default
(`deploy_ios.sh` without `IOS_MODEL`). A fixed 12.5 GiB `vm_allocate` on the M2 iPad Pro succeeds at `0x4_0000_0000` and `0x8_0000_0000` in every start
(`BDSP_PROBE_FIXED=1`, three starts); `0x1_` is invalid, `0x2_`/`0x3_` are used by the system, everything from `0x10_0000_0000` up is invalid.

Measured on the M2 iPad Pro, 240 s, the same input script (left/right walking on the Route 222 beach, `BDSP_INPUT_SCRIPT`), 120 fps target,
cool start. CPU time is the process CPU time of all threads per presented frame (`BDSP_PERF_LOG=1`):

| | B (C SIMD, `G2H`) | A-low (NEON asm, direct) | Mac M1 Pro, model A |
|---|---|---|---|
| CPU ms per frame, cool (30 to 60 s) | about 28 to 32 | about 22 to 25 | about 28 |
| CPU ms per frame, after 2 minutes | about 47 | about 37 to 42 | about 28 (flat) |
| fps after 2 minutes | about 70 | about 90 to 100 | about 118 |

The growth over time is **thermal throttling**, not a leak: a fixed integer calibration loop in the perf log (`cal_us`) takes 7.5 ms on a cool device
and 12 to 14 ms after one to three minutes of load, also when the player stands still (`thermalState` stays 0 the whole time). At a 60 fps target
the same scene runs at a flat 22 to 23 ms per frame and `cal_us` stays at 7.4 ms for 200 s. The game needs about 2.7 busy cores at 120 fps (it runs its
whole per-frame logic at the display rate, the original ran it at 30), which the passively cooled iPad cannot sustain. Practical consequence: 60 fps
is the sustainable setting on the iPad; 120 fps drops to about 90 after a minute.

**iPhone target.** The Xcode project builds for iPhone and iPad (`TARGETED_DEVICE_FAMILY = "1,2"`, model A-low by default through `BDSP_RT_DIR = ios-rt-a`);
the touch overlay scales with the screen and the safe area. `DEVICE_NAME=<part of the device name> scripts/recomp/ios/deploy_ios.sh ...` selects the phone;
`deploy_ios.sh data` copies the RomFS (Xcode does not). Measured on an iPhone 11 Pro Max (A13, iOS 26.6.1) with `BDSP_PROBE_FIXED=1`:

- A fixed `vm_allocate` window succeeds at `0x5_` to `0xC_0000_0000` (4 and 12.5 GiB), but `0x2_` and `0x4_0000_0000` are taken. The A-low base is therefore
  **`0x8_0000_0000`**, which is free on the iPad as well (`gen32.sh`/`build_rt32.sh` default `ORG`).
- `supportsBCTextureCompression` is 0 (Apple6 family). The renderer converts BC textures while uploading (`nvn/src/nvn/bctc.c`): BC1, BC2, BC3 and BC7 into
  ASTC 4x4, BC4 and BC5 into R8/RG8 texels; BC6H is not converted (not seen in the game). In the field the game holds only 34.6 MiB of BC textures (BC3 25.2,
  BC1 5.7, BC7 2.5, BC4/BC5 1.2; ASTC 6x6 18.7 MiB runs natively; measured with `BDSP_TEX_INVENTORY=1`), so the conversion costs about 6 MiB and, on an M1 Pro,
  0.6 µs per BC1 block and 1 to 1.4 µs per BC3/BC7 block. `BDSP_TEST_NO_BC=1` forces the path on any GPU (iPad: same picture as with BC).
  `scripts/recomp/rt-bdsp/test/run_bctc_test.sh` checks the decoders and the written ASTC blocks against Metal's own decoders.
- The next limit on the phone is memory: with the save in the field the footprint reached 1.9 GiB while loading and iOS ended the app (signal 9) after 28 s.
  Measured with `BDSP_MEM_REPORT=1`: the title screen sits at about 1.3 GiB; entering the game adds about 300 MiB of guest memory within a second (1.05 to
  1.43 GiB), GPU resources are about 340 MiB, and the app is killed at roughly 1.8 to 2.0 GiB. The shader source text (330 MiB of malloc) is freed after compiling now,
  and the ring buffers default to 16 MiB x 4 on devices with less than 5 GiB of RAM (about 50 MiB instead of 180). The jetsam report says `vm-pageshortage`, i.e. system-wide
  pressure, not the per-process limit (`os_proc_available_memory` still showed 600 MiB free at the kill, limit about 2.3 GiB with the increased-memory-limit entitlement,
  which the provisioning profile contains). What made the field load survive is the **application memory the game is told** (`GetInfo` 6/21): 1.6 GiB (`0x66000000`) on
  devices with less than 5 GiB of RAM instead of 1.98 GiB (measured only on the iPhone 11 Pro Max; `BDSP_APPMEM` overrides); 1.4 GiB is too little (null pointer in the game's allocator after 33 s). With 1.6 GiB the phone stays in
  the field for more than five minutes; the picture has no regressions, 30 fps hold, and 55 to 60 fps without a cap until the A13 throttles (`thermalState` 2, the calibration loop
  `cal_us` doubles from about 9300 to 14000 to 25000).
- **Audio drops out in the field, and the cause is found.** The game keeps delivering sound (the output is fed in real time, about 48 buffers per second, the queue plays 48000
  samples per second, no interruption or route change is reported), but the sound is gone 5 to 20 s after the field starts. `BDSP_MEM_REPORT=2` shows why: on entering the field
  the system-wide wired memory jumps from about 1.07 to 2.6 GiB and decompressions rise from about 100 to 10000 to 30000 per second, with 30 to 50 MiB free. The first command
  buffer that binds the Metal buffer over guest memory (`gmem` shaders, vertex streams written by compute skinning) makes iOS wire the whole range, which the compressor cannot
  touch, so everything else is squeezed and the audio server of the system starves. With `BDSP_NO_GUEST_BUFFER=1` (the GPU never sees that buffer; the picture breaks as expected)
  wired stays at 710 to 1060 MiB, decompressions drop to 0 to 300 per second and the sound stays. The GPU needs under 1 MiB of storage buffers in four 16 MiB areas, so the real fix
  is a small shadow arena for those ranges instead of the whole window (planned, not done). Not the cause: the texture change check, heat or load (the cap of 30 fps does not help),
  RomFS reads (none slower than 20 ms), the audio session (category `Playback`, no events).
- `maxBufferLength` is 2 GiB. The envelope of all `MapPhysicalMemory` blocks is 3.5 GiB because small blocks lie far below the main one; all memory pools sit in the
  application chunk from `ORG + 0x8000_0000`, so `metal.m` wraps only that part when the envelope exceeds the limit (2047 MiB; a warning is logged for a pool outside).
- With that the game runs 90 s (4761 frames, RSS 771 MiB) on the phone. RAM (2.3 GiB available to the app) and the two performance cores are not evaluated yet.

## Memory entitlements and address space (research, 2026-10-18; sources are Apple's documentation)

| Question | Finding | Confidence |
|---|---|---|
| Extended Virtual Addressing (`com.apple.developer.kernel.extended-virtual-addressing`, iOS/iPadOS 14.0+) | Boolean entitlement for a larger address space, aimed at games that map assets for the GPU. Changes the address space, not the memory limit | documented |
| EVA with a free team | Apple's "Supported capabilities (iOS)" table lists it only for the paid program and Enterprise | documented |
| Increased Memory Limit (`com.apple.developer.kernel.increased-memory-limit`, 15.0+) | Allows exceeding the standard limit on supported devices; the real value comes from `os_proc_available_memory()`. Not in the capability table, but it **can be added with a free Personal Team** (builds, signs, runs on the M2 iPad Pro) | observed |
| Memory limit measured on the M2 iPad Pro (8 GB) | **5,120 MiB** without the entitlement, **8,192 MiB** with it (`os_proc_available_memory() + phys_footprint`) | measured |
| Increased Debugging Memory Limit | development builds only; paid program only | documented |
| A fixed multi-GB region at a fixed address (like 12.5 GiB at `0x70_0000_0000`) | Not reliable: the public XNU limit for arm64 outside macOS is far lower, an ordinary iOS process has roughly 7.4 GiB of usable address space, and one report says `mmap` fails without an entitlement | one report, unverified on current iPadOS |
| Address-space size with EVA | not specified by Apple | unverified |

Consequences: the macOS model (guest address = host address, fixed window) is unsuitable for iPadOS, hence model B above (32-bit
offsets, everything below 4 GiB, host thread stacks of a few MiB instead of 256 MiB). Plan the runtime budget with
`os_proc_available_memory()` and measure on the device, because that is the only reliable figure. A free team signs the app for 7
days. Sources: the Apple documentation pages for the two entitlements, the capability table at
`developer.apple.com/help/account/reference/supported-capabilities-ios/`, and `os_proc_available_memory`.

## Known issues and regression evidence

The empty released-audio-buffer response must write tag zero; stale tags caused
a guest Wwise loop and field freeze. Preserve duration-based release pacing.

A kernel timed-wait race was fixed: if a waker already completed the wait and
transferred mutex ownership, its result wins over ETIMEDOUT. Otherwise the SDK
could lock a mutex it already owned.

The early zero-frame stall of 2026-10-19 (GC thread suspension and IPC) occurred
in 2 of 10 runs without drain and did not occur in the 2 drain runs (too few to
conclude). Its cause is still open; the host-lock explanation remains a
hypothesis. The earlier suspension experiment was reverted; do not reintroduce
it or use device repetition loops. Additional diagnostic changes remain uncommitted.

Remaining manual checks include touch/controller/keyboard hardware behavior,
audio interruptions/device changes, extended play/battles and the guest memory
limit, and shader/rendering differences such as water. Do not infer a successful
alternate-icon switch from merely seeing the default icon.

Full historical measurements, address tables, and investigation notes (the former
German report) are in the git history. Historical statements about
silent output or an old installed build describe that earlier state.

## Historical findings (research snapshot, 2026-10-19)

This section preserves the detailed measurements and implementation notes from
the original research log. Values below describe that dated test state, not
current performance guarantees. The log marked a result *measured* when it had
a run log under `work/builds/` or images under `work/visual/ipad-recomp/`, and
*suspected* when it was an inference without a test. The work was stopped at the
user's request at 17:30 on 2026-10-19. Its references were
`docs/architecture.md` (memory model B) and the memory entitlements research
(now a section of this document). The tested device was a 12.9-inch, 6th
generation M2 iPad Pro (8 GB, iPadOS 26.4.2), signed with a free team and the
increased-memory-limit entitlement, verified by `codesign -d --entitlements`;
the Mac was an M1 Pro with 16 GB. The repository contained names, numbers, and
structure only: no game data, generated code, images, or team ID; logs, images,
and objects were kept under `work/`.

The archived 2026-10-20 icon update described an opaque icon image with 6.25%
inset, with iPadOS supplying the outer rounding. That records an earlier
design iteration; the current icon design and language selection are described
at the top of this guide and in [recomp-icons.md](recomp-icons.md).

### Model B implementation details

The `gen32.sh` pipeline generated all modules below 4 GiB (`main` at
`0x01000000`, `sdk` at `0x07000000`, `subsdk0` at `0x08000000`, and `rtld` at
`0x09000000`) with `--simd c`, made module images using
`mkimg.py --hle-base 0x0A000000` and the `hle_nvn.txt` HLE list, then compiled
for iPhoneOS arm64. Outputs were `work/recomp/gen32`, `img32`, and `obj32`.
`compile_chunk_ios.sh` used `-O1` except that individual functions larger than
300 KB used `-O0`, plus `-fno-fast-math -ffp-contract=off`,
`-DREBASE32 -DRT32_GEN`, and `-I rt32`. Objects were tagged for iOS; the Mac
validation removed that platform tag with `vtool -remove-build-version` so the
objects could also link on macOS. Generated `memset` calls for the lifter's DC
ZVA operation go through the guest base under `-DRT32_GEN` using
`(void *)(uintptr_t)`. DC ZVA did not occur in generated C (zero matches across
2,303 chunks), but the guard remained.

The 4 GiB `mmap` window used `g_base`, with the first 64 KiB marked
`PROT_NONE`. `BDSP_WATCH=hexaddress,…` logged calls with x0–x2 and lr for
debugging. iOS used a conditional path because `mach_vm.h` is unavailable
there; `kernel.c` used `vm_region_64` instead of `mach_vm_region`. `GetInfo`
values 2, 3, and 6 could be overridden for diagnosis with
`BDSP_ALIAS_BASE/SIZE` and `BDSP_APPMEM`. `nvn_glue.c` supplied only fallback
alias-region values for model B. The model-B runtime header also defined
`APP_MEMORY`, `HEAP_REPORT`, and `ADDR_SPACE_END` for its layout and reporting.

`nvn_rebase32.py` copied LAS NVN sources from `work/recomp/nvn-src` to
`nvn-src32`. It rewrote 78 uses where the clone treated a guest address as a
`(uintptr_t)` pointer through `GA()` (`(uintptr_t)G2H()`); host pointers in
command buffers remained untouched. Every rewrite rule had to match or the
script aborted. It separately rewrote `movie_glue.c` as `movie_glue32.c`,
placing host pointers read by the guest into guest memory through `H2G` and
`gstr`. The checked-in `scripts/recomp/rt-bdsp/nvn/` sources stayed unchanged
for model A. `build_rt32.sh mac` made the model-B runtime and NVN (Metal, SDL3,
FFmpeg) at `work/recomp/bdsp_boot32`; `build_rt32.sh ios` made the iPhoneOS
`libbdsp_rt.a` without SDL, since the app supplied the window and input. The
`nvn_ios.py` generator produced `metal_ios.m` and `renderer_ios.m`.

The model-B address layout was: main `0x01000000` (82 MiB), SDK `0x07000000`,
subsdk0 `0x08000000`, rtld `0x09000000`, HLE slots `0x0A000000`, TLS
`0x0A100000`, and a 96 MiB HLE heap beginning at `0x0A200000`. The 1 MiB
`SetHeapSize` region began at `0x10300000`; BDSP never called `SetHeapSize`, and
measured guest heap use was 0 MiB in every run. Thread stacks occupied 252 MiB
from `0x10400000`. The alias region ran from `0x20000000` to `0x100000000`
(3.5 GiB).

The 4 GiB window constrained SDK application memory to `0x83000000` (1.98
GiB), versus 3.14 GiB in model A. `nninitStartup` requested one contiguous
application-memory allocation through `AllocateAddressRegion` (`GetInfo` 6/21
minus 64 MiB); `AddressSpaceAllocator::AllocateSpace` placed it at a random
2 GiB boundary in the alias region (model A example: `0x7200000000`). In the
4 GiB window only the block from `0x80000000` to `0xFF000000` fit. Starting
the alias region at `0x40000000` or `0x7F000000` caused the later 32 MiB file
cache allocation to fail, measured using `BDSP_ALIAS_BASE/SIZE`.
`ThreadManager::CreateThread` first failed on thread 20 because the SDK mapped
thread stacks in the stack region (`GetInfo` 14/15); 32 MiB held 19 threads,
while 252 MiB allowed 39. The Metal buffer wrapping all `MapPhysicalMemory`
areas was 3,583 MiB, below the iPad's measured 4,096 MiB `maxBufferLength`;
model A had 5,069 MiB. BC texture compression was supported on M2
(`supportsBCTextureCompression == 1`), so no BC decoder was needed.

On the Mac model-B run (`work/builds/mac-b-run9.log`), the game reached the
title as in model A, at 45–47 fps (model A: 45), with 39 threads, peak RSS of
1,153 MiB, and 2.0–2.2 GiB of Metal buffer occupied. The extra `g_base`
address calculation was not visible in this measurement; the only
microbenchmark was from the spike and showed a 5% increase in an exception
test.

### Device probe, app, and build measurements

The `deploy_ios.sh build-stub` probe reported an Apple M2 GPU, BC and ASTC
support, `maxBufferLength` 4,096 MiB, `recommendedMaxWorkingSetSize` 5,461 MiB,
and `os_proc_available_memory` 8,183 MiB with the entitlement. Anonymous
`mmap` allocations of 4, 5.2, 6, and 12.8 GiB succeeded without
`MAP_NORESERVE`; only touched pages counted (writing 256 MiB gave a 266 MiB
footprint). A Metal buffer around 4 GiB also succeeded. This showed that
iPadOS could host the 4 GiB window without Extended Virtual Addressing.

The hand-written app used UIKit and `CAMetalLayer`. Its touch pad had a
direction pad, console-positioned A/B/X/Y, L/R/ZL/ZR, plus/minus, and
multitouch. GameController support mapped buttons by position, supported
sticks, and hid the touch pad when connected. Hardware keyboard mapping
matched the Mac (arrows/WASD, Return/Space for A, Backspace for B, and other
keys). The app imported saves and emitted footprint, available-memory, and
thermal-state measurements every five seconds. `Info.plist` limited the app
to iPad and landscape full-screen mode, enabled file sharing and opening
documents in place, and required arm64/Metal. `BDSP.entitlements` carried
`com.apple.developer.kernel.increased-memory-limit`; the Xcode project and
shared scheme were hand-written.

`libbdsp_rt.a` was 1.8 MiB, built with `-Dmain=bdsp_runtime_main`, and ran on a
thread with an 8 MiB stack. `libgame.a` was 352 MiB with 2,303 objects. Both
were linked with `-force_load` because NVN functions in a Mach-O section would
otherwise be discarded. The app executable was 308 MB and the bundle 398 MB,
including 105 MiB of module images in `res/`. Mach support for the Boehm GC
(`thread_suspend`/`thread_get_state` on its own threads) worked without an
entitlement: SVC 0x32/0x33 were called 344/135 times in the run, without
errors.

The iOS FFmpeg build used FFmpeg 9.0.2 fetched from ffmpeg.org into
`work/ios`. It enabled native software VP8/VP9 decoders, parsers,
Matroska/WebM demuxing, and the file protocol, but not swscale: runtime code
gave YUV to the guest and the guest shader converted it. VideoToolbox could
not decode VP8. At 720p/30, playback had no dropped frames; the film ran at
50–52 fps with a maximum 25 ms frame gap and four FFmpeg decoder threads.
The source movies had no audio streams.

Generation took 74 seconds (57 seconds for `main`, 1,795 chunks, 916 MB of C
source). Compiling 2,303 files took about 37 minutes with three jobs on an
overloaded machine (load 40–50 with two agents); cumulative individual CPU
time was 6,074 seconds, 55 files used `-O0`, the longest file took 273 seconds,
and objects totaled 395 MB. Incremental compilation of changed chunks and
linking the app executable took about 13 seconds. The proposed `recomp-ios`
stage for `scripts/build_all.sh` did not modify that script; the sequence was
`gen32.sh all 3`, `build_ffmpeg_ios.sh`, then `deploy_ios.sh build`, followed
by `install`/`run`. It required `DEVELOPER_DIR` pointed at Xcode,
`work/exefs` with modules and `main.npdm`, and `TEAM_ID` in
`work/local.env`.

### Deployment and measured iPad run

The deployment helper's `run [seconds]` used `devicectl … --console`, wrote
`work/builds/ipad-recomp-<timestamp>.log`, and accepted its environment as
`RUN_ENV` JSON, including `BDSP_INPUT_SCRIPT` and `BDSP_SCREENSHOT_EVERY`.
The `data` command copied the 4.7 GB RomFS (18,028 files) to
`Documents/GameData/romfs` using `devicectl copy to`; USB transfer took under
three minutes. `devicectl` created those directories as root, and the app only
read them. The `save` command copied `SaveData.bin`, `Backup.bin`, and
`user_id.hex` as files into `Documents/`; the app imported them into
`Documents/Saves/save_1`, recorded a hash marker, and backed up the previous
save under `Documents/Backups`. `shots` copied `Documents/Shots` to
`work/visual/ipad-recomp/`. The free provisioning profile allowed only three
apps on the iPad, so the user's `dev.local.xnumemprobe` memory probe was
uninstalled to make room for `dev.local.xnubdsp`.

The measured runs had no touch input; scripted input was used only for the
save. The first frame appeared within a few seconds. Loading 105 MiB of module
images and indexing 18,022 RomFS files took under one second. Footprint was
0.7 GiB at five seconds and 1.57 GiB at ten seconds. The title prompt “Press
the A button” appeared after 4,500–6,000 frames; the capture at
`work/visual/ipad-recomp/frame_06000.png` showed the logo, Dialga silhouette,
and stars correctly. Film, title, and city ran at 50–52 fps; the largest frame
gap was 24 ms, with a brief drop to 35 fps at a scene change. Footprint was
1.56 GiB in film/title and 2.07 GiB in the city (130,000 draw calls per five
seconds), peaking at 2,051 MiB; available memory stayed at or above 6,101 MiB.
`thermalState` remained 0 in all runs, the longest lasting 300 seconds. Peak
guest memory mapped by `MapPhysicalMemory` was 1,718 MiB of the 1.98 GiB
available. The image at `frame_04500.png` showed the red-capped player, an NPC,
a blue-roofed house, conifers, and shadows, and depicted the same city scene as
the Mac capture (aside from the cloud shadow noted above).

### Additional investigation and unresolved behavior

The historical audio freeze appeared after about 100 seconds in the field.
`nn::audio::GetReleasedAudioOutBuffer` read a tag from an uninitialized stack
slot; when the service had no completed buffer, the stale tag made the guest
loop (`while (GetReleased())`) run indefinitely while holding the main
thread's Wwise lock. The service was changed to return tag zero on an empty
response. The earlier log recorded about 74,000 empty polls; after the change
the count was zero. Release pacing remained duration based.

The timed-wait race fix in `block_current` addressed one intro freeze. Before
the fix, three of five runs froze after 200–712 frames with the main thread in
`ArbitrateLock`; a `BDSP_BT=1 BDSP_WAIT=1` report showed mutex `0x601f40c`
owned by thread 113, which was calling `ArbitrateLock` on that same mutex.
This was a self-deadlock in `TimedWait` (`nn::os::TimedWaitEvent`) on the film
path. After `pthread_cond_timedwait` returned `ETIMEDOUT`, `block_current`
reported `R_TIMEOUT` even if the waker (`SignalProcessWideKey`/
`mutex_release`) had already ended the wait and transferred mutex ownership to
the waiter. The SDK then attempted to lock the mutex again. The race was rare,
but frequent in the film with 39 threads on the iPad's multiple cores; it had
not appeared on the Mac. The fix lets the waker's result win when
`wait_kind == WAIT_NONE`. Nine subsequent runs (four × 45 seconds, two × 130
seconds to title, three × 40 seconds) did not show this failure, at 1,480–6,089
frames. The user report that the app “crashes” unless A skips the intro
immediately, after two or three starts, was consistent with skipping the
timed-wait path. No system crash or Jetsam report was found via
`devicectl copy from --domain-type systemCrashLogs`; the guest had hung rather
than crashed, and the entitlement was signed.

A separate, earlier zero-frame freeze remained unresolved. After the race fix,
two logs (`work/builds/ipad-recomp-20261019-171301.log` and
`…-171815.log`) showed a 526 MiB footprint; main thread 80 and audio thread
113 were both in `SendSyncRequest`. The main thread was in the touch-query
`hid` call, with no SVC for 31–36 seconds; other threads were queued. SVC
0x32 counted 140 calls and SVC 0x33 counted 68–70, so the Boehm GC's
suspend/resume calls were unbalanced. The proposed explanation was
unconfirmed: the GC may suspend the main thread during IPC while it holds a
host lock (`seen_lock` in `ipc_count`, or malloc), then the suspending thread
may call IPC and deadlock on that lock. A trial that suspended only outside
SVC sections (`in_svc`/`suspend_pending`) froze at zero frames in three of
eight iPad runs, no improvement over the earlier one in twelve and one in
seven with this symptom. That change was reverted at the user's direction;
`kernel.c` and `bdsp.h` returned to the timeout-fix-only state. The last app
installed on the iPad still contained the reverted trial, so a fresh repo
build was required. The next diagnostic proposed was `BDSP_TRACE_SYNC` plus a
count of suspended threads in the result report, to identify a suspended
thread before attempting another fix; `BDSP_SUSPEND_STRESS=1` on Mac was the
suggested reproduction probe. The dated estimate was one such freeze per
8–12 starts, with the cause only suspected as GC suspension during IPC.

At startup, the approved path displayed only “shader compilation n / N” at
the upper left. Runtime started on its own thread after `viewDidAppear`, so
the UI main thread did not block. Watchdog time was excluded; footprint was
0.7 GiB after five seconds with no Jetsam event. The trial observations do not
authorize changing that startup gate or repeating device launch loops.

The alternative HEVC path was not implemented because software VP8 at 720p/30
had no dropped frames. The retained fallback proposal was
`scripts/video_convert.sh` with libx265 CRF 18 and `hvc1` (41% larger files),
plus VideoToolbox in `movie_glue`; HLE would swap the file internally while
preserving guest duration and frame count. Estimated effort was one to two
days, only if film CPU load reduced the frame rate.

Other dated gaps: water had not been visited on iPad. The renderer was the
same cloned `renderer.m`/`metal.m`, unchanged on iOS except for Depth24 format
and the window, so code inspection did not predict a Mac/iPad difference; the
issue belonged to the Metal/NVN side (`ap-recomp-qa`). Long play and battles
had not tested the 1.98 GiB guest-memory limit. Touch, controller, and keyboard
hardware behavior had not been manually tested; scripted `g_ext_buttons`
input covered A presses and walking. Opening files through the Files app was
not checked despite `UIFileSharingEnabled`. Performance was not capped at 60
or 30 fps: 50–52 fps exceeded the 30 fps target but was not tied to the
ProMotion refresh rate.

The historical Mac reproduction used:

```sh
scripts/recomp/ios/gen32.sh all 3
scripts/recomp/ios/build_ffmpeg_ios.sh 9.0.2 2
scripts/recomp/ios/build_rt32.sh mac
BDSP_IMG=work/recomp/img32 work/recomp/bdsp_boot32 --headless --save work/recomp/save --timeout 170 \
  --input-script "100:A:0.4,110:A:0.4,120:A:0.4,130:A:0.4" --screenshot-after 600
```

The device sequence was `deploy_ios.sh build && deploy_ios.sh install`, then
`deploy_ios.sh data && deploy_ios.sh save` once, followed by
`RUN_ENV='{"BDSP_TIMEOUT":"130"}' scripts/recomp/ios/deploy_ios.sh run`.
The historical notes also recorded one `sed -i` type correction in
`scripts/recomp/ios/app/app.m` instead of the preferred `edit` operation (the
content was checked), and background jobs that died when the tool ended and
were restarted with `nohup`.
