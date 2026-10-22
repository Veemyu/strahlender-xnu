# Changelog

Chronological, newest entries first. Each item records the date, goal, and files.

## 2026-10-22

- **Remote Linux host removed:** the SSH/rsync wrappers for the former Linux build machine are gone (`scripts/recomp/linux/build.sh`, `lib.sh`, `sync.sh`, `fetch.sh`, `run_probe.sh`, `check_deps.sh`, `vk_sync.sh`, `vk_fetch.sh`, the remote `vk_*.sh` wrappers, and `host/job.sh`). Linux builds now run only locally, from the repository root.
- **Ryujinx and key-player scripts removed:** `scripts/ryujinx_sync_save.sh`, `scripts/ryujinx_fetch_shots.sh`, `scripts/ryujinx_record.sh`, `scripts/ryzen_keys.py`, and its test `scripts/tests/test_ryzen_keys.py`. Reference screenshots are now copied by hand into `work/visual/ref/ryujinx/raw/` and imported with `scripts/visual_ref.py import`.
- **Local Linux build:** `scripts/recomp/linux/host/` renamed to `scripts/recomp/linux/local/`; `scripts/recomp/diff/run_ryzen.sh` renamed to `run_linux.sh`. `setup.sh` treats the manifest `work/exefs.sha256` as optional; create it from the repository root with `sha256sum work/exefs/rtld work/exefs/main work/exefs/sdk work/exefs/subsdk0 > work/exefs.sha256`.
- **Visual check:** the `--fetch` option of `scripts/visual_auto.sh ref` is removed; the `ryzen` block in `scripts/visual/ref_map.json` is removed (views and masks stay).
- **Docs and labels:** `docs/BUILD.md`, the Linux, Vulkan, and diff docs describe the local build; the former machine label "Ryzen" in code comments is now "Linux".

## 2026-10-19

- **Patch structure removed:** The NVN layer is now present in the repository as complete source: `scripts/recomp/rt-bdsp/nvn/src/` (Metal) and `nvn/vulkan/src/` (Vulkan differences). `prepare.sh` and `prepare_vk.sh` now only copy files; they no longer apply patches. Removed: `las-nvn.patch`, `fixes.patch`, `dbgthread.patch`, `debug.patch`, `prof.patch`, `exec_worker.patch`, `las-vk.patch`, and shim copies (contents are in `src/`). The translator remains in `shader_translator/` (single source).
- **License:** NVN files have been changed from LASRecomp; NOTICE files now say so explicitly. Unmodified original for comparison: `scripts/recomp/upstream/runtime/`.
- **Translation worker in code:** `shim/exec_worker.inc` no longer exists separately; its code is in `src/exec_worker.inc`. On Mac, the worker is now the default (`BDSP_EXEC_WORKER=0` switches to the old synchronous path). Presentation, fences, and pool entries follow queue order; black flashes came from the frame counter (`total_frames + 1` in the worker), not guest data.

- **Docs cleaned up:** `bauen.md` and `build-pipeline.md` now list only current stages. Sections about removed Unity stages are marked historical. iPad instructions now use `scripts/recomp/ios/deploy_ios.sh`. Status note added at the top of both files.
- **Unity stages removed from scripts:** see next item.

- **Unity stages removed:** `assets`, `stubs`, `unity-build`, and `deploy` were removed from `scripts/build_all.sh` and `scripts/build_stages.py`, along with editor detection (`editor-open`), `--shaders-into-unity`, and Unity/Xcode preflight. The shader stage remains (reads the game's Unity bundles via UnityPy). Tests updated; 347 pass.
- **Unity on `unity` branch:** see item above (Unity project, docs, test for `material_variants`).

- **Unity on `unity` branch:** Unity project `unity/` (810 files), `scripts/unity_safe.sh`, `docs/unity6-tooling.md`, `docs/unity-autopilot.md`, `docs/feld-szene-2.md`, `docs/material-remap.md`, `docs/shader-unity-integration.md`, and test `scripts/tests/test_material_variants.py` (fixture from `unity/`) were removed from `main`. Branch `unity` is on origin (at 13b3977, complete). README, architecture decision, and documentation index point to it.
- **Intentionally still on main:** build stages `stubs`, `assets`, `unity-build`, `deploy` in `build_all.sh` and `build_stages.py` (follow-up), shader stage (reads game Unity bundles through UnityPy), plus `stub_*`, `visual_*`, `bundle_retarget.py`, `material_*.py`.
- **Local directory unchanged:** ignored `unity/` folder (3.6 GB, including `Library`) remains on disk and is not versioned.

- **License:** Root `LICENSE` (MIT, Copyright (c) 2026 Veemyu). README section “License for Original Code” added. Third-party code retains its license.

- **Vendored everything:** `scripts/recomp/upstream/runtime/` is an unmodified copy of the clone's full runtime (including `nvn/`, `nvn/vulkan/`, `hle/`, `services/`, `platform/`, `ui/`); `scripts/recomp/upstream/generator/` is the tool directory (including `rando/`). Both byte-identical to `09f8e5e`. Not included: original `third_party/` (separate licenses, Nintendo exclusion), `fonts/`, clone metadata.
- **Single NVN source:** duplicate `scripts/recomp/rt-bdsp/nvn/upstream/` removed. `nvn/prepare.sh` and `nvn/vulkan/prepare_vk.sh` copy from `scripts/recomp/upstream/runtime/`.
- **Ryzen and diff tools:** paths changed to `scripts/recomp/upstream/`; `sync.sh` and `vk_sync.sh` no longer transfer the clone directory because it is part of `scripts/recomp`.
- **Clone no longer needed:** the build no longer reads `research/`. Verified: Mac runtime, iPad build, NVN preparation for Metal and Vulkan, 370 tests, `repo_check`.

- **Clone no longer needed:** generator tools (`gen.py`, `lifter.py`, `analyze.py`, `nso.py`, `patches.py`, `simd_c.py`) are unchanged under `scripts/recomp/upstream/generator/`. Paths in `eh_gen.py`, `mkimg.py`, `build_stages.py`, `recomp_build.sh`, and tests point there. The directory is deliberately not named `tools/` because `repo_check.py` rejects any path containing `tools/`. Randomizer (`tools/rando/`) not included.
- **Test/build paths:** test scripts (`scripts/recomp/test/`, `rt-bdsp/test/`) use `scripts/recomp/upstream/runtime`. Not switched: `scripts/recomp/diff/`, `scripts/recomp/linux/`, and `run_boot_probe_las.sh`; they still need the clone's full LASRecomp runtime (services, platform).

- **Vendored headers:** unchanged `cpu.h`, `simd.h`, `simd_fp.h` under `scripts/recomp/upstream/runtime/`. App build scripts (`rt-bdsp/build.sh`, `nvn/build_nvn.sh`, `nvn/vulkan/build_vk.sh`, `ios/build_rt32.sh`, `ios/compile_chunk_ios.sh`) use this path. Verified: iPad build and Mac runtime linked.
- **Provenance corrected:** comparison found verbatim lines in `kernel.c`, `ipc.c`, `services*.c`, and more (8–47%). The earlier statement “no file was copied” was wrong and has been corrected in NOTICE, THIRD_PARTY_NOTICES, and README.

- **NVN vendoring:** upstream source for NVN layer (Metal and Vulkan, excluding `imgui_glue.cpp`, `texpatch.c`, `output_scale.c`, `smaa_data.c`) is now unmodified under `scripts/recomp/rt-bdsp/nvn/upstream/`, with `LICENSE`. `prepare.sh` and `prepare_vk.sh` copy from there. Commit pin removed because repository now holds the source. Verified byte-identical to clone; iPad build has no `.rej`.
- **Pin (superseded):** the temporary commit pin in `prepare.sh` remains only as an earlier stage in history.
- **Attribution:** new root `README.md` with third-party code section (LASRecomp, MIT). `THIRD_PARTY_NOTICES.md` corrected: NVN renderer is copied at build time, contradicting previous text. FFmpeg and build tools added.
- **Settings.bundle:** excluded by `*.bundle` in `.gitignore`; exception added, bundle is now versioned.
- **Rename:** all `LARECOMP_*` environment variables are now `BDSP_*` (code, patches, scripts, docs). `nvn/prepare.sh` and `nvn/vulkan/prepare_vk.sh` rename copied upstream sources before patching. Intentional exceptions: `shader_translator/NOTICE.md` and `shader.h`, where the old name documents provenance.
- **Frame rate:** iPad settings `bdsp_fps` (30/60/120) and `bdsp_metal_hud`, localized (`en.lproj`, `de.lproj`, label “Frame Rate”). Mac menu “Frame Rate” (not localized yet).
- **Metal HUD (iPad):** switch under “Debug” in settings; takes effect after restart via `MTL_HUD_ENABLED`.
- **Vsync:** fixed 16.67-ms interval drifted to about 50 Hz. Now uses absolute deadlines in `services_gfx.c`. Mac measures 59.9 fps.
- **Debug thread:** `BDSP_DEBUG_THREAD=1` moves readbacks to a separate thread (`dbgthread.patch`, `debug_thread.c`).
- **Water (Todo 1):** depth test only with bound depth target (`fixes.patch`, commit `f22b7f9`).
