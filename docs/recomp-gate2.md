# Recompilation, Gate 2 “Graphics” (`ap-recomp` Gate 2)

Status: 2026-10-19, interim (updated after each phase). Based on `docs/recomp-gate1.md` (Gate 1 reached), `docs/recomp-machbarkeit.md`, `docs/shader-translator.md`, and `docs/referenz-las-shader.md`. Task: draw the first image through Metal in the recompiled game (macOS arm64, **no audio**); criterion: screenshot contains a recognizable, non-black start screen.

**Labels:** **measured** = obtained from runs under `work/recomp/` (M1 Pro, 16 GB, load 11–19 from other processes, window hidden); *suspected* = inference without a test. No game binaries, generated code, shaders, or images are in repository (screenshots, shader cache, and dumps under `work/recomp/`).

## Summary

| | |
|---|---|
| **Gate 2** | **Reached and exceeded (Metal):** with a save file, run shows in sequence (screenshots inspected) the **opening movie** (VP8 WebM, “Pokémon Brilliant Diamond” logo on blue sparkling background), **title screen** (“Pokémon Brilliant Diamond”, “Press A Button”), then after A the save's **3D city** (player in red hat, NPC, blue-roofed house, trees, shadows)—see phase 3. Without save, language-selection screen appears (phase 2). Images: `work/recomp/shots/gate2_film_metal.png`, `gate2_titel_metal.png`, `gate2_stadt_metal.png`, `gate2_sprachauswahl_metal.png` (never in repo). 40–51 fps. |
| Blockers | None for Gate 2. Still open: water on left of city is white rather than blue; camera offset 28 px from Ryujinx reference (timing); title text “Press A Button” is red rather than white (*suspected*: color animation or translator bug); storage buffers/compute through wrapped guest memory (phase 2). |
| RSS | 400–1,100 MiB (peak 1,103 MiB after 60 s); Metal buffer 5,069 MiB (reserved/address space only, pages allocated lazily) |
| Missing NVN functions | 495 of 524 present; of 29 missing, 22 actually exist in LAS layer (name-list count error), 2 provided by glue (`nvnBootstrapLoader`, `nvnDeviceGetProcAddress`), 7 debug checkpoints are no-op stubs. **In run: 0 called functions without host implementation.** |
| Shaders | LAS translator: **2,977/2,977** BDSP programs fail with “bindless tex” (100%). Our translator (`shader_translator/`): **0 errors** across 5,959 programs created; all Metal compilations succeed. Our translator selected. |
| Found and fixed (kernel) | **Two Gate 1 kernel bugs that stopped real Unity run after seconds** (lost wakeup, self-deadlock after timeout); see Kernel section |

## Graphics layer structure (`scripts/recomp/rt-bdsp/nvn/`)

| File | Contents |
|---|---|
| `prepare.sh` | **Copies** LAS source `scripts/recomp/upstream/runtime/nvn` (MIT, vendored, unchanged) to `work/recomp/nvn-src` (none kept in repo), places replacement headers from `shim/` alongside, replaces `maxwell/translate.c` and `shader.h` with `shader_translator/`, applies `las-nvn.patch`. Excluded: Vulkan portion, `texpatch.c` (Zelda texture tables), `output_scale.c`, `smaa_data.c`, all game hooks. |
| `las-nvn.patch` | Our changes to LAS sources (14 sections, listed below) |
| `shim/` | Replacements for clone's `rt.h`, `hle.h`, `platform.h`, `kernel.h`, `paths.h`, `settings.h`, `ui/menu.h`, `texpatch.h`: only what's needed by `objects.c`, `cmdbuf.c`, `renderer.m`, `metal.m`; address space and heap come from BDSP runtime |
| `nvn_glue.c` | `nvnBootstrapLoader`/`nvnDeviceGetProcAddress` (function table by name), 9 bound imports from `main` (5 nn::vi, 3 nv), application-memory wrapper for Metal buffer, output size, 7 checkpoint stubs, no-op stubs for clone game hooks (widescreen, Zelda effects, menu, input, restart) |
| `build_nvn.sh` | Incrementally builds objects (Apple Clang for Objective-C: Homebrew LLVM emits class stubs that Apple linker cannot resolve); `NVN_KEEP=1` prevents recreation of copied tree (development) |

**Backend selection** (`build.sh`, `NVN_BACKEND` env): `metal` (macOS, default), `vulkan` (not implemented yet, exits with message), `none` (no graphics, `-DBDSP_NVN_NONE`: SDK NVN driver remains, Gate 1 behavior; default on Linux, objects under `work/recomp/rt-bdsp-none`). On Linux, `build.sh` automatically adds `scripts/recomp/linux/compat` (Mach shim); ELF section table for `HLE_FUNC` (`__start_hle_impls`) is prepared in `shim/hle.h`/`nvn_glue.c`. **Not tested on Ryzen.**

Designed backend-independent shared layer: `objects.c` (objects, builders, pools), `cmdbuf.c` (command recording in guest memory), `tegra.c`/`formats.c`/`astc.c` (block-linear layout, formats, ASTC decoder). Metal-specific: `renderer.m` (execute commands, pipelines, render targets) and `metal.m` (window, textures, presentation). Clone's Vulkan equivalents are `vulkan/*.c` (see Vulkan path section).

## Runtime changes (`rt-bdsp/*.c`)

| File | Change |
|---|---|
| `main.c` | **Main thread owns window** (`ui_run`, SDL3/AppKit); monitor (`monitor_loop`) runs on a thread. Options: `--screenshot-after N` (frame N and every N frames thereafter to `work/recomp/shots`; `BDSP_SHOT_DIR` changes directory), `--exit-after-shot`, `--headless` (window never visible), `--window WxH`, `--no-window`, `--timeout S`. Gate 1 stop now requires `BDSP_STOP_AT_GATE=1`. |
| `kernel.c` | **Bug 1:** `WaitProcessWideKeyAtomic` set key *after* releasing mutex; SDK calls `Signal` only if key ≠0 and reads it without kernel lock → lost wakeup (Unity semaphores: main and render threads wait on each other; 100% of runs after 1–5 s). Now set key first. **Bug 2:** on **timeout**, kernel reacquired mutex but SDK then locks it again → self-deadlock at first `TimedWait` (5 ms). Now match real Horizon: don't reacquire. Also `kernel_phys_range` (wrapper over `MapPhysicalMemory` ranges), synchronization SVC trace (`BDSP_TRACE_SYNC=n`), per-thread backtrace (`BDSP_BT=1`). |
| `dispatch.c` | Per-host-function call counts (`BDSP_NVN_STATS=1`), trace first n calls (`BDSP_TRACE_HLE=n`), report imports without host implementation, per-thread function ring (`BDSP_FNPROF=1 BDSP_RINGDUMP=n`) |
| `services_audio.c` (new) | **Silent** audio services: `audout:u` (IAudioOut buffers “played” in real time and returned), `audren:u` (IAudioRenderer/IAudioDevice, empty responses), `hwopus` (work-buffer sizes, 0 samples), `audin:u` (error). No sound. |
| `services.c` | `acc:u0` command 131 (open users), `ITimeZoneService` command 202 |
| `services_net.c` | `bcat:u` reports success (otherwise `nn::bcat::Initialize` aborts) |
| `services_gfx.c` | `vi_vsync_handle` for bound `GetDisplayVsyncEvent` (60 Hz) |

## Phases

### Phase 1: NVN layer integrated, first image, measurement

Obstacles found, in order (with cause):

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | `nvnBootstrapLoader` has no effect | HLE slots from `mkimages.sh --hle-list` had no function | `nvn_glue_init` binds `HLE_FUNC` entries to slots; `hle_nvn.txt` now has 9 names (nvnBootstrapLoader, nn::vi::Initialize/OpenDefaultDisplay/CreateLayer/GetNativeWindow/GetDisplayVsyncEvent, nv::InitializeGraphics/SetGraphicsAllocator/SetGraphicsDevtoolsAllocator) |
| 2 | Abort at `nn::audio::ListAudioOuts` | `audout:u` was error stub | Silent audio services |
| 3 | Crash at `nvnCommandBufferBindProgram` (program `NULL`) | Unity passes NULL | `cmdbuf.c`: allow NULL |
| 4 | Hang after seconds | Kernel bugs 1 and 2 (above) | `kernel.c` |
| 5 | Crash at `nvnMemoryPoolMap(0)` | `nvnTextureGetMemoryPool` returned 0 | Remember pool pointer |
| 6 | Abort in `nn::bcat`, `GetReleasedAudioOutBuffer` busy loop (17 million IPC) | Service stubs | `bcat:u`; throttle queries |
| 7 | All draw calls skipped | Unity binds **separable programs** (one `NVNprogram` per stage, stage mask in `nvnCommandBufferBindProgram`); LAS binds one program with every stage | `renderer.m`: combine stage programs into one |
| 8 | Everything magenta (error shader) | `nvnDeviceGetInteger(0x5e)` returned 0; Unity then treats most shaders as unsupported (2,654 instead of 5,959 programs; rest “unsupported,” error shader). Value is probably **GPU code version**; shaders' control sections have `1, 0x10` | Return **16** (`BDSP_DEV94` sets it): Unity now creates 5,959 programs. Values 1 and 288 behave like 16. |
| 9 | LAS translator: “bindless tex” for every shader | Unity shaders read texture handles bindlessly (`TEX.B`) from constant buffer 2 (texture at `0x568`, sampler at `0x168`, 8 bytes each) | Use **our translator** instead of LAS translator (supports TEX.B); `renderer.m` builds handle from `nvnCommandBufferBindSeparateTexture` (texture) and `BindSeparateSampler` (sampler, new `CMD_BIND_SAMPLERS` command), sets `no_rscale` |
| 10 | Textures black (“partial WriteTexels,” 1,232 messages) | `nvnTextureWriteTexels` only wrote mip 0 for whole textures | Use mip and layer from view; support arbitrary region with read-modify-write |

**Measurement, run to 280 s (`--headless`):** 35 threads, 25 distinct SVCs, 1.1 million SVCs per 60 s (mostly Unity job mutex/condvar), 30,855 IPC per 60 s (100 distinct service/command pairs; 4 default responses: `IParentalControlService` 1, `ICommonStateGetter` 66, `acc:u0` 130, `IAudioController` 0), 0 exceptions, 0 unwound frames, 0 guest log lines (release build). 45–47 fps, GPU time 40–75 ms per 2 s (Metal: 7 draw calls, 3–4 passes/frame). Memory: **RSS 400 MiB–1.1 GiB**, 1.2 GiB of 3.14 GB MapPhysicalMemory committed.

**Last guest RomFS accesses (in order):** `globalgamemanagers`, `resources.assets(.resS)`, `unity default resources`, `Dpr.bin`, `Dpr/masterdatas`, `Dpr/shaders`, Wwise bank `Delphis_Main.bnk` (+ `.wem`), `Dpr/scenes/title`, fonts (`efigs`, `jpn`, `sch`, `kor`), `scriptableobjects/gamesettings`, `fieldui/main`, `Pokemon Database/pokemons/*pm0446*` (Munchlax). No further reads after that.

**Image:** First frames (t=6 s) black, then magenta (error shader, step 8), then black again after steps 8–10. Debug dump of frame 1,500 (`BDSP_DEBUG_FRAME`): one 1280×720 render target (game renders 1280×720 into 1920×1080 window image), 7 draw calls: full-screen quad (mode 7, 4 indices) and 6 meshes (1,086, 48, 96, 54, 6, and 384 indices) sampling a **2048×2048 ASTC atlas** (format `0x7d`, 1.4–1.6 MB nonzero) and a 1024×1024 atlas. Atlas is **recognizable** in dump (character selection images, clouds and crystal background, UI panels), so ASTC → block-linear → Metal → bindless sampling works. Fragment constant color factor (`fubo0`) is `[0 0 0 0]` for these calls: image is in a fade-to-black transition.

### Phase 2: reveal game flow, fix black image, load save, input

**Tool: IL2CPP names at runtime.** `scripts/recomp/il2sym.py` reads `global-metadata.dat` (version 24) and main-module memory image, writes `work/recomp/il2sym.tsv` (68,183 methods: address/name; names only, no game binaries in repo). With `BDSP_IL2SYM=work/recomp/il2sym.tsv`, runtime reports **each game method on its first call** (`[il2] <ms> t<Thread> <Name>`; forces function-entry hook and is somewhat slower); `scripts/recomp/symres.py` adds names to guest addresses in reports (crashes, `BDSP_RINGDUMP`). Game flow is now visible (measured, first launch without save): `GameController..cctor` 0.7 s · `SaveSystem.Load/MountSaveData` 1.2 s · asset manifest 1.3–4.6 s · Wwise init and `LoadInitBank` 6.7 s · master data (`XLSXContent.*`) 7–10.7 s · `nn.oe.Language.GetDesired` 10.75 s · scene change 18.6 s · **`OpeningController.OpenSelectLanguage` 22.0 s**. Game was **not hung**: it was waiting for input at language selection (earlier timing/`audren`/fence/Vsync hypotheses are ruled out; `GetSystemTick` and `cntvct` run at 19.2 MHz).

**Black image (measured, cause found).** Vulkan branch rendered same 7 calls visibly, so fault was in Metal execution, not guest logic or constant buffers. Calls had valid vertices (white vertex color, 1280×720 background quad), matrices, indices, viewport. “Color factor 0” from phase 1 was a false lead: `f0=[0 0 0 0]` is UI program's `_TextureSampleAdd`. Key tests: (a) set each fragment output to solid color (`BDSP_FS_RED`) → only first draw call (no index buffer) appeared; (b) also derive vertex position from `vertex_id` (`BDSP_VS_TEST`) → still nothing, so indexed draw calls were **not seeing valid index/vertex data**; (c) copy data through ring buffer (`BDSP_NO_GUEST_BUF`, now default) → full language-selection screen appears. Cause: guest memory was wrapped as one Metal buffer (5,069 MiB, `newBufferWithBytesNoCopy`); pages had never been written when wrapped, and GPU did not see pages subsequently written by guest (*suspected*: shared zero page replaced on first write by copy-on-write; `UnmapPhysicalMemory` does **not** happen during run, 0 calls in 30 s, so pages are not being discarded). Fixed in `fixes.patch`: vertex/index data go through ring; `BDSP_GUEST_BUF=1` restores old path. **Still open:** storage buffers/compute (`uses_gmem`, compute skinning, particles) still read wrapped buffer; needs pre-touched pages or ring dump with writeback. Ring cost: RSS 1.5 GiB at language selection (was 0.4–1.1 GiB); 51 fps (was 46).

**Bindless textures.** `fixes.patch` swaps texture/sampler tables (textures from `0x168`, samplers from `0x568`; Vulkan finding, affects 847/3,592 fragment programs). Metal language-selection text is now legible (“Select the language you would like to play in.”; Vulkan branch had broken glyphs before its fix).

**Image description** (screenshot frame 2,600, 1920×1080 target, visually inspected): upper-left 1280×720 crop (rest black: game's `nvnWindowSetCrop` does not reach presentation, Vulkan change request 2, still open), light-blue crystal background; two columns of five buttons (left: English [selected, red border], Español, Français, Deutsch, Italiano; right: にほんご, 日本語, 한국어, 简体中文, 繁體中文); text box at bottom with English sentence. System font (`nn::pl`) not used; text comes from game font assets (TextMeshPro SDF atlas).

**Save file.** `scripts/recomp/rt-bdsp/install_save.sh` copies a Ryujinx save (source `BDSP_SAVE_SRC` = directory containing `SaveData.bin`/`Backup.bin`, optional `BDSP_SAVE_EXTRA` = directory with `ExtraData0`; or same variable names in `work/local.env`) to `work/recomp/save/save_1` (account type 1, matching guest request; previous version moves to `backup-<time>/`; output logs sizes and hashes only), and writes user ID from `ExtraData0` (bytes 8–23) to `work/recomp/save/user_id.hex`; `acc:u0` reports this ID (`user_id_load`). Option `--save <dir>` (default `work/recomp/save`). Game queries `main2` and `SaveData.bin` (`[fs-save]` log, `fsp-srv` 51/53, `IFileSystem` 7/8) and opens `SaveData.bin`. Expected current test-save hash: `SaveData.bin` 979,108 bytes, SHA-256 `0396a4a62735…` (verified match), `Backup.bin` `7a324b865ea9…`. **Result:** with save, `OpenSelectLanguage` is skipped; flow proceeds to `Title.Start` (23.5 s). **Ryzen:** `scp Ryujinx/bis/user/save/0000000000000006/0/{SaveData.bin,Backup.bin} <RZ_HOST>:<REMOTE_DIR>/work/recomp/save/save_1/` and `ExtraData0` → `user_id.hex` with same command as script (`dd … | xxd -p`), or run script there with `BDSP_SAVE_SRC` (writes only under `<REMOTE_DIR>/work/recomp/save`, never repo tree).

**Title scene and video.** `Title.PlayOpeningSequence` launches opening movie (`Movie/<language>/Opening/movie_*_op.webm`, VP9) through `SwitchVideoPlayer` (SDK's Stagefright/OMX, hardware decoder via `nvdec`). Finding: signal 11 in `strcasecmp(…, NULL)` in `android::OMXCodec::findMatchingCodecs`, because codec list is empty (no OMX component registry). Workaround: NULL-safe `strcasecmp` HLE (`nvn_glue.c`, `hle_nvn.txt`): search returns empty and run remains stable (tested 100 s). Afterward game calls `GetCurrentTime`/`GetVideoLength` every frame and waits for movie end; image remains black. **Next step:** replace host video-player timing (report movie ended; Unity functions lack symbols, resolving via `icall` table is open) or supply decoder (`mm:u`/`nvdec` ioctls, VP9 via FFmpeg/libvpx, video only, no sound).

**Input (`hid`).** SDK functions `nn::hid::GetNpadState`/`GetNpadStates` (five state types each) and `GetNpadStyleSet` are replaced with HLE (`nvn_glue.c`, based on clone `runtime/hle/input.c`): player 1 is connected Pro Controller; window keyboard (Enter/Space/K = A, Backspace/J = B, X, Y, arrows and WASD = D-pad, Q/E = L/R, P = Plus, O = Minus) and test script `--input-script "second:BUTTON[+BUTTON]:duration,…"` (from process start, e.g. `26:A:0.4,32:A+DOWN:0.2`; `BDSP_TRACE_INPUT=1` logs it). Measured: game reads button (`buttons 0x1`), but in title scene it does not advance while movie is running.

**Debug hooks and patches.** `nvn/fixes.patch` (ring buffer instead of wrapped guest memory, texture/sampler tables; always applied) and `nvn/debug.patch` (only with `NVN_DEBUG=1 prepare.sh`): `BDSP_FS_RED` (solid color per fragment program; UI green, rest red), `BDSP_VS_TEST` (position from `vertex_id`), `BDSP_DUMP_VUBO` (with `BDSP_DEBUG_FRAME=N`: render target, viewport, constant buffers per call), `BDSP_DUMP_IDX` (initial indices). Runtime: `BDSP_IL2SYM`, `BDSP_TRACE_UNMAP`, `BDSP_TRACE_INPUT`, `[fs-save]`.

**Measurement (M1 Pro, 16 GB, hidden window):** language selection (no save): about 22 s to first image, 2,791 frames in 58 s, 51 fps, 7 draw calls and 309 passes per 2 s, RSS 1,500 MiB (peak 1,537), 37,362 IPC requests, 1,612 RomFS reads (148 MiB), 0 NVN functions without host implementation. Title scene (with save): title at 23.5 s, 4,337 frames in 100 s, 51 fps, peak RSS 793 MiB, 1,668 RomFS reads (160 MiB).

**Note:** “Title scene and video” above describes pre-phase-3 state (the `strcasecmp` workaround); movie now runs through `movie_glue.c`.

### Phase 3: movie, title, load save, city

**Movie (`nvn/movie_glue.c`, new).** Unity `SwitchVideoPlayer` uses Android-style `movie::` interface (nnMedia: `Extractor`, `Decoder`, `MediaData`, `Buffer`; 23 imports served by SDK Stagefright/OMX and hardware decoder). `movie_glue.c` replaces it with FFmpeg (design and parts based on LAS clone's `runtime/hle/movie.c`, MIT, adapted for BDSP; NOTICE applies): `Extractor` opens `rom:/Data/StreamingAssets/Movie/<language>/Opening/*.webm` from RomFS folder and exposes **video track only** (no sound); `Decoder` outputs NV12 (VP8, 1280×720, 30 fps; opening `movie_*_op.webm` and title loop `movie_*_op_loop.webm`). Findings (measured): (a) game also calls `SetDataSource` through **vtable slot 2** (path in x1), not only directly; (b) player provides output buffers itself (`Buffer::SetDataAndCapacity`, memory in guest pool) and reads frame **from there** (`nvnCommandBufferCopyBufferToTexture`, R8 1280×720 and RG8 640×360). Thus `GetOutputBuffer` must **write into the player's buffer**, not return its own (initial attempt produced green area because data was all zero). `hle_nvn.txt` binds 23 `movie::` names to host functions (`mkimages.sh` with `HLE_LIST`). Build links FFmpeg through `pkg-config` (Homebrew; `BDSP_NO_MOVIE=1` builds without it). Linux/Vulkan: same source, requires FFmpeg development packages (`ffmpeg-free-devel`) *(not built yet)*. Earlier `strcasecmp` workaround remains registered but is no longer reached.

**Flow** (save-file run, input script `--input-script "75:A:0.4,85:A:0.4,95:A:0.4,105:A:0.4"`, measured): title scene after 20–23 s; opening movie; title screen (“Press A Button”) after movie (frame 2,400 in run without script); press A → **load save** (`PlayerWork`/`FieldPlayerEntity`, `EvDataManager`, `KinomiResources` in log) → save's **city scene** after about 100 s. Stable through 150 s (no crash, 39 threads, 4,306 frames, peak RSS 1,041 MiB, 2,695 RomFS reads/229 MiB, 1.7 million SVC calls, 1,704 MiB via `MapPhysicalMemory`, 44 fps in city, 40,320 draw calls and 720 compute dispatches per 2 s ⇒ **compute skinning/particles now run**, 0 skipped draw calls).

**Repeat with clean build** (run 12, without `NVN_KEEP`, script `62:A:0.4,72:A:0.4,82:A:0.4,92:A:0.4`, measured): `SaveSystem.Load` 1.1 s · `Title.Start`/`PlayOpeningSequence` 21.9 s · first A press 62 s · `EvDataManager.EnvironmentControllerCallBack` (field setup) 75.0 s · `FieldPlayerEntity.CheckSwim` (player in field) 91.1 s · same city image (frame 3,600, 45 fps, 45,864 draw calls and 819 dispatches per 2 s). About 22 s to title, about 29 s from A press to city.

**City image description** (screenshot frame 4,200, 1280×720, visually inspected): overhead view of paved street in purple/gray-blue herringbone pattern and soft shadows; small blue-roofed house with turquoise door on left, three shrubs in white planters in front; player character (red hat) center and brown-haired man to right; rows of conifers on right; red-roofed building (Pokémon Center-like) near upper center; wooden structure upper left. **Compared with Ryujinx reference** (`work/visual/ref/ryujinx/views/ref_01_feld_weiter.png`, same scene, user's F8 frame; calculated with numpy, not `visual_compare` because its `ref compare` expects Unity images): camera is **28 px to the right** (camera-motion timing); mean recomp RGB (109.7/122.1/120.0) vs reference (106.2/120.0/118.3); after shift, mean absolute differences 16.5/17.1/15.2 per R/G/B channel, 19.8% pixels differ by >40 (edges/shadows; shift is approximate). Colors, shadows, characters, and models otherwise match. **Differences:** **water on left** is blue in reference but white in recomp; red “Press A Button” title text has not been checked against reference.

**FPU environment (`ap-recomp-diff`):** `rt_fp_guest_mode()` (`scripts/recomp/c_exact/fp_env.h`) at each guest-thread start (`kernel.c`, `thread_main`) and after every SVC (`rt_svc`): on arm64 FPCR = 0 (RN, FZ = 0, DN = 0).

**Cross-platform:** four `#include` lines (`SDL3/SDL.h`, `stdatomic.h`, `string.h`, `strings.h`) are no longer inside `__APPLE__` block in `nvn_glue.c` (request from `docs/recomp-vulkan.md`). `nvnWindowSetCrop` now reaches Metal presentation (`fixes.patch`: screenshot is 1280×720 rather than 1920×1080 with black border); `nvn_window_crop()` in `objects.c` is also available to Vulkan path.

## Shader choice: measurement

| | LAS translator (`runtime/nvn/maxwell/translate.c`) | Our translator (`shader_translator/translate.c`) |
|---|---|---|
| Programs in run (`nvnDeviceGetInteger(0x5e)` = 16) | 2,977 requested, **2,977 failures** (“bindless tex”: 2,941 fragment, 36 vertex) | 5,959 created, **0 errors** in translation or Metal compilation (no “pipeline failed”) |
| Corpus coverage (`docs/shader-translator.md`) | not measured (fails on first TEX.B) | recognized 13,710/13,710 programs (100%); fidelity test uses 500 pairs |
| Missing opcodes/features per corpus | TEX.B, HSETP2 (cbuf/imm) | none; remaining gaps: STG/second storage buffer, 64-bit integers, subgroup instructions, compute (not needed yet) |

No switch to LAS translator is planned: its Zelda specialization (fixed texture bindings) does not fit Unity. Measured is the path to an image, **not pixel fidelity against our guest-run references** (fidelity test is offline: `scripts/shader_fidelity.py`).

**Compute skinning (5 programs), instancing, MRT, particle storage buffers:** **not reached** in current run (0 `nvnCommandBufferDispatchCompute`, no MRT pass); remains open and can be measured only with more game progress.

## Open items (priority order)

1. **Title movie** (see phase 2): replace video player through host (report movie end/time) or provide decoder; then title screen (“Press A”) and advance with A.
1b. **Crop/target size:** game renders 1280×720 into 1920×1080 window image and calls `nvnWindowSetCrop`; crop does not reach presentation (image upper-left, rest black). Feed `WIN->crop` into presentation in both backends.
1c. **Wrapped guest memory** for storage buffers/compute (phase 2).
1d. Call `rt_fp_guest_mode()` (`scripts/recomp/c_exact/fp_env.h`, recommendation from `ap-recomp-diff`: disable FTZ/DAZ, RN, FPCR 0) at each guest-thread start and after host calls *(not yet integrated)*.
2. Handle `audren:u` request/response (timing/replies) only once guest asks; so far only `audout:u` is served, no audio output.
3. Frame pacing: currently 60 Hz Vsync event from host thread (`services_gfx.c`); window's `PresentInterval` is not used; no real sync to Metal display.
4. Input: keyboard/script exists (phase 2); controller through GameController/SDL and sticks are missing.
5. Memory model B (iPad, 4 GiB): open (see Gate 1); Metal buffer covers whole `MapPhysicalMemory` mapping (5.07 GiB address space), impossible in variant B.

## Vulkan path (Linux/Windows), preparation status

| Item | Status |
|---|---|
| Sources | LAS: `runtime/nvn/vulkan` (6,019 lines: `device.c` 709, `exec.c` 3,789, `shaders.c` 454, `textures.c` 858, `vma.cpp`, `vk.h`, `imgui_glue.cpp`), `runtime/platform/linux.c`, `docs/linux.md` (x86-64, Vulkan 1.3, AVX2; clang, SDL3, FFmpeg, shaderc, VMA) |
| Shared layer | `objects.c`, `cmdbuf.c`, `tegra.c`, `astc.c`, `formats.c` are backend-independent and reusable unchanged for Vulkan; `renderer.m`/`metal.m` are Metal-specific and would be replaced by `vulkan/*.c` |
| Shader path | **Difference:** LAS Vulkan path translates Maxwell **to GLSL through same translator** (`key->glsl`, with `glsl_rewrite()` converting MSL body to GLSL) and compiles **to SPIR-V at runtime with shaderc** (disk cache `cache/spirv`). Our translator's GLSL branch is **untested and does not implement TEX.B** (`docs/shader-translator.md`, section 3.6); instead it has HLSL branch (`key->hlsl`, for Unity wrapper, no compute). Three Vulkan routes: (A) add TEX.B to GLSL branch and use shaderc as LAS does; (B) HLSL → DXC/glslang → SPIR-V (offline possible: 13,710 programs, 2,859 code bodies); (C) MSL → SPIRV-Cross (not available). **Recommend (A)** because LAS draw layer expects GLSL bindings (contract in `shader.h`); *suspected* effort 1–2 weeks (TEX.B/bindless in GLSL: texture array or descriptor indexing, Vulkan fidelity test). |
| Build | `NVN_BACKEND=vulkan` is declared but not implemented; `prepare.sh` deliberately does not copy Vulkan portion yet |
| Missing | window loop (SDL3, Vulkan surface); renderer support for `CMD_BIND_SAMPLERS`/separate textures and separable programs (both implemented in `renderer.m`, not `exec.c`); 16 KiB/4 KiB page size (`plat_*`; macOS 16 KiB); Linux Mach shim in `kernel.c` (signal-based suspension; available under `scripts/recomp/linux/compat`) |

**Packages for Ryzen host (`<RZ_HOST>`), for user to install (agent does not use sudo):** `vulkan-headers`, `SDL3-devel`, `ffmpeg-free-devel` (LAS video only; not required by BDSP), `shaderc-devel`, `VulkanMemoryAllocator-devel`. Per task, Vulkan loader, `vulkan-tools`, RTX 2080 Ti are present. Without these packages, `NVN_BACKEND=none` still builds (Gate 1 behavior).

## Changes to LAS sources (`las-nvn.patch`, `fixes.patch`, `debug.patch`)

`fixes.patch` (after `las-nvn.patch`): vertex/index data through ring, bindless texture/sampler table; `debug.patch`: debug hooks (only with `NVN_DEBUG=1`). `las-nvn.patch` contains:
`cmdbuf.c`: NULL program, record separate samplers · `metal.m`: memory range from kernel layer, screenshot directory, window title · `nvn.h`: texture pool pointer, `CMD_BIND_SAMPLERS` command · `objects.c`: `nvnDeviceGetInteger(0x5e)`, `nvnTextureGetMemoryPool`, `nvnTextureWriteTexels` (mip/layer from view, regions) · `renderer.m`: separable programs, bindless textures (`shader_handle`), sampler state, translator debug hooks, shader cache at `work/recomp/cache/shaders` (LAS wrote to `cache/` in working directory: **never put it in repo**), disable clone tint, `no_rscale`. Patch applies to fresh clone and produces same copy as working tree (checked by `diff -r`).

## Reproduction

```
scripts/recomp/rt-bdsp/nvn/prepare.sh                         # LAS sources + patch + translator to work/recomp/nvn-src
IMG=work/recomp/img_gfx HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh
scripts/recomp/rt-bdsp/build.sh                               # Metal backend (macOS); NVN_BACKEND=none for Gate 1 behavior
BDSP_IMG=work/recomp/img_gfx work/recomp/bdsp_boot --headless --timeout 120 --screenshot-after 600
# Phase 2: named logs, save, input (images to work/recomp/shots)
python3 -I scripts/recomp/il2sym.py                                                       # work/recomp/il2sym.tsv
BDSP_SAVE_SRC=<Ryujinx>/bis/user/save/<id>/0 BDSP_SAVE_EXTRA=<Ryujinx>/bis/user/save/<id> scripts/recomp/rt-bdsp/install_save.sh
IMG=work/recomp/img_gfx2 HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh
BDSP_IL2SYM=work/recomp/il2sym.tsv BDSP_IMG=work/recomp/img_gfx2 work/recomp/bdsp_boot --headless --timeout 100 --save work/recomp/save --input-script "26:A:0.4" --screenshot-after 1500
# NVN_DEBUG=1 scripts/recomp/rt-bdsp/nvn/prepare.sh  (debug hooks from debug.patch)
# Diagnostics: BDSP_NVN_STATS=1 BDSP_BT=1 BDSP_TRACE_SYNC=3000 BDSP_TRACE_HLE=5000 BDSP_TRACE_IPC=1 BDSP_LOG_FILES=1 BDSP_DEV94=16
```

License: `scripts/recomp/rt-bdsp/NOTICE.md` (section “NVN layer”), license text `LICENSE-LASRecomp`.
