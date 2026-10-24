#!/bin/bash
# Isolated native iPhone/iPad build phases for the GUI JSONL driver.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
R=${BDSP_IOS_BUILD_DIR:?Set BDSP_IOS_BUILD_DIR under work/recomp}
case "$R" in "$ROOT/work/recomp/"*) ;; *) echo "iOS build directory must be under work/recomp" >&2; exit 2;; esac
export MODEL=a ORG=0x800000000
export GEN="$R/gen" IMG="$R/img" OBJ="$R/obj"
export BDSP_EXEFS_DIR=${BDSP_EXEFS_DIR:-$ROOT/work/exefs}
export NVN_SRC="$R/nvn-base" BDSP_IOS_NVN_DIR="$R/nvn-ios" BDSP_IOS_RT_DIR="$R/rt"
mkdir -p "$R"
run_script() {
  local script="$1" source; shift
  source=$(cat "$script")
  bash -c "$source" "$script" "$@"
}
gen_hash() {
  { echo "model=$MODEL org=$ORG"
    shasum -a 256 "$BDSP_EXEFS_DIR"/{rtld,main,sdk,subsdk0} scripts/recomp/{eh_gen.py,eh_lsda.py} scripts/recomp/ios/gen32.sh
    [ ! -f "$BDSP_EXEFS_DIR/subsdk1" ] || shasum -a 256 "$BDSP_EXEFS_DIR/subsdk1" "$BDSP_EXEFS_DIR/"*.entries
    find scripts/recomp/upstream/generator -name '*.py' -type f | LC_ALL=C sort | while IFS= read -r file; do shasum -a 256 "$file"; done
  } | shasum -a 256 | cut -c1-64
}
case "${1:-}" in
  gen)
    fingerprint=$(gen_hash)
    if [ -d "$GEN/main" ] && [ "$(cat "$R/.generator-hash" 2>/dev/null || true)" = "$fingerprint" ]; then
      echo "iOS generator: unchanged inputs, using cached C"
    else
      run_script scripts/recomp/ios/gen32.sh gen
      [ "$fingerprint" = "$(gen_hash)" ] || { echo "Generator inputs changed during this build; retry." >&2; exit 4; }
      printf '%s\n' "$fingerprint" > "$R/.generator-hash"
    fi ;;
  compile) run_script scripts/recomp/ios/gen32.sh build ;;
  images) run_script scripts/recomp/ios/gen32.sh img ;;
  runtime)
    for library in avformat avcodec avutil; do
      [ -f "work/ios/ffmpeg-ios/lib/lib${library}.a" ] || { echo "iOS FFmpeg libraries are missing; prepare scripts/recomp/ios/build_ffmpeg_ios.sh first." >&2; exit 10; }
    done
    run_script scripts/recomp/ios/build_rt32.sh ios
    libtool -static -o "$R/rt/libgame.a" "$OBJ"/*.o 2>/dev/null ;;
  package)
    [ -f work/local.env ] && source work/local.env
    [ -n "${TEAM_ID:-}" ] || { echo "Configure an Apple signing team in work/local.env (TEAM_ID)." >&2; exit 10; }
    : "${BDSP_IOS_UDID:?Choose a connected iPhone or iPad}"
    : "${BDSP_IOS_BUNDLE_ID:?Set the application identifier}"
    mkdir -p "$R/res/img32"
    for file in "$IMG"/*.img "$IMG"/*.mod "$IMG"/*.syms.json "$IMG/hle.txt"; do cp "$file" "$R/res/img32/"; done
    cp "$BDSP_EXEFS_DIR/main.npdm" "$R/res/main.npdm"
    xcodebuild -project scripts/recomp/ios/app/BDSP.xcodeproj -scheme BDSP -configuration Release \
      -destination "id=$BDSP_IOS_UDID" -derivedDataPath "$R/derived" \
      DEVELOPMENT_TEAM="$TEAM_ID" PRODUCT_BUNDLE_IDENTIFIER="$BDSP_IOS_BUNDLE_ID" \
      BDSP_RT_DIR="${R#"$ROOT/work/recomp/"}/rt" BDSP_RES_DIR="$R/res" \
      OTHER_LDFLAGS='$(inherited) -framework CoreText -framework AudioToolbox -framework AVFAudio' \
      -allowProvisioningUpdates build > "$R/xcodebuild.log" 2>&1 \
      || { tail -n 35 "$R/xcodebuild.log" >&2; exit 4; }
    APP="$R/derived/Build/Products/Release-iphoneos/BDSP.app"
    ICONARGS=(ios --source "${BDSP_ICON_SOURCE:-work/recomp/icons/source}" --output "$R/icons" --bundle "$APP")
    [ -z "${BDSP_MOD_ROOT:-}" ] || ICONARGS+=(--mod-root "$BDSP_MOD_ROOT" --mod-name "${BDSP_MOD_NAME:-}")
    python3 scripts/recomp/app/game_icons.py "${ICONARGS[@]}"
    python3 scripts/recomp/app/game_icons.py sign-ios --bundle "$APP"
    mkdir -p "$R/export/Payload"
    ditto "$APP" "$R/export/Payload/BDSP.app"
    (cd "$R/export" && ditto -c -k --keepParent Payload "$R/BDSP.ipa")
    echo "Built universal iPhone/iPad app: $APP"
    echo "IPA: $R/BDSP.ipa" ;;
  *) echo "Usage: installer_build.sh gen|compile|images|runtime|package" >&2; exit 2 ;;
esac
