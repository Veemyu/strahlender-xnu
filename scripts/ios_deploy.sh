#!/usr/bin/env bash
# Baut das von Unity erzeugte Xcode-Projekt, installiert die App auf ein per
# USB verbundenes iPad und startet sie. Eigener Code, kein Fremdcode.
#
# Aufruf:  scripts/ios_deploy.sh [Projektordner] [--no-launch]
# Umgebungsvariablen (alle optional):
#   DEVICE_NAME  Teil des Gerätenamens (Standard: erstes verbundenes iPad)
#   BUNDLE_ID    Bundle-ID der App (Standard: dev.local.xnum0)
#   DERIVED_DATA Ablage für Xcode-Build (Standard: work/builds/ios-derived), DEPLOY_LOG Logdatei
#   CONFIG       Xcode-Konfiguration (Standard: Release)
#   TEAM_ID      Apple-Team-ID; sonst aus work/local.env (gitignored) oder aus dem Projekt
# Voraussetzung: Gerät entsperrt, gekoppelt, Entwicklermodus an. Die Team-ID
# gehört nicht ins Repo und nicht in ProjectSettings.
set -euo pipefail

export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="${1:-$ROOT/work/builds/ios/xnu-m0}"
LAUNCH=1
[[ "${2:-}" == "--no-launch" || "${1:-}" == "--no-launch" ]] && LAUNCH=0
[[ "${1:-}" == "--no-launch" ]] && PROJECT_DIR="$ROOT/work/builds/ios/xnu-m0"
BUNDLE_ID="${BUNDLE_ID:-dev.local.xnum0}"
CONFIG="${CONFIG:-Release}"
DD="${DERIVED_DATA:-$ROOT/work/builds/ios-derived}"
LOG="${DEPLOY_LOG:-$ROOT/work/builds/ios-deploy.log}"
# Lokale, nicht getrackte Einstellungen (z. B. TEAM_ID=...) einlesen.
[[ -f "$ROOT/work/local.env" ]] && source "$ROOT/work/local.env"

[[ -d "$PROJECT_DIR/Unity-iPhone.xcodeproj" ]] || { echo "Xcode-Projekt fehlt: $PROJECT_DIR" >&2; exit 2; }
mkdir -p "$DD"

# Verbundenes iPad suchen (JSON von devicectl, nur Kennungen ausgeben).
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
xcrun devicectl list devices --json-output "$TMP" >/dev/null 2>&1
read -r UDID COREID NAME < <(DEVICE_NAME="${DEVICE_NAME:-}" python3 - "$TMP" <<'EOF'
import json, os, sys
want = os.environ.get("DEVICE_NAME", "").lower()
for d in json.load(open(sys.argv[1]))["result"]["devices"]:
    name = d["deviceProperties"].get("name", "")
    ok = d["connectionProperties"].get("tunnelState") == "connected"
    if ok and d["hardwareProperties"].get("platform") == "iOS" and (want in name.lower() if want else "iPad" in d["hardwareProperties"].get("productType", "") ):
        print(d["hardwareProperties"]["udid"], d["identifier"], name.replace(" ", "_"))
        break
EOF
) || true
[[ -n "${UDID:-}" ]] || { echo "Kein verbundenes, entsperrtes iPad gefunden." >&2; exit 3; }
echo "Gerät: ${NAME//_/ }"

echo "Build ($CONFIG) ... Log: $LOG"
xcodebuild -project "$PROJECT_DIR/Unity-iPhone.xcodeproj" -scheme Unity-iPhone \
  -configuration "$CONFIG" -destination "id=$UDID" -derivedDataPath "$DD" \
  ${TEAM_ID:+DEVELOPMENT_TEAM="$TEAM_ID"} \
  -allowProvisioningUpdates build > "$LOG" 2>&1 || { tail -n 25 "$LOG" >&2; exit 4; }

APP="$(find "$DD/Build/Products" -maxdepth 2 -name '*.app' -path "*iphoneos*" | head -1)"
[[ -n "$APP" ]] || { echo "Gebaute .app nicht gefunden." >&2; exit 5; }
echo "Installiere $(basename "$APP") ..."
xcrun devicectl device install app --device "$COREID" "$APP" >> "$LOG" 2>&1 || { tail -n 15 "$LOG" >&2; exit 6; }

if [[ $LAUNCH -eq 1 ]]; then
  echo "Starte $BUNDLE_ID ..."
  xcrun devicectl device process launch --device "$COREID" --terminate-existing "$BUNDLE_ID" >> "$LOG" 2>&1 \
    || { tail -n 15 "$LOG" >&2; echo "Start fehlgeschlagen (Gerät entsperrt? Profil vertraut?)" >&2; exit 7; }
fi
echo "Fertig."
