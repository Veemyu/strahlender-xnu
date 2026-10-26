# Bundled UI assets

These assets are embedded in the executable during compilation. The installed
application never downloads UI icons, fonts, scripts or styles from a CDN.
No system icon theme, emoji renderer or installed icon font is required.

- `brand/icon.svg`: approved installer identity, color artwork on a white rounded
  tile. Rust renders it at build time for Linux and window icons; native Apple
  tools add the macOS material treatment. See `brand/README.md` for provenance
  and platform details. No alternate installer branding is shipped.

- `ui/copy.svg` and `ui/check.svg`: original geometric utility icons under
  the repository MIT license, embedded locally and shared by all platforms.
- `github.svg`: GitHub's Primer Octicons `mark-github-16.svg`, retrieved from
  https://github.com/primer/octicons/blob/main/icons/mark-github-16.svg on
  2026-10-23. License: `OCTICONS-LICENSE` (MIT).
- `lucide/*.svg`: sun, moon, monitor, laptop, tablet and smartphone, from
  https://github.com/lucide-icons/lucide/tree/c32d98db9b8e11ac5aa7db58d70d17b662679461/icons.
  The unmodified SVGs are in the repository. Full ISC/Feather MIT license is in
  `lucide/LICENSE`. Rendering uses the app palette; no platform glyph lookup
  is required.
  The tablet is displayed in landscape orientation to distinguish it from the phone.
- macOS device target cards first request the system symbols `macbook`,
  `ipad.landscape`, and `iphone` through AppKit. They remain system-provided
  images and are not copied into the installer bundle. If a symbol is missing,
  or macOS is older than 11, the app falls back to the bundled Lucide SVG.
  Linux and Windows use the bundled SVGs directly. This is limited to the
  macOS installer build under Apple's Xcode and SDK Agreement, section 2.10;
  the app runs on macOS even when its selected output target is iPad or iPhone.
- Fira Sans Regular: bundled and embedded by the pinned Iced dependency's
  `fira-sans` feature. Cargo retrieves it at build time; the binary contains the
  font bytes. `FIRA-LICENSE` contains Mozilla Fira's SIL Open Font License from
  https://github.com/mozilla/Fira/blob/master/LICENSE.

Use SVG/image assets for future UI icons rather than Unicode pictograms. New
fonts must be bundled and cover the supported text scripts. Fira Sans covers the
current German/English UI; localized game titles in CJK scripts will need bundled
fallback fonts before that metadata UI is accepted. Do not rely on the end user's
font installation for that feature.

Third-party asset licenses are embedded as well and can be read with `--licenses`.

Release artifacts must include everything needed to render the installer without
a network connection. Backend downloads (source/toolchains) are separate,
explicit installation activities. End users download prebuilt installers; they
do not build Rust or fetch UI assets. Installer packaging and explicit
publication controls are documented in `../docs/releases.md`.
