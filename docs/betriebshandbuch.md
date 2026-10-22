# Operations Manual (Resume Without Conversation History)

Status: 2026-10-19 17:20. Complements `docs/arbeitsstand-2026-10-19.md` (technical details, measurements, decisions). This document records what is **not** in the technical docs: work rules, commands, save distribution, agent/todo status, unsupported assumptions, and the order of work after restarting a session.

## 1. User Work Rules (Apply Permanently to This Project)

| Area | Rule |
|---|---|
| Permissions | No `sudo` or workarounds. Anything requiring admin rights is given to the user as an installation list. Whole-disk scan prohibited (touch only repository and known directories). |
| Audio | Previously prohibited, now allowed (user, 2026-10-19): audio may be investigated, implemented, and tested (Todo `rc-audio`). Until then audio services are silent stubs. |
| Git | Commit only with user's identity (`Veemyu`), **no co-author trailer**, `git push` (origin/main) after each commit. Pre-commit hook runs `scripts/repo_check.py`. Add specific files only with `git add <file>`, never `-A`. |
| Repository contents | Never include game data, keys, dumps, generated code, saves, screenshots, or team ID. Generated C and binaries stay under `work/`. Third-party projects only as clones in gitignored `research/`; summarize in your own words; never commit machine-translated game code. Team ID only in `work/local.env`. |
| Editing files | Repository files only via `edit`/`create`, not `sed -i`, heredoc, or Python write scripts. Stop processes only with `kill <PID>`, never `pkill`/`killall`. Long runs: `nohup`/`setsid` with a log file. |
| Language | Default repository documentation is English. German originals are retained as `.de.md` files. Use UTF-8; code comments are short and only when needed. |
| Models | Use small models (`claude-haiku-5.5` or `gpt-6-luna`) for runs, measurements, inspection, docs; Sonnet for debugging and central code. At most two large agents at once. Agents never commit. |
| Space | Keep at least 15 GB free on Mac (last observed about 36 GB). Stop and report if less. |
| Strategy | Unity rebuild is deprecated (decision 4, `unity/DEPRECATED.md`): no further work, reference only. There is one track: recompilation. Do not develop three things in parallel. |
| Linux machine | No longer connected to this workflow. Linux builds run only locally on a Linux machine, from the repository root (`scripts/recomp/linux/local/`). |

## 2. Command Cheat Sheet (Checked Against Script Headers)

macOS tools are BSD variants (`ls --time-style` and GNU options are unavailable). Xcode is selected through `DEVELOPER_DIR`.

| Purpose | Command |
|---|---|
| Repository check and tests | `python3 scripts/repo_check.py` · `python3 -m unittest discover -s scripts/tests` (most recently 358–370 passing) |
| Full build (stages) | `scripts/build_all.sh` (stages in `scripts/build_stages.py`; Unity stages deprecated, `recomp-ios` stage still missing) |
| Mac, headless | `work/recomp/bdsp_boot --headless --save <directory> --timeout S --input-script "SEC:KEY:DURATION,…" --screenshot-after N` (images to `BDSP_SHOT_DIR`); symbols via `BDSP_IL2SYM`/`work/recomp/il2sym.tsv` |
| Mac app | `work/builds/macos-recomp/BDSP.app` (`docs/recomp-macapp.md`) |
| Install save into runtime | `scripts/recomp/rt-bdsp/install_save.sh` (source `BDSP_SAVE_SRC`, optional `BDSP_SAVE_EXTRA`, destination `work/recomp/save`) |
| Build/start iPad | `scripts/recomp/ios/deploy_ios.sh build|install|run [SEC]|data|save|shots|files`; runtime environment via `RUN_ENV='{"BDSP_TIMEOUT":"40","BDSP_BT":"1","BDSP_WAIT":"1"}'`; logs `work/builds/ipad-recomp-<time>.log` (`docs/recomp-ios.md`, section 6) |
| iPad save | `scripts/ios_push_save.sh [--source FILE] [--reimport] [--dry-run]` |
| QA scenarios | `scripts/recomp/qa/qa_run.sh <scenario>|--list|--report <directory>` (lock file, save copy from `work/recomp/qa/save_base`) |
| Unity (deprecated, only if ever needed again) | `scripts/unity_safe.sh open|restart|status|test|watch` is only on branch `unity` (absent on `main`; `visual_auto.sh` needs it to start Editor); never test in Play mode (hangs), run `editor_stop` first |

Known runtime helper variables: `BDSP_TIMEOUT`, `BDSP_BT` (backtrace), `BDSP_WAIT` (wait reports), `BDSP_WATCH`, `BDSP_ALIAS_BASE/SIZE`, `BDSP_APPMEM`, `BDSP_SHOT_DIR`, `BDSP_SCREENSHOT_*`.

## 3. Standard Test Save and Distribution

- **Contents:** user's Ryujinx save from 2026-10-19: city in Zone 24 (Canalave City area), play time 69:08:16, 79,996 money, 179 items, same trainer ID. SaveData SHA-256 starts `0396a4a62735`, backup `7a324b865ea9`. Save before Victory Road archived at `work/save-archive/`.
- **Position:** `PLAYER_DATA` at 0x79BF4/0x79BF8 = grid cell (57, 729); `zoneID` at 0x5634 = 24; `TownMapLocation` is stale (Zone 416; do not use). Closest match to Ryujinx image is cell (58, 729), based on only one image.
- **Installed at** (old save backed up each time):

| Target | Path |
|---|---|
| Mac Ryujinx folder | `Ryujinx/bis/user/save/0000000000000006/{0,1}` |
| Mac recompilation | `work/recomp/save/save_1` (via `install_save.sh`) |
| iPad | `Documents/SaveData.bin` (drop-in; imported on next “Continue” to `Documents/Saves/save_1`, backup under `work/ipad-save-backup/`) |
| Unity Editor (deprecated) | `~/Library/Application Support/DefaultCompany/xnu/Saves/Saves/main` |

- **A previous pitfall:** Ryujinx creates a separate directory for each profile. If save was in `…04` but active profile read `…0e`, the game showed “Select the language.” Choose the profile folder by hand. The user ID is in `ExtraData0` (bytes 8–23, each 8-byte half byte-reversed).
- With a save, game skips language selection: title after about 22 s, “Continue,” city after about 91 s.

## 4. Agent Status, Open Work, Todos (Session Data, Not in Repository)

**In progress (both Sonnet, hard deadline 19:00):**
- `ap-recomp-qa`: test harness `scripts/recomp/qa/`, `docs/recomp-qa.md`. Priority 1: water (Metal), then Pokémon Center interior (solid blue with dark stripes). Suspected: render-target textures `_OpaqueDepthTexture`/`_ReflectionTex` are read incorrectly in Metal path.
- `ap-recomp-ios`: `scripts/recomp/ios/`, `docs/recomp-ios.md`. Reproduce rare startup hang: loop up to 8 runs with `BDSP_TIMEOUT=40`, mark “HANG” if last Metal image is below 600 (at 17:12 there were 22 runs in log, none with crash signal, two without video start). Already fixed: self-deadlock in `block_current` (`kernel.c`), audio infinite loop (`services_audio.c`). iPad must remain unlocked.
- All other agents (about 55) are inactive. Model for `ap-recomp-*` agents is environment default (probably Sonnet, not verified).

**Uncommitted (belongs to active agents; review only after their report):** `scripts/recomp/ios/`, `scripts/recomp/qa/`, `docs/recomp-ios.md`, `docs/recomp-qa.md`, changes in `rt-bdsp/kernel.c`, `rt-bdsp/nvn/nvn_glue.c`, `rt-bdsp/services_audio.c`, `rt32/cpu.h`. Process: read report, run tests and `repo_check.py`, add files individually, commit (user identity only), push.

**Todos (session SQL, reconstructable here if lost):**
- Complete: 43 (extraction, analysis, Unity slices, recompilation gates 1/2, image inspection).
- Blocked due to Unity retirement (19): `ap-audio`, `ap-battle`, `ap-cutscenes-video`, `ap-effects-fidelity`, `ap-field`, `ap-ipad-perf`, `ap-localization`, `ap-packaging`, `ap-qa-ci`, `ap-resolution-framerate`, `ap-save-compat`, `ap-save-io`, `ap-settings-ui`, `ap-shaders`, `ap-ui`, `todo-ai`, `todo-astc`, `todo-host-cmds`, `todo-ui-screens`. Re-scope for recompilation if still relevant (resolution/frame rate, packaging, save import are being developed there).
- `ap-build-all` (continues: one-command build, now with `recomp`/`recomp-ios` stages). `ap-shader-unity` and `ryzen-optional` were obsolete and marked complete/blocked.

## 5. Unsupported Claims and Assumptions (Do Not Repeat as Facts)

- **User decision (2026-10-19 afternoon): no more repetition runs.** Earlier crash came from VP8 video, which has been stable for a long time. We will not pursue the rare startup hang (0–40 images, about 4 of 9 recent runs); it is a low-priority edge case. No agent should start iPad loops for this. Resume only if it affects real gameplay.
- The **iPad crash when intro is not skipped** has not been reproduced; self-deadlock is a documented but unproven cause. One hang (2 images) after fix is unexplained.
- **32-bit model (`rebase32`) on device:** reported working in `recomp-ios.md`, but with only 1.98 GiB rather than 3.14 GiB guest memory; long sessions and battles unmeasured.
- **Image comparison:** camera offset 28 px (probably timing), cell mapping (58,729) from one image, mapping Ryujinx game clock to time of day assumed.
- **ARM64 floating-point FPSR/QC flags** are not modeled (`recomp-diff.md`).
- **Vulkan/Linux:** run with video and save not repeated; Mac fixes (vertex/index ring buffer, crop 1280×720 inside 1920×1080) not ported everywhere. Shared include lines in `nvn_glue.c` were moved out of `__APPLE__` block (the Linux machine's build had failed before).
- **Water cause** is a hypothesis; target region values: RGB mean ≈ 87/127/210, standard deviation ≈ 26/17/25, ≈ 0.3% very bright pixels (`docs/wasser.md`).
- **Legal status** of public distribution is unresolved. opendpr prohibits generative AI: reference only, no code reused. LASRecomp is MIT (notices in `shader_translator/NOTICE.md`).
- Free-team iPad app signature expires after 7 days; only three apps with free profile allowed (measurement probe was therefore removed).

## 6. Brief History

1. 2026-10-18: setup, extraction (title `0100000011d90000`, update `…800`, Master Key Rev 0xC), Ghidra (166,095 functions), Il2CppDumper, save spec; chose path D (Unity 6.3).
2. Unity rebuild with emulation oracle (763 tests passing), shader translator, macOS and iPad player builds.
3. 2026-10-19: recompilation spike, Gate 1 (boot through NVN), Gate 2 (Metal renders, video, input, city at 45 fps), Vulkan, bit-exact differential test, Linux machine (temporarily a build/test helper), image check against Ryujinx.
4. User observations on iPad: “looks great”; water wrong; startup took 2–3 attempts; crash if intro is not immediately skipped with A. Intro video plays through VP8 software decoder (FFmpeg, `movie::` HLE).
5. Decision 4 (16:57): Unity deprecated. Since then two agents are working (QA/water, iPad).

## 7. Order After Restarting a Session

1. `git status`, `git log -3`, `git log origin/main -1`: is everything pushed?
2. Read `docs/README.md` and `docs/arbeitsstand-2026-10-19.md`, then this manual.
3. Get reports from `ap-recomp-qa` and `ap-recomp-ios` (agent list); if missing, inspect files in section 4.
4. Check whether an iPad run is still active (`ps`; stop only own PIDs).
5. Run tests, `repo_check.py`, add specific files, commit, push.
6. Then follow section 8 of project status (water, interior, iPad startup, QA scenarios, touch/controller, Vulkan run, `recomp-ios` stage).

Outside the repository there are only session checkpoints (`~/.copilot/session-state/…/checkpoints/`), session todo table, and saved memories. Everything else is in `docs/`.
