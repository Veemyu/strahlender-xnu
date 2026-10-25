# Rendering: the Metal renderer, debugging, performance, frame rate, water

Everything about how the native macOS build draws and how fast: what "looks like the original" means, how rendering errors were
found, what limited the frame rate, the counters to measure with, frame pacing, and the findings about the water. The NVN layer
itself is described in [architecture.md](architecture.md), the shader translator in [shaders.md](shaders.md).

## 1. Fidelity goal

The game must look like the original. The game's own command stream and shaders run, so the work is to make the NVN-to-Metal layer
faithful. Settings measured in the game data: the **built-in render pipeline** (no SRP), **gamma** color space, one quality level
(shadows on, distance 20, no MSAA setting; the G-buffer itself is 4x multisampled), GPU skinning on. The game renders 1280x720
internally. Reference images come from Ryujinx (copied by hand into `work/visual/ref/ryujinx/raw/`); the language selection screen
is pixel-identical to Ryujinx (SSIM 0.999), city colors are close, water was the long-standing difference (section 6).

## 2. Finding: no MSAA resolve (Professor Rowan missing)

**Symptom.** In the intro the professor, the Munchlax next to him and the bokeh background did not render: a flat blue screen with
the text box. Every draw of the models reached the GPU with valid data, so it looked like a geometry problem.

**Cause.** The scene draws into a 4x multisample G-buffer. Three things in the NVN to Metal layer did not handle that:
- `NVN Downsample` (the MSAA resolve) went through `copy_texture` to a sampled draw, which bound the multisample texture to a
  `texture2d` fragment input. Metal drops such draws, so the resolved image never received the models.
- The pipeline for `clear()` was cached without the sample count, so clears in the multisample pass used a 1-sample pipeline.
- Depth-only multisample passes got a 1-sample pipeline (the sample count was only taken from colour attachments).

**Fix.** `copy_texture` resolves with a render pass (`MTLStoreActionMultisampleResolve`); `pass_samples()` gives the pass's sample
count (colour, else depth) to the pipeline, its hash and the `clear()` cache key.

**How it was found.** `MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1`, messages grouped by text: 6835 "incorrect type of texture
(MTLTextureType2DMultisample)" and 4558 "sample count does not match" per run, none after the fix. Before that, hours went into
per-draw measurements that only ruled things out. **Run the Metal validation first** when something is drawn but not visible.

## 3. Finding: compute work group size read too late

**Symptom.** Vertex explosions (giant stretched triangles) on skinned objects such as the computer terminal in the Pokémon Center,
a missing or shredded cap on the player, shadow errors in the nurse room. Intermittent: about every second run, depending on how
the scene was entered.

**Cause.** `compute_program` read the work group size of a compute shader at its first dispatch from the game's control block
(`control + 0x748`). The game owns that block and may reuse it once `nvnProgramSetShaders` has returned. The log showed a
different size for the same program in nearly every run, mostly garbage and `64x1x1` only when the block happened to be intact.
With a size of 1 the skinning program computes only a fraction of the vertices, and the draws read the rest unwritten.

**Fix.** `nvnProgramSetShaders` copies the three values into `NvnShaderStage.local_size`; the renderer uses the copy. All four
compute programs report `64x1x1` in every run.

**Related fixes.**
- A draw copies its vertex streams from guest memory when it is encoded, but a compute dispatch writes such buffers on the GPU. A
  stream that overlaps a range a dispatch writes (`hz_ranges`, `streams_pending_compute`) is bound straight from the guest buffer,
  so the GPU orders the draw after the dispatch (`BDSP_HZ_FLUSH=1` restores the old full flush).
- `TexBackend` remembers the guest descriptor (target, size, format, samples) its Metal texture was created from and is recreated
  when it changes. This removed 29 of 30 "type mismatch" fallbacks.

**Ruled out by measurement** (so nobody repeats it): a 16-byte fallback for vertex streams of size 0, index values beyond the bound
stream, NaN in the first floats of the vertex uniform buffers, the guest rewriting storage buffers after they were encoded,
missed texture updates in the cheap change check, stale shader caches.

## 4. Method that worked

0. Run `MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1` and group the messages by text (`sort | uniq -c`).
1. Reproduce deterministically: one instance, scripted input, a fixed save, no keys pressed in the window.
2. Measure at the draw level instead of comparing screenshots: the geometry check shows which vertex shader produces broken
   vertices; per-program logs of compute dispatches showed the bad work group size.
3. Compare runs: the same value differing between runs points at a read of memory the renderer does not own.

Debug tools (`nvn/src/nvn/render_debug.inc`, all off unless the variable is set):

| Variable | Effect |
|---|---|
| `BDSP_GEOM_CHECK=1` `BDSP_GEOM_FROM=<f>` `[BDSP_GEOM_TO=<f>]` `[BDSP_GEOM_EVERY=<n>]` `[BDSP_GEOM_WARM=<n>]` `[BDSP_GEOM_LIMIT=<x>]` | Geometry check: vertex shaders also store their clip positions; every n-th frame in the window is scanned draw by draw and vertices with NaN/Inf, w near 0 or \|x/w\|, \|y/w\| above the limit are logged. Flushes per draw: short windows only. Programs compile asynchronously, hence the warm-up frames |
| `BDSP_SKIP_VS=<vs hex>[:<count>][,...]` | Hide the draws of a vertex shader to find out what it paints |
| `BDSP_SAVE_CS_DIR=<absolute dir>` | Write the translated MSL of every compute program |
| `BDSP_DEBUG_FRAME=<f>` | Detailed draw log of one frame (also accepted as `BDSP_GEOM_FROM`) |
| `BDSP_PASS_DIR=<absolute dir>` | With `BDSP_DEBUG_FRAME`: write the colour target of every pass as `pass_NNN.png` (multisample targets are not readable this way) |

## 5. Performance: the render worker, not the GPU, was the limit

Setup: M1 Pro, 120 fps target. On Route 222 the game ran at about 61 fps and the GPU showed the same utilisation at 60 and 110 fps.
A Metal System Trace showed only ~25 % fragment, ~9 % vertex and ~5 % compute time; the render worker (`xw_main`, the single thread
that encodes command lists) was 96 to 100 % busy. Found and fixed, in this order:

| Cause | Fix | Effect |
|---|---|---|
| A full GPU flush before each draw that reads compute-written (skinning) vertex streams, about 4 ms per frame | such streams are bound directly from the guest buffer (GPU-ordered) | Route 222 ~65 → ~85 fps |
| Whole vertex streams copied into the ring per draw (11 GB per 2 s, two thirds of the worker) | only the range the draw's indices reach is copied (`draw_vertex_range`; `BDSP_FULL_VB=1` copies whole streams) | ~3 GB per 2 s |
| A full GPU flush per buffer-to-buffer copy (~25 per frame along the water, ~35 fps) | flush only when the range overlaps what a compute dispatch uses (`range_pending_compute`) | beach walking ~35 → ~74 fps |
| Guest fences waited for the newest committed command buffer | a fence waits for the command buffer of its own job (`xw_job_seq`; `BDSP_FENCE_LAST=1` restores the old wait) | guest wait on the worker: 0 |
| The three hottest guest functions (Unity job workers at 65 to 78 % CPU) were compiled with `-O0`, so every flag helper was a real call | `scripts/recomp/hot_o2.txt`: chunks defining listed functions are built with `-O2` (a few seconds, no full rebuild) | beach walking ~85 → ~112 fps |
| Every ring wrap allocated a new 64 MB buffer (~25 per second, zeroed and faulted in by the kernel; the copy ran at ~2 GB/s) | retired rings are reused once their last command buffer completed (`BDSP_RING_POOL=0` allocates fresh ones) | beach walking ~112 → ~118 fps, Route 222 ~95 → ~120 fps |

Results at the 120 fps target: Route 222 about 61 → 120 fps; Sonnewik beach standing ~85 → ~118, walking ~35 → ~118 fps.
Rebuilding the other 63 `-O0` chunks with `-O2` (11 min) gave nothing measurable. Add a function to `hot_o2.txt` when
`sample <pid> 6` shows it at the top of a guest thread (`scripts/recomp/symres.py` names IL2CPP methods; engine code has no names).

**Do not** bind vertex data straight from the wrapped guest heap to save the worker's copy (`BDSP_GUEST_BUF=1`): it reaches ~117
fps, but the GPU then reads stale pages (an early finding of the graphics bring-up, kept in the git history) and the water mesh covers the whole scene.

**Measuring.** Metal validation and Instruments traces slow the game to 20 to 30 fps; measure without them, at the real target
(`BDSP_FPS=120`), with a scripted input and a save copy. Tools: Metal System Trace (`xctrace record --template "Metal System
Trace" --attach <pid>`), Time Profiler, and the lighter `sample <pid> 6`. The M1 Pro supports only stage-boundary counter sampling.

| Counter / variable | Effect |
|---|---|
| (always, in the `[metal]` stats line) | `flush by hazard/readback/buf2buf/other n/ms` (full GPU flushes by cause and CPU wait time); `ring MB vertex/uniform/index/other MB/calls` (bytes copied into the ring) |
| `BDSP_PASS_TIMES=1` (`=2` also dumps a per-pass timeline) | `[pass]` lines: GPU time per pass target from stage-boundary timestamps; a pass is charged only the time after the previous one ended |
| `BDSP_XW_LOG=1` | Render worker: time per command list, queue length, how long the guest waits, share of time the worker is busy |
| `BDSP_HZ_FLUSH=1`, `BDSP_FULL_VB=1`, `BDSP_FENCE_LAST=1`, `BDSP_RING_POOL=0` | Switch an optimisation off to compare |
| `BDSP_EXEC_WORKER=0`, `BDSP_EXEC_FRAMES=<n>` | Synchronous renderer path; how many frames the guest may run ahead (default 2) |

Hang diagnostics (runtime, not rendering); none does anything in a normal session:

| Switch | Effect |
|---|---|
| `BDSP_HANG_DUMP=1` | The end-of-run report also prints the host state of every guest thread (briefly suspends busy ones) |
| `BDSP_VSYNC_LOG=1` | Counts vsync events and logs the count every 120 ticks |
| `-DBDSP_DEBUG_MOVIE` at build time, then `BDSP_MOVIE_LOG=1` or `=ring` | Movie decoder entry/exit tracing; `ring` keeps the last entries and dumps them before the timeout |

Known: Metal validation reports one start-up message (a 1D texture used as a render attachment, 21 times) and nothing else.
`gpudebug` and `gpucapture` are documented in the macOS 27 SDK but not part of Xcode 27.1 on macOS 26.6.

## 6. Frame rate, pacing and the HUD

- **Target:** 30, 60 or 120 fps. It sets the vsync interval (`services_gfx.c`, `bdsp_set_fps()`) and presentation (`frame_pace` in
  `nvn_glue.c`). `BDSP_FPS` overrides the saved setting; Mac: "Frame Rate" menu (`config.ini` key `fps`); iPad: Settings bundle key
  `bdsp_fps` (applies after a restart). `BDSP_FPS_INTERVAL` sets the interval of the fps log line (default 2 s).
- **The old 50 fps ceiling** was a vsync thread that slept a relative 16.67 ms and accumulated drift; it now uses absolute
  deadlines (`CLOCK_MONOTONIC`): 59.9 fps measured.
- **ProMotion:** without a target time, images appeared one to three 120 Hz ticks after completion (8.3 / 25 ms alternation). On the
  Mac, `BDSP_PRESENT_AT=lock` (default; `off` = old behavior) schedules `presentDrawable atTime:` exactly `step` ticks after the
  previous image from a grid derived from the last `presentedTime`; a late image resets the schedule (`BDSP_PRESENT_LEAD`).
  Share of intervals within 16.67 ± 0.3 ms at 60 fps rose from 71 to 94 % to 98.4 to 99.5 %. The remaining outliers (one image a
  tick late, on a roughly one-second grid) also occur in a minimal empty-window Metal test program, so they are the ProMotion
  compositor's limit, not the game. Rejected variants: `afterMinimumDuration`, `grid`, `CADisplayLink` with a 60 fps range, double
  presentation.
- **Drawables and delay (Mac):** `maximumDrawableCount` was 3 and is 2 on the Mac now (`BDSP_DRAWABLES` overrides; the iPad keeps 3). With 3 the game
  ran up to three frames ahead of the screen: from the pad read to the picture (`BDSP_PRESENT_STATS=1` prints "Eingabe bis Anzeige") 40 to
  53 ms in the overworld at 60 fps, 34 ms with 2, 28 ms at 120 fps. With the `lock` schedule 2 drawables hold 60.0 fps with 96 to 98 % of
  the intervals in the target band, the same as 3 (an earlier test with another schedule had rejected 2). The rest is the game's own frame
  (about 28 ms of CPU) and the compositor.
- **Presentation menu (Mac, debug):** View > Debug > Presentation sets the buffering (Double = 2 drawables, the default; Triple = 3) and VSync
  (on, the default; off = `displaySyncEnabled = NO`). Both apply at once, without a restart, and are kept in the defaults keys
  `bdsp_drawables` and `bdsp_vsync_off`; `BDSP_DRAWABLES` and `BDSP_DISPLAYSYNC` win at the start. VSync off measured 29.0 instead of 34.4 ms from
  the pad read to the picture at 60 fps, with larger spikes (47 instead of 36 ms); no tearing was seen in a window. The self-test actions
  `buf2`, `buf3`, `vsync0`, `vsync1` (`BDSP_UI_SELFTEST`) call the same methods as the menu items.
- **Animation speed (open):** at 60 fps the original under an emulator runs the game at 1x but NPCs and water twice as fast,
  because the engine ties them to the 30 fps design (`Application.targetFrameRate(30)`); the runtime's time sources are real-time
  exact, so there is no runtime-only correction. Not measured at 30/60/120 in the recompilation.

## 7. Water

Findings for the Canalave City pool (zone 24) in the original, measured on a Ryujinx reference image and the game's material data:

- Appearance: deep saturated blue, sharp bright caustics, faint reflection of the bridge, dark cast shadows. In the 1280x720 image
  the water region has mean RGB about (87, 127, 210), standard deviation about (26, 17, 25), ~0.3 % very bright pixels; two frames two
  seconds apart differ by a regional mean absolute difference of about 9 while the mean stays put.
- Shader `Delphis/Map/FlowmapWater` (one forward pass, queue Transparent, `SrcAlpha OneMinusSrcAlpha`, `ZWrite Off`, Cull Back,
  no grab pass). Textures: caustics 256x256 (tiled 4x4), flow map, time-offset map; key scalars: caustics intensity 6, exponent 3,
  flow speed 0.1, time scale 0.5.
- What the runtime must provide: `_OpaqueDepthTexture` (depth after the opaque pass; without it the shader draws a uniform brown
  surface), `_ReflectionTex` / `_ReflectionVP` (a mirrored reflection camera; whether zone 24 reads it is *unresolved*), `_Time`
  from game time, the blend state and transparent draw order, and the bindless texture handles (constant buffer 2: textures from the
  table starting at `0x168`, samplers from the one at `0x568`, 8 bytes each). Wrong handles or unloaded textures give a uniform surface.
- Other water shaders (`Map/Water`, `Wave`, `Fog`, `WaterSurface`) use a grab pass: copy the current color target between the
  opaque and transparent passes. Zone 24 does not need it.
- Check: the same measurements as above on a recompiled frame. No movement suggests a missing `_Time`; movement without the net
  suggests a missing caustics texture. Water that covers the whole scene is the stale-vertex-data symptom described in section 5.
