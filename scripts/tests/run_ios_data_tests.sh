#!/bin/bash
# Native host tests, optionally repeated in a separate, save-free device app.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$PWD
REPORT=work/ios-export-tests
mkdir -p "$REPORT"
case "${1:-host}" in
  host)
    BUILD=$(mktemp -d "$REPORT/native-host.XXXXXX")
    trap 'rm -rf "$BUILD"' EXIT
    /usr/bin/clang -O1 -g -fobjc-arc -Wno-deprecated-declarations -DBDSP_SAVE_FAULT_TESTS \
      -fsanitize=address,undefined -fno-omit-frame-pointer -framework Foundation \
      scripts/recomp/ios/app/test_data_store.m scripts/recomp/ios/app/data_library.m \
      scripts/recomp/ios/app/save_archive.m scripts/recomp/runtime/save_snapshot.c -o "$BUILD/tests"
    "$BUILD/tests" ;;
  device)
    : "${2:?Usage: run_ios_data_tests.sh device DEVICE_ID (TEAM_ID in private environment)}"
    : "${TEAM_ID:?Set TEAM_ID in the private environment for this isolated test app}"
    BUILD=$(mktemp -d "$REPORT/native-device.XXXXXX")
    trap 'rm -rf "$BUILD"' EXIT
    mkdir "$BUILD/DataTests.xcodeproj"
    cat > "$BUILD/DataTests.xcodeproj/project.pbxproj" <<'PROJECT'
// !$*UTF8*$!
{ archiveVersion = 1; classes = {}; objectVersion = 56; objects = {
 AA0000000000000000000001 = { isa = PBXProject; mainGroup = AA0000000000000000000002; productRefGroup = AA0000000000000000000003; buildConfigurationList = AA0000000000000000000010; targets = (AA0000000000000000000004); compatibilityVersion = "Xcode 14.0"; developmentRegion = en; };
 AA0000000000000000000002 = { isa = PBXGroup; sourceTree = "<group>"; children = (AA0000000000000000000021, AA0000000000000000000022, AA0000000000000000000023, AA0000000000000000000024, AA0000000000000000000003); };
 AA0000000000000000000003 = { isa = PBXGroup; name = Products; sourceTree = "<group>"; children = (AA0000000000000000000005); };
 AA0000000000000000000004 = { isa = PBXNativeTarget; name = DataTests; productName = DataTests; productType = "com.apple.product-type.application"; productReference = AA0000000000000000000005; buildConfigurationList = AA0000000000000000000011; buildPhases = (AA0000000000000000000006); buildRules = (); dependencies = (); };
 AA0000000000000000000005 = { isa = PBXFileReference; explicitFileType = wrapper.application; path = DataTests.app; sourceTree = BUILT_PRODUCTS_DIR; };
 AA0000000000000000000006 = { isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; runOnlyForDeploymentPostprocessing = 0; files = (AA0000000000000000000031, AA0000000000000000000032, AA0000000000000000000033, AA0000000000000000000034); };
 AA0000000000000000000010 = { isa = XCConfigurationList; buildConfigurations = (AA0000000000000000000012); defaultConfigurationName = Release; defaultConfigurationIsVisible = 0; };
 AA0000000000000000000011 = { isa = XCConfigurationList; buildConfigurations = (AA0000000000000000000013); defaultConfigurationName = Release; defaultConfigurationIsVisible = 0; };
 AA0000000000000000000012 = { isa = XCBuildConfiguration; name = Release; buildSettings = { SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 17.0; CLANG_ENABLE_OBJC_ARC = YES; GCC_OPTIMIZATION_LEVEL = 1; }; };
 AA0000000000000000000013 = { isa = XCBuildConfiguration; name = Release; buildSettings = { PRODUCT_NAME = DataTests; PRODUCT_BUNDLE_IDENTIFIER = dev.local.xnubdsp.datatests; ARCHS = arm64; TARGETED_DEVICE_FAMILY = "1,2"; CODE_SIGN_STYLE = Automatic; GENERATE_INFOPLIST_FILE = YES; INFOPLIST_KEY_CFBundleDisplayName = "Game Data Tests"; INFOPLIST_KEY_UILaunchScreen_Generation = YES; OTHER_LDFLAGS = ("-framework", UIKit, "-framework", Foundation); }; };
 AA0000000000000000000021 = { isa = PBXFileReference; lastKnownFileType = sourcecode.c.objc; path = "../../../scripts/tests/ios_data_test_app.m"; sourceTree = SOURCE_ROOT; };
 AA0000000000000000000022 = { isa = PBXFileReference; lastKnownFileType = sourcecode.c.objc; path = "../../../scripts/recomp/ios/app/data_library.m"; sourceTree = SOURCE_ROOT; };
 AA0000000000000000000023 = { isa = PBXFileReference; lastKnownFileType = sourcecode.c.objc; path = "../../../scripts/recomp/ios/app/save_archive.m"; sourceTree = SOURCE_ROOT; };
 AA0000000000000000000024 = { isa = PBXFileReference; lastKnownFileType = sourcecode.c.c; path = "../../../scripts/recomp/runtime/save_snapshot.c"; sourceTree = SOURCE_ROOT; };
 AA0000000000000000000031 = { isa = PBXBuildFile; fileRef = AA0000000000000000000021; };
 AA0000000000000000000032 = { isa = PBXBuildFile; fileRef = AA0000000000000000000022; };
 AA0000000000000000000033 = { isa = PBXBuildFile; fileRef = AA0000000000000000000023; };
 AA0000000000000000000034 = { isa = PBXBuildFile; fileRef = AA0000000000000000000024; };
 }; rootObject = AA0000000000000000000001; }
PROJECT
    xcodebuild -project "$BUILD/DataTests.xcodeproj" -scheme DataTests -configuration Release \
      -destination "id=$2" -derivedDataPath "$BUILD/derived" DEVELOPMENT_TEAM="$TEAM_ID" \
      GCC_PREPROCESSOR_DEFINITIONS=BDSP_SAVE_FAULT_TESTS=1 -allowProvisioningUpdates build > "$REPORT/device-tests-build.log" 2>&1
    xcrun devicectl device install app --device "$2" "$BUILD/derived/Build/Products/Release-iphoneos/DataTests.app" > "$REPORT/device-tests-install.log" 2>&1
    xcrun devicectl device process launch --device "$2" --terminate-existing --console dev.local.xnubdsp.datatests > "$REPORT/device-tests-run.log" 2>&1
    rm -f "$REPORT/device-tests-result.txt"
    xcrun devicectl device copy from --device "$2" --domain-type appDataContainer --domain-identifier dev.local.xnubdsp.datatests \
      --source Documents/result.txt --destination "$REPORT/device-tests-result.txt" > "$REPORT/device-tests-copy.log" 2>&1
    cat "$REPORT/device-tests-result.txt"
    xcrun devicectl device uninstall app --device "$2" dev.local.xnubdsp.datatests > "$REPORT/device-tests-uninstall.log" 2>&1 ;;
  *) echo "Usage: run_ios_data_tests.sh host | device DEVICE_ID" >&2; exit 2 ;;
esac
