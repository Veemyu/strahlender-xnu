# iOS Textures: BC → ASTC During Build (Todo `ap-ios-textures`)

> **Note (status 2026-10-20):** `scripts/bundle_retarget.py` has been removed from `main` (only on the `unity` branch); steps for changing the platform identifier are historical. `scripts/texture_transcode.py` remains.

Status: 2026-10-19. Goal: the game's map bundles contain BC1/BC3/BC4/BC5/BC7 (DXT). Apple GPUs (iPhone, iPad) do not support BC; on iOS Unity reports “format is not supported, decompressing texture” for each texture, followed by “Failed to decompress” (Zone 422: 1,884 messages, `docs/player-build-1.md`, section 6). Solution: `scripts/texture_transcode.py` converts textures to ASTC **during the build**. All figures come from runs on the development computer (Apple M1 Pro, 8 cores); no game data is in the repository.

## Summary

| Question | Result |
|---|---|
| Tools | No Homebrew required: `tools/pydeps` contains `astc_encoder` (Python binding for ARM astcenc, aarch64 NEON), `texture2ddecoder` (BC decoder), `UnityPy`, and `Pillow`. `astcenc` was not installed via `brew`. |
| Target format | **ASTC 6×6** for color textures (3.56 bits/pixel, same choice as the original character and UI textures), **ASTC 4×4** for BC4/BC5 (normal/grayscale maps). Options: `--texture-format 4x4|6x6|8x8|off`. |
| Texture memory, Zone 422 (`area001`, 208 textures) | **46.4 MiB → 25.5 MiB** (Unity runtime counter `Profiler.GetRuntimeMemorySizeLong`, macOS Editor 6000.3.26f1) |
| Quality | PSNR against decoded BC source, 50 textures, main setting: **median 46.2 dB**, mean 47.8, minimum 35.1 dB (quality `medium`). Measured in Unity with a GPU blit (all 208 textures, 128×128): median 43.6 dB, minimum 31.7 dB. |
| Duration | `area001` (205 BC textures, 46.7 MB raw) **24–26 s** on one core (`medium`), 10 s with `fast`. `ipad-start` subset (5 bundles): 24 s. Second run: 0.8 s (nothing to do). |
| Disk size | Increases because ASTC packs less efficiently than BC under LZ4: `area001` 23.4 MB → 36.7 MB; total `ipad-start` 34.6 MB → 47.9 MB. This is disk space, not memory. |

## What the Script Does

`scripts/texture_transcode.py` (invoke with `PYTHONPATH=tools/pydeps`):

1. Reads a UnityFS bundle with UnityPy and finds all `Texture2D` entries in formats DXT1 (BC1), DXT5 (BC3), BC4, BC5, BC7, and `DXT1Crunched`/`DXT5Crunched`.
2. Decodes **each mip level separately** (`texture2ddecoder`, BGRA) and encodes it as ASTC with astcenc. The source mip chain is preserved (no newly calculated mip chain); width, height, and mip count do not change. Exception: Crunch textures (rare, one 4×4 placeholder here) are decoded only at the main level, and the mip levels are generated with a box filter.
3. Sets `m_TextureFormat` (ASTC_4x4 = 48, 5x5 = 49, **6x6 = 50**, 8x8 = 51; same identifiers as the game's ASTC textures) and `m_CompleteImageSize`. Names, PathIDs, `m_ColorSpace`, wrap/filter/aniso, `m_IsReadable`, and all other fields are left untouched. The texture's sRGB flag selects the astcenc profile (`LDR_SRGB` or `LDR`).
4. **Streaming is preserved:** texture data lives in the bundle's `.resS` file, which is rebuilt (new data at the same position in the sequence); `m_StreamData.offset/size` are set, **including for unchanged textures** whose offsets move (a test covers this). If another object (Mesh, AudioClip, VideoClip, etc.) shares the same `.resS`, data is appended instead; the old region remains unused space.
5. Writes the bundle with its original flags (LZ4HC, block info at the beginning), so `scripts/bundle_retarget.py` can still read and patch it. The platform identifier remains unchanged (measured).

Not converted (but counted and reported): ASTC, RGBA32, Alpha8, and other iOS-compatible formats; BC6H (HDR); Cubemap, Texture2DArray, Texture3D. They do not occur in `area001` (only Alpha8 ×1 and RGBA32 ×2, both iOS-compatible). Whether other bundles contain BC6H was not evaluated.

### Why These Formats

- **ASTC 4×4** uses 8 bits/pixel, as much as BC3/BC7 and **twice as much as BC1**. Measured: `area001` would grow from 46.7 MB to **54.4 MB**. Unsuitable for the “keep texture memory small” goal; use only for data/normal maps (BC4/BC5) and as a maximum-quality option (median PSNR 61.6 dB, mean 62.5 dB).
- **ASTC 6×6** (3.56 bits/pixel): 24.8 MB instead of 46.7 MB (−47%), median 46.2 dB. Default. This is also what the game uses for characters and UI (`ASTC_RGB_6x6`).
- **ASTC 8×8** (2 bits/pixel): 13.9 MB, but median only 39.5 dB (quality `fast`); an emergency option for memory-budget planning, not the default.
- Quality (`--quality`): `medium` is the default. `fast` costs about 1 dB (median 43.8 rather than 46.2 dB at 6×6) and saves about 60% of the time.

| Variant (`area001`, texture payload only) | Texture bytes | Median PSNR | Time |
|---|---:|---:|---:|
| Original BC | 46.7 MB | – | – |
| ASTC 4×4, medium | 54.4 MB | 61.6 dB | 14 s |
| **ASTC 6×6, medium** | **24.8 MB** | **46.2 dB** | 26 s |
| ASTC 6×6, fast | 24.8 MB | 43.8 dB | 10 s |
| ASTC 8×8, fast | 13.9 MB | 39.5 dB | 11 s |

(Times are approximate because measurements ran in parallel.) The high PSNR at 4×4 is because the BC source itself is encoded in 4×4 blocks with few colors. PSNR measures deviation from the **decoded BC source**, not from a nonexistent original. 99 dB in the tables means identical (flat textures).

## Usage

```
export PYTHONPATH=tools/pydeps
scripts/texture_transcode.py info    BUNDLE                       # formats and sizes
scripts/texture_transcode.py bundle  SOURCE DEST [--block 6x6] [--quality medium]
scripts/texture_transcode.py tree    DIRECTORY [--list FILE] [--jobs N] [--dry-run]
scripts/texture_transcode.py psnr    SOURCE DEST --samples 50     # numbers only
```

`tree` writes a new file for each bundle and replaces the old one (an APFS clone of the original remains untouched). `--list` (subset; same file as `--bundle-subset`, paths relative to the directory) and `--dry-run` (count BC textures, write nothing) enable **selective transcoding**; `--jobs` distributes bundles across processes (default: half the core count).

### In the Build Pipeline

In the `assets` stage, this runs **after** setting the platform identifier and before copying videos/master data, unless `--texture-format` is `off`. Default: `6x6` for bundle platform `ios` (`--target ios`), otherwise `off` (Mac GPUs can use BC). Example for iPad:

```
scripts/build_all.sh --only assets --target ios --bundle-subset scripts/subsets/ipad-start.txt
scripts/build_all.sh --only assets --target ios --texture-format 4x4      # all bundles, best quality
```

**Idempotency:** A bundle without BC textures is unchanged; a second run changes nothing (0.8 s for the subset, measured). The `assets` stage marker hash (`work/.stages/assets.json`) now also includes `texture_transcode.py` and the selected format; changing the format rebuilds the stage. An already-transcoded bundle cannot be “rebuilt” into another ASTC format (there is no BC left in the source): to change formats, use `--force` or regenerate the stage from the original bundles.

## Checks

1. **Python roundtrip** (`scripts/tests/test_texture_transcode.py`, synthetic textures and a hand-built mini bundle only): mip layout and sizes for 4×4/6×6/8×8, including dimensions not divisible by the block size; minimum PSNR values; contiguous `.resS` and byte-identical unchanged texture with shifted offset; idempotency; list/dry-run options; further processing with `bundle_retarget` (platform remains 38 and can be set to 9). Test writing exposed a real bug (unchanged textures with shifted offsets were not rewritten); it has been fixed.
2. **PSNR against decoded BC source**, 50 textures from `area001` (6×6, `medium`): minimum 35.06 / median 46.20 / mean 47.79 dB; quality `fast`: 34.38 / 43.80 / 45.58 dB.
3. **Unity test on macOS** (Metal, ASTC supported), separate batch-mode run in disposable project `work/unity-astc-test` (not the main editor): `scripts/astc_bundle_check.cs` loads original and transcoded `area001` sequentially (macOS platform identifier) and compares them. Result: **208 of 208 textures load**; before: Alpha8 ×1, BC5 ×2, BC7 ×28, DXT1 ×55, DXT5 ×119, DXT5Crunched ×1, RGBA32 ×2; after: Alpha8 ×1, **ASTC_6x6 ×203, ASTC_4x4 ×2**, RGBA32 ×2. Name, size, and mip count are unchanged for all 208 (5–11 mips); runtime memory 46.4 → 25.5 MiB; GPU comparison median 43.6 dB, mean 45.0 dB, minimum 31.7 dB. **Not checked:** display on iPad (no device in this run) and visual inspection.
4. **Size/duration of iPad subset** (`scripts/subsets/ipad-start.txt`, 5 bundles plus catalog):

| | Before | After |
|---|---:|---:|
| Total size (bundles + catalog) | 34,565,820 bytes (34.6 MB) | 47,886,074 bytes (47.9 MB) |
| Texture bytes in converted bundles | 48.1 MB | 26.2 MB |
| Duration | – | 24.3 s total (4 processes; `area001` 23.8 s, `fc0001_11` 0.8 s) |

   Only `area001` (205 textures) and `fc0001_11` (one BC5 texture, which would also fail on iOS) are converted. The other three bundles (character `fc0001_00`, `pc_parts`, UI) already use ASTC 6×6.

## Estimate for All Bundles

Dry run `tree --dry-run` across all of `AssetAssistant` (14,053 files, 3.8 GB, 30 s): **2,838 bundles** contain BC textures, a total of **24,690 textures with 5.21 GB** of raw BC data; 11,214 bundles have none. Based on `area001` (about 0.5–0.55 s per MB of raw BC data on one core, `medium`), all bundles are estimated to take **about 45–50 minutes, or 10–15 minutes with 4–6 processes** (estimate, not measured; `fast` takes about one third as long). Total texture memory across all bundles: about 5.2 GB (BC) → about 2.8 GB (ASTC 6×6, based on the `area001` ratio). Due to disk size, total bundles are estimated at about 1.5× (≈ 5.5–6 GB instead of 3.8 GB; estimate). What matters for iPad is the amount loaded at once (by zone), not the total; against the planning budget “textures about 1.2 GB” (`docs/ipad-messung-1.md`), Zone 422's 25.5 MiB is uncritical.

## Alternatives Considered

- **Unity Editor transcoding** (`TextureImporter`, `EditorUtility.CompressTexture`) works on assets imported into the project. But the textures are already inside third-party bundles and are not imported; this path would be “extract bundle textures, import into project, rebuild,” losing PathIDs and references. Not chosen.
- **Runtime conversion** in the player: no ASTC encoder is available in the player (`Texture2D.Compress` cannot translate BC to ASTC, and a GPU blit does not encode). Falling back to RGBA32 (decode on load) would multiply memory by eight for BC1 and by four for BC3/BC7 (Zone 422: roughly 180 MiB instead of 25 MiB, estimated from the ratio, not measured) and add load time. Possible as an emergency fallback, not recommended.
- **Offline in the bundle (chosen):** no runtime cost, lowest memory use, PathIDs and references preserved.

## Limits and Open Items

- No run on iPad with converted bundles and no visual inspection; the macOS test confirms loading, format, and memory use.
- The `assets` stage through `scripts/build_all.sh` (real run, not dry run) was not run to avoid modifying the working game-data directory.
- The estimate for all bundles is an extrapolation from one zone and does not account for texture dimensions or content differences across zones.
