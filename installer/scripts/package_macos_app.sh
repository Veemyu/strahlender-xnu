#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PACKAGE_ARCH="${BDSP_INSTALLER_PACKAGE_ARCH:-$(uname -m)}"
case "$PACKAGE_ARCH" in
  arm64|aarch64) RUNTIME_ARCH=aarch64; RUST_TARGET=aarch64-apple-darwin ;;
  x86_64) RUNTIME_ARCH=x86_64; RUST_TARGET=x86_64-apple-darwin ;;
  *) echo "Unsupported macOS architecture: $PACKAGE_ARCH" >&2; exit 2 ;;
esac
PRIVATE_RUNTIME="${BDSP_INSTALLER_RUNTIME:-$ROOT/work/installer-runtime-probe/private-macos-$RUNTIME_ARCH}"
if [[ ! -f "$PRIVATE_RUNTIME/runtime.json" || ! -x "$PRIVATE_RUNTIME/python/bin/python3" ]]; then
  echo "Verified macOS $RUNTIME_ARCH runtime not found at: $PRIVATE_RUNTIME" >&2
  echo "Set BDSP_INSTALLER_RUNTIME or assemble it using installer/runtime/README.md." >&2
  exit 1
fi

[[ "$(plutil -extract profile raw -o - "$PRIVATE_RUNTIME/runtime.json")" == shaders && \
   "$(plutil -extract target raw -o - "$PRIVATE_RUNTIME/runtime.json")" == "macos-$RUNTIME_ARCH" ]] || {
  echo "Full shader runtime for macOS $RUNTIME_ARCH required" >&2; exit 1;
}
RUSTFLAGS="${RUSTFLAGS:-} --remap-path-prefix=$HOME=/build --remap-path-prefix=$ROOT=." cargo build --locked --release --bins --target "$RUST_TARGET" --manifest-path "$HERE/Cargo.toml"
BINARIES="$HERE/target/$RUST_TARGET/release"

APP="$ROOT/work/installer-packages/macos/Strahlender Installer.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"
cp "$BINARIES/strahlender-xnu-installer" "$MACOS/strahlender-xnu-installer"
cp "$BINARIES/ips_patch" "$MACOS/ips_patch"
cp "$BINARIES/installer_update" "$MACOS/installer_update"
cp "$BINARIES/installer_setup" "$MACOS/installer_setup"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$RESOURCES/THIRD_PARTY_NOTICES.md"
cp -R "$HERE/assets/lucide" "$RESOURCES/lucide"
cp "$HERE/assets/FIRA-LICENSE" "$HERE/assets/OCTICONS-LICENSE" "$RESOURCES/"
cp "$HERE/vendor/iced_winit/LICENSE" "$RESOURCES/ICED-WINIT-LICENSE"
git -C "$ROOT" rev-parse HEAD > "$RESOURCES/installer-revision"
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
VERSION="$(awk -F '"' '/^version = / {print $2; exit}' "$HERE/Cargo.toml")"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$CONTENTS/Info.plist"
plutil -replace CFBundleVersion -string "$VERSION" "$CONTENTS/Info.plist"
ICON_STAGE="$(mktemp -d "$ROOT/work/installer-icons.XXXXXX")"
"$BINARIES/installer_icons" --output "$ICON_STAGE/artwork"
python3 "$HERE/scripts/package_icons_macos.py" --artwork "$ICON_STAGE/artwork" \
  --app "$APP" --scratch "$ICON_STAGE/native"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
ditto -c -k --keepParent "$APP" "$ROOT/work/installer-packages/macos/installer-macos-$RUNTIME_ARCH.zip"
cd "$ROOT/work/installer-packages/macos"
NATIVE_ZIPS=()
for native in installer-macos-aarch64.zip installer-macos-x86_64.zip; do
  [[ ! -f "$native" ]] || NATIVE_ZIPS+=("$native")
done
shasum -a 256 "${NATIVE_ZIPS[@]}" > SHA256SUMS
printf 'Packaged %s (%s)\n' "$APP" "$PACKAGE_ARCH"
