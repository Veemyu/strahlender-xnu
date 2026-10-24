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

cargo build --locked --release --bins --manifest-path "$HERE/Cargo.toml"

APP="$ROOT/work/installer-packages/macos/Strahlender Installer.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"
cp "$HERE/target/release/strahlender-xnu-installer" "$MACOS/strahlender-xnu-installer"
cp "$HERE/target/release/ips_patch" "$MACOS/ips_patch"
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
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
printf 'Packaged %s (%s)\n' "$APP" "$ARCH"
