#!/usr/bin/env bash
# Builds the iPadOS app of the recompilation (memory model B), installs it on the paired iPad, starts it and fetches files.
# Own code; pattern like scripts/ios_push_save.sh. The team ID comes from work/local.env (TEAM_ID=..., gitignored)
# and is never printed or stored.
#
# Usage:   deploy_ios.sh build            build runtime library, libgame.a (from work/recomp/obj32), resources and app (xcodebuild)
#          deploy_ios.sh install          install the app on the iPad
#          deploy_ios.sh run [seconds]    start (--console), log to work/builds/ipad-recomp-<time>.log; without a time until Ctrl-C
#          deploy_ios.sh data             copy RomFS (work/romfs) to Documents/GameData/romfs (once, about 4.7 GB)
#          deploy_ios.sh save             put SaveData.bin/Backup.bin/user_id.hex from work/recomp/save into Documents/ (the app imports them)
#          deploy_ios.sh shots            fetch Documents/Shots to work/visual/ipad-recomp/
#          deploy_ios.sh files [path]     file list of the container (default Documents)
# Environment: DEVICE_NAME (part of the device name), BUNDLE_ID (default dev.local.xnubdsp), RUN_ENV (JSON for --environment-variables)
set -euo pipefail
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
[[ -f work/local.env ]] && source work/local.env
BUNDLE_ID="${BUNDLE_ID:-dev.local.xnubdsp}"
DD="$ROOT/work/builds/ios-recomp-derived"
RT=work/recomp/ios-rt
RES=work/ios/res
mkdir -p work/builds work/visual/ipad-recomp work/ios

# RomFS manifest (file count and total size of work/romfs). If it is on the iPad, the state is complete.
romfs_manifest() {
  python3 - > work/ios/romfs.manifest <<'EOF'
import os
c = s = 0
for dp, _, fn in os.walk("work/romfs"):
    for f in fn:
        c += 1
        s += os.path.getsize(os.path.join(dp, f))
print(f"{c} {s}")
EOF
}
# Copies RomFS completely (replaces the folder so no orphaned files remain) and the manifest.
romfs_copy() {
  echo "Copying work/romfs to Documents/GameData/romfs (takes a while) ..."
  romfs_manifest
  xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source work/romfs --destination Documents/GameData/romfs --remove-existing-content true 2>&1 | tail -n 5
  xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source work/ios/romfs.manifest --destination Documents/GameData/romfs.manifest > /dev/null 2>&1
}
# Checks the manifest on the iPad and copies RomFS only if it is missing or does not match.
romfs_ensure() {
  romfs_manifest
  rm -f work/ios/romfs.device.manifest
  xcrun devicectl device copy from --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source Documents/GameData/romfs.manifest --destination work/ios/romfs.device.manifest > /dev/null 2>&1 || true
  if [[ -f work/ios/romfs.device.manifest ]] && cmp -s work/ios/romfs.device.manifest work/ios/romfs.manifest; then
    echo "RomFS on the iPad is up to date."
  else
    echo "RomFS is missing or outdated on the iPad."
    romfs_copy
  fi
}

device() {
  local tmp="$ROOT/work/ios/devices.json"
  xcrun devicectl list devices --json-output "$tmp" > /dev/null 2>&1 || true
  read -r UDID COREID NAME < <(DEVICE_NAME="${DEVICE_NAME:-}" python3 - "$tmp" <<'EOF'
import json, os, sys
want = os.environ.get("DEVICE_NAME", "").lower()
for d in json.load(open(sys.argv[1]))["result"]["devices"]:
    name = d["deviceProperties"].get("name", "")
    ok = d["connectionProperties"].get("tunnelState") == "connected"
    if ok and d["hardwareProperties"].get("platform") == "iOS" and (want in name.lower() if want else "iPad" in d["hardwareProperties"].get("productType", "")):
        print(d["hardwareProperties"]["udid"], d["identifier"], name.replace(" ", "_"))
        break
EOF
) || true
  [[ -n "${UDID:-}" ]] || { echo "No connected, unlocked iPad found." >&2; exit 3; }
}

case "${1:-}" in
  build)
    scripts/recomp/ios/build_rt32.sh ios
    rm -f "$RT/libgame.a"
    libtool -static -o "$RT/libgame.a" work/recomp/obj32/*.o 2> /dev/null
    rm -rf "$RES"; mkdir -p "$RES/img32"
    for f in work/recomp/img32/*.img work/recomp/img32/*.mod work/recomp/img32/*.syms.json work/recomp/img32/hle.txt; do cp "$f" "$RES/img32/"; done
    cp work/exefs/main.npdm "$RES/main.npdm"
    device
    xcodebuild -project scripts/recomp/ios/app/BDSP.xcodeproj -scheme BDSP -configuration Release -destination "id=$UDID" \
      -derivedDataPath "$DD" ${TEAM_ID:+DEVELOPMENT_TEAM="$TEAM_ID"} -allowProvisioningUpdates OTHER_LDFLAGS='$(inherited) -framework CoreText -framework AudioToolbox -framework AVFAudio' build > work/builds/ios-recomp-xcodebuild.log 2>&1 \
      || { tail -n 30 work/builds/ios-recomp-xcodebuild.log >&2; exit 4; }
    echo "built:$(find "$DD/Build/Products" -maxdepth 2 -name 'BDSP.app' | head -1)"
    # The Xcode build phase puts the shader cache, metallibs and pipelines.bin into the bundle (app/copy_bundle_resources.sh)
    APPB="$(find "$DD/Build/Products" -maxdepth 2 -name 'BDSP.app' -path '*iphoneos*' | head -1)"
    python3 scripts/recomp/app/game_icons.py ios --source "${BDSP_ICON_SOURCE:-work/recomp/icons/source}" \
      --output work/ios/icons --bundle "$APPB"
    python3 scripts/recomp/app/game_icons.py sign-ios --bundle "$APPB"
    ;;
  build-stub)   # probe build without runtime and guest code: device data, 4 GiB window, Metal buffer (container for the data copy)
    mkdir -p "$RES"
    device
    xcodebuild -project scripts/recomp/ios/app/BDSP.xcodeproj -scheme BDSP -configuration Release -destination "id=$UDID" \
      -derivedDataPath "$DD" ${TEAM_ID:+DEVELOPMENT_TEAM="$TEAM_ID"} -allowProvisioningUpdates GCC_PREPROCESSOR_DEFINITIONS='BDSP_STUB=1' \
      OTHER_LDFLAGS='-framework UIKit -framework Foundation -framework CoreGraphics -framework Metal -framework MetalFX -framework GameController -framework QuartzCore -framework CoreText -framework AVFAudio' build > work/builds/ios-recomp-xcodebuild.log 2>&1 \
      || { tail -n 30 work/builds/ios-recomp-xcodebuild.log >&2; exit 4; }
    echo "Sondenbau gebaut"
    ;;
  install)
    device
    APP="$(find "$DD/Build/Products" -maxdepth 2 -name 'BDSP.app' -path '*iphoneos*' | head -1)"
    [[ -n "$APP" ]] || { echo "BDSP.app missing (deploy_ios.sh build)" >&2; exit 5; }
    xcrun devicectl device install app --device "$COREID" "$APP" 2>&1 | tail -n 4
    romfs_ensure
    ;;
  run)
    device
    romfs_ensure
    LOG="work/builds/ipad-recomp-$(date +%Y%m%d-%H%M%S).log"
    echo "Log: $LOG"
    ENVJ="${RUN_ENV:-}"
    [[ -n "$ENVJ" ]] || ENVJ='{"BDSP_TIMEOUT":"86400"}'
    if [[ -n "${2:-}" ]]; then   # time-limited run: end the process on the device after N seconds (devicectl then aborts with it)
      (
        sleep "$2"
        P="$(xcrun devicectl device info processes --device "$COREID" --json-output "$ROOT/work/ios/procs.json" > /dev/null 2>&1; python3 - "$ROOT/work/ios/procs.json" <<'EOF'
import json, sys
try:
    for p in json.load(open(sys.argv[1]))["result"]["runningProcesses"]:
        if "BDSP.app" in p.get("executable", ""):
            print(p["processIdentifier"]); break
except Exception:
    pass
EOF
)"
        [[ -n "$P" ]] && xcrun devicectl device process terminate --device "$COREID" --pid "$P" > /dev/null 2>&1
      ) &
    fi
    xcrun devicectl device process launch --device "$COREID" --terminate-existing --console --environment-variables "$ENVJ" "$BUNDLE_ID" > "$LOG" 2>&1 || true
    tail -n 5 "$LOG"
    ;;
  data)
    device
    romfs_copy
    ;;
  save)
    device
    for f in SaveData.bin Backup.bin; do
      [[ -f work/recomp/save/save_1/$f ]] && xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
        --source "work/recomp/save/save_1/$f" --destination "Documents/$f" 2>&1 | tail -n 1
    done
    [[ -f work/recomp/save/user_id.hex ]] && xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
      --source work/recomp/save/user_id.hex --destination Documents/user_id.hex 2>&1 | tail -n 1
    ;;
  shots)
    device
    xcrun devicectl device copy from --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
      --source Documents/Shots --destination work/visual/ipad-recomp 2>&1 | tail -n 3
    ;;
  files)
    device
    xcrun devicectl device info files --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" --subdirectory "${2:-Documents}" 2>&1 | tail -n 40
    ;;
  *) awk 'NR > 1 && /^set -euo/ {exit} NR > 1 {sub(/^# ?/, ""); print}' "$0"; exit 2 ;;
esac
