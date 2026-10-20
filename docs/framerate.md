# Frame Rate, Metal HUD, and Animation Timing

## Behavioral Requirement (User Observation, Not Confirmed by Code)

In the original emulator, observed at 60 fps, the game runs at 1x game speed. NPCs and the water animation, however, run twice as fast. In the original, water animation is tied to 30 fps. At 60 fps presentation, recompilation should run the game at 1x and show NPCs and water behaving as on the console. Whether it already does so must be **measured** (record the same scene at 30 and 60 fps), not assumed. Not implemented yet.

## Frame Rate: Status

- Choose 30, 60, or 120 fps. The value affects the Vsync interval (`services_gfx.c`, `bdsp_set_fps()`) and presentation (`frame_pace` in `scripts/recomp/rt-bdsp/nvn/nvn_glue.c`, macOS only).
- iPad: “Frame Rate” setting in the app's iOS settings (`Settings.bundle`, key `bdsp_fps`). Takes effect after restarting the app. Localized (en, de).
- Mac: “Frame Rate” menu (`app_ui.m`, key `bdsp_fps`, default in `config.ini` via `fps`). Not localized yet; 30/60/120 have not been measured.
- Environment variable `BDSP_FPS_INTERVAL` controls the logging interval for the FPS display (default 2 s).

## Cause of the 50-fps Limit (Fixed)

- The Vsync thread in `services_gfx.c` slept with `nanosleep(16666667)` without an absolute deadline. The sleep duration accumulated frame by frame, and the interval fell to about 19.8 ms (roughly 50 Hz).
- Fix: absolute deadlines (`CLOCK_MONOTONIC`). Mac measurements: 59.98 and 59.87 fps. Setting the MacBook display to 60 Hz makes frame times much more stable. Pacing for a 60 fps target was not ideal with ProMotion (120 Hz; see below, now fixed).

## ProMotion, 60-fps Target: Phase-Locked Presentation (Mac, Default)

- Cause: `presentDrawable` had no target time. The image appeared on the next 120 Hz tick after completion; the pacing clock (`frame_pace`) was not aligned to the display phase, so images alternated between 1 and 3 ticks (8.3 / 25 ms).
- Solution (`metal.m`, `BDSP_PRESENT_AT=lock`, Mac default; `off` = old behavior): each image gets `presentDrawable atTime:` scheduled exactly `step` display intervals after the previous one (chain, 2 ticks at 60 fps), using a grid derived from the last actual `presentedTime`. If an image is late, the schedule is reset with a lead (`BDSP_PRESENT_LEAD`, default 1.0 `step` intervals). Disabled on iPad until measured (`BDSP_PRESENT_AT=lock` to test).
- Measurement (Mac, ProMotion, overworld `auto-input2.txt`, `BDSP_PRESENT_STATS=1`, 3 runs of about 55 s from game start, share of intervals in 16.67 ± 0.3 ms): before 92.4 / 94.4 / 71.0%; after 98.4 / 99.0 / 99.1% (default 98.9 / 99.4%; without worker 99.0%). Mean 16.67 ms. Remaining outliers: loading stalls (4+ ticks).
- Rejected: `afterMinimumDuration` (95.7% once, broken without worker), `grid` (60.8% with worker), shorter interval `BDSP_PACE_PCT=90/97` (92.6 / 85.9%, measurement aid only).
- Second measurement round (HUD off, `BDSP_NO_HUD=1`, frames only after frame 1000, 3 overworld runs with worker, `BDSP_PRESENT_OUT=1` lists every interval outside 16.67 ± 0.3 ms): 99.51 / 99.49 / 99.39% in range (13 / 14 / 17 outliers per ~2700 frames, including 6–8 intervals of 25 ms, and at most one interval ≥ 33 ms each). Without worker: 99.54%. Acceptance criteria (≥ 99.5%, no interval ≥ 25 ms) **not met**.
- Cause of remaining outliers: one image appears one display tick late (25 ms), and the next returns to the grid (8.3 ms). Not GPU (GPU completion ~45 ms before display), not commit timing (lead ~35–50 ms), not loading/scene transition (also occurs in title screen without input), not Metal HUD; changing `atTime` offset (0 / 0.25 / 0.5 / 0.75 ticks) or lead (0.5–3.5) has no effect. Events fall on an approximately one-second grid. A minimal Metal test program (empty window, same chain, no game) shows the same 25/8.3 ms pairs: 98.4–98.9% in range. This is the ProMotion compositor's limit, not the game.
- Other rejected attempts (test program and game): `CADisplayLink` with `preferredFrameRateRange` 60 (display stays on 120 Hz ticks, 98.5%); double presentation per image (98.4%); `maximumDrawableCount` 2 (98.4%). `afterMinimumDuration` in the test program: 99.55% (only 25 ms delays, no 8.3 ms catch-up frames), but only 44–82% in the game (guest pacing has up to 29 ms jitter and there is no queue in front of the display).
- Rarely (2 of about 45 runs, also with `BDSP_PRESENT_AT=off`): startup hangs before the first image (no `[metal]` log). Independent of lock mode; unresolved.
- `BDSP_FPS=60` now takes precedence over the saved menu setting.

- Earlier drops to about 20 fps came from debug instrumentation (`waitUntilCompleted`, `getBytes`), not the runtime.
- Debug thread: `BDSP_DEBUG_THREAD=1` moves readbacks to a separate thread (`nvn/dbgthread.patch`, `nvn/debug_thread.c`). Mac: 43.4 fps without, 49.6 fps with the debug thread (measured before the Vsync fix).

## Metal HUD

- macOS: set `MTL_HUD_ENABLED=1` at launch (shows FPS, GPU time, and frame time at the Metal layer). Cannot be checked visibly in a headless run.
- iPad: “Show Metal HUD” switch in the “Debug” section of the app settings (key `bdsp_metal_hud`). The app sets `MTL_HUD_ENABLED=1` at launch, before Metal initialization. Takes effect after restarting. Confirmed on device.
- App Store apps cannot be displayed on a device without Xcode or a third-party tool; the in-app switch is therefore the way to enable it.
- Log: `[metal] … fps` every `BDSP_FPS_INTERVAL` seconds.

## Where Animation Timing Comes From (Analysis, Open)

The game clock comes from guest code (Unity IL2CPP, time delta per frame); water shader time and NPC updates run there and are not timed by the runtime. The runtime supplies only time sources (`rt_now_ns`, `kernel.c`) and presentation (`metal.m`). Areas to investigate: guest time base/delta, water time variable in shader uniforms (water agent, `renderer.m`).

## Animation Speed Analysis at 30/60/120 (Code Evidence, Not Measured)

- Runtime time sources are real-time accurate: `rt_ticks()` (`kernel.c:29`, 19.2 MHz from `rt_now_ns`), SVC `GetSystemTick` (`kernel.c:680`), Vsync interval with absolute deadlines (`services_gfx.c:31`). Player character and world run at the same speed at 30/60/120, so the time base is not the problem.
- The runtime does not provide guest code with water or NPC timing (no hook or time uniform in `renderer.m`). The difference arises in guest code: NPC animation and water advance on each update/frame (Ryujinx with 60-fps mods shows the same behavior), rather than using `DeltaTime.deltaTime` (`Dpr.Field.Walking.DeltaTime` uses it for the character/world). There is no runtime-only correction without changing guest code.
- Next: use binary analysis (REA, NPC animator update and water material time in the guest ELF) to find the per-frame increment, then scale its step by 30/fps or execute only every (fps/30)-th call. Measure at 30/60/120 afterward.

### Guest Findings from ISIL Dump (Addresses Are Offsets in Main Module; Not Measured)

- `Sequencer::Update` (0x02BC2C70, AssetAssistant): gets `Time.get_deltaTime`, writes it to static field +0x50 (read by `DeltaTime::get_deltaTime`, 0x01CD08B0, multiplied by `TimeScale`), and calls `TickCallback`s with `Time.deltaTime`.
- `Sequencer::Awake` calls `Application.set_targetFrameRate(30)`: the game is designed for 30 fps.
- NPC: `FieldCharacterEntity::OnUpdate` (0x017885E0) → `AnimationPlayer::AdvanaceTime(deltaTime)` (0x0211EEA0): blend uses `weight += _increase * dt`, so it is time-based. Managed code (Assembly-CSharp) has no frame counter for NPCs or water, no `Time.frameCount`, and no per-frame constant being added.
- Conclusion: the per-frame progression happens in the Unity engine (Playables/Animator, shader time `_Time`), not in game scripts. No unambiguous constant for an environment-controlled fix has been found.
- Open checks: use `BDSP_IL2SYM` to compare the caller of engine time (`Time.deltaTime` ICall, time manager) during 30 and 120 fps runs; inspect PlayableGraph update mode (GameTime or DSPClock).
