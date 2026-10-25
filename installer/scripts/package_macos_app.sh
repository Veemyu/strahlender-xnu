#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ARCH="$(uname -m)"
case "$ARCH" in
  arm64) RUNTIME_ARCH=aarch64 ;;
  x86_64) RUNTIME_ARCH=x86_64 ;;
  *) echo "Unsupported macOS architecture: $ARCH" >&2; exit 2 ;;
esac
PRIVATE_RUNTIME="${BDSP_INSTALLER_RUNTIME:-$ROOT/work/installer-runtime-probe/private-macos-$RUNTIME_ARCH}"
if [[ ! -f "$PRIVATE_RUNTIME/runtime.json" || ! -x "$PRIVATE_RUNTIME/python/bin/python3" ]]; then
  echo "Verified macOS $RUNTIME_ARCH runtime not found at: $PRIVATE_RUNTIME" >&2
  echo "Set BDSP_INSTALLER_RUNTIME or assemble it using installer/runtime/README.md." >&2
  exit 1
fi

"$PRIVATE_RUNTIME/python/bin/python3" -I -B -c 'import json,sys; from pathlib import Path; assert json.loads((Path(sys.executable).resolve().parents[2]/"runtime.json").read_text())["profile"] == "shaders", "Full shader runtime required"'
RUSTFLAGS="${RUSTFLAGS:-} --remap-path-prefix=$HOME=/build --remap-path-prefix=$ROOT=." cargo build --locked --release --bins --manifest-path "$HERE/Cargo.toml"

APP="$ROOT/work/installer-packages/macos/Strahlender Installer.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"
cp "$HERE/target/release/strahlender-xnu-installer" "$MACOS/strahlender-xnu-installer"
cp "$HERE/target/release/ips_patch" "$MACOS/ips_patch"
cp "$HERE/target/release/installer_update" "$MACOS/installer_update"
cp "$HERE/target/release/installer_setup" "$MACOS/installer_setup"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$RESOURCES/THIRD_PARTY_NOTICES.md"
cp -R "$HERE/assets/lucide" "$RESOURCES/lucide"
cp "$HERE/assets/FIRA-LICENSE" "$HERE/assets/OCTICONS-LICENSE" "$RESOURCES/"
cp "$HERE/vendor/iced_winit/LICENSE" "$RESOURCES/ICED-WINIT-LICENSE"
ditto "$PRIVATE_RUNTIME" "$RESOURCES/runtime"
chmod 755 "$MACOS/strahlender-xnu-installer" "$MACOS/ips_patch"

cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleExecutable</key><string>strahlender-xnu-installer</string>
  <key>CFBundleIdentifier</key><string>dev.veemyu.strahlender-xnu-installer</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>Strahlender Installer</string>
  <key>CFBundleDisplayName</key><string>Strahlender Installer</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

plutil -lint "$CONTENTS/Info.plist"
VERSION="$("$PRIVATE_RUNTIME/python/bin/python3" -I -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1],"rb"))["package"]["version"])' "$HERE/Cargo.toml")"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$CONTENTS/Info.plist"
plutil -replace CFBundleVersion -string "$VERSION" "$CONTENTS/Info.plist"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
ditto -c -k --keepParent "$APP" "$ROOT/work/installer-packages/macos/installer-macos-$RUNTIME_ARCH.zip"
tar -czf "$ROOT/work/installer-packages/macos/installer-macos-$RUNTIME_ARCH.tar.gz" -C "$(dirname "$APP")" "$(basename "$APP")"
cd "$ROOT/work/installer-packages/macos"
shasum -a 256 "installer-macos-$RUNTIME_ARCH.zip" "installer-macos-$RUNTIME_ARCH.tar.gz" > SHA256SUMS
printf 'Packaged %s (%s)\n' "$APP" "$ARCH"
