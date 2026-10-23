# Mods: RomFS mods with a save of their own

The app can start the game with a mod from the Ryujinx/yuzu mod layout (`<mod>/romfs`, `<mod>/exefs`). The mod's RomFS files are laid
over the game's, a mod runs with a **save folder of its own**, and without a mod the game starts unchanged. This page records what is
supported, how to install a mod on each platform, and what is not supported yet.

## What works, what does not

| | State |
|---|---|
| RomFS files (Unity assets, `Data/StreamingAssets/...`, movies) | **Supported.** Files with the same path replace the game's, new files are added. Names match ignoring case. |
| Separate save | **Supported.** A mod gets `Saves/mods/<name>/` (macOS: `<save>/mods/<name>/`). The game's save folder is not opened while a mod is active. |
| ExeFS `.ips` patches, extra NSOs (`subsdk1`) | **Not applied yet.** The game's code is compiled ahead of time, so code changes need regenerated and recompiled C. The runtime logs a warning for a mod that brings ExeFS files and runs it with its RomFS only. |
| Several mods at once | No. One mod is active; most big mods replace the same files. |

A mod that changes only data (text, models, textures, movies, master data) can work with its RomFS alone. A mod that also patches the code
(Luminescent Platinum does: 155 instruction patches in `main` that branch into an added `subsdk1`) is only partly there without its ExeFS.

## Installing a mod

Copy the folder that holds `romfs/` (and `exefs/`) into the app's mods folder. The app finds it up to four levels down, so an unpacked
archive with a wrapper folder works, and folder names may differ in case (`ROMFS`).

| Platform | Mods folder |
|---|---|
| iPhone, iPad | `Documents/Mods/` (Files app: On My iPhone/iPad > BDSP > Mods) |
| macOS | `~/Library/Application Support/dev.local.xnubdsp/mods/` (`mods =` in `config.ini`, or `BDSP_MODS_DIR`) |
| Linux, tests | `BDSP_MODS_DIR=<folder> BDSP_MOD=<name>` |

Large mods are unpacked with a program that copes with their size (Luminescent Platinum asks for 7-Zip); a corrupt archive gives a
corrupt game. The mod folder is separate from `GameData/romfs`, so copying the game data again (`deploy_ios.sh data`) does not touch it.

## Choosing the game or a mod

- **iPhone and iPad:** with at least one mod in `Documents/Mods`, a dialog at launch asks for "Brilliant Diamond" or a mod; the last
  choice is preselected. Without a mod there is no dialog.
- **macOS:** the same dialog with a "Don't ask again" box; hold Option at launch to ask again. `--mod <name|none>` or `BDSP_MOD`
  skips the dialog. The window title shows the active mod.
- To switch a mod off, start "Brilliant Diamond", or remove the folder from `Mods`.

## Saves

Mod saves are ordinary Brilliant Diamond saves in a folder of their own, so they stay out of the game's save:

```
Saves/save_1/...                  the game
Saves/mods/<name>/save_1/...      that mod
```

`user_id.hex` is copied from the game's save folder once (an existing one is never overwritten), so the account stays the same.
A mod starts with an empty save (new game). The macOS app's backups, import and reset work on the active save folder only.
A `SaveData.bin` dropped into `Documents/` on iPhone/iPad is imported at the next start of the **game**, not of a mod.

## Measurements

- **macOS (M1 Pro), Luminescent Platinum 2.2F, RomFS only:** 2,197 game files replaced and 1,260 added (3,459 files in the mod), 19,282
  files in the merged tree. The game's save, a copy, stayed bit-identical (hash before and after), the mod got its own empty save and the
  new-game intro ran.
- **iPad Pro (M2), same mod:** 3,459 files merged at start, 60.0 fps for the 75 s of the run, footprint 1,725 MiB, no crash. The mod's save
  was created under `Documents/Saves/mods/Luminescent`.
- Not measured: a full playthrough, mods other than Luminescent Platinum, the iPhone with this mod.

## How it works

`scripts/recomp/rt-bdsp/mods.c` finds mods and creates the save folder. `services_fs.c` builds the virtual RomFS from the game's folder and
merges the mod's `romfs/` over it before the layout, so the game's own file lookups see the merged tree; the movie layer
(`nvn/movie_glue.c`) opens files by host path and goes through `fs_resolve_rom_path`. Tests: `scripts/recomp/rt-bdsp/test/run_mods_test.sh`
(synthetic folders, no game data).

## Code mods (open)

IPS patches in `.text` and an extra `subsdk1` need generated code. The plan is a build step on the Mac (patched `main` regenerated, the changed
functions kept next to the originals and switched at run time, `subsdk1` as a fifth module); on iPhone and iPad such a mod could then only be
switched on from the app, not added from the Files app.
