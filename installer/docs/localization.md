# Localization contract

## Installer interface

- **Current status:** German, English, Spanish, Portuguese and Russian are implemented.
  The default follows the operating-system locale. `BDSP_LANG` is a development/
  test override, not a build-language selector.
- All translatable interface text goes through `i18n::Label`. Every one of the
  222 labels has five required translations in the same catalog in `i18n.rs`.
  New labels must provide all five translations; tests reject empty strings or
  changed interpolation parameters.
- Regional UI locales share exactly one base-language catalog: `es-ES`, `es-419`,
  `es-MX`, `es-AR` and all other `es-*` variants use Spanish; `pt-PT`, `pt-BR`,
  `pt-AO` and all other `pt-*` variants use Portuguese. There are no separate
  Latin American UI files or regional overrides. The Portuguese catalog uses
  European Portuguese vocabulary. Every `ru-*` locale uses Russian.
- `uk` and all `uk-*` installer locales currently fall back to Russian.
  Ukrainian is a distinct language; this is an explicit product
  fallback, not a Ukrainian translation or a claim that it is a regional Russian
  variant. No Ukrainian catalog or regional override is shipped. Unsupported
  languages otherwise fall back to English. This mapping only affects installer
  text, not the full system locale used for original game metadata.
- Locale parsing accepts hyphens, underscores, codesets and POSIX modifiers,
  case-insensitively. File sizes and disk-space dialogs use decimal commas for
  German, Spanish, Portuguese and Russian; English uses a decimal point.
  Russian file counts select singular/few/many forms, including 11–14 exceptions,
  and file sizes use Cyrillic unit labels.
- Dark-mode captures cover the translated primary views, mod builds, build
  options, generator progress, error dialogs and completion. Linux CPU options
  are additionally checked using the platform simulation. The embedded Iced
  Fira Sans font contains the entire Russian alphabet and additional Ukrainian
  filename characters; no font download or system font is required. Raw external tool
  diagnostics retain their original language; interface labels, explanations,
  sample filenames, dependency purposes/manual guidance and error wrappers are localized.
  Package identifiers and package-manager commands remain unchanged.
- Technical names (prod.keys, XCI, NSP, GitHub, iPhone) stay unchanged. Sizes use
  the UI decimal separator; file counts distinguish singular/plural. Future
  download/time/error messages need parameterized messages rather than fragments.
- The project link is a bundled SVG button on the right of the header, beside
  the sun/moon appearance toggle, with localized tooltips for both. It opens only the fixed
  project URL in the system browser, with no embedded browser or WebKit.
- The UI font and icon fallbacks are embedded at build time; there are no runtime
  CDN requests or dependencies on host emoji/icon fonts. The macOS build may use
  native SF Symbols for device targets, with embedded SVG fallbacks; Linux and
  Windows use those SVGs directly. See `assets/README.md` for provenance and
  license details.

## Original game metadata and installer preview

- Keep the full system locale independently of the installer catalog. An English
  fallback UI on a Japanese system must still preview Japanese game metadata.
- Read titles and publisher names from the 16 NACP title slots, display version
  from NACP, and original artwork from `icon_<Language>.dat` in the matching
  Control NCA. Do not derive the game title from the filename or maintain a
  hardcoded list of translated Pokémon names.
- Original game content retains its actual regional variants: es-419/es-ES,
  pt-BR/pt-PT, en-US/en-GB, Chinese scripts, etc. Sharing UI catalogs must not
  collapse these original assets.
- For the preview choose exact locale, language/script-compatible variant, then
  English (US/UK), then a deterministic available original. Resolve titles and
  artwork independently when their available language sets differ.
- An update overrides matching original language entries while retaining other
  base entries. Absent metadata stays absent; display a localized explanation
  and filename fallback rather than claiming a verified title/region.
- Sales region is separate from language. Never infer EU/US/JP from the UI locale
  or from the fact that a game includes English/Japanese artwork.

## Finished applications are language universal

The installer preview is never an asset filter. Every build includes **all**
available original title translations, icon variants, and runtime localization
resources. There is no language-specific `.app` or IPA and no build-language
argument derived from the current computer. A recipient can use a different
system language, and changing language must not require rebuilding.

`game_icons.py ingest` retains every title in `icons.json` alongside every icon.
The Apple builders write every original display name to the corresponding
`InfoPlist.strings` and retain all artwork in AppIcons/the platform icon assets.
Existing runtime `Localizable.strings` remain bundled. Native runtime/OS locale
handling and existing icon-selection support choose from the bundled set.
The manifest's stable `default` is a packaging fallback, never the selected
installer preview locale. All resources must be present before final signing.

## Remaining metadata backend work

The Iced prototype currently performs filesystem checks; it does not yet display
real Control-NCA metadata. The existing `extract` helper still unpacks containers.
Do not connect that expensive path to drag-and-drop previews.

The shared inspect backend must instead index PFS0 (NSP) or HFS0 secure partitions
(XCI), read/decrypt NCA headers with the supplied keys, resolve application/Control
association, and access only the relevant Control RomFS metadata/icon files.
NCA directories use the same reader. Prefer bounded random-access views over
copying large NCAs; never extract Program/Data content for a preview. Ticket/title
key handling is reused from the backend. Missing keys and malformed/ambiguous
containers produce actionable localized status plus technical log details.

Return all names and icons in the shared manifest, tied to source/key request
generation. Discard stale results after replacement/removal, re-inspect on key
changes, and perform reading off the UI thread. UI review should cover selected
game, missing icon, unavailable locale, long title, update override and errors.
No preview should access third-party artwork services.

Sources: existing `scripts/recomp/app/game_icons.py`,
`scripts/recomp/app/icon_variants.h`, the checked-out emulator implementations,
and [Ryubing's ApplicationControlProperty layout](https://git.h3cjp.net/H3cJP/ryujinx/src/commit/80cbf5d1fcbbf3dcfbacbd841c2beeeedc7df239/src/Ryujinx.Horizon/Sdk/Ns/ApplicationControlProperty.cs).

The GitHub SVG comes from [Primer Octicons](https://github.com/primer/octicons/blob/main/icons/mark-github-16.svg),
with its MIT license in `assets/OCTICONS-LICENSE`. It links to this project;
see [GitHub's logo guidance](https://brand.github.com/foundations/logo).
