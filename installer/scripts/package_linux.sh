#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|x86_64) ;;
  *) echo 'Unsupported Linux architecture' >&2; exit 2 ;;
esac
# The AppImage tools are rolling "continuous" builds, so there is nothing to pin: take the SHA-256 GitHub publishes
# for the asset right now (HTTPS) and verify the download against it.
published_digest() {
  curl -fsSL --retry 3 ${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"} "https://api.github.com/repos/$1/releases/tags/continuous" |
    python3 -c 'import json,sys; name=sys.argv[1]; print(next(a["digest"].removeprefix("sha256:") for a in json.load(sys.stdin)["assets"] if a["name"]==name))' "$2"
}
TOOL_HASH="$(published_digest AppImage/appimagetool "appimagetool-$ARCH.AppImage")"
RUNTIME_HASH="$(published_digest AppImage/type2-runtime "runtime-$ARCH")"
PRIVATE_RUNTIME="${BDSP_INSTALLER_RUNTIME:?Set BDSP_INSTALLER_RUNTIME to the verified full runtime}"
"$PRIVATE_RUNTIME/python/bin/python3" -I -B -c 'import json,sys; from pathlib import Path; assert json.loads((Path(sys.executable).resolve().parents[2]/"runtime.json").read_text())["profile"] == "shaders", "Full shader runtime required"'
RUSTFLAGS="${RUSTFLAGS:-} --remap-path-prefix=$HOME=/build --remap-path-prefix=$ROOT=." cargo build --release --locked --bins --manifest-path "$HERE/Cargo.toml"
OUTPUT="$ROOT/work/installer-packages/linux-$ARCH"
APPDIR="$OUTPUT/Strahlender.AppDir"
if [[ -e "$APPDIR" ]]; then
  if [[ "${1:-}" != --repack || ! -x "$APPDIR/usr/bin/strahlender-xnu-installer" || ! -f "$APPDIR/usr/Resources/runtime/runtime.json" ]]; then
    echo "Output already exists: $APPDIR. Use --repack to package this staged installer again." >&2
    exit 1
  fi
else
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/Resources" "$OUTPUT/tools"
cp "$HERE/target/release/strahlender-xnu-installer" "$HERE/target/release/ips_patch" "$HERE/target/release/firmware_import" "$HERE/target/release/installer_update" "$HERE/target/release/installer_setup" "$APPDIR/usr/bin/"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$HERE/assets/FIRA-LICENSE" "$HERE/assets/OCTICONS-LICENSE" "$APPDIR/usr/Resources/"
cp "$HERE/vendor/iced_winit/LICENSE" "$APPDIR/usr/Resources/ICED-WINIT-LICENSE"
cp -R "$HERE/assets/lucide" "$APPDIR/usr/Resources/lucide"
cp -R "$HERE/assets/firmware-import-licenses" "$APPDIR/usr/Resources/firmware-import-licenses"
cp -a "$PRIVATE_RUNTIME" "$APPDIR/usr/Resources/runtime"
cat > "$APPDIR/strahlender.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Strahlender Installer
Exec=strahlender-xnu-installer
Icon=strahlender
StartupWMClass=strahlender
Categories=Utility;
Terminal=false
DESKTOP
cat > "$APPDIR/AppRun" <<'LAUNCHER'
#!/bin/sh
APPDIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$APPDIR/usr/bin/strahlender-xnu-installer" "$@"
LAUNCHER
chmod 755 "$APPDIR/AppRun"
fi
ICON_STAGE="$OUTPUT/icons"
"$HERE/target/release/installer_icons" --output "$ICON_STAGE"
cp "$ICON_STAGE/icon.svg" "$APPDIR/strahlender.svg"
cp "$ICON_STAGE/256.png" "$APPDIR/.DirIcon"
for size in 16 32 48 64 128 256 512 1024; do
  ICON_DIR="$APPDIR/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$ICON_DIR"
  cp "$ICON_STAGE/$size.png" "$ICON_DIR/strahlender.png"
done
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps" "$APPDIR/usr/share/applications"
cp "$ICON_STAGE/icon.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/strahlender.svg"
cp "$APPDIR/strahlender.desktop" "$APPDIR/usr/share/applications/strahlender.desktop"
TOOL="$OUTPUT/tools/appimagetool-$ARCH.AppImage"
RUNTIME="$OUTPUT/tools/runtime-$ARCH"
fetch_verified() {
  local url="$1" destination="$2" digest="$3"
  if [[ -f "$destination" ]] && printf '%s  %s\n' "$digest" "$destination" | sha256sum -c - >/dev/null 2>&1; then return; fi
  curl -fL --connect-timeout 20 --max-time 300 --retry 3 "$url" -o "$destination.partial"
  printf '%s  %s\n' "$digest" "$destination.partial" | sha256sum -c -
  mv "$destination.partial" "$destination"
}
fetch_verified "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage" "$TOOL" "$TOOL_HASH"
fetch_verified "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-$ARCH" "$RUNTIME" "$RUNTIME_HASH"
chmod 755 "$TOOL"
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run --runtime-file "$RUNTIME" "$APPDIR" "$OUTPUT/installer-linux-$ARCH.AppImage"
cd "$OUTPUT"
sha256sum "installer-linux-$ARCH.AppImage" > SHA256SUMS
