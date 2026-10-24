# Mods: RomFS mods with a save of their own

The app can start the game with a mod from the Ryujinx/yuzu mod layout (`<mod>/romfs`, `<mod>/exefs`). The mod's RomFS files are laid
over the game's, a mod runs with a **save folder of its own**, and without a mod the game starts unchanged. This page records what is
supported, how to install a mod on each platform, and what is not supported yet.

## What works, what does not

| | State |
|---|---|
| RomFS files (Unity assets, `Data/StreamingAssets/...`, movies) | **Supported.** Files with the same path replace the game's, new files are added. Names match ignoring case. |
| Separate save | **Supported.** A mod gets `Saves/mods/<name>/` (macOS: `<save>/mods/<name>/`). The game's save folder is not opened while a mod is active. |
| ExeFS IPS/IPS32 | **Build-time support on native Mac and Mac → iPhone/iPad.** Select the mod in the installer to build a separate compiled app. Dropping ExeFS into an existing app does not apply code patches. |
| Additional `subsdk1` | **Apple build path connected.** Compiled alongside IPS/IPS32, with cross-module entry points, imports and constructors. Its fixed main-relative layout must fit before the SDK. See device validation below. |
| Other added NSOs, rtld patches | **Not supported yet.** The installer rejects these code mods. |
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

## Code mods

On a native Mac build or a Mac-hosted iPhone/iPad build, the installer accepts a selected mod folder containing IPS/IPS32 files and an optional `subsdk1` in `exefs/`. Its Rust `ips_patch` helper matches patch filenames to the NSO build IDs, validates the records, decompresses and patches the NSOs, and stages them without touching the original extraction or mod. It checks the additional module's size including BSS and emits cross-module branch entry offsets, including returns into the middle of the game code. The generator consumes those offsets; image linking includes the extra exports and imports, and the runtime loads its function table and runs its constructors before the game's. The generator, compiler and runtime build in a mod-specific work folder. The result has its own bundle identifier. The Mac app also has its own installation receipt and shares the base game's RomFS. On iOS, the app has its own data container and base-data copy. The chosen code mod is fixed at launch and uses a mod-specific save directory. The base `BDSP.app` is not replaced.

Choose the whole downloaded mod folder in the GUI. It finds `romfs/` and `exefs/` inside common wrapper folders without copying the mod. A mod-provided `icon.png`/JPEG/WebP or localized `icon_<language>.dat` and `control.nacp` take precedence over the game's icons and title strings in the separate app. Without standalone icons, the icon pipeline reads matching `Texture2D` artwork from the mod's known `Dpr/movie/dia|pea/logo/logo_*` RomFS bundles. It uses the existing UnityPy reader and native texture/image decoders, fits the actual logo into an opaque square, and preserves all extracted languages. Languages without their own mod logo use the mod's English artwork. The manifest records each source bundle, texture name and SHA-256. No artwork is downloaded or committed. A mod with neither standalone nor embedded artwork gets a visible MOD badge on the base icon. The mod folder name supplies title strings where no mod control metadata exists.

Lumi 2.2F supplies its artwork inside those RomFS bundles, rather than as `icon.png`. The shared pipeline now extracts twelve locale variants and builds all sixteen icon selections from that actual Lumi artwork; it does **not** use the original Diamond icon with a MOD badge. This works before Apple icon compilation and final signing. The existing UnityPy shader profile is required for embedded-logo extraction, and the installer checks that reader before compiling. Standalone icons do not need UnityPy.

A no-op IPS against the local `main` has passed generator/image, compiler, runtime-link and signed-app checks on Mac and iPadOS. This verifies the build plumbing, not the behavior of a real code mod. Rtld patches, additional modules beyond `subsdk1`, arbitrary ExeFS files, Linux code-mod builds and switching code variants inside one app remain unsupported. The GUI blocks unsupported ExeFS file types; patch applicability and module layout are checked during staging, before generation or compilation.

Pure RomFS mods still need no rebuild: copy them into the app's mods folder with a file manager. The GUI can also select a downloaded mod folder directly. An in-app choice between multiple compiled ExeFS variants remains a later step; the present IPS path builds a separate app.

### iPhone/iPad deployment

The Mac-hosted driver builds a signed universal iPhone/iPad app and IPA in an isolated work directory. It uses the existing local Xcode signing team and iOS FFmpeg libraries. The chosen device receives the base RomFS and selected mod under content-versioned directories inside this app's own Documents container. Copying never removes existing contents or copies saves. The signed bundle records the exact mod directory and stable name; a compiled code-mod app starts that mod directly and keeps its save separate. Pure RomFS mods remain dynamically selectable and need no rebuild. Separate iOS app containers currently require separate base-data copies; cross-app sharing is not implemented.

Mod icons feed directly into the existing shared game-icon preparation, before platform icon generation and signing. All localized variants are retained.

Device proof (2026-10-24): a separate test bundle on an M2 iPad Pro compiled 2,478 C objects using eight dynamically selected jobs (330 s), installed successfully, activated the no-op IPS mod and reached the game's language-selection screen. A screenshot at frame 600 was checked; the last measured interval was 60 fps. No existing saves were imported. This checks startup and packaging, not a real code mod's gameplay. Device selection currently prefers one connected iPad; explicit selection is available in the driver. A GUI device picker, signing setup and recovery from interrupted deployment remain work to do.

Full Lumi integration (2026-10-24): all 155 IPS32 records and `subsdk1` were staged, compiled and installed as `dev.local.xnubdsp.mod.2b0b431628`, alongside the original `dev.local.xnubdsp` (same original installation path verified). Its signed bundle contains the extracted Lumi logos; its RomFS overlay replaces 2,197 files and adds 1,260. Constructors executed on the iPad. Two starts exposed missing dispatch entries for jump tables split across generated function partitions, first in newlib inside `subsdk1`, then in the main module. The generator now discovers those targets across partitions and emits separate dispatch entries; synthetic tests cover modules both with and without unwind headers. The final build has 2,490 objects and recompiled the affected files in 9 seconds. The corrected app passed a 90-second device run, reached the new-game intro and player house, and ended at the configured time limit with exit code 0. Screenshots at frames 1,800 and 3,600 were visually checked. After initial shader compilation, most five-second intervals ran at 60 fps, with scene transitions briefly around 50–59 fps. Only the separate mod save was used; no existing saves were imported. Battles and extended gameplay remain untested. Logs, screenshots, IPA and `device-proof.json` remain under `work/recomp/mods/ec0ed3afe4b2f7b54c65/ios/`.
