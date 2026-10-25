# Installer identity

`icon.svg` is the approved color artwork on a white rounded tile. It is the
single source for every installer icon, independent of the UI theme. The Vee
mark is 378/512 of the canvas width, inset 38 px from the left and bottom.
The original installation glyph sits at the upper right.

The Vee artwork was supplied by the project owner in `install.svg`. That draft
contained a font-based V and a transparent bitmap. The final SVG outlines the V,
traces the bitmap silhouette deterministically, and approximates its blue and
charcoal gradients. It contains no fonts, embedded images or external resources.
The installation glyph was drawn for this project from basic SVG paths; it is
not an imported icon-pack asset. Final artwork ships under the repository's MIT
license. Earlier proposals and source drafts are not release assets.

## Build outputs

The Rust build script uses pinned resvg without text or raster-image features.
It produces rounded PNGs at 16, 32, 48, 64, 128, 256, 512 and 1024 px, a 64 px
RGBA window icon, and native Apple inputs. `installer_icons --output DIRECTORY`
exports these build-time resources for packaging; this tool is not shipped.

Linux uses the flat rounded SVG/PNGs in the AppImage, hicolor theme hierarchy
and window icon. There are no painted reflections, glass materials or shadows.
The Wayland app ID and X11 window class match the `strahlender.desktop` entry.
macOS uses a classic ICNS fallback and an Icon Composer asset catalog compiled
locally with the same Apple tool integration as the game. The reviewed binaries
in `macos/` are versioned, so CI does not need to run the native icon compiler.
Packaging verifies their checksums and the hash of the approved SVG before use.
Apple supplies the native
outer mask and lighting; the foreground input is transparent, without a second
rounded tile. The background stays explicitly white in default and dark
appearances, and the material settings match BDSP. User-selected tinted rendering
remains controlled by the OS.

Generated PNGs, `.icon` documents and compiler scratch output live under Cargo's
`OUT_DIR` or the gitignored `work/` directory. Only the reviewed Mac ICNS/catalog
and their provenance metadata are versioned. End users never need an SVG
renderer, font, icon pack or network connection to display the installer icon.

## Regenerate the Mac assets

On a Mac with current Xcode and Icon Composer, export fresh Rust-rendered inputs
and choose a new scratch directory for each run:

```sh
cargo run --locked --manifest-path installer/Cargo.toml --bin installer_icons -- --output work/installer-icons/artwork
python3 -S installer/scripts/package_icons_macos.py --artwork work/installer-icons/artwork --scratch work/installer-icons/native-review
python3 -S installer/scripts/package_icons_macos.py --verify
```

The command updates `macos/Installer.icns`, `macos/Assets.car`, and `metadata.json`.
Review default/dark native previews and the icon resolved by Finder, then commit
these three files with any SVG change. The metadata records Xcode's version,
source hash and binary hashes without local paths. The existing macOS 12
deployment target remains independent of the icon compiler's catalog target.
