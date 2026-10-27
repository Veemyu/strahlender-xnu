#!/bin/bash
# Validate the real app's signing identity/capabilities with a tiny C app. Never install it.
set -euo pipefail
: "${BDSP_IOS_BUILD_DIR:?Set the build directory}"
: "${BDSP_IOS_TEAM_ID:?Choose an Apple development team}"
: "${BDSP_IOS_BUNDLE_ID:?Set the final application identifier}"
: "${BDSP_IOS_UDID:?Choose an iPhone or iPad}"
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
mkdir -p "$BDSP_IOS_BUILD_DIR"
PROBE=$(mktemp -d "$BDSP_IOS_BUILD_DIR/signing-check.XXXXXX")
trap 'rm -rf "$PROBE"' EXIT
mkdir "$PROBE/SigningCheck.xcodeproj"
printf '%s\n' 'int main(void) { return 0; }' > "$PROBE/main.c"
cp "$ROOT/scripts/recomp/ios/app/BDSP.entitlements" "$PROBE/BDSP.entitlements"
cat > "$PROBE/SigningCheck.xcodeproj/project.pbxproj" <<'PROJECT'
// !$*UTF8*$!
{ archiveVersion = 1; classes = {}; objectVersion = 56; objects = {
 AA0000000000000000000001 = { isa = PBXProject; mainGroup = AA0000000000000000000002; productRefGroup = AA0000000000000000000003; buildConfigurationList = AA0000000000000000000010; targets = (AA0000000000000000000004); compatibilityVersion = "Xcode 14.0"; developmentRegion = en; };
 AA0000000000000000000002 = { isa = PBXGroup; sourceTree = "<group>"; children = (AA0000000000000000000021, AA0000000000000000000003); };
 AA0000000000000000000003 = { isa = PBXGroup; name = Products; sourceTree = "<group>"; children = (AA0000000000000000000005); };
 AA0000000000000000000004 = { isa = PBXNativeTarget; name = SigningCheck; productName = SigningCheck; productType = "com.apple.product-type.application"; productReference = AA0000000000000000000005; buildConfigurationList = AA0000000000000000000011; buildPhases = (AA0000000000000000000006); buildRules = (); dependencies = (); };
 AA0000000000000000000005 = { isa = PBXFileReference; explicitFileType = wrapper.application; path = SigningCheck.app; sourceTree = BUILT_PRODUCTS_DIR; };
 AA0000000000000000000006 = { isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; runOnlyForDeploymentPostprocessing = 0; files = (AA0000000000000000000031); };
 AA0000000000000000000010 = { isa = XCConfigurationList; buildConfigurations = (AA0000000000000000000012); defaultConfigurationName = Release; defaultConfigurationIsVisible = 0; };
 AA0000000000000000000011 = { isa = XCConfigurationList; buildConfigurations = (AA0000000000000000000013); defaultConfigurationName = Release; defaultConfigurationIsVisible = 0; };
 AA0000000000000000000012 = { isa = XCBuildConfiguration; name = Release; buildSettings = { SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 17.0; GCC_OPTIMIZATION_LEVEL = 0; }; };
 AA0000000000000000000013 = { isa = XCBuildConfiguration; name = Release; buildSettings = { PRODUCT_NAME = SigningCheck; ARCHS = arm64; TARGETED_DEVICE_FAMILY = "1,2"; CODE_SIGN_STYLE = Automatic; CODE_SIGN_ENTITLEMENTS = BDSP.entitlements; GENERATE_INFOPLIST_FILE = YES; INFOPLIST_KEY_UILaunchScreen_Generation = YES; }; };
 AA0000000000000000000021 = { isa = PBXFileReference; lastKnownFileType = sourcecode.c.c; path = main.c; sourceTree = "<group>"; };
 AA0000000000000000000031 = { isa = PBXBuildFile; fileRef = AA0000000000000000000021; };
 }; rootObject = AA0000000000000000000001; }
PROJECT
LOG="$BDSP_IOS_BUILD_DIR/signing-preflight.log"
echo "Checking Apple signing, provisioning and app entitlements before game-code compilation. No app is installed."
if ! xcodebuild -project "$PROBE/SigningCheck.xcodeproj" -scheme SigningCheck -configuration Release \
    -destination "id=$BDSP_IOS_UDID" -destination-timeout 20 -derivedDataPath "$PROBE/derived" \
    "DEVELOPMENT_TEAM=$BDSP_IOS_TEAM_ID" "PRODUCT_BUNDLE_IDENTIFIER=$BDSP_IOS_BUNDLE_ID" \
    -allowProvisioningUpdates -allowProvisioningDeviceRegistration build > "$LOG" 2>&1; then
    tail -n 45 "$LOG" >&2
    echo "Apple signing preflight failed. Check the selected team and Xcode Accounts before retrying; existing game build outputs were kept." >&2
    exit 10
fi
/usr/bin/codesign --verify --strict "$PROBE/derived/Build/Products/Release-iphoneos/SigningCheck.app"
echo "Apple signing preflight passed."
