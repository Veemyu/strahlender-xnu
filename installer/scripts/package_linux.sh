#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64)
    TOOL_HASH=a595ea34cd6136c7f595e9dcbb16f3e9725d7610efb9e43b38c3c6e86cafc270
    RUNTIME_HASH=9a72a744d221576c9347ec074243acc5c3c7568896b12714e0e82e9f0bf47900 ;;
  x86_64)
    TOOL_HASH=95cbe7cce9717fce90c484e34052ee7c7f1d7635b33c12525b4776826a7d29b6
    RUNTIME_HASH=617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46 ;;
  *) echo 'Unsupported Linux architecture' >&2; exit 2 ;;
esac
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
cp "$HERE/target/release/strahlender-xnu-installer" "$HERE/target/release/ips_patch" "$HERE/target/release/installer_update" "$HERE/target/release/installer_setup" "$APPDIR/usr/bin/"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$HERE/assets/FIRA-LICENSE" "$HERE/assets/OCTICONS-LICENSE" "$APPDIR/usr/Resources/"
cp "$HERE/vendor/iced_winit/LICENSE" "$APPDIR/usr/Resources/ICED-WINIT-LICENSE"
cp -R "$HERE/assets/lucide" "$APPDIR/usr/Resources/lucide"
cp -a "$PRIVATE_RUNTIME" "$APPDIR/usr/Resources/runtime"
cp "$HERE/assets/lucide/monitor.svg" "$APPDIR/strahlender.svg"
cat > "$APPDIR/strahlender.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Strahlender Installer
Exec=strahlender-xnu-installer
Icon=strahlender
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
tar -czf "$OUTPUT/installer-linux-$ARCH.tar.gz" -C "$OUTPUT" Strahlender.AppDir
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
sha256sum installer-* > SHA256SUMS
