# iPad Vertical Slice 1: Title → Continue → Field → Door → Sister → Wild Battle → Save on iPad (Todo `ap-ipad-slice`)

> **Historical (status 2026-10-20):** Unity path, discontinued. The `assets` stage and `scripts/bundle_retarget.py` have been removed from `main` (only on the `unity` branch); the commands below no longer run there.

Status: 2026-10-19, iPad Pro 12.9-inch (6th generation, `iPad14,6`, M2, 8 GB, iPadOS 26), Unity 6000.3.26f1, IL2CPP, Metal, Built-in RP, Release build, subset `scripts/subsets/ipad-start.txt` (789 files, 229 MB, ASTC 6×6). Names, numbers, and structure only; no game text, real saves, or images in the repository (logs and images under gitignored `work/`). **Audio stayed off** (`AudioSafety`; device volume untouched; device was only started and stopped). Verification levels as in `docs/spielkern-1.md`: **[A]** assumption, **[P]** documented.

## 1. Summary

| Question | Result |
|---|---|
| Run without manual input | **Runs to completion on iPad** (input script supplied as a file in the container; 3 complete runs and 3 short runs, each ending with `quit`, exit code 0): title → “Continue” → Zone 167 → door (transition 167 → 168) → sister (4 text windows, 1 choice, event 1/1) → wild battle (9 log steps, 1 command, battles 1/1) → save (979,108 bytes). |
| Cause of “no slot” | **Duplicated path** (app looked in `Documents/Saves/Saves/main`, file was in `Documents/Saves/main`) **and** a directory created by `devicectl` belonged to `root`, so the app could not write there (section 2). Both fixed. |
| Zone texture errors | **0** (previously 1,884 BC failures); zero error messages in all runs. Images show textures correctly (section 5). |
| Load time | Master data 1.3 s; Zone 167 ready **2.4 s** (fallback materials) or **3.2–3.4 s** (generated shaders, remap 61/61) after “Continue”; door 167 → 168 about 4.2–4.6 s until interior map is ready. |
| Frame rate | Target 30: **30.0 FPS**; target 60: **60.0**; target 120: **119.9** (also with outdoor map, 2,431 renderers). Without a target Unity delivers 30 (as in `docs/ipad-messung-1.md`). |
| Memory | Footprint **736–861 MiB** (peak 861.2 MiB), `os_proc_available_memory` at least **7,342 MiB** (8,192 MiB limit with entitlement), `lowMemory` 0, no leak over 190 s of field operation. |
| Thermals | `thermalState` **0** (nominal) in every run; only 3–4 minutes of gameplay, no sustained test. |
| Crash-free runs | 6 runs of 50–190 s, no crash. |
| Tests | **696 of 696 passing** (688 before, 8 new). |

## 2. Cause of Missing Slot Detection **[P]**

The device was checked at `Application.persistentDataPath` (iPadOS: `/var/mobile/Containers/Data/Application/<UUID>/Documents`). Four issues were found, in this order:

1. **Duplicate `Saves` directory.** `GameDriver` passed `persistentDataPath/Saves` as the storage root, and `SaveStore` itself appends `Saves/<Slot>`: expected location was `Documents/Saves/Saves/main/SaveData.bin`. The previous transfer placed the file at `Documents/Saves/main/SaveData.bin`, where nothing looked for it. This went unnoticed on Mac because the app created the slot itself. Now the root is `persistentDataPath` (new `SaveSlotService.ResolveRoot`), and the slot is under **`Documents/Saves/main`**. If an older Mac slot exists at `…/Saves/Saves/main`, that directory remains authoritative.
2. **Slot meant “directory exists.”** `HasSlot` checked only that a `main` directory existed; an empty directory or partially transferred file counted as a save, causing “Continue” to fail later with an unclear error. Now a slot is valid only with a valid `SaveData.bin` or `Backup.bin` (version, size, MD5); otherwise the reason is logged and shown on the title screen (“No valid save: …”). `SaveSlotService.Diagnose()` logs paths, sizes, short hash (SHA-256, 12 characters), and reasons at startup (`[Game] Save: …`); “Continue” rereads the state if the file arrives after startup.
3. **Directory owned by `root`.** `devicectl device copy to … --destination Documents/Saves/main/SaveData.bin` creates missing intermediate directories with `ownerUid 0`, mode 755 (observed with `devicectl device info files --json-output`); the file itself belongs to user 501. The app (user `mobile`, 501) then cannot write into `Saves/main`: `SaveFileIO.WriteAtomic` failed when writing a temporary file with `UnauthorizedAccessException`, making saves impossible. Result: see issue 4. Now `scripts/ios_push_save.sh` copies the file to `Documents/SaveData.bin` **without intermediate directories** (Documents belongs to the app); the app imports it into a slot it creates itself (correct owner). If a slot directory is still not writable, `Diagnose()` reports that (“Slot directory not writable (owner root …)”).
4. **Script-command errors retried forever.** The failed `save` was retried every tick, creating another backup each time: **11,190 backups (about 10.7 GB) in 80 s** on iPad, plus 2,289 error messages in 120 s. Now `GameDriver.Execute` catches exceptions per command (reports the error, increments `ScriptCommandErrors`, marks the command complete), and `SaveNow` reports write failures as text. The test container was then cleared by uninstalling the app.

Side finding: arguments after the bundle ID (`devicectl device process launch … dev.local.xnum0 -- -xnuPerfLog`) **do not reach the app** (launch line lacks option; no `XNUPERF`). **Environment variables** via `--environment-variables '{…}'` work (each option has a variable: `XNU_START_SCENE`, `XNU_SCRIPTED_INPUT`, `XNU_PERF_LOG`, `XNU_TARGET_FPS`, `XNU_GENERATED_SHADERS`, `XNU_ENV_HOUR`). Input script paths are resolved relative to `Documents` (`XNU_SCRIPTED_INPUT=run-ipad.txt`).

## 3. Save Transfer to iPad **[P]**

Source remains unchanged (`Ryujinx/bis/user/save/0000000000000006/0/SaveData.bin`, 979,108 bytes, gitignored; read only). Output reports only sizes and hashes.

**(a) `scripts/ios_push_save.sh`** (standard path, tested)
- `scripts/ios_push_save.sh [--source FILE] [--bundle-id ID] [--reimport] [--dry-run]`; device selected from `xcrun devicectl list devices` (first connected iPad, optionally `DEVICE_NAME`), bundle ID `dev.local.xnum0`; no team ID needed or printed.
- Flow: validate source (size ≤ 1 MiB, SHA-256) → back up existing device slot to `work/ipad-save-backup/<time>/` → copy file to `Documents/SaveData.bin` → retrieve it and compare size/SHA-256 (checksum before and after).
- On the next **“Continue,”** the app imports the file into `Documents/Saves/main`, backs up any existing slot under `Documents/Backups/main/<timestamp>/`, and writes the file's SHA-256 to `Documents/ImportedDropIn.sha256`. The same file is **not** imported again, so progress in the slot is preserved. A **different** file replaces the slot (with backup). `--reimport` resets the marker (the same file replaces the slot again, e.g. for repeat runs).
- `scripts/ios_push_save.sh --pull [--dest DIRECTORY]` retrieves `Saves/main/SaveData.bin` and `Backup.bin` (only into `work/`).
- After saving on the device: `Documents/Saves/main/SaveData.bin` and `Backup.bin`, each 979,108 bytes (valid, owner 501); previous save in `Documents/Backups/main/<timestamp>/`.

**(b) Files app and Finder** (`IosPostBuild`, **[A]** not viewed on device)
- Build step `OnPostBuildDocumentSharing` adds `UIFileSharingEnabled` and `LSSupportsOpeningDocumentsInPlace` to `Info.plist` (plain-text step `Xnu.Core.InfoPlistPatch`, idempotent, no team ID; `plutil -lint` on build result: OK). This exposes the app's Documents directory in the Files app (“On My iPad”) and Finder; a dropped `SaveData.bin` in Documents (or `Documents/Import/`) is imported on the next “Continue,” as in (a). Whether the directory really appears in Files was **not checked on-device** (UI interaction was outside the task).

**(c) In-app import through document picker:** not implemented (requires a native plugin and device interaction; (a) and (b) cover the need).

## 4. Measurement Setup

- **Build/deploy times:** `scripts/build_all.sh --target ios --texture-format 6x6 --only assets --bundle-subset scripts/subsets/ipad-start.txt --force`: 33 s, 789 files, 229 MB. Unity iOS build through `Xnu/Build/iOS und iPadOS (Xcode-Projekt)`: 18–26 s (editor target switch took about 1.5 minutes beforehand). `scripts/ios_deploy.sh work/builds/ios/xnu --no-launch`: 1 min 9 s. The Editor was then switched back to **macOS** and `unity/Assets/StreamingAssets/GameData` deleted. Important: `IosPostBuild` is behind `#if UNITY_IOS`; after a target switch, build again because the first build does not yet include iOS post-processing (entitlement, Info.plist).
- **Measurement code** (new, `GameDriver`): script command `mem`; with `XNU_PERF_LOG=1`, every 5 seconds of real time it writes `XNUPERF|t|state|fps|worstMs|ticks|footprintMiB|peakMiB|internalMiB|compressedMiB|availMiB|thermal|lowPower|unityMiB|monoMiB|errors|warnings|lowMemory` (counters from `Xnu.Probe`/`os_proc_available_memory`, `phys_footprint`, `thermalState`); error/warning counters (`Application.logMessageReceived`), `Application.lowMemory`; `XNU_TARGET_FPS` sets `Application.targetFrameRate`; `report` reports errors. One-time log: “Zone loaded after … s since ‘Continue’” with memory line.
- **Launch:** `xcrun devicectl device process launch --device <ID> --terminate-existing --console --environment-variables '{"XNU_START_SCENE":"Game","XNU_SCRIPTED_INPUT":"run-ipad.txt","XNU_PERF_LOG":"1","XNU_GENERATED_SHADERS":"1","XNU_ENV_HOUR":"12"}' dev.local.xnum0 > work/builds/ipad-run-N.log`. Script (`work/ipad-run/run-ipad*.txt`, commands such as `work/vslice/run5.txt`, plus `shot` and `mem`) is copied into `Documents/` with `devicectl device copy to`. Images: script command `shot` renders the game camera into a 1280 × 720 RenderTexture and writes PNGs to `Documents/Shots`; retrieved with `devicectl device copy from` to `work/visual/ipad/` (only there).
- Runs: 1 (before fix, save failed, stopped manually), 2 (fallback materials, 50 s), 3 (remap, 190 s, started indoors), 4 (remap, outdoor map, 50 s), 60-FPS run, 120-FPS indoor run, 120-FPS outdoor run.

## 5. Measurements **[P]**

| Metric | Value |
|---|---|
| Load master data (“Continue”) | 1.3 s (707 trainers, 183 zones, 209 text files, 856 script files, 12,985 labels; on Mac 2.2–2.6 s in Editor) |
| Zone 167 ready, since “Continue” | 2.4 s (fallback materials), 3.2–3.4 s (remap with generated shaders, “Shader 61/61, 109 material entries,” 2,431 renderers, 4 blocks) |
| Door 167 → 168 | 4.2–4.6 s until interior “map built” (61 renderers, 32 material entries), transition 634 ms |
| Zone texture errors | **0** (zero errors in all runs; 39–125 warnings were “referenced script … is missing” for original components, as on Mac) |
| Texture memory (Unity counter) | Outdoor map 25 MB, interior 27–29 MB (Mac with BC: 40 MB) |
| Frame rate 30 / 60 / 120 | 30.0 (window 29.2–30.0) / 60.0 (longest frame 17 ms) / 119.9 (longest 8–12 ms, one 100 ms during loading) |
| First window after “Continue” | At target 30, only 10–15 FPS in first 5-s window, because one frame takes 2.2–3.4 s (synchronous zone load, no runtime streaming) |
| Footprint | 726 MiB right after zone load (interior, remap) to 818 MiB (outdoor); during runs 736–861 MiB, peak 861.2 MiB (`peak`); `internal` 605–705 MiB; `compressed` 0 |
| `os_proc_available_memory` | 7,342–7,466 MiB (8,192 MiB limit with entitlement) |
| Managed heap (Mono) | 266–335 MiB; in 190-s run 286 → 315 → 296 MiB (GC working, no growth); Unity allocator 92–107 MiB |
| Stable duration | 190 s field/battle/interior (run 3): footprint constant at 766.7–795.1 MiB, 30.0 FPS, `thermalState` 0, `lowMemory` 0 |
| Thermals | `thermalState` 0, `lowPower` 0 in all runs (3–4 minutes, brief) |
| Save on device | `Documents/Saves/main/SaveData.bin` and `Backup.bin`, each 979,108 bytes, valid hash (validated on next launch), previous save under `Documents/Backups/main/…`; one backup directory per save |
| Device storage after failed run 1 | 11,190 backups ≈ 10.7 GB, removed by uninstall |
| Result matches Mac **[A]** | Save after the run (Zone 168, same cell) has same SHA-256 (`082a7fb0…`) as earlier device file originating from Mac run: iPad saves byte-for-byte the same as macOS player (same input, same location). Observed in run 2; not checked again. |

**Image observations** (local only, factual description; image size 1280 × 720):
- *Outdoor map (run 4, `f0_feld`):* Pokémon Center from above with red roof and white ball symbol; rocky beige/brown terraces and edges with visible texture (cracks, stone edges); darker ground at lower right; medium brightness, high contrast, no black or magenta areas. Character is gray (fallback shader).
- *Interior (`f1_innen`):* counter with healing device, plant, shelf, cushion, and rugs in red, blue, and yellow; tiled floor with ball symbol; wood walls with gradient; textures and brightness match Mac run; NPC markers are blue capsules; player character gray.
- *Text window (run 2, `f2_textbox`):* original frame from `sharedui` (light gray field, dark outline, continue indicator at lower right), two lines of dark sans-serif text, umlauts correct (Pokémon); map behind it was still unremapped in run 2 (gray fallback material, sky blue).
- *Battle (run 4, `f4_kampf_befehl`):* placeholder boxes (#396 red, #407 blue) instead of models on two-tone green; two info panels with name, level, and green HP bar (own side also has number); command menu with Fight/Bag/Pokémon/Run and cursor; dark message bar; readable, layout like Mac.

## 6. Gaps (Honestly)

- **Player-character fallback shader** (gray) and **battle placeholders** remain (as in `docs/vertikaler-durchstich-1.md`); map remap runs with `XNU_GENERATED_SHADERS=1` (not default, see `docs/feld-szene-2.md`); without the variable the map remains gray (run 2).
- **Files app/Finder** (section 3b) was not inspected on device; **document picker** (3c) is missing.
- **Loading stalls:** zone loading is synchronous and the first image stalls for 2.2–3.4 s; same for door transition (4.2–4.6 s). No loading screen, no streaming during run.
- **Outdoor map at 60 FPS was not measured separately** (30 and 120 were; 120 holds, 60 lies between); interior measured at all three rates. No load or sustained test beyond 190 s; **thermals** nominal but say nothing about 30 minutes of play; room temperature and charge level not recorded.
- **Only one device, one iPadOS version, one zone** (Pokémon Center outside and inside), bundle subset (229 MB, not the full 4.9 GB); no other zones, trainer battle, or grass encounter tests (same as Mac).
- **Arguments** do not reach the app via `devicectl` (environment variables only); options such as `-xnuPerfLog` therefore work on iPad only through a variable.
- The marker mechanism remembers only **one** last-imported file; switching between multiple drop-in files requires `--reimport`. Earlier runs without the marker start with an existing slot if valid (drop-in file replaces it only if hash differs).
- **Measurement probe in game build:** `Xnu.Game.Unity` now references `Xnu.Probe` (native plugin `XnuMemoryProbe.m` is included in every iOS build).

## 7. Next Steps

1. Load zones in the background (no 2–4-second stall) and show a loading screen; stream by block instead of synchronously.
2. Measure outdoor map at 60 FPS and run 30 minutes with thermal monitoring; test additional zones from subset (field paths, caves) and full bundle set.
3. Test document picker or Files app on device (section 3).
4. Add player-character and NPC models, battle models, and original UI (see `docs/vertikaler-durchstich-1.md`, section 8).

## 8. Changed and New Files

`unity/Assets/Scripts/Game/Runtime/SaveSlotService.cs` (slot validation, `ResolveRoot`, `DropInSources`, marker, `Diagnose`), `GameDriver.cs` (drop-in, diagnosis, measurement, script-command error handling), `GameOptions.cs` (`XNU_TARGET_FPS`, `XNU_PERF_LOG`), `Xnu.Game.Unity.asmdef` (reference to `Xnu.Probe`); `unity/Assets/Scripts/Core/InfoPlistPatch.cs` (new); `unity/Assets/Scripts/Build/Editor/IosPostBuild.cs` (Info.plist); `unity/Assets/Tests/EditMode/GameUnityTests.cs` (8 new tests: root, slot after external copy, truncated/empty slot, loose file and corrupt slot, new drop-in replaces slot once, invalid source, Info.plist, options); `scripts/ios_push_save.sh` (new).
