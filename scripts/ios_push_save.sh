#!/usr/bin/env bash
# Legt den eigenen Spielstand (SaveData.bin) als Ablage-Datei in den App-Container des iPads: Documents/SaveData.bin.
# Beim nächsten „Weiter“ importiert die App sie in ihren Slot (Documents/Saves/main), sichert den bisherigen Slot unter
# Documents/Backups/main und merkt sich den Hash der Datei (docs/recomp-ios.md). Eigener Code, kein Fremdcode.
#
# Warum nicht direkt nach Documents/Saves/main/SaveData.bin: devicectl legt fehlende Ordner mit Besitzer root an; die App (mobile)
# darf dort keine Datei anlegen, Speichern schlüge fehl. Documents selbst gehört der App, die Ablage-Datei braucht keinen Ordner.
#
# Aufruf:  scripts/ios_push_save.sh [--source DATEI] [--bundle-id ID] [--reimport] [--dry-run]
#          --reimport  setzt die Merkdatei zurück: auch dieselbe Datei ersetzt den Slot beim nächsten „Weiter“ (Fortschritt weg, Backup bleibt)
#          scripts/ios_push_save.sh --pull [--dest ORDNER]     holt Saves/main (SaveData.bin, Backup.bin) vom Gerät
# Umgebung (optional):
#   SAVE_SRC     Quelldatei (Standard: Ryujinx/bis/user/save/0000000000000006/0/SaveData.bin im Repo-Ordner, gitignoriert)
#   BUNDLE_ID    Bundle-ID der App (Standard: dev.local.xnum0)
#   DEVICE_NAME  Teil des Gerätenamens (Standard: erstes verbundenes iPad)
# Ablauf: Quelle prüfen (nur lesen; Größe, SHA-256) → den Slot auf dem Gerät (falls vorhanden) nach work/ipad-save-backup/<Zeit>/ sichern →
#   Datei kopieren → zurückholen und SHA-256 vergleichen. Dieselbe Datei wird nicht zweimal importiert (Hash-Merkdatei der App),
#   Fortschritt im Slot bleibt also bei erneutem Aufruf erhalten. Ausgegeben werden nur Pfade, Größen und Hashes, nie Inhalte.
#   Die Team-ID wird nicht gebraucht und nicht ausgegeben.
# Voraussetzung: Gerät entsperrt, gekoppelt, App installiert (Container existiert). Ton und Lautstärke bleiben unberührt.
set -euo pipefail

export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$ROOT/work/local.env" ]] && source "$ROOT/work/local.env"
SRC="${SAVE_SRC:-$ROOT/Ryujinx/bis/user/save/0000000000000006/0/SaveData.bin}"
BUNDLE_ID="${BUNDLE_ID:-dev.local.xnum0}"
SLOT_DIR="Documents/Saves/main"
DROP="Documents/SaveData.bin"
DRY=0 PULL=0 DEST="" REIMPORT=0
MAX_SIZE=1048576

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SRC="$2"; shift 2 ;;
    --bundle-id) BUNDLE_ID="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --reimport) REIMPORT=1; shift ;;
    --pull) PULL=1; shift ;;
    --dest) DEST="$2"; shift 2 ;;
    -h|--help) awk 'NR > 1 && /^set -euo/ {exit} NR > 1 {sub(/^# ?/, ""); print}' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
done

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
size() { stat -f %z "$1"; }

WORK="$ROOT/work/ipad-save"
mkdir -p "$WORK"
TMPJ="$WORK/devices.json"
xcrun devicectl list devices --json-output "$TMPJ" >/dev/null 2>&1 || true
read -r COREID NAME < <(DEVICE_NAME="${DEVICE_NAME:-}" python3 - "$TMPJ" <<'EOF'
import json, os, sys
want = os.environ.get("DEVICE_NAME", "").lower()
try:
    devices = json.load(open(sys.argv[1]))["result"]["devices"]
except Exception:
    devices = []
for d in devices:
    name = d["deviceProperties"].get("name", "")
    ok = d["connectionProperties"].get("tunnelState") == "connected"
    if ok and d["hardwareProperties"].get("platform") == "iOS" and (want in name.lower() if want else "iPad" in d["hardwareProperties"].get("productType", "")):
        print(d["identifier"], name.replace(" ", "_"))
        break
EOF
) || true
rm -f "$TMPJ"
[[ -n "${COREID:-}" ]] || { echo "Kein verbundenes, entsperrtes iPad gefunden." >&2; exit 3; }
echo "Gerät: ${NAME//_/ }, App: $BUNDLE_ID"

dev_copy_from() { # $1 Quelle im Container, $2 lokales Ziel (Datei)
  xcrun devicectl device copy from --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "$1" --destination "$2" --timeout 60 >"$WORK/last.log" 2>&1
}

STAMP="$(date +%Y%m%dT%H%M%S)"

if [[ $PULL -eq 1 ]]; then
  OUT="${DEST:-$ROOT/work/ipad-save-pull/$STAMP}"
  mkdir -p "$OUT"
  for f in SaveData.bin Backup.bin; do
    if dev_copy_from "$SLOT_DIR/$f" "$OUT/$f"; then echo "geholt: $f $(size "$OUT/$f") Byte sha256 $(sha "$OUT/$f")"
    else echo "nicht vorhanden: $SLOT_DIR/$f"; rm -f "$OUT/$f"; fi
  done
  echo "Ablage: $OUT (nur unter work/, nie ins Repo)"
  exit 0
fi

[[ -f "$SRC" ]] || { echo "Quelle fehlt: $SRC" >&2; exit 2; }
SZ="$(size "$SRC")"
(( SZ > 0 && SZ <= MAX_SIZE )) || { echo "Quelle hat unplausible Größe: $SZ Byte" >&2; exit 2; }
H="$(sha "$SRC")"
echo "Quelle: $SZ Byte sha256 $H (nur gelesen)"

BK="$ROOT/work/ipad-save-backup/$STAMP"
mkdir -p "$BK"
if dev_copy_from "$SLOT_DIR/SaveData.bin" "$BK/SaveData.bin"; then
  echo "Slot auf dem Gerät: $(size "$BK/SaveData.bin") Byte sha256 $(sha "$BK/SaveData.bin") (gesichert in $BK)"
else
  echo "Slot auf dem Gerät: keiner"
  rm -f "$BK/SaveData.bin"; rmdir "$BK" 2>/dev/null || true
fi
if dev_copy_from "$DROP" "$WORK/prev-drop.bin"; then
  echo "Ablage-Datei vorher: $(size "$WORK/prev-drop.bin") Byte sha256 $(sha "$WORK/prev-drop.bin")"
  rm -f "$WORK/prev-drop.bin"
else
  echo "Ablage-Datei vorher: keine"
fi

if [[ $DRY -eq 1 ]]; then echo "Trockenlauf: würde nach $DROP kopieren."; exit 0; fi

xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source "$SRC" --destination "$DROP" --timeout 120 >"$WORK/last.log" 2>&1 \
  || { tail -n 12 "$WORK/last.log" >&2; echo "Kopieren fehlgeschlagen (App installiert? Gerät entsperrt?)" >&2; exit 5; }

CHECK="$WORK/verify-$STAMP.bin"
dev_copy_from "$DROP" "$CHECK" || { tail -n 12 "$WORK/last.log" >&2; echo "Rückholen zur Prüfung fehlgeschlagen" >&2; exit 6; }
AH="$(sha "$CHECK")"; AS="$(size "$CHECK")"
rm -f "$CHECK"
echo "Ablage-Datei nachher: $AS Byte sha256 $AH"
[[ "$AH" == "$H" && "$AS" == "$SZ" ]] || { echo "Prüfsumme stimmt nicht überein!" >&2; exit 7; }
if [[ $REIMPORT -eq 1 ]]; then
  # Leere Merkdatei: der Hash der Ablage-Datei gilt wieder als „neu“, die App ersetzt den Slot (Backup vorher).
  : > "$WORK/empty-marker.txt"
  xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "$WORK/empty-marker.txt" --destination "Documents/ImportedDropIn.sha256" --timeout 60 >"$WORK/last.log" 2>&1 \
    || { tail -n 12 "$WORK/last.log" >&2; echo "Merkdatei zurücksetzen fehlgeschlagen" >&2; exit 8; }
  echo "Merkdatei zurückgesetzt: der Slot wird beim nächsten „Weiter“ ersetzt."
fi
echo "OK: $DROP im Container von $BUNDLE_ID; die App importiert sie beim nächsten „Weiter“ (Slot: $SLOT_DIR)."
