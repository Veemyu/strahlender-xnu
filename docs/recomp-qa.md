# Recompilation QA (`ap-recomp-qa`)

Status: 2026-10-19, interim (to be updated after each scenario). Based on `docs/recomp-gate2.md`, `docs/architektur-entscheidung.md` (decision 3: recompilation is the main path), and `docs/visuelle-pruefung.md`. Task: systematically test the recompiled runtime (`work/recomp/bdsp_boot`, Metal, headless), find and fix errors, and compare images with the Ryujinx reference. **No audio** (audio services are silent); no game binaries, saves, or screenshots in the repository (everything is under `work/recomp/qa/`).

**Labels:** **measured** = recorded in runs under `work/recomp/qa/<run>/`; *suspected* = inference without a test. **Test conditions:** M1 Pro, 16 GB. Another agent was building and testing in parallel during these runs (Mac load averaged 25–55; at times a second game instance was running), so **frame rates from these runs are not representative** (see long run). Each report includes load and process CPU.

## Harness (`scripts/recomp/qa/`)

| File | Contents |
|---|---|
| `qa_run.sh <scenario>` | Entry point: `qa_run.sh --list`, `qa_run.sh <scenario> [--bin PATH] [--img DIR] [--no-il2sym] [--timeout S] [--label TEXT]`, `qa_run.sh --report <run>` (regenerate report). Exit code 0 passed, 1 check failed, 2 usage error, 3 disk has <15 GB free. Only one run at a time (lock file). |
| `qa_run.py` | Loads scenario, starts `bdsp_boot --headless`, samples RSS/CPU/load every 2 s, sends inputs, analyzes log, writes `report.md` and `report.json`, creates screenshot contact sheets |
| `scenarios/*.txt` | Scenarios (syntax documented at the top of `qa_run.py`); names beginning with `_` are helper files or explorations |
| `patches/` | Proposed changes to files other agents are editing |

**Run sequence:** (1) Copy baseline save `work/recomp/qa/save_base` (city save, `SaveData.bin` SHA-256 `0396a4a62735…`) for each run; the baseline remains unchanged. (2) Run `bdsp_boot --headless --save <run>/save --screenshot-after N --input-script …` with `BDSP_IL2SYM` (log each game method's name on its first call), `BDSP_BT=1`, `BDSP_TRACE_SYNC=300`, `BDSP_DUMP=7004f91f60:24` (wait states, mutex owners, synchronization sequence, and event state in the report; only costs time at shutdown). (3) Analyze.

**Event-driven input.** The runtime input script (`--input-script "second:BUTTON:duration"`) counts from process start. But loading to the title varies from 31 s to over 120 s (other load, shader cache, disk), so absolute times are unreliable. The harness supports **anchors** (`anchor field EvDataManager::EnvironmentControllerCallBack`): the time of the first call to a game method (from the IL2CPP name log); inputs can then be specified in the scenario as `field+12 UP 2.0`. It writes the button mask to a control file (`BDSP_INPUT_CTL`, new in `nvn_glue.c`), read at every Npad poll and ORed with scripted and keyboard input. `finish <s>` ends the run (SIGINT; the runtime writes its report) that many seconds after the last input; the timeout remains a fallback. The runtime script now supports up to 8,192 steps and can be loaded through `@file` (long run).

**Checks included in every report:** crashes (exit code, `*** Signal`, `FATAL`, missing result report, harness abort), with host backtrace and **last guest stack symbolized with IL2CPP names** (`il2sym.tsv`) plus the most recently first-called game methods; **frozen image** (>12 s without a frame), with thread states, mutex owners, synchronization sequence, and guest memory; **unhandled IPC commands** (service:command, count), unimplemented SVCs, NVN functions without host implementation; notable log lines (`unimplemented`, `not implemented`, `failed`, `mismatch`, …) counted by pattern; frame rate (median, p5, minimum) and RSS history; screenshots (black, unchanged from previous); save (`bdsp_save.py check`, changed?). Each scenario adds `expect` checks.

## Scenarios

Status when paused at the user's request (2026-10-19, about 17:25, early instead of 19:00). **Only the first scenarios were calibrated; `menu`, `wild_battle`, `save_load`, and `long_run` are NOT implemented/measured** (`_menu_explore.txt` is exploration only, not a scenario). In total, 26 runs under `work/recomp/qa/<run>/` (reports `report.md`/`report.json`). Runs before 16:44 had errors described and fixed below; those earlier versions are not counted.

| Scenario | File | Result | Evidence |
|---|---|---|---|
| Language selection (no save) | `sprachauswahl.txt` | **not run** (written only) | — |
| boot_title | `boot_titel.txt` | **inconclusive**: the only run, `boot_titel-…-a2`, crashed due to my own intermediate change (signal 11, see issue 3); not repeated. The title was reached in all `weiter_stadt` runs (title screen seen). | `work/recomp/qa/boot_titel-20261019-164130-a2/` |
| continue_city | `weiter_stadt.txt` | **passed** (versions v2 and v5: Title::Start at 21–86 s depending on load, city at 36–102 s) | `weiter_stadt-…-161239-v2`, `…-171256-skipws2`, `…-171924-wlog2` |
| walk_city | `laufen_stadt.txt` | **failed/not retested**: two of five runs, `laufen_stadt-…-rep1..5` (timed script, before audio fix), hung (issue 1); not repeated with event-driven inputs and corrected runtime | `work/recomp/qa/laufen_stadt-2026101916*` |
| Pokémon Center | `pokecenter.txt` | **passed** (3/3 runs with audio pacing: entered door, interior rendered (hall, nurse, yes/no dialog “Hello! Welcome to the Pokémon Center!”, healing, Pokémon screen), 0 hangs). An earlier run (k1, without pacing) hung inside (issue 2). | `pokecenter-…-162752-k2`, `…-164447-a3`, `…-164824-a4` |
| menu | — | **not implemented**; exploration `_menue_erkunden-…-165203-m1`: X opens menu (Pokédex, Pokémon, Bag, Trainer Card, Map, Capsule Decoration, Settings, Mystery Gift; prompts “Save R”, “Open map +”), B closes it; 0 errors. Saving was not tested. | `work/recomp/qa/_menue_erkunden-20261019-165203-m1/` |
| wild battle | — | **not implemented** | — |
| save_load | — | **not implemented** (harness supports `phase`, `save-valid`, `save-changed`; untested) | — |
| long run (30 min) | — | **not run**: no sustained memory-leak or FPS data | — |

**Measurements (measured, one run each):** `pokecenter-…-164447-a3` (Mac nearly idle, load 3): median 46.6 FPS, p5 33.3, minimum 11.8, 5,684 frames in 137 s; peak RSS 1,968 MiB, median 869 MiB, CPU 138%; 58,231 IPC, 2.35 million SVCs. `…-164824-a4`: median 51.2, p5 29.4; peak RSS 1,882 MiB. Under other load (25–55 from parallel compilers/Unity), rate fell to median 17–35 with minimum 0.5; **these runs say nothing about runtime performance**. No crashes in the city/Pokémon Center with version v4 or later.

## Issues found

| # | Issue | Cause | Status |
|---|---|---|---|
| 1 | **Game hangs** (image freezes; 2/5 `walk_city` runs (rep1, rep2), 1/2 Pokémon Center runs): main thread waits in `AkGameObj::SetPosition` for Wwise lock (mutex `700501f008`), owned by thread 113, the audio loop `GetReleasedAudioOutBuffer` (50,000 IPC) | **Verified** (thread state and mutex owner in report): `audout_obj` returned every queued buffer immediately, so Wwise's audio loop always saw free buffers and ran without pausing, while holding the global Wwise lock. Also, `ntags` was unlocked (two guest threads append/query it). | **Fixed** in `services_audio.c`: per-`AudOut` lock; buffers are returned only after their playback duration (from `dataSize`, at least 5 ms); timer thread signals the event. Then 3 runs without hangs. No audio. |
| 2 | Kernel self-deadlock after timeout coincides with wakeup (thread owns mutex then tries to lock it again; run `weiter_stadt-…-170620-skipws` hung at 23 s, thread 113 `ArbitrateLock` on its own mutex `700501f40c = 4000015e`) | **Verified** (mutex owner in report) | The `ap-recomp-ios` branch made the same fix in `kernel.c` at the same time (`block_current`: account for the waker's wakeup). I did not touch it. Version v5 includes it; no further hang in 5 runs. |
| 3 | Signal 11 crash at startup (`GetAudioOutBufferDataPointer`, address 0x30) | **Verified:** my first pacing version returned the tag after 0 ms, before the guest system had queued the buffer | **Fixed** (minimum duration 5 ms); intermediate version was never committed |
| 4 | Harness needs event-driven input (loading takes 21–120 s) | — | Fixed (anchors, `BDSP_INPUT_CTL`) |

## Image comparison against Ryujinx (`scripts/visual_ref.py import --source recomp` / `refs`; already present in the worktree, I did not change it)

- City, zone 24 (`ref_01_feld_weiter`): best recomp image (frame 1440, `pokecenter-…-164447-a3`) versus Ryujinx reference: **SSIM 0.708 (aligned 0.704), MAD 16.0 (16.6), 17.8% changed pixels, 10/64 grid cells poor**, brightness ratio 1.02. House, characters, trees, and road pattern look the same. **Difference: water on the left** (below). Camera time differs (28 pixels), limiting SSIM.
- **Time of day:** lighting follows the computer clock (runs around 16:xx yield violet/blue dusk colors; runs around 17:xx are reddish). Comparison with the reference (in-game time about 12:00) is only partly fair; reproducible measurements would require fixing the clock (`ITimeZoneService`/`ISystemClock`), which was not implemented.
- Heatmap: `work/visual/ref/recomp_vs_ryujinx/` (local).

## Water (priority 1, unfinished)

Verified by skipping fragment shaders (`BDSP_SKIP_FSHASH`, runs `…-skipwater`, `…-skipws2`): the white water on the left of the city image does **not** come from `Delphis/Map/FlowmapWater` (hash `87bfeb6485a0650a`; skipping it does not change the image), but from **`Delphis/WaterSimulation/WaterSurface`** (hash `81f72a1870a4930f`, one draw call, 6 times per measured frame). Without this shader the area shows a violet-blue ground; with it, overexposed white. Shader inputs (4 textures according to translation, from `BDSP_LOG_WATER` in a local debug build): #0 512×512 RG8 (`0xd`), #1 1280×720 depth/stencil (`0x35`, = `_OpaqueDepthTexture`), #2 1280×720 R11G11B10F (`0x3f`, scene color, copied from 1920×1080 `0x25`), #3 512×512 RGBA8 (`0x25`, reflection/simulation texture). Saved dumps show **#0 entirely zero** (simulation normal/flow map never written or not visible), and #2 nearly black in the first draw calls, then bright (mean ≈213); whether dumps are timed correctly (Metal command buffer might not have executed when saved) is **unresolved**. **Hypothesis (unverified):** simulation textures (`Custom/WaterInteration/DynamicNormalMap`, `WaterSimulation`, one draw call each) are written to a render target that the water shader reads empty/without a load action (load/store or pass ordering in Metal path). Next: dump only after `renderer_flush()` and compare with Ryujinx water images `free_wasser_a/b` (targets in `docs/wasser.md`: means ≈87/127/210).

## Pokémon Center interior (report from `ap-recomp-macapp`: solid blue with dark lines)

**Not reproduced:** in 3 runs (v3, v4, v5, each title → city → Pokémon Center), the interior shows the correct orange/yellow hall, nurse, dialog box, and healing screen (`contact_p1_03/04.png` under `pokecenter-…-164824-a4/`). The reported issue likely belongs to another build (app wrapper/different image directory) or another time of day; unresolved.

## Open items (priority order)

1. **Water `WaterSurface`** (P1, above).
2. Repeat `walk_city` with corrected runtime; write and measure `menu` (including saving), `save_load`, `wild_battle`, and `long_run` scenarios (P2); the harness is ready.
3. Fix the in-game clock (reproducible lighting) (P2).
4. Smaller findings: `[tex] type mismatch` (29 messages per run, dummy texture), `[texdump]` prints “3555734656959.2 MB” (debug text formatting error), unhandled IPC: `ICommonStateGetter:66` ×7, `IParentalControlService:1`, `acc:u0:130`, `IAudioController:0` (all known since Gate 2, with no visible effect) (P3).

## Files changed (at pause)

All build; version v5 and the local debug build were linked from this state.

| File | Change | Status |
|---|---|---|
| `scripts/recomp/qa/qa_run.sh`, `qa_run.py` | Harness (anchors, control file, reports, contact sheets) | done, tested only with scenarios above |
| `scripts/recomp/qa/scenarios/*.txt` | 7 files (2 explorations prefixed with `_`; `sprachauswahl` untested) | partly done |
| `scripts/recomp/rt-bdsp/services_audio.c` | Audio pacing, lock, timer, `BDSP_TRACE_AUDIO` | done (issue 1 fixed) |
| `scripts/recomp/rt-bdsp/nvn/nvn_glue.c` | Input script up to 8,192 steps, `@file`, `BDSP_INPUT_CTL` (the `ap-recomp-macapp` branch also added `g_ext_buttons` in the same area; compatible) | done |
| `scripts/recomp/rt-bdsp/kernel.c` | Report only: mutex owners in thread state (`BDSP_BT`); timeout fix came from `ap-recomp-ios` | done |
| `docs/recomp-qa.md` | This document | done (status as described) |
| `work/recomp/nvn-qa/nvn/renderer.m` (not in repo) | Debug output `BDSP_LOG_WATER` | local only, **no** repo patch (`scripts/recomp/qa/patches/` empty) |

Not in the repository: runs, save copies, screenshots, and binary copies under `work/recomp/qa/` (about 300 MB; `bdsp_v5`, `bdsp_dbg`). No processes remain active, lock file removed, Linux machine not used.
