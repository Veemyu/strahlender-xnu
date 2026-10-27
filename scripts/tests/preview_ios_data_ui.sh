#!/bin/bash
# Render real UIKit dialogs using synthetic state, without the game runtime or real saves.
set -euo pipefail
cd "$(dirname "$0")/../.."
REPORT="$PWD/work/ios-export-tests"
mkdir -p "$REPORT"
BUILD=$(mktemp -d "$REPORT/menu-ui.XXXXXX")
OWN_SIMULATOR=0
cleanup() {
  rm -rf "$BUILD"
  if [ "$OWN_SIMULATOR" = 1 ]; then
    xcrun simctl shutdown "$SIMULATOR_ID" >/dev/null 2>&1 || true
    xcrun simctl delete "$SIMULATOR_ID" >/dev/null 2>&1 || true
  else
    xcrun simctl uninstall "$SIMULATOR_ID" dev.local.xnubdsp.dialogpreview >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
if [ -z "${SIMULATOR_ID:-}" ]; then
  SIMULATOR_ID=$(xcrun simctl create "Installer Dialog Preview" com.apple.CoreSimulator.SimDeviceType.iPhone-11-Pro-Max "${SIMULATOR_RUNTIME:-com.apple.CoreSimulator.SimRuntime.iOS-26-0}")
  OWN_SIMULATOR=1
  xcrun simctl boot "$SIMULATOR_ID"
fi
xcrun simctl bootstatus "$SIMULATOR_ID" -b > "$REPORT/menu-ui-boot.log" 2>&1
APP="$BUILD/Dialogs.app"
mkdir "$APP"
cat > "$APP/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>dev.local.xnubdsp.dialogpreview</string>
<key>CFBundleName</key><string>Dialogs</string><key>CFBundleExecutable</key><string>Dialogs</string>
<key>CFBundlePackageType</key><string>APPL</string><key>CFBundleVersion</key><string>1</string>
<key>CFBundleShortVersionString</key><string>1</string><key>MinimumOSVersion</key><string>17.0</string>
<key>LSRequiresIPhoneOS</key><true/><key>UIRequiresFullScreen</key><true/>
<key>UIDeviceFamily</key><array><integer>1</integer><integer>2</integer></array>
<key>UISupportedInterfaceOrientations</key><array><string>UIInterfaceOrientationLandscapeRight</string><string>UIInterfaceOrientationLandscapeLeft</string></array>
<key>UILaunchScreen</key><dict/>
</dict></plist>
PLIST
SDK=$(xcrun --sdk iphonesimulator --show-sdk-path)
xcrun --sdk iphonesimulator clang -target arm64-apple-ios17.0-simulator -isysroot "$SDK" \
  -fobjc-arc -Wno-deprecated-declarations -framework UIKit -framework Foundation -framework UniformTypeIdentifiers \
  scripts/tests/ios_data_ui_preview.m scripts/recomp/ios/app/data_manager.m \
  scripts/recomp/ios/app/data_library.m scripts/recomp/ios/app/save_archive.m scripts/recomp/rt-bdsp/save_snapshot.c \
  -o "$APP/Dialogs" > "$REPORT/menu-ui-build.log" 2>&1
codesign --force --sign - "$APP" > "$REPORT/menu-ui-sign.log" 2>&1
xcrun simctl install "$SIMULATOR_ID" "$APP"
for LANGUAGE in de en es pt ru; do
  for SCREEN in menu saveMenu backupMenu; do
    xcrun simctl terminate "$SIMULATOR_ID" dev.local.xnubdsp.dialogpreview >/dev/null 2>&1 || true
    xcrun simctl launch --stdout="$REPORT/menu-ui-${LANGUAGE}-${SCREEN}.log" --stderr="$REPORT/menu-ui-${LANGUAGE}-${SCREEN}.err" \
      "$SIMULATOR_ID" dev.local.xnubdsp.dialogpreview --screen "$SCREEN" --has-save -AppleLanguages "($LANGUAGE)" -AppleLocale "$LANGUAGE" > /dev/null
    sleep 2
    xcrun simctl io "$SIMULATOR_ID" screenshot "$REPORT/menu-ui-${LANGUAGE}-${SCREEN}.png" > /dev/null 2>&1
  done
done
