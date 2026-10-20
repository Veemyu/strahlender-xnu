# Data Inventory (RomFS Dump)

Basis: local, read-only dump `work/romfs/Data/StreamingAssets`. All figures come from `scripts/data_inventory.py` (headers only; nothing is unpacked or changed). This document intentionally contains only names, numbers, and header versions—no game data.

Note: `docs/spielcode-inventar.md` does not yet exist. Loading notes below come from `work/il2cpp/dump.cs` and `stringliteral.json`. `work/decomp/*.c` currently contains only save functions, so it provides no asset-loading evidence.

## 1. Directory Structure

| Directory | Files | Size | File types |
|---|---:|---:|---|
| `AssetAssistant` | 14,053 | 3930 MiB | 14,052 Unity bundles (no extension; UI/GMS/Contest bundles may have language suffix), 1 × `.bin` |
| `Audio/GeneratedSoundBanks/Switch` | 3,939 | 420 MiB | 3,241 `.wem`, 696 `.bnk`, `PluginInfo.xml`, `Wwise_IDs.h` |
| `Movie/dia` | 18 | 456 MiB | 18 `.webm` |

`AssetAssistant` also contains `Dpr.bin` (5.3 MB, not UnityFS; initial bytes look like .NET BinaryFormatter, probably bundle manifest; see open questions). At root level there are only subdirectories.

Subdirectories of `AssetAssistant` (bundles; each file is a bundle):

| Subdirectory | Bundles | Size | Likely contents (based on name) |
|---|---:|---:|---|
| Environments | 644 | 2239.5 MiB | maps, backgrounds, Underground |
| Characters | 414 | 642.8 MiB | character models |
| Pokemon Database | 5,748 | 596.2 MiB | Pokémon models (`pokemons/...`) |
| Effects | 2,987 | 252.4 MiB | effects, seal data |
| UIs | 1,995 | 80.9 MiB | UI textures, language variants |
| Dpr | 141 | 66.6 MiB | core game: scenes, scripts, shaders, settings |
| Message | 12 | 14.5 MiB | text by language |
| Battle | 1,411 | 6.8 MiB | battle camera/sequences, battle master data |
| Contest | 579 | 6.3 MiB | contests |
| FureaiHiroba | 14 | 5.4 MiB | recreation area (Fureai Plaza, Poffin) |
| StatuePlacementEdit | 3 | 4.4 MiB | statues |
| GMS | 87 | 3.1 MiB | Global Mission Station (GTS) |
| Union | 4 | 2.9 MiB | Union Room |
| DigFossil | 3 | 2.8 MiB | fossil minigame |
| UnderGround | 4 | 0.5 MiB | Underground |
| Pml | 2 | 0.1 MiB | Pokémon library (personal data) |
| LightStone, UgFather | 2 each | < 0.1 MiB | small |

## 2. Unity Bundles (Headers)

| Property | Value |
|---|---|
| Count | 14,052 (all `UnityFS`), 3925 MiB |
| Format version | 7 (all) |
| Unity version / revision | plugin `5.x.x`, revision `2019.4.27f1` (all) |
| Header flags | `0x43` (all): block info compression = LZ4HC, block info directly after header |
| Header size field | matches file size in every case |
| Data block compression | 87,104 LZ4HC blocks, 86 uncompressed |
| Nodes (internal files) | 1 → 6,331 bundles, 2 → 7,720, 4 → 1 |
| Unreadable block info | 0 |

Size distribution (file size):

| Class | Bundles |
|---|---:|
| < 1 KiB | 0 |
| 1–4 KiB | 639 |
| 4–16 KiB | 4,888 |
| 16–64 KiB | 4,394 |
| 64–256 KiB | 2,394 |
| 256 KiB–1 MiB | 1,067 |
| 1–4 MiB | 424 |
| 4–16 MiB | 228 |
| 16–64 MiB | 18 |
| ≥ 64 MiB | 0 |

Minimum 1,961 B, median 31,299 B, maximum 32.9 MiB. Blocks per bundle: 1 block in 6,618 bundles; 2–9 blocks in 6,189; ≥10 blocks in 1,320.

Sample (small bundles at 5%, 15%, and 25% of size order):

| Bundle | Size | Nodes | Blocks (uncompressed → compressed, type) |
|---|---:|---:|---|
| `Battle/btlv/waza/sequence/ew306` | 4,196 B | 1 | 1: 12,800 → 4,067, LZ4HC |
| `UIs/textures_mass/pokemon_dp/pm0136_00_00_00_dp` | 5,364 B | 2 | 1: 42,052 → 5,213, LZ4HC |
| `Battle/btlv/waza/camera/wait/envcamera_w_f_138` | 10,527 B | 1 | 1: 36,740 → 10,398, LZ4HC |

Only block info (a few dozen bytes) was decompressed for the table; payload data remained untouched.

## 3. Master Data and Loading

Bundles containing master data by name (size in bytes):

| Bundle | Size | Likely contents |
|---|---:|---|
| `Pml/personal_masterdatas` | 125,957 | basic Pokémon data (Personal table) |
| `Dpr/masterdatas` | 449,274 | main game master data (items, moves, trainers, shops, …) |
| `Battle/battle_masterdatas` | 37,820 | battle |
| `UIs/masterdatas/uimasterdatas` | 353,687 | UI data |
| `Effects/masterdatas/effectdatabase` | 38,342 | effect database |
| `Contest/md/contest_masterdatas` | 23,744 | contest |
| `GMS/md/gms_masterdatas` | 15,821 | GTS |
| `FureaiHiroba/fureai/masterdata` | 153,624 | recreation area |
| `UnderGround/masterdata` | 12,629 | Underground |
| `Union/unionroom/masterdata` | 2,259 | Union Room |
| `Dpr/scriptableobjects/gamesettings` | 18,056,668 | settings, ScriptableObjects (large) |
| `Message/*` | 1.2–1.5 MB per language | text (see section 6) |

Loading clues from code (Il2CppDumper output):

- Asset access runs through `SmartPoint.AssetAssistant.AssetManager` (`RequestAssetBundle`, `LoadAssetBundle`, `LoadAsset(assetPath)`), configured by an `AssetBundleDownloadManifest` (version 6, list of `AssetBundleRecord`). Bundle names correspond to relative paths under `AssetAssistant`.
- `DataManager` (`StartUpLoad`, `Load(string assetBundleName)`) holds static tables (including trainer, shop, and tower tables) and loads them from bundles at startup.
- Table classes are `ScriptableObject`s with “Sheet” subclasses: `PersonalTable`, `ItemTable`, `WazaTable`, `GMSMasterData`. This confirms master data is serialized ScriptableObjects in bundles, not a separate binary format.
- String literals name bundles `personal_masterdatas`, `battle_masterdatas`, `masterdatas`, `md/gms_masterdatas`, `md/contest_masterdatas`, `masterdatas/uimasterdatas`, `masterdatas/effectdatabase`; also `pokemons/battle/{0}`, `pokemons/field/pm{0:D4}_00_00`.
- Text: `MessageManager` with `MsgDataFileLoader`; language IDs select the bundle (`GetFileNameByLanguageId`).

## 4. Audio (Wwise)

| Property | Value |
|---|---|
| `.bnk` | 696 files, 56.5 MiB (smallest 2,804 B, median 39,457 B, largest 23.4 MiB) |
| `.wem` | 3,241 files, 361.5 MiB |
| Total audio | 419.6 MiB (including `PluginInfo.xml`, `Wwise_IDs.h`) |
| Bank header | all 696 banks start with `BKHD`, version field = **135** |
| WEM container | all RIFF/WAVE, `fmt` codec tag `0xFFFF` (Wwise Vorbis) |

To my knowledge, bank version 135 corresponds to Wwise 2019.2.x (not confirmed against dump). Code contains `AkSoundEngine`, `AkSwitchSettings`, `Init.bnk`, and a message about copying banks into StreamingAssets.

## 5. Movies

18 files, 456 MiB, all `.webm` (EBML, DocType `webm`). In first 64 KiB, **VP8** (`V_VP8`) is identifiable in all; no VP9. No audio track is identified in that region (unresolved).

| Group | Files | Each file |
|---|---:|---:|
| Opening by language (`op`) | 9 | about 19.8–20.7 MB |
| Opening loop | 1 | 0.97 MB |
| Ending (`ed_female/male_00–03`) | 8 | about 37 MB |

## 6. Text and Localization

Message bundles (12): `Message/Message` (3.7 KB, likely index), `common_msbt` (language-independent), and `jpn`, `jpn_kanji`, `english`, `french`, `german`, `italian`, `spanish`, `korean`, `simp_chinese`, `trad_chinese`. These are 10 language variants (Japanese in kana and kanji). Code knows language IDs JPN, USA, FRA, ITA, DEU, ESP, KOR, SCH, TCH (ID 6 absent).

Filename language suffixes, 9 languages each (`en`, `fr`, `ge`, `it`, `jp`, `ko`, `si`, `sp`, `tr`): UIs (10 files per language), GMS (9), Contest (1), all 9 opening movies. Codes `si`/`tr` probably mean simplified/traditional Chinese (assumption).

## 7. Open Questions

- ~~What exactly is `Dpr.bin`?~~ Resolved: bundle catalog (`AssetBundleDownloadManifest`, .NET BinaryFormatter, version 6), see `docs/bundle-katalog.md`.
- Which assets (paths) are inside bundles? Requires decompressing block data and reading serialization (TypeTree).
- How do `Message/Message` and `common_msbt` work together, and what format is text in bundles (MSBT?)?
- Exactly which bundles contain items, moves, maps, trainers (probably `Dpr/masterdatas`, but unverified)?
- Caller chain `DataManager.StartUpLoad` → concrete bundle names is not yet confirmed by decompilation.
- Does movie container have audio track (Vorbis/Opus), and what are resolution/frame rate?
- Exact Wwise version and mapping `.wem` ↔ bank (event IDs from `Wwise_IDs.h`)?
- Do bundles with 4 nodes (1 bundle) and 86 uncompressed blocks serve a special purpose?
