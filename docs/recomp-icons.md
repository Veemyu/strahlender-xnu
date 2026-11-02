# Native app icons

Updated: 2026-10-20. The user approved Full Bleed for every language variant.
Applies to macOS, iPadOS, and both Linux Qt launch paths.

## Source-only supply chain

Every original icon comes from the control NCA in the user's own legally obtained
game dump. The repository supplies processing code and synthetic tests only.
It must never contain Nintendo artwork, converted icons, generated .icon packages,
asset catalogs, or finished app icons. All generated data stays under ignored work/.

The reproducible path is:

1. Unpack the supplied XCI or base NSP using hactool and the user's local keys.
2. Identify the application title family and its control NCA.
3. Read the actual icon_<language>.dat files; merge valid update variants over
   same-language base variants. Invalid/missing update images do not replace a
   valid base image.
4. Validate square image dimensions, normalize to RGB PNG, hash and deduplicate,
   and write icons.json under work/recomp/icons/source.
5. Generate full-bleed 1024px artwork and editable Icon Composer documents from
   those validated originals. No staging preview is used as a build input.
6. Compile native Apple assets/metadata with actool (Xcode 26 or newer; before that a classic ICNS/AppIcon
   catalog, see below), or generate Linux PNG sizes.
7. Include settings, finalize/sign the app, and verify its signature.

An existing main.npdm or explicit --title-id selects the title. On a fresh
container without main.npdm, exactly one base Program title family is required.
Ambiguous applications/control NCAs fail with an actionable error rather than
silently choosing an unrelated icon. No game-code generation is needed to
extract icons alone.

The local dump contains nine variants: German, US English, Spanish, French,
Italian, Japanese, Korean, Simplified Chinese, and Traditional Chinese. Every
original is 256 × 256. Resampling does not invent additional source detail.
A different dump exposes only variants actually present there.

## Window title

The game window shows the game's own name from control.nacp in the system language, for example "Pokémon Strahlender Diamant"
(German system) or "Pokémon Brilliant Diamond" (English); Diamond or Pearl follows the dump. A mod build adds " - <mod name>", and
`BDSP_WINDOW_TAG=<name>` adds " [<name>]" so parallel test builds can be told apart:
`<game name>[ - <mod name>][ [<tag>]]`.

`game_icons.prepared()` writes `titles.json` next to `icons.json` (`icons/windows`, `icons/linux`, `Resources/AppIcons` on the Mac):
`{"schema": 1, "titles": {"<NACP locale>": "<name>"}, "mod": "<mod name>"}`. A mod build keeps the game's names there (its
`icons.json` titles are the mod name). `runtime/window_title.c` reads it and matches the system language list in order
(de-DE to de, en-GB to en-GB else en-US, es-MX to es-419 else es-ES, pt-BR to pt-BR else pt-PT, fr-CA to fr-CA else fr, zh-TW and
zh-HK to zh-Hant, zh-CN to zh-Hans, ja, ko, it, nl, ru). Without a name for any system language the title uses en-US, then the
first name, then "BDSP Recomp". Test: `scripts/recomp/runtime/test/run_window_title_test.sh`. The Linux desktop entry and the
Windows file properties keep the name BDSP.

## Extraction and automatic builds

The extraction stage (scripts/build_all.sh and the Windows installer pipeline run the
Rust tool `installer/extract`) retains the source icons from the base XCI or NSP and the
optional update NSP in `work/recomp/icons/source` before it cleans up control data.
There is no separate icon extractor; run the extract stage once and every platform
build reads the same source:

```sh
scripts/build_all.sh --only extract --xci <game.xci> --nsp <update.nsp> --prod-keys <prod.keys>
```

Key values and potentially sensitive hactool output are never logged. Keys are
not transferred to Linux. The user provides their own keys; they are not part of
the repository.

Mac make_app.sh and deploy_ios.sh build automatically regenerate native icons.
There is no longer a transfer step to the Linux machine. The Vulkan/Qt builds
there read the validated source manifest and images from `work/recomp/icons/source`
in the working copy (`BDSP_ICON_SOURCE` can override this path) and generate Linux
assets. The user provides these files on that machine.

Outputs outside work/ are rejected. Icons and processing scripts participate in
the Mac packaging fingerprint, independently of guest generation/object markers.
Pillow and Xcode (16 or newer) are required for Apple builds; Xcode 26 or newer adds the Liquid Glass icon.
Missing tools fail rather than installing software automatically. The preflight reads `actool --version`:
Xcode 26 or newer is plain OK, Xcode before 26 is a note ("classic app icon, no Liquid Glass"), and only an
unreadable `actool` counts as missing. `compile_icons` still checks that actool wrote `Assets.car` (and the `.icns`
on macOS), because an `actool` before 26 skips `.icon` documents without an error.

## Classic icon (Xcode before 26)

Icon Composer documents need the actool of Xcode 26. With an older actool, with an unreadable version, or with
`BDSP_LEGACY_ICONS=1` (forces it on any Xcode, also part of the recomp fingerprint) the builders take a classic path
and log `Notice: classic app icon without Liquid Glass (...)`. It needs no `.icon` documents and no Icon Composer:

- macOS: `icon_artwork.mac_artwork` renders the usual macOS tile from the same original artwork (transparent 100 px
  margin at 1024, rounded corners, soft shadow, artwork edge to edge), ten iconset sizes (16 to 512 at 1x and 2x) go
  through `iconutil --convert icns`. Result: `BDSP.icns`, `AppIcons/<name>.icns`, `CFBundleIconFile` in Info.plist;
  no `Assets.car`, no `CFBundleIconName`. macOS 26 shows such an icon on its own plate instead of the glass icon.
  The Dock override for non-default languages (`applicationIconImage`) uses the same per-variant ICNS as before.
- iPhone/iPad: no actool and no asset catalog. Opaque square PNGs (the system applies the corner mask, no alpha) are
  written into the app bundle per distinct artwork: `<name>60x60@2x.png` (120), `60x60@3x` (180), `76x76~ipad` (76),
  `76x76@2x~ipad` (152) and `83.5x83.5@2x~ipad` (167), named like the files actool emits. `CFBundleIcons` and
  `CFBundleIcons~ipad` get `CFBundlePrimaryIcon.CFBundleIconFiles` and one `CFBundleAlternateIcons` entry per other
  variant (key = icon name, the value `setAlternateIconName:` takes), so the language selection works as before.
  Icon files and `Assets.car` of an earlier build in the same bundle are removed first. Unlike actool, this needs no
  iOS simulator runtime (actool of Xcode 16 stops with "No available simulator runtimes" without one).

Geometry, interpolation, source hashes, and generated document definitions are
deterministic. Native rendering/compilation is Apple-toolchain-dependent; this
does not promise byte-identical Assets.car archives across Xcode versions.
There is no placeholder icon: without valid original icons (`work/recomp/icons/source/icons.json` with at least one
variant, created by the extract stage from your game file) the macOS preflight reports them as missing and every icon
build stops with "No original game icon found".

## Approved Apple design

Full Bleed replaces the earlier dark inset frame. The 256px original is
resampled once to 1024 × 1024 with Lanczos. Icon Composer uses scale 100% and
X/Y translation zero. There is no source margin or pre-baked outer corner mask.
Apple supplies the outer shape and glass edge. The logo/character are not
artificially separated into invented layers.

Specular lighting is enabled. Blur and translucency are disabled to preserve
the image. Highlights are not painted into the source PNG. A dark derived
background fill remains behind the opaque artwork, without a visible inner frame.
See [Apple Icon Composer](https://developer.apple.com/icon-composer/).

iPad: all unique variants compile into real layered Assets.car icon stacks,
with primary and alternative registrations generated by actool, including
CFBundleIcons~ipad. The default is English. Settings → Apps → BDSP → App icon
stores manual language selection; the next activation applies it using the public
alternate-icon API. System language is a recommendation only. Identical artwork
does not trigger redundant changes; concurrent requests are guarded. Missing
saved variants revert to the default. iPadOS can show a system change notification.

Mac: the English embedded default uses native Assets.car plus Apple's generated
compatibility ICNS. The default Dock path does not replace the system-rendered
layered icon with a flattened PNG. Manually selected language variants use
native-compiled compatibility ICNS through applicationIconImage; this is a static
Dock override, not a promise of animated alternate icons or a changed Finder icon.
See [Apple: applicationIconImage](https://developer.apple.com/documentation/appkit/nsapplication/applicationiconimage).

Personal project.pbxproj signing settings are not modified. The iPad bundle is
signed after icons/settings/shaders are included, then checked using
codesign --verify --deep --strict. The accepted shader start gate is unchanged.

## Linux and selection limits

Linux remains full bleed without Apple-specific material effects. Builds generate
PNG sizes 16, 32, 48, 64, 128, 256, and 512 under work/recomp/icons/linux.
Both Qt hosts share an App icon menu and persisted QSettings choice.
The generated desktop launcher uses the English default and remains under work/;
no system installation occurs. BDSP_ICON_DIR overrides the generated directory.

Default preference: US English, British English, German, then another valid variant.
Identical artwork shares generated assets while
remaining selectable by language. Game language is independent.
Arbitrary runtime image import is not implemented; iPad icons must be registered
at build time.

## Review and verification

The earlier preview helper (`stage_glass_icons.py`, rendered 1024 px previews with Icon Composer's `ictool` at light
angles 0 and 120) was a development check and was removed on 2026-10-29: Xcode 27 dropped the light angle from
`ictool`, and no build used its output. The app icons come from `actool --compile` (`icon_composer.compile_icons`);
compiled bundles were checked with Xcode 27.1 for iPad/iPhone (`Assets.car`, `AppIcon60x60@2x.png`,
`AppIcon76x76@2x~ipad.png`) and macOS (`AppIcon.icns`). Static previews never replace on-device appearance and
switching verification. The .icon schema and CLI are validated against the installed Apple tools, not treated as a
stable public file-format API.

Approved design examples: work/recomp/icons/staging-liquid-glass-03-full-bleed.
All nine variants: work/recomp/icons/staging-liquid-glass-04-full-bleed-all.

Synthetic tests cover fresh XCI/base-NSP icon extraction without old work data,
title filtering, base/update merges, corruption, deduplication, full-bleed pixels,
document scale/position, settings/metadata, fingerprints, and language recommendations. Existing Apple and Linux Qt
tests cover selection, persistence, and removed-variant fallback.

Final bundles were checked for nine language variants. iPad registration names
match all nine native icon stacks in Assets.car; Mac includes its native default
stack and nine compatibility ICNS variants. Signatures are checked. No repeated
iPad launch loops are used. Device appearance and actual alternate-icon switching
remain separate manual checks.

Logs: work/builds/logs/icons-*.log and work/recomp/icons/.
The earlier German report is historical and lives in the git history.
