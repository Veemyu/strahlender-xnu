# iPad Measurement 1: Memory, Frame Rate, Thermals (Todo `ap-ipad-perf`)

> **Historical (status 2026-10-20):** Unity measurement. `scripts/ios_deploy.sh` has been removed from `main` (only on the `unity` branch). For recompilation, use `scripts/recomp/ios/deploy_ios.sh`.

Status: 2026-10-19. Measured on an iPad Pro 12.9-inch (6th generation, `iPad14,6`, M2, 8 GB, iPadOS 26.4.2) with the **MemoryProbe** measurement app (Unity 6000.3.26f1, IL2CPP, Metal only, Release build, free team, installed via `scripts/ios_deploy.sh`). The app contains no game content, just an empty scene, a custom load shader, and allocations. Audio stayed off (`AudioSafety` active, `audioListenerVolume=0` and `audioPause=1` in every run); device volume was not touched.

Raw logs (device console, each line `XNUPROBE|...`) are stored locally under `work/measurement/` (gitignored).

## 1. Summary
| Question | Result |
|---|---|
| Memory limit **without** entitlement | **5120 MiB (5 GiB)**, identical across all phases in 3 runs (sum of `os_proc_available_memory` and `phys_footprint`). |
| Memory limit **with** Increased Memory Limit | **8192 MiB (8 GiB)**, visible at startup. This exceeds the device's visible memory (7518 MiB), so it is an upper bound, not a guarantee. |
| Entitlement with a free team | Accepted, signed, and effective (`codesign -d --entitlements` shows it; the app runs and the limit rises by 3 GiB). |
| System warning (`Application.lowMemory`) | Without entitlement at **about 4.0–4.2 GB** footprint; with entitlement at about **5.9 GB** (native test only). |
| Footprint of an empty Unity scene (Metal) | **about 180 MiB** after startup, about 193 MiB after 8 minutes under load. |
| Frame rate | **120 FPS is reachable** (119.9 measured), as are 60 and 30, if `Application.targetFrameRate` is set. Without a target, Unity delivers 30 FPS. |
| ProMotion key `CADisableMinimumFrameDurationOnPhone` | No effect on this iPad (120 FPS also with `false`; unchanged with `true`). |
| Thermals | `thermalState` stayed **nominal (0)** in all runs, including 150 s of GPU load and 300 s of GPU plus CPU load. Says nothing about longer play sessions. |
| Game budget | Target **2.5 GB**, hard ceiling **4 GB** footprint; leave entitlement enabled (section 6). |

## 2. Measurement Setup
- **Code:** `unity/Assets/Scripts/Probe/` (`MemoryProbe.cs`, `NativeProbe.cs`, `ProbeMath.cs`, shader `ProbeLoad`), native plugin `unity/Assets/Plugins/iOS/XnuMemoryProbe.m` (`os_proc_available_memory`, `task_info(TASK_VM_INFO)` with `phys_footprint`, `internal`, `compressed`, `limit_bytes_remaining`, `NSProcessInfo.thermalState`, `physicalMemory`, `UIScreen.maximumFramesPerSecond`, Info.plist keys, Metal `currentAllocatedSize`). Math tests: `ProbeTests.cs` (5 tests, passing in suite).
- **Scene and build:** `unity/Assets/Scenes/MemoryProbe.unity`, built via `Xnu/Probe/...` in the Editor (`MemoryProbeBuild.cs`) with its **own scene list**; project Build Settings remain empty and unchanged. Bundle ID `dev.local.xnumemprobe` and product name apply only during the build, then are reset. Output under `work/builds/ios/memprobe-*`.
- **Entitlement switch:** `IosPostBuild` adds the entitlement by default (enabled by default). Disable with compile symbol `XNU_NO_INCREASED_MEMORY` or SessionState key `Xnu.Build.NoIncreasedMemoryLimit` (set by `MemoryProbeBuild`). The no-entitlement case was also checked: the generated Xcode project has no `CODE_SIGN_ENTITLEMENTS`, and `codesign` does not show the entitlement.
- **Each launch (about 9 minutes, about 3 in `fps` mode):** snapshots at Awake, first image, and every 5 s; baseline (8 s with project setting); frame-rate matrix (idle and light GPU load, 5 s each, first 1.5 s discarded); sustained load for 150 s (GPU saturated, full-screen shader, about 44 FPS) and 300 s (plus 6 CPU threads); then three memory ramps in 128-MiB steps: **native** (`AllocHGlobal`, filled with random data so it cannot disappear as a zero page or through repetition), **render** (RenderTexture 4096 × 4096 ARGBHalf = 128 MiB, written once), and **managed** (`byte[]`, capped at 3 GB). Before each step, stop if `available - 128 MiB < 300 MiB` or footprint would exceed 6 GiB; then free everything and wait 3 s. Each line is written to disk immediately (`Documents/memprobe_*.log`), so even a kill would have been traceable.
- **Repeat:** `Xnu/Probe/Build iPad (Entitlement on|off)` in the Editor, then
  `DERIVED_DATA=work/builds/ios-derived-memprobe BUNDLE_ID=dev.local.xnumemprobe scripts/ios_deploy.sh work/builds/ios/memprobe-ent --no-launch` and
  `xcrun devicectl device process launch --device <ID> --terminate-existing --console dev.local.xnumemprobe > work/measurement/console_....log` (`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`). `ios_deploy.sh` now accepts `DERIVED_DATA` and `DEPLOY_LOG`. The file in `Documents` can be retrieved with `devicectl device copy from --domain-type appDataContainer` (tested).
- **Runs:** 2 complete with entitlement (one with ProMotion key set) plus 1 frame-rate run; 3 complete without entitlement. No run ended due to Jetsam; no restart or crash.

## 3. Memory With and Without Entitlement
All values in MiB. “Limit” = `os_proc_available_memory` + `phys_footprint` at the same time (sum was always 5120.0 or 8192.0 ± 0.5, including during ramps).

| | Without entitlement | With Increased Memory Limit |
|---|---:|---:|
| `os_proc_available_memory` at first image | 4941.9 (3 runs: 4941–4963) | 8013.8 (2 runs: 8014) |
| Limit (sum) | **5120** | **8192** |
| Native: held until stop | 4480 (reason: reserve, 402.7 available) | 5888 (reason: 6-GiB ceiling, 2108.8 available) |
| Render: held until stop | 4480–4608 (reserve, 289.6–420.4 available) | 5888 (ceiling, 2076 available) |
| Managed: held until stop | 2816 (3-GiB ceiling) | 2816 |
| `lowMemory` | at footprint 4035–4205 (native) and 4057–4164 (render), in all 3 runs | native at 6083, render **no** warning through 6116 |
| Jetsam | not triggered (stopped with reserve) | not triggered |

Observations:
- The limit can be calculated exactly at runtime: `Limit = os_proc_available_memory() + phys_footprint`. The game can determine its own budget instead of hard-coding values.
- **GPU memory fully counts toward footprint:** each 128-MiB RenderTexture increased footprint by about 128 MiB (`mtlAllocMiB` reached 6028 MiB, above `recommendedMaxWorkingSetSize` of 5461 MiB, without consequences). Unified memory means textures and render targets use the same budget as everything else. `SystemInfo.graphicsMemorySize` reports only 2048 MB and is not useful as a budget.
- **Native pages are heavily compressed or paged out on this iPad** (`compressed` 5326 with entitlement at `internal` 626 MiB; 4324 without at 220 MiB), despite the data being random. Footprint still counts them fully. After `FreeHGlobal`, footprint fell from 6083 to 832 (3 s later; `compressed` initially remained at 320–484). Accessing paged-out pages costs time; this was not measured.
- **The managed heap (Mono/Boehm) does not return memory:** after freeing the `byte[]`, footprint stayed around 3025 MiB (`internal` 2851) until the app exited. Large short-lived managed peaks are costly; native buffers and RenderTextures are freed correctly.
- A small one-time extra cost appeared during render steps: footprint grew by slightly more than 128 MiB per step (without entitlement, the reserve fell below 300 MiB in two runs, to 289.6, with no consequences).

## 4. Empty Unity Scene Footprint (Metal, Release)
| Time | Footprint | Of which `internal` | Resident | Unity allocator | Metal `currentAllocatedSize` |
|---|---:|---:|---:|---:|---:|
| `Awake` (about 2.1 s) | 156.4–177.9 | 52 | 141 | 48 | 97–119 |
| First image | 178.1–178.5 | 52 | 142 | 48 | 119 |
| After 8 s (baseline) | 179.4–179.6 | 53 | 143 | 48 | 117 |
| During sustained load | 190.7–192.9 | 64 | 154 | 48 | 117 |

**Baseline: about 180 MiB** (no game content, with Metal device, layer, backbuffer at 2732 × 2048, and Unity core). This is 7% of the 2.5-GB target. The `Profiler` counters also return values in Release builds (`unityAllocMiB`, `monoHeapMiB`). Note: the game adds IL2CPP metadata, assemblies, and shader-variant memory, which are absent here.

## 5. Frame Rate, ProMotion, Thermals
Display: `Screen.currentResolution` 120 Hz, `UIScreen.maximumFramesPerSecond` 120, resolution 2732 × 2048 at 264 dpi. Averages over 3–4 runs; all runs agree within ±0.1 FPS. “Idle” = empty scene, “light” = full-screen shader with 24 iterations.

| `vSyncCount` | `targetFrameRate` | Measured idle | Measured light | p99 frame time |
|---|---:|---:|---:|---:|
| 0 | -1 (default) | **30.0** | – | 33.4 ms |
| 1 | -1 | **30.0** | – | 33.4 ms |
| 2 | -1 | **30.0** | – | 33.4 ms |
| 0 | 120 | **119.9** (min 107–117) | 119.9 | 8.5 ms |
| 1 | 120 | 119.9 | 119.9 | 8.5 ms |
| 2 | 120 | 119.9 | – | 8.5 ms |
| 0 | 60 | 60.0 | 60.0 | 16.8 ms |
| 1 | 60 | 60.0 | – | 16.8 ms |
| 2 | 60 | 60.0 | 60.0 | 16.8 ms |
| 0 | 30 | 30.0 | 30.0 | 33.4 ms |
| 4 | 30 | 30.0 | 30.0 | 33.4 ms |

- **Unity on iOS follows `Application.targetFrameRate`; `vSyncCount` alone changes nothing** (all values with target -1 gave 30 FPS; all with target 60 gave 60 FPS). The project must always set the target. `DisplayController` sets both (`FrameRatePlanner`: 120 Hz, 60 FPS → vSync 2, target 60; 30 FPS → vSync 4, target 30), which is correct; all three combinations were measured. The Probe build's project setting (iOS quality level, measured `vSyncCount` 1, target -1) also gave 30 FPS. Note: `ProjectSettings/QualitySettings.asset` contains six default levels (vSync 0–2), not the single original level with vSync 2 from `docs/render-treue.md`; not investigated further here.
- **ProMotion key:** Apple says `CADisableMinimumFrameDurationOnPhone` is needed only for iPhone. On iPad, 120 FPS was the same with `false` (Unity default, `appleEnableProMotion: 0`) and `true` (separate build). Both cases had `CADisableMinimumFrameDuration` in Info.plist (Unity sets both identically). Keep the switch off.
- The 5-s windows did not show whether the system temporarily lowers the rate below target during variable ProMotion operation (minimum individual frame rate about 107 FPS in one window, otherwise 113–117). `FrameRateMode.Variable120` has thus only been checked with target 120 and vSync 0, not under changing load.
- **Sustained load:** 10-s window, then 150 s with a full-screen shader (160 iterations), GPU saturated: steady **44.5–44.7 FPS**, minimum individual frame rate about 27–30 FPS, `thermalState` 0 in all 15 windows, no decline. Then 300 s with 6 additional background threads (compute loop): FPS immediately fell to **31.2** (first window 33.9) and stayed there for 15 windows; `thermalState` remained 0. The decline was due to CPU contention, not heat; the cause was not analyzed further.
- Footprint remained stable during sustained load (190–193 MiB, no leak).

## 6. Derived Memory Budget
Basis: limit without entitlement 5120 MiB, with entitlement 8192 MiB; warning threshold about 4.1 GB without entitlement and 5.9 GB with it; baseline 0.18 GB.
- **Hard ceiling 4 GB footprint** (user requirement, Switch-level): with entitlement this is 1.9 GB below the first warning and 4.1 GB below the limit. **Without** entitlement, 4 GB is right at the warning threshold and only 1 GiB below the limit, too tight. Therefore: **leave entitlement enabled** (default in `IosPostBuild`).
- **Target 2.5 GB** footprint during sustained operation: leaves 2.6 GB to the limit and 1.6 GB to the warning even without entitlement. After subtracting baseline, about **2.3 GB for content** remains.
- **Proposed allocation** (not measured, planning value only; adjust after measuring the actual game): textures and render targets about 1.2 GB, meshes/animation/material about 0.4 GB, native buffers and loaded bundles about 0.4 GB, managed heap at most 0.3 GB (keep small because memory is not returned), remainder as reserve.
- **Code implications:**
  1. Read `Limit = available + footprint` at startup and before each zone transition, and budget against it (do not hard-code it; other iPads with 4 or 6 GB will differ).
  2. Handle `Application.lowMemory` (clear caches, unload bundles): without entitlement the warning came 1 GiB before the limit.
  3. Keep large textures and bundles only for the current zone (see `docs/feld-szene-1.md`, section 9), then unload them; avoid managed allocations in the loading path.
  4. Unified memory: render targets (e.g. shadows, post-processing at 2732 × 2048) count fully.
  5. Always set `Application.targetFrameRate` (section 5).

## 7. Measurement Uncertainty and Gaps
- **One device, one iPadOS version (26.4.2), one app with no game content.** 8-GB model; these numbers do not apply to 4- or 6-GB iPads or 16-GB models (1 and 2 TB).
- The **8192 MiB with entitlement** figure was demonstrated only up to 6116 MiB footprint; we deliberately stopped (target was about 6 GB). The point at which system pressure causes a real kill at 7.5 GB of memory use was **not measured**. The limit is an upper bound, not available memory: other background apps reduce the practical maximum, and this was not measured (background apps were not controlled during runs).
- The development signature (`get-task-allow`, 7-day profile, free team) may differ from another distribution. Only this case was observed; the app also ran under `devicectl --console` (without debugger, but with console attached).
- The ramps fill memory with random data. Real game state (compressible textures, streaming) behaves differently under compression and paging. The effect of paging on frame time was not measured.
- `os_proc_available_memory` and `phys_footprint` are rounded system counters; differences below 1 MiB between runs are noise. Footprint growth per render step (>128 MiB) includes driver auxiliary memory.
- Frame-rate windows last 3.5–6.5 s each, enough for averages but not rare stutters. Load was synthetic (a full-screen shader), not the game. A **real** heat test (30 minutes of gameplay, device case, room temperature) is missing: `thermalState` stayed nominal after about 8 minutes, which says nothing about sustained operation. Room temperature and iPad charge level were not recorded.
- The display was on during runs (the app sets `Screen.sleepTimeout = NeverSleep`, only while it is running); measurement depends on the iPad staying unlocked.
- Process side effect: during the Probe run with ProMotion key set, bundle ID `dev.local.xnum0` was accidentally overwritten at first (build-script bug: stale SerializedObject). The script was fixed and `xnu-m0` reinstalled on the iPad. Project settings were reset every time (`git status` for `ProjectSettings` remained empty).
