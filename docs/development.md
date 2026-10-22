# Development guide

How to work on this repository: the rules that apply to every change, the commands you need, how to test with saves, what lives in
`work/`, and the known limits. Read [architecture.md](architecture.md) for how the recompilation works and [BUILD.md](BUILD.md)
for building.

## 1. Rules

| Area | Rule |
|---|---|
| Permissions | No `sudo` inside project scripts and no workarounds for missing rights. Anything that needs admin rights is handed to the user as an install list (the guided installers on Linux ask for `sudo` themselves, after confirmation). No whole-disk searches: look only inside the repository or at paths the code or docs name. |
| Git | Commit only as the project owner; **no co-author or "generated with" trailers** in commits, pull requests, issues, README or docs. `git add <file>` one file at a time, never `-A`. The pre-commit hook runs `scripts/repo_check.py`. Check before every push that only your own commits are ahead of `origin/main`. Push to `main` directly. |
| Repository contents | Never commit game data, keys, dumps, generated C, saves, screenshots or a team ID. Generated files, builds, traces and screenshots stay under `work/`; third-party clones only under the gitignored `research/`. Summarize third-party work in your own words; never commit machine-translated game code. The team ID lives only in `work/local.env`. |
| Editing files | Change repository files with the editor tools, not with `sed -i`, heredocs or script-written patches. Stop processes with `kill <PID>`, never `pkill`/`killall`. Run long jobs with `nohup` and a log file. |
| Language | Documentation is English; German exists only for `README` and `BUILD` (`*.de.md`). **Code comments, docstrings and runtime, log and build messages are English only**; tests assert the English texts. Exceptions: the app UI texts and `scripts/install/lang/*` (deliberate translations). UTF-8; code comments short and only where needed. |
| Instances and saves | Run one game instance at a time. Never change the real save: tests use a copy through `BDSP_SAVE=<dir>` (fresh directory, never deleted afterwards). No repeat or loop tests on the iPad; the accepted iPad start path stays as it is. |
| Diagnostics | Debug and measurement features are off by default and switched on with an environment variable (see [rendering.md](rendering.md)). Do not make them part of a release build's normal behavior. |
| Builds | Do not rebuild the generated game code (`work/recomp/obj4`) from scratch without asking; runtime and NVN changes are rebuilt on their own. Keep at least 15 GB free on the Mac. |
| Strategy | There is one track: the recompilation. The Unity rebuild is deprecated and lives on the branch `unity`; do not develop on it. Do not run several large efforts in parallel. |

## 2. Commands

macOS tools are BSD variants (no GNU `ls --time-style` and similar); Xcode is selected through `DEVELOPER_DIR`.

| Purpose | Command |
|---|---|
| Guided install | `./install.command` (macOS) · `./install-linux.sh` (Linux); `--dry-run` shows the plan |
| Check and tests | `python3 scripts/repo_check.py` · `python3 -m unittest discover -s scripts/tests` (one known failure: `test_stage_glass_icons … test_native_renderer_accepts_document_and_changes_lighting`) |
| Build stages | `scripts/build_all.sh --only tools,extract,recomp --target macos …` (stages `tools extract recomp shaders`; `--dry-run`, `--force`) |
| Test build from the working tree | build the runtime and NVN layer into a separate bundle and keep the shipped app untouched; guest code (`work/recomp/obj4`) is reused |
| Hot functions at `-O2` | add the function to `scripts/recomp/hot_o2.txt` when `sample <pid> 6` shows it at the top of a guest thread; the next `recomp` build recompiles only that chunk |
| Run the Mac app | `work/builds/macos-recomp/BDSP.app/Contents/MacOS/BDSP` with environment variables, for example `BDSP_FPS=120`, `BDSP_SAVE=<dir>`, `BDSP_INPUT_SCRIPT=@<file>` (lines `SECONDS:KEY:DURATION`), `BDSP_SHOT_DIR`, `BDSP_SCREENSHOT_FROM`, `BDSP_SCREENSHOT_EVERY` (see [recomp-macapp.md](recomp-macapp.md)) |
| Names for guest functions | `python3 -I scripts/recomp/il2sym.py` writes `work/recomp/il2sym.tsv`; `BDSP_IL2SYM=work/recomp/il2sym.tsv` logs each game method on first call; `scripts/recomp/symres.py` annotates crash reports. Engine code has no names |
| Performance and rendering | counters and switches in [rendering.md](rendering.md) (`BDSP_XW_LOG`, `BDSP_PASS_TIMES`, flush causes in the `[metal]` line) |
| Metal validation | `MTL_DEBUG_LAYER=1 MTL_SHADER_VALIDATION=1`, group the messages by text; slows the game to 20–30 fps, so never measure with it |
| Save into the runtime | `scripts/recomp/rt-bdsp/install_save.sh` (sources `BDSP_SAVE_SRC`, optional `BDSP_SAVE_EXTRA`) |
| iPad | `scripts/recomp/ios/deploy_ios.sh build\|install\|run [SEC]\|data\|save\|shots\|files` ([recomp-ios.md](recomp-ios.md)); save: `scripts/ios_push_save.sh [--source FILE] [--reimport] [--dry-run]` |
| Linux | scripts in `scripts/recomp/linux/local/` ([recomp-linux.md](recomp-linux.md)) |
| QA scenarios | `scripts/recomp/qa/qa_run.sh <scenario>\|--list\|--report <dir>` ([recomp-qa.md](recomp-qa.md)) |
| Spike measurements | `scripts/recomp_survey.py`, `scripts/recomp/test/run_*.sh` (listed in [architecture.md](architecture.md)) |

Other runtime variables: `BDSP_TIMEOUT`, `BDSP_BT` (backtrace), `BDSP_WAIT` (wait reports), `BDSP_WATCH`, `BDSP_ALIAS_BASE/SIZE`,
`BDSP_APPMEM`, `BDSP_FPS` (30, 60, 120), `BDSP_PRESENT_AT`, `BDSP_EXEC_WORKER=0` (synchronous renderer path).

## 3. Testing with saves

- The game reads input only after about 5 s; with a save it skips the language selection, the title appears after about 20 s,
  "Continue" leads to the field after about a minute. A scripted input has to press A repeatedly through the title.
- Test copies: put a save in a directory with `SaveData.bin` and `Backup.bin` (the two files hold different positions, so the start
  position can alternate) and start with `BDSP_SAVE=<dir>`. The app's own data lives in
  `~/Library/Application Support/dev.local.xnubdsp` (save, RomFS clone, shader cache).
- Ryujinx saves: a separate folder is created per profile; if the game shows the language selection despite a save, the wrong
  profile folder was used. The user ID is in `ExtraData0` (bytes 8 to 23, each 8-byte half byte-reversed). More in [saves.md](saves.md).
- Keys pressed in the app window still reach the game while a scripted input runs.

## 4. What lives in `work/`

| Needed (do not delete) | `exefs`, `romfs`, `local.env`, `.stages/`, `recomp/gen4` and `recomp/obj4` (guest code), `recomp/img_*`, `recomp/icons`, `recomp/cache` (shader cache copied into every app), `builds/macos-recomp`, `venv`, saves (`save-*`, `ipad-save*`) |
|---|---|
| iPad chain (needed for the iPad build) | `recomp/gen32`, `obj32`, `obj32m`, `img32`, `ios-rt`, `nvn-src32`, `ios/`, `builds/ios-recomp-derived` |
| Disposable | logs, traces, screenshots, `recomp/tree-*`, `rt-*`, `nvnsrc-*` (test builds), old bundles in `builds/` |

Also outside the repository and never touched by cleanups: `nsp/`, `Ryujinx/`, `Ryujinx_*/` (your dumps and emulator data).

## 5. Known limits and assumptions (do not repeat as facts)

- A rare startup hang or early crash (signal 11 within seconds) exists independently of rendering changes; retrying works. It is a
  low-priority edge case (decision: no repetition test loops).
- Metal validation reports one known start-up message: a 1D texture used as a render attachment (21 times). Nothing else should appear.
- FPSR/QC floating-point flags are not modeled ([recomp-diff.md](recomp-diff.md)).
- The 32-bit memory model on the iPad works with about 1.98 GiB of guest memory instead of 3.14 GiB; long sessions and battles are
  not measured.
- Vulkan/Linux: the Mac fixes (vertex and index ring buffer, crop inside the window) are not ported everywhere.
- A free developer team signs the iPad app for 7 days and allows three apps.
- Legal status of any public distribution is unresolved; built apps contain your game data and are for personal use only.

## 6. Picking work up again

1. `git status`, `git log -3`, `git fetch` and compare with `origin/main`.
2. Read the [README](README.md), [architecture.md](architecture.md) and this guide.
3. Run `python3 scripts/repo_check.py` and the unit tests.
4. Check that no game instance is still running before starting one.
