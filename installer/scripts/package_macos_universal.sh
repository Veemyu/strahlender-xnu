#!/usr/bin/env bash
# Join two independently built and tested native installers into one Mac download.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ARM_ZIP="${1:?Usage: package_macos_universal.sh ARM64-ZIP INTEL-ZIP}"
INTEL_ZIP="${2:?Usage: package_macos_universal.sh ARM64-ZIP INTEL-ZIP}"
OUTPUT="$ROOT/work/installer-packages/macos-universal"
APP="$OUTPUT/Strahlender Installer.app"
[[ ! -e "$OUTPUT" ]] || { echo "Output already exists: $OUTPUT" >&2; exit 1; }

verify_zip() {
  local archive="$1" filename expected actual
  filename="$(basename "$archive")"
  expected="$(awk -v name="$filename" '$2 == name {print $1}' "$(dirname "$archive")/SHA256SUMS")"
  actual="$(shasum -a 256 "$archive")"
  [[ ${#expected} == 64 && "$expected" == "${actual%% *}" ]] || {
    echo "Native package checksum mismatch: $filename" >&2; exit 1;
  }
}
verify_zip "$ARM_ZIP"
verify_zip "$INTEL_ZIP"
mkdir -p "$ROOT/work"
STAGE="$(mktemp -d "$ROOT/work/installer-universal.XXXXXX")"
ditto -x -k "$ARM_ZIP" "$STAGE/arm"
ditto -x -k "$INTEL_ZIP" "$STAGE/intel"
ARM_APP="$STAGE/arm/Strahlender Installer.app"
INTEL_APP="$STAGE/intel/Strahlender Installer.app"
for key in CFBundleIdentifier CFBundleShortVersionString CFBundleVersion CFBundleIconFile CFBundleIconName; do
  [[ "$(plutil -extract "$key" raw -o - "$ARM_APP/Contents/Info.plist")" == \
     "$(plutil -extract "$key" raw -o - "$INTEL_APP/Contents/Info.plist")" ]] || {
    echo "Native installer bundle metadata differs: $key" >&2; exit 1;
  }
done
cmp "$ARM_APP/Contents/Resources/installer-revision" "$INTEL_APP/Contents/Resources/installer-revision"
cmp "$ARM_APP/Contents/Resources/installer-icon.svg" "$INTEL_APP/Contents/Resources/installer-icon.svg"
for native_app in "$ARM_APP" "$INTEL_APP"; do
  for icon_resource in Installer.icns Assets.car installer-icon.svg; do
    [[ -s "$native_app/Contents/Resources/$icon_resource" ]] || {
      echo "Missing installer icon resource: $icon_resource" >&2; exit 1;
    }
  done
done
for pair in "arm macos-aarch64" "intel macos-x86_64"; do
  read -r side target <<< "$pair"
  marker="$STAGE/$side/Strahlender Installer.app/Contents/Resources/runtime/runtime.json"
  [[ "$(plutil -extract target raw -o - "$marker")" == "$target" && \
     "$(plutil -extract profile raw -o - "$marker")" == shaders ]] || {
    echo "Invalid private runtime for $target" >&2; exit 1;
  }
done

mkdir -p "$OUTPUT"
ditto "$ARM_APP" "$APP"
for binary in strahlender-xnu-installer ips_patch firmware_import installer_update installer_setup; do
  arm="$ARM_APP/Contents/MacOS/$binary"
  intel="$INTEL_APP/Contents/MacOS/$binary"
  lipo "$arm" -verify_arch arm64
  lipo "$intel" -verify_arch x86_64
  lipo -create "$arm" "$intel" -output "$APP/Contents/MacOS/$binary"
  lipo "$APP/Contents/MacOS/$binary" -verify_arch arm64
  lipo "$APP/Contents/MacOS/$binary" -verify_arch x86_64
done

# Python wheels and standalone Python builds keep their own native libraries and
# configuration. Each universal Rust slice chooses its matching verified profile.
RESOURCES="$APP/Contents/Resources"
mv "$RESOURCES/runtime" "$STAGE/arm-runtime"
mkdir "$RESOURCES/runtime"
mv "$STAGE/arm-runtime" "$RESOURCES/runtime/macos-aarch64"
ditto "$INTEL_APP/Contents/Resources/runtime" "$RESOURCES/runtime/macos-x86_64"

codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
ditto -c -k --keepParent "$APP" "$OUTPUT/installer-macos-universal.zip"
cd "$OUTPUT"
shasum -a 256 installer-macos-universal.zip > SHA256SUMS
printf 'Packaged universal installer: %s\n' "$APP"
