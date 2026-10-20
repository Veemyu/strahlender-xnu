#!/usr/bin/env bash
# Baut die iPadOS-App der Rekompilation (Speichermodell B), installiert sie auf das gekoppelte iPad, startet sie und holt Dateien.
# Eigener Code; Muster wie scripts/ios_push_save.sh. Die Team-ID kommt aus work/local.env (TEAM_ID=..., gitignoriert)
# und wird nie ausgegeben oder gespeichert.
#
# Aufruf:  deploy_ios.sh build            Laufzeitbibliothek, libgame.a (aus work/recomp/obj32), Ressourcen und App bauen (xcodebuild)
#          deploy_ios.sh install          App auf das iPad installieren
#          deploy_ios.sh run [Sekunden]   starten (--console), Log nach work/builds/ipad-recomp-<Zeit>.log; ohne Zeitangabe bis Ctrl-C
#          deploy_ios.sh data             RomFS (work/romfs) nach Documents/GameData/romfs kopieren (einmalig, ca. 4,7 GB)
#          deploy_ios.sh save             SaveData.bin/Backup.bin/user_id.hex aus work/recomp/save nach Documents/ legen (die App importiert sie)
#          deploy_ios.sh shots            Documents/Shots nach work/visual/ipad-recomp/ holen
#          deploy_ios.sh files [Pfad]     Dateiliste des Containers (Standard Documents)
# Umgebung: DEVICE_NAME (Teil des Gerätenamens), BUNDLE_ID (Standard dev.local.xnubdsp), RUN_ENV (JSON für --environment-variables)
set -euo pipefail
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
[[ -f work/local.env ]] && source work/local.env
BUNDLE_ID="${BUNDLE_ID:-dev.local.xnubdsp}"
DD="$ROOT/work/builds/ios-recomp-derived"
RT=work/recomp/ios-rt
RES=work/ios/res
mkdir -p work/builds work/visual/ipad-recomp

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
  [[ -n "${UDID:-}" ]] || { echo "Kein verbundenes, entsperrtes iPad gefunden." >&2; exit 3; }
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
      -derivedDataPath "$DD" ${TEAM_ID:+DEVELOPMENT_TEAM="$TEAM_ID"} -allowProvisioningUpdates build > work/builds/ios-recomp-xcodebuild.log 2>&1 \
      || { tail -n 30 work/builds/ios-recomp-xcodebuild.log >&2; exit 4; }
    echo "gebaut: $(find "$DD/Build/Products" -maxdepth 2 -name 'BDSP.app' | head -1)"
    ;;
  build-stub)   # Sondenbau ohne Laufzeit und Gastcode: Gerätedaten, 4-GiB-Fenster, Metal-Puffer (Container für die Datenkopie)
    mkdir -p "$RES"
    device
    xcodebuild -project scripts/recomp/ios/app/BDSP.xcodeproj -scheme BDSP -configuration Release -destination "id=$UDID" \
      -derivedDataPath "$DD" ${TEAM_ID:+DEVELOPMENT_TEAM="$TEAM_ID"} -allowProvisioningUpdates GCC_PREPROCESSOR_DEFINITIONS='BDSP_STUB=1' \
      OTHER_LDFLAGS='-framework UIKit -framework Foundation -framework CoreGraphics -framework Metal -framework MetalFX -framework GameController -framework QuartzCore' build > work/builds/ios-recomp-xcodebuild.log 2>&1 \
      || { tail -n 30 work/builds/ios-recomp-xcodebuild.log >&2; exit 4; }
    echo "Sondenbau gebaut"
    ;;
  install)
    device
    APP="$(find "$DD/Build/Products" -maxdepth 2 -name 'BDSP.app' -path '*iphoneos*' | head -1)"
    [[ -n "$APP" ]] || { echo "BDSP.app fehlt (deploy_ios.sh build)" >&2; exit 5; }
    xcrun devicectl device install app --device "$COREID" "$APP" 2>&1 | tail -n 4
    ;;
  run)
    device
    LOG="work/builds/ipad-recomp-$(date +%Y%m%d-%H%M%S).log"
    echo "Log: $LOG"
    ENVJ="${RUN_ENV:-}"
    [[ -n "$ENVJ" ]] || ENVJ='{"BDSP_TIMEOUT":"86400"}'
    if [[ -n "${2:-}" ]]; then   # zeitbegrenzter Lauf: nach N Sekunden den Prozess auf dem Gerät beenden (devicectl bricht dann mit ab)
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
    echo "Kopiere work/romfs nach Documents/GameData/romfs (dauert) ..."
    xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
      --source work/romfs --destination Documents/GameData/romfs --remove-existing-content true 2>&1 | tail -n 5
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
