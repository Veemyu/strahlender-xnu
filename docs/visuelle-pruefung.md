# Automated Visual Review (Screenshots, Comparison, Ryujinx Reference)

> **Historical report:** This document describes the deprecated Unity rebuild. The native static recompilation is the current product; this document is retained as project history.

Status: 2026-10-19, 14:40. Goal: capture images of Unity scenes and compare them **automatically**, rather than by hand. One command:

```
scripts/visual_auto.sh run            # capture -> compare with baseline -> report + contact sheets
```

Images, reports, and references live only under ignored `work/`; the repository contains scripts, scenario lists, routes, and this guide. No audio: nothing plays anything (tests and scripts use synthetic images only).

**Delivery status (honest, 15:30):** comparison, anomaly detector, reports, contact sheets, scenario list, orchestration, reference import (Ryujinx and recompilation), and key player are complete and tested (Python tests, dry runs, real F8 test on the Linux host). **Unity Editor capture code** (`Xnu.Visual.Capture`) runs in the **lab Editor** (`work/unity-shader-lab`, copied under `Assets/XnuSrc/Visual/Editor/`): `XNU_UNITY_PROJECT=$PWD/work/unity-shader-lab scripts/visual_auto.sh run …` captured 11 field scenarios in 30 s (zones 24, 27, 422, 425, 54, 367, 167, 168), compared them, and wrote reports and reference comparisons. Source remains under `work/visual/phaseB/`; it will only be copied into `unity/Assets` after approval (section 7). Until then, `visual_auto.sh run` in the main Editor exits with code 4.

## 1. Commands

| Command | Effect |
|---|---|
| `scripts/visual_auto.sh run [--quick] [--only a,b] [--mode editor\|player\|ipad] [--strict] [--ref]` | Capture, compare, report at `work/visual/auto/run-<time>/report.md`. `--quick`: only scenarios tagged `quick` (4 field images, about 1–2 minutes). Exit 0 = no regression, 1 = regression, 2 = error, 4 = capture code missing |
| `scripts/visual_auto.sh compare [--run RUN\|latest] [--ref [ryujinx\|recomp\|both]]` | Compare an existing run only; `--ref` adds reference comparison (Ryujinx F8 images, recompilation, or both) |
| `scripts/visual_auto.sh accept [RUN]` | Accept run as the **new baseline** (`work/visual/auto/baseline/`, old baseline to `baseline.alt/`). **Only after** the main agent/user has reviewed contact sheets |
| `scripts/visual_auto.sh watch [--interval MIN] [--once]` | Run every N minutes (default 10) when `unity/Assets/Scripts/{Field,Render}` or `scripts/shader_*` changes |
| `scripts/visual_auto.sh ref [--fetch] [--run RUN] [--ref ryujinx\|recomp\|both]` | Fetch references (`--fetch`, Ryujinx) and compare with a run (section 8); for lab Editor, set `XNU_UNITY_PROJECT=$PWD/work/unity-shader-lab` before `run` |
| `scripts/visual_auto.sh scenarios \| test \| status` | Validate scenarios, run Python tests, show status |
| `python3 scripts/visual_compare.py analyze IMAGE… [--kind field\|room\|ui]` | Run anomaly detector on individual images only |
| `scripts/ryujinx_fetch_shots.sh [fetch\|status\|cache\|reset]` | Fetch F8 screenshots from the Linux host (section 8) |
| `scripts/ryujinx_record.sh ROUTE [--dry-run]` | Play a key sequence in Ryujinx and collect images (section 9) |

Capture modes: **editor** (default: field scenarios through `Xnu.Visual.Capture` in `FieldTest2`, then sequences in the `Game` scene in Editor play mode), **player** (macOS build `work/builds/macos/xnu.app`, game-scene sequences only), **ipad** (`devicectl`, game-scene sequences only; not yet run). Control the Editor with `scripts/unity_safe.sh` (status/open) and `unity command … eval`; `visual_auto.sh` starts it only if it is not already open.

## 2. Files

| File | Purpose |
|---|---|
| `scripts/visual/scenarios.json` | Capture list: 13 field scenarios (standard test save: zone 24 at hour 2, zone 27 inside Pokémon Center; also 422 at hour 4, 425, 54, 367, and older 167 at hour 2 and 168), 14 game-scene images in two sequences (`durchlauf`: title, field, interior, text, choice, battle; `menue`: menu, team, bag, status); 1280×720, stable names, wait frames (`settle_frames`), type (`kind`), allowed flags, per-scenario thresholds |
| `scripts/visual_scenarios.py` | Validate/export list (`validate`, `list`, `script SEQUENCE`, `export-field`, `mark-requested`) |
| `scripts/visual_compare.py` | Comparison, anomaly detection, reports, contact sheets, `accept`, `ref` mode |
| `scripts/visual_ref.py` | Ryujinx references: import/normalize, compare with heatmap, shader cache counts |
| `scripts/visual_auto.sh` | Orchestration |
| `scripts/visual/ref_map.json` | Reference views, scenario mapping, masks, Linux-host paths |
| `scripts/visual/routes/*.keys` | Ryujinx key sequences |
| `scripts/ryzen_keys.py`, `scripts/ryujinx_fetch_shots.sh`, `scripts/ryujinx_record.sh` | Key player, fetch, capture driver |
| `scripts/tests/test_visual_*.py`, `test_ryzen_keys.py` | 49 tests with synthetic images (`scripts/visual_auto.sh test`) |
| `work/visual/phaseB/Capture.cs`, `Xnu.Visual.Editor.asmdef` | Editor capture code (not yet in `unity/`) |

A run folder contains: `shots/<name>.png`, `capture.json` (capture metadata, `requested` = expected names), `report.md/json`, `diff/<name>.png` (difference ×4), `contact/overview_NN.png`, `contact/compare_NN.png`; with `--ref`, also `ref_report.md`, `ref/*_heatmap.png`, `contact/ref_NN.png`.

## 3. Baseline comparison (per image)

Metrics: RGB mean (old/new), mean absolute difference (MAD), changed-pixel share (channel difference >16), **SSIM** (custom implementation, 8×8 luminance windows), Laplacian variance (edge sharpness/texture detail) and ratio, histogram distance, histograms (16 luma bins, 8 bins per RGB channel) in JSON, plus resized dimensions.

A **regression** (exit 1) occurs when a threshold is violated: SSIM <0.80, MAD >12, changed >25%, detail ratio <0.5, mean shift >25, increase in “directed structures” >0.03 or largest flat region >0.08, **new** error flags compared with baseline, or an expected capture is missing. Flags already present in baseline are “known” and do not trigger (known defects such as the white player character remain visible until fixed but do not block). `--strict`: flags on images without a baseline also count as regressions. Per-scenario thresholds: `thresholds` in `scenarios.json`.

## 4. Anomaly detector (no reference, heuristic error images)

Image kinds (`kind`): **field** (all detectors), **room** (skip `flat_large`, since rooms sit against a flat camera background), **ui** (only empty, mean, colors; menus legitimately contain white panels).

| Flag | Detection | Threshold |
|---|---|---|
| `bars` | black edge columns/rows (≥93% of pixels ≤10) | ≥1.5% of width/height |
| `empty_constant` | luma spread or 5-bit color count | spread <1.5 or ≤4 colors |
| `mean_out_of_range` | content luma mean | <10 or >245 |
| `magenta`, `cyan` | pixel share (R,B ≥180 and G ≤⅓; or G,B ≥180 and R ≤⅓) | ≥0.2% |
| `white_region` | connected components with all channels ≥250, size ≥0.5% (at least 3,000 px), rectangularity ≥0.40 | total ≥0.5% of image |
| `black_region` | connected components, all channels ≤8 | total ≥4% |
| `large_flat` | 8×8 blocks with channel range ≤3; largest connected region | ≥10% of image |
| `stretched` | structure tensor per 16×16 tile: coherent (≥0.93), diagonal (≥22° from axes) | ≥15% (see limitations) |
| `hud_text` | bright text-glyph components in upper-left (informational, not an error) | ≥20 components and ≥3% bright |

Each flag reports value, threshold, and rectangles; the contact sheet outlines error regions in red.

### Calibration against existing images (`scripts/visual_compare.py analyze`)

| Image | Flags |
|---|---|
| **User screenshot** `user/mac-preview-zone167.png` (known defects) | **`bars`** (16.5%), **`white_region`** (2.5%, bounding box 449–709 × 258–438, fill 0.67), **`large_flat`** (28% water and flat ground), **`hud_text`** (33 glyphs); 4 flags |
| `z422_h12_final.png` (good), `v3_z422_h12`, `z422_h22`, `v3_z54_h12`, `v3_z367_h12`, `v3_z425_h12` (room), `fieldrender/w1.png` | **none** |
| `fieldrender/before_167.png`, `before_54.png` (before fix) | `white_region` (25,975 and 23,771 px) + `large_flat` |
| `fieldrender/before_422.png`, `before_425.png` | `large_flat` (35%); `black_region` (4.6%) |
| `fieldrender/gen_167b.png` (current fix) | `large_flat` only (13%: water remains flat and dark brown) |
| `fieldrender/gen_167.png` | `cyan` |
| `z425_h12.png` (old) | `magenta` (0.34%, player character after zone transition) |
| `ipad/run4/g1_innen.png` | `empty_constant` (blank frame during transition) |
| Game UI images (`vslice`, `ui2`, iPad), as `ui` | none (except `g1_innen`) |

Thresholds were tuned so legitimate white shapes (Poké Ball emblem, 3,700 px, fill 0.22) do not trigger, while defect quads (24,000–31,000 px, fill >0.65) reliably do.

### Detector limitations (honest)

- **Stretched/smeared rock walls and the diagonal triangle band** in the user screenshot are **not detectable without a reference**: tile coherence and edge patterns cannot distinguish them from legitimate patterns (herringbone paving in zone 54: 8% “directed tiles”; rock wall in user image: 0.8%). A diagonal-band detector was tried and dropped (zone 367 fence has longer diagonal edges). These defects show up **in comparison** (SSIM, detail ratio, increase in directed structures, difference image) and Ryujinx reference comparison (section 8); contact-sheet review is still needed.
- **White character:** gray-white, hard to distinguish from window panes; no flag. It appears in every field image and is treated as a known baseline condition.
- Animated elements (water, character) produce small image differences; thresholds account for them.

## 5. Report and agent review

`report.md` contains a summary, table (image, status, SSIM, MAD, changed, Laplace old→new, mean RGB, flags; bold = error flag, `*` = new), regressions, flag details with regions, and at the end **“For manual/agent review”** with absolute paths to contact sheets. The main agent opens them with the image-view tool:

- `contact/overview_NN.png`: run-wide image grid (5 rows × 4), error regions in red.
- `contact/compare_NN.png`: per image **baseline | run | difference ×4**, sorted by amount changed, four images per sheet (1248 px wide).

Workflow: `run` → read report → inspect contact sheets → fix issues and rerun → `accept` after approval. Only the main agent accepts a baseline after review.

## 6. Scenarios (excerpt)

Field (Editor, `FieldTest2`): **`field_z24_h12|h18`** (standard test save: Mio City/Fleetburg, cell 57/729, facing north), **`field_z27_h12`** (inside Pokémon Center there, type `room`), `field_z422_h07|h12|h18|h22` (cell 116/886, facing north; hour via `XNU_ENV_HOUR`), `field_z425_h12` (player home interior, type `room`), `field_z54_h12` (locator 0), `field_z367_h12` (cell 512/726), older checkpoints from the previous save `field_z167_h12|h18` (cell 840/599, Pokémon Center entrance before water/rock wall; known issues in user screenshot), and `field_z168_h12`. Game scene (`Game`, input script such as `work/vslice/run4.txt` and `work/ui2/run1b.txt`): `game_titel`, `game_feld_z24`, `game_innen_z27`, `game_text`, `game_auswahl`, `game_nach_ereignis`, `game_kampf_befehl|attacken|meldung`, `game_menue`, `game_menue_rechts`, `game_team`, `game_beutel`, `game_bericht_frage`. Game-scene images use script command `shot` (`-xnuShotDir`); sequence ends with `quit` (Editor: `visual_auto.sh` exits play mode after last image).

### 6.1 Standard test save from 14:50 (location derived from SaveData)

SaveData SHA-256 `0396a4a62735…`, Backup.bin `7a324b865ea9…`, play time 69:08:16, Mio City (Japanese ミオシティ; German version Fleetburg). Do **not** infer location from `TownMapLocation` anymore. Finding from Python reading of 979,108 bytes, compared with the 69:05 save and older Victory Road save:

| Field (offset) | Previous save (zone 167) | 69:05 save | **new save** |
|---|---|---|---|
| `zoneID` (0x5634) | 167 | 416 | **24** (`C02`, bundle `fields/area010`) |
| `TownMapLocation` (0x8FB04 + 0x54: zone, x, y, z) | 167, −842 / 6 / 597 | 416, −789 / 1 / 355 | 416, −789 / 1 / 355 (**stale**: zone ≠ `zoneID`) |
| **PLAYER_DATA cell** (0x79BF4: int gx, int gy, float height) | **852, 599**, 6.0 | 789, 357, 1.0 | **57, 729**, 1.0 |

The new save is therefore in **zone 24, cell (57, 729)**; `TownMapLocation` points to the previous zone (416) and is not updated in cities. Evidence: (a) cell (57, 729) lies in zone 24 (locators 37–63 / 714–755), seven cells below the Pokémon Center locator (58, 723)—exactly as in the Ryujinx screenshot (Pokémon Center at top, player below, harbor crane at left); (b) in both older saves, the PLAYER_DATA cell is near the zone locator (789/357 ≈ locator 2 (789, 357) in zone 416). Facing direction is not in the block found (**[A]** assumed north). **Game-core consequence (not changed here):** `SavedPosition.Read` in `Game/Runtime/SaveSlotService.cs` discards the position when `TownMapLocation` zone ≠ `zoneID`; driver then starts at zone locator 0 (58, 723) instead of (57, 729). Better: read cell from PLAYER_DATA 0x79BF4/0x79BF8 (valid if x/y are inside the zone), use `TownMapLocation` only as fallback.

Updated to this save: scenarios `field_z24_h12|h18`, `field_z27_h12`, `game_feld_z24`, `game_innen_z27`; input sequence `durchlauf` (door at locator (58, 723), interior zone 27); reference views `ref_01_feld_weiter` (Unity: `game_feld_z24`, `field_z24_h12`) and `ref_03_innen_eintritt` (`game_innen_z27`, `field_z27_h12`); routes `boot_weiter`, `tuer_innenraum` (one cell right, seven up). No baselines existed yet (nothing to discard).

## 7. Adopting capture code (Phase B)

Only after approval from the main agent (main Editor currently belongs to `ap-field-render`; check `scripts/visual_auto.sh status`, `scripts/unity_safe.sh status`; no tests or play mode running):

0. **Proven in lab Editor (15:12–15:25):** copied `Capture.cs` and `Xnu.Visual.Editor.asmdef` to `work/unity-shader-lab/Assets/XnuSrc/Visual/Editor/`, recompiled (0 errors), used menu `Xnu/Field/Create FieldTest2 Scene` (lab scene did not exist), then `unity command … eval 'Xnu.Visual.Capture.CaptureAll("<list>", "<output>");'` (**trailing semicolon is required**, otherwise “; expected”). Result: 8 scenarios in 30 s, 11 in about 40 s (50–75 ms capture per image, remainder zone transitions); `capture.json` state `finished`. Then `visual_auto.sh run --name lab-full --only … --ref both` ran from capture through report in the lab Editor without manual steps (`XNU_UNITY_PROJECT` points to lab).
1. Copy `work/visual/phaseB/Capture.cs` to `unity/Assets/Scripts/Visual/Editor/Capture.cs`, and `Xnu.Visual.Editor.asmdef` beside it (references `Xnu.Field`, `Xnu.Field.Editor`, `Xnu.Core`; Editor-only). Unity creates `.meta` files.
2. Recompile (`unity command … recompile`) and check console errors (lab: 0).
3. Run `scripts/visual_auto.sh run --quick`: capture four images, review report and contact sheets.
4. Run `scripts/visual_auto.sh run`: all scenarios including game-scene sequences (not tested in lab: it has no `Game` scene); after review, `accept`.

How `Xnu.Visual.Capture.CaptureAll(scenariosPath, outDir)` works: reads exported list (`visual_scenarios.py export-field`), opens `FieldTest2`, sets `XNU_GAMEDATA`, `XNU_GENERATED_SHADERS=1`, `XNU_ENV_HOUR`, and enters play mode (state in `SessionState` survives domain reload). For each scenario: set hour, `FieldController.BeginSwitchZone(zone, locator)`, wait for transition, if a cell is specified, `Mover.Teleport` + `ForceStream`, wait `settle_frames`, call `FieldShot.Capture` (RenderTexture, alpha 255). Writes `<outDir>/shots/<name>.png` and `capture.json` (`state` running/finished/error, timings, per-image status and zone state). Unsaved state from another scene aborts instead of opening a dialog; menu `Xnu/Visual/Capture All` reads `work/visual/auto/current-job.json`.

## 8. Ryujinx reference

Ryujinx 1.2.78 (Vulkan, `res_scale` 1, `Fixed16x9`) on the Linux host supplies reference images of the original game. Screenshot key **F8**, output `~/.config/Ryujinx/screenshots/` on that host (filename `Pokémon Brilliant Diamond_<date>_<hh-mm-ss>.png`, 1280×720).

### 8.1 Fetch and assign

`scripts/ryujinx_fetch_shots.sh fetch [--since "2026-10-19 14:40"]` fetches only **new** files (`rsync -rt --ignore-existing`, preserves file times) into `work/visual/ref/ryujinx/raw/`, assigns them to views from `scripts/visual/ref_map.json`, and writes normalized 1280×720 images in `views/<view>.png` (remove black bars, center on 16:9, scale) and `assignments.json` (file, time, **game hour**). Idempotent. Errors: host offline → exit 2 with a hint; screenshot folder not yet present → exit 3. `status` shows state, `cache` shader-cache counts, `reset` archives assignments (deletes nothing). `--since` skips older test images.

Assignment uses file-time order for free views, or explicit renaming: a file whose name starts with a view name (e.g. `ref_03_innen_eintritt….png`) claims that view; files prefixed `free_` remain unassigned.

### 8.2 User instructions (two exactly reproducible states)

Reproduce the moment after choosing “Continue” at the saved location (standard test save: zone 24, Mio City/Fleetburg, cell 57/729, section 6.1) and the door-to-Pokémon-Center-interior route (zone 27). First run `scripts/ryujinx_sync_save.sh status` (save hash `0396a4a62735` must match on Mac and Linux host).

1. Start Ryujinx and reach the **title screen** (“Continue”). Keep its window in front.
2. Select **Continue** (A = `Z`), wait for the field to settle. **Do not move. Press F8** → `ref_01_feld_weiter`.
3. Open main menu (Switch X = `C`), press **F8** → `ref_02_menue`; close menu with B (`X`).
4. Walk straight up through the Pokémon Center door (hold Up); after loading, press **F8** immediately upon entry without further input → `ref_03_innen_eintritt`.
5. Optional: press A at the counter, capture the nurse's first text box with **F8** → `ref_04_text_schwester`.
6. On Mac, run `scripts/ryujinx_fetch_shots.sh fetch --since "<time before step 1>"`.

**Time:** no need to note it. Comparison derives game hour from screenshot file time: `((epoch + system_time_offset) mod 86400) / 3600` in UTC (config: `system_time_offset` −1388 s, `system_time_zone` UTC). Example: screenshot at 14:32 local (12:32 UTC) → game hour 12.2. This is an **assumption [A]** (host clock + offset, UTC timezone); if needed, edit `game_hour` in `assignments.json`. `visual_auto.sh run` renders Unity scenarios for reference views at that hour (`export-field --ref-hours`; Editor path uses `XNU_ENV_HOUR`). If brightness still differs, comparison aligns histograms.

**Reference status (14:47):** first real reference image is available, `Pokémon Brilliant Diamond_2026-10-19_14-47-54.png` (game hour ≈12.4 by formula): Mio City/Fleetburg plaza, blue roof on left, Pokémon Center above, red player character (ours still white), neighbor NPC on right, evergreens, harbor crane. Assigned to `ref_01_feld_weiter` (`fetch --since "2026-10-19 14:45"`); earlier images (14:19–14:35) showed language selection and are excluded by `--since`. It is not confirmed that the image is exactly “Continue, no movement” (player is in the middle of the plaza).

### 8.3 Reference comparison

`python3 scripts/visual_compare.py ref compare --run work/visual/auto/<run>` (also `visual_auto.sh ref`, `run --ref`). For each view (Unity image from `ref_map.json`, e.g. `game_feld_z24` or `field_z24_h12`):

- Normalize both to 1280×720; exclude HUD/debug area with a **mask** (fractions of image; top-left for game scenes).
- Align image offset using cross-correlation (±48 px).
- Compute **SSIM** raw and after **histogram matching** (removes brightness/time-of-day offset), mean difference raw/aligned, **detail ratio** (Unity/reference Laplacian), **color cast** (Unity/reference channel means, brightness-adjusted), brightness ratio.
- Build **8×8 difference grid** (cells A1–H8), count poor cells (>28 mean difference), list **worst cells**.
- Write contact sheet `contact/ref_NN.png`: **reference | Unity | difference heatmap** (cells outlined/labeled red), plus `ref_report.md` with “For manual/agent review.”

Thresholds (`ref_map.json`, `gates`) apply only with `--gate` (exit 1). Unity and Ryujinx will never be pixel-identical; metrics show trends and locate errors (e.g. cell E7 = water).

### 8.4 Shader-cache comparison (counts only)

`scripts/ryujinx_fetch_shots.sh cache` reads only file sizes, header counts, and a hash prefix of `.toc` files under the host's `games/0100000011d90000/cache/shader` (format: 32-byte header, 16 bytes per entry) and compares them with our used variants (`work/materials_all/used_final.json`):

| Cache | `.toc` | Entries |
|---|---:|---:|
| `guest` (guest shaders) | 19,584 bytes | **1,222** (header count matches) |
| `shared` | 22,704 bytes | 1,417 |
| `vulkan_nvidia` (host programs) | 45,376 bytes | **2,834** |
| Our used variants (`used_final.json`) | – | **120** (119 translatable) |

Ratios: 10.2 (guest) and 23.6 (host) per used variant. These are **not directly comparable**: cache counts programs per stage combination and pipeline/specialization state, while we count shaders × keyword variant. Useful comparisons are scale (~120 shader variants versus ~1,200 guest programs: material variants are covered, not state variants) and change over time (cache grows during play; user estimates about 3,500 when complete).

### 8.5 Recompilation as second reference source (Phase C, `--ref recomp`)

The recompiled original engine (Mac Metal runtime, Linux Vulkan) is the second reference beside Ryujinx: it executes original code without an emulator. Sources: `work/recomp/shots/*.png` (Mac) and `work/visual/recomp/*.png` (Linux host). `python3 scripts/visual_ref.py import --source recomp` assigns **by filename only** (view name as prefix, `aliases` in `ref_map.json`, `free_` prefix; many `frame_NNNNN.png` files are skipped, `--all-free` imports them as `free_…`) and writes normalized images to `work/visual/ref/recomp/views/`; changed files are re-imported. Aliases: `gate2_titel*` → `ref_00_titel`, `gate2_sprachauswahl*` → `ref_00b_sprachauswahl`. To submit a recompilation image for a view, name it `ref_01_feld_weiter_metal.png` (or add an alias).

- **Unity versus recompilation:** `visual_compare.py ref compare --run RUN --source recomp` (also `visual_auto.sh run --ref recomp`, `--ref both` for both sources); report `RUN/recomp/ref_report.md`, contact sheets `RUN/recomp/contact/`.
- **Recompilation versus Ryujinx:** `visual_ref.py refs` (default `--a recomp --b ryujinx`): compare shared views, Ryujinx is the reference. Report `work/visual/ref/recomp_vs_ryujinx/ref_report.md`. This helps separate recompilation defects from emulator behavior.
- First metric: language selection (`ref_00b_sprachauswahl`, Mac Metal recompilation at 1920×1080 scaled to 1280×720 versus Ryujinx at 1280×720): **SSIM 0.999**, mean difference 0.1—practically pixel-identical.
- Recompilation title screen (`gate2_titel_metal.png`) has a **dark green background** (mean 33/88/37) and red “Press the A button” text. No Ryujinx title image for comparison yet: capture F8 at title (name `ref_00_titel….png`), then `refs` can check color/text.

## 9. Ryujinx key player (`scripts/ryzen_keys.py`)

Runs **on the Linux host** (KDE Plasma Wayland + Xwayland; `/dev/uinput` ACL for user, python-evdev available), stored at `~/xnu-recomp/tools/ryzen_keys.py`, routes at `~/xnu-recomp/routes/`, logs at `~/xnu-recomp/logs/ryzen_keys-*.log`. Nothing outside `~/xnu-recomp` is written; the user starts Ryujinx and the game (the player starts **neither**).

Using `evdev.UInput`, it creates a virtual keyboard **`xnu-virtual-keyboard`**, waits 0.7 s for the compositor to detect it, then plays a `.keys` file.

### 9.1 Key mapping (from `~/.config/Ryujinx/Config.json`, `input_config[0]` WindowKeyboard, Pro Controller, Player1; not guessed)

| Switch | Key | | Switch | Key |
|---|---|---|---|---|
| **A** | `Z` | | D-pad up/down/left/right | Arrow keys |
| **B** | `X` | | Left stick up/down/left/right | `W` `S` `A` `D` (click `F`) |
| **X** | `C` | | Right stick | `I` `K` `J` `L` (click `H`) |
| **Y** | `V` | | Minus | `Minus` |
| L / ZL | `E` / `Q` | | Plus | `Plus` |
| R / ZR | `U` / `O` | | Hotkeys | F8 screenshot, F5 pause, F4 UI, F2 mute, F1 VSync |

`ryzen_keys.py --list` displays the mapping with evdev codes. The host layout is `us`: `Plus` is sent as `KEY_EQUAL`, `Minus` as `KEY_MINUS` (**[A]**, not tested in-game; if wrong, use `map PLUS KEY_KPPLUS` in route). In BDSP, **X** (key `C`) opens main menu, **A** confirms, **B** cancels.

### 9.2 Commands in a `.keys` file

`key NAME [ms]`, `hold NAME ms`, `down/up NAME`, `combo A+B [ms]`, `type TEXT`, `wait MS`, `shot [timeout]` (F8, then wait for a **new file in screenshot folder** instead of blind delay), `shot_as VIEW [timeout]`, `wait_shot`, `require_focus`, `repeat N … end`, `map NAME KEY_XXX`, `note TEXT`; names can be Switch buttons, `KEY_…`, or Ryujinx key names. Options: `--dry-run`, `--focus`, `--time-limit`, `--speed`, `--hold-ms`, `--check`, `--list`. Final output line: `RESULT {json}` with new screenshots.

### 9.3 Safety (input must never reach another user window)

- **Before every key press**, check active window: `xprop -root _NET_ACTIVE_WINDOW` on Xwayland server (get `DISPLAY`/`XAUTHORITY` from Ryujinx process), then title (`_NET_WM_NAME` starts with “Ryujinx”) **and** `WM_CLASS` “Ryujinx”. KWin reports no active X11 window for Wayland-native windows (terminal, browser), treated as “no focus.” Send only when status is “ok”; otherwise **abort (exit 5)** and release all held keys.
- Creating `~/xnu-recomp/STOP` aborts at any time (exit 3; from Mac: `scripts/ryujinx_record.sh --stop`); timeout defaults to 300 s (exit 4); single-instance lock (exit 8); `--dry-run` sends nothing (no uinput).
- `--focus` tries `wmctrl -i -a` (often works for Xwayland windows under Wayland; otherwise focus manually).
- Tested (Python tests with simulated focus): foreign window → no key; Wayland window → no focus; focus lost mid-sequence → release key and abort; STOP, timeout, dry run.

### 9.4 Routes (`scripts/visual/routes/`) and capture driver

| Route | Contents | Status |
|---|---|---|
| `f8_only` | check focus and press F8 only | **actually run** (twice, harmless): key registered, new image after 0.36 s |
| `boot_weiter` | title → A → Continue (A) → load 12 s → F8 `ref_01_feld_weiter` → X menu → F8 `ref_02_menue` → B | **dry run only** |
| `tuer_innenraum` | F8 before door → hold Up 1.6 s → load 4.5 s → F8 `ref_03_innen_eintritt` | **dry run only** |

On Mac, `scripts/ryujinx_record.sh ROUTE [--dry-run] [--focus] [--no-compare]` displays save sync status (`ryujinx_sync_save.sh status`, read-only), copies `ryzen_keys.py` and route to Linux host, checks focus (exit 5 and sends no key if not focused), runs sequence, fetches new images to `work/visual/ref/ryujinx/<route>/` and `raw/<view>__<original>.png`, assigns them, then compares references against latest Unity run.

**Timing values are assumptions [A]** (12 s load, 1.6 s walk to door, 4.5 s transition). Only observed: uinput startup 0.7 s; F8 to file 0.36 s. Calibrate first real runs by comparing screenshot timestamps with `wait` log lines (logs under `~/xnu-recomp/logs/`), then adjust the `.keys` values. `shot` waits for a new file instead of using a blind delay; loading has no marker (no game-state access), so it uses fixed waits.

### 9.5 Approval before movement/menu keys

**Only F8 keys were actually sent** (two `f8_only` runs with verified Ryujinx focus). Movement and menu routes (`boot_weiter`, `tuer_innenraum`) were dry-run only. User approval is required before first real run (main agent asks): game must be at title (“Continue”). At status 14:47, game was already in town; return to title first or use route from the field, otherwise A would confirm something in-game. Ryujinx window must be focused. Then run:

```
scripts/ryujinx_record.sh boot_weiter            # title -> field -> menu, 2 reference images
scripts/ryujinx_record.sh tuer_innenraum         # door -> interior, 1 reference image
```

## 10. Known limits and next steps

- Editor capture code: tested in **lab Editor**, **not** in `unity/` (section 7). `player` and `ipad` are documented but unrun; they capture only game-scene sequences, no field scenarios. Game-scene sequences (`game_*`) have not run in lab or main Editor.
- Game-scene sequences use the `Game` scene's save import (source Ryujinx folder in repository); without it, `game_feld_z24` is absent and run reports a missing capture.
- Zones 54, 27, and 168 use locator 0 (cell unknown); zone 24 at cell 57/729 comes from save (6.1), facing is assumed. Game core still reads position from `TownMapLocation` (6.1): `game_feld_z24` therefore initially shows locator (58, 723), not (57, 729), until `SavedPosition.Read` is updated.
- Detector cannot identify stretched textures, diagonal band, or white character without reference (section 4); Ryujinx reference and difference image cover them.
- Ryujinx game clock and timezone are assumptions; `ref_04` timing is not exactly reproducible (counter position).

## 11. First reference comparisons (status 15:30, lab Editor versus Ryujinx)

Basis: two real user Ryujinx images in Mio City/Fleetburg (`14-47-54` = `ref_01_feld_weiter`, game hour ≈12.4; `15-03-21` = `ref_05_vor_pokecenter`, ≈12.7) and lab Editor captures (`work/visual/auto/run-lab-z24`, `run-lab-full`, at reference hours). Runs `lab1` (cell 57/729) and `lab-cells` (12 candidate cells) are included. Game-scene images (UI, menu, battle) have no reference yet; therefore there is no UI/menu finding (`ref_02_menue` missing).

### 11.1 Position: saved cell differs from Unity cell (new finding)

Twelve candidate cells around (57, 729) (`lab-cells`, SSIM after histogram matching, residual offset after cross-correlation):

| Unity cell | Matched SSIM | Residual offset (x, y) px |
|---|---:|---:|
| **(58, 729)** | **0.414** | **(8, −24)** |
| (57, 729) | 0.408 | (−68, −24) |
| (59, 730) | 0.406 | (92, 24) |
| (57, 730) | 0.406 | (−60, 24) |
| (58, 728) | 0.355 | (0, −84) |
| (56, 729) | 0.346 | (−100, −20) |

Reference image matches Unity cell **(58, 729)** (residual horizontal offset 8 px), not saved cell (57, 729): save cell and Unity cell differ by **+1 in x** (and about +0.4 cells in y; the 24 px offset is independent of cell, more likely camera). **[A]** Explanation: original world cell centers use half-integers (world position −(gx + 1) or gy + 0.5), while `FieldCoords` uses integers; only image match for this one screenshot is certain. `field_z24_h12|h18` therefore use (58, 729). For game core (`SavedPosition`), verify saved cell (57, 729) → spawn at Unity cell (58, 729) once a second reference with known cell is available.

### 11.2 `ref_01_feld_weiter` ↔ `field_z24_h12` (Unity cell 58/729, hour 12.4)

| Metric | Value |
|---|---|
| SSIM raw / after histogram matching | **0.449 / 0.416** |
| Mean difference raw → matched | 32.8 → 25.1 |
| Detail ratio (Unity/reference Laplacian) | **×1.37** (Unity sharper/noisier) |
| Color cast R/G/B (brightness-adjusted) | 0.98 / 1.00 / 1.05 (slightly blue) |
| Unity/reference brightness | **×0.83** (Unity 17% darker) |
| Poor cells (>28) | 17 of 62; worst A2 (86), A3 (86), A4 (69) |

Mean values after color masks (image at cell 57/729, reference → Unity):

| Region | Reference RGB | Unity RGB |
|---|---|---|
| Paving (gray-violet) | 141 / 137 / 161 | 118 / 117 / 138 (**−16%**) |
| Tree canopy | 50 / 106 / 32 | 57 / 111 / 40 (brighter, more yellow) |
| Blue roof | 57 / 120 / 185 | 58 / 116 / 166 (less blue, darker) |
| Water | 55 / 119 / 186 | 59 / 117 / 168 |
| Overall | 106 / 120 / 118 | 88 / 103 / 111 |
| Pixels with luma >200 | 1.8% | **0.1%** |
| Luma spread | 42.9 | **33.3** |

Findings from contact sheet `contact/ref_01.png` and metrics:

- **Brightness/contrast:** Unity is about 17% darker overall, especially paving and house walls (blue house wall: reference light gray, Unity dark blue-gray; bright on difference heatmap). Bright highlights are missing (1.8% → 0.1% of pixels above luma 200), reducing contrast (spread 33 versus 43). Original likely uses bloom/tone post-processing and brighter ambient light on vertical surfaces. This also raises the detail metric (Unity is ×1.37 sharper; reference looks softer/smoother, likely antialiasing/bloom).
- **Color:** overall good (cast under 6%); roof blue is duller, tree green more yellow and brighter, Unity shadows bluer (29/47/35 versus 25/49/24 in reference).
- **Player character:** colorful in lab (red cap, dark top), pose and size match original; clothing is darker than reference (same lighting issue). Brown-haired NPC stands beside player as in reference (small position/animation difference).
- **Water:** Unity shows a harbor basin with blue sparkling water at left edge. Reference has a **wooden harbor crane/pier** at upper left (dark metal, wood), with turquoise water below. **The crane is missing in Unity** (cells A2–A4 are worst, MAD 69–86). Water mask: reference 55/119/186, Unity 59/117/168 (less blue and darker; masks cover different image regions, so treat as indicative only).
- **Shadows:** house-shadow direction and shape match; Unity shadows are somewhat darker and cooler.
- **UI/menu:** not compared (no reference image).

### 11.3 `ref_05_vor_pokecenter` ↔ `field_z24_vor_pc` (not informative)

SSIM 0.37 / 0.31 after matching, 56 of 64 cells poor: reference shows a **different place** from estimated Unity cell (54, 722). Left: evergreen wall; right: an **orange-brown building with white gutters and a Poké Ball emblem** (not the red Pokémon Center shown by Unity), with a Poké Ball sign in front. Unity shows water on the left and the red Pokémon Center. Likely another building (sign/shape resembles a market) elsewhere in town; cell unknown. Until the cell is known, image is useful for viewing only. A `lab-cells`-style grid search should find it (12 cells = 35 s; a 40×50-cell grid with step 3 takes about 10 minutes).

### 11.4 Recompilation (Phase C)

- Mac Metal language select versus Ryujinx: **SSIM 0.999**, mean difference 0.1, practically pixel-identical (section 8.5).
- Mac Metal title: green background and red text; Ryujinx counterpart missing (request an F8 at title).
- Recompilation has no other views yet (town, menu).

### 11.5 Implications for Unity (ordered by impact)

1. **Overall brightness and contrast** (−17%, missing highlights): inspect ambient light, brighten vertical surfaces, and post-processing (bloom, tone); largest effect across all town images.
2. **Missing objects** (harbor crane/pier in zone 24): container mapping/streaming (block 4) or categories omitted by map assembly.
3. **Coordinate offset** between save and Unity cell (11.1).
4. Water color (reference bluer/more turquoise); tree green less yellow.
