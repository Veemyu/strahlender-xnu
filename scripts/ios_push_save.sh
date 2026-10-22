#!/usr/bin/env bash
# Places your own save (SaveData.bin) as a drop file in the iPad's app container: Documents/SaveData.bin.
# On the next "Continue" the app imports it into its slot (Documents/Saves/main), backs up the previous slot under
# Documents/Backups/main and remembers the hash of the file (docs/recomp-ios.md). Own code, no third-party code.
#
# Why not directly to Documents/Saves/main/SaveData.bin: devicectl creates missing folders owned by root; the app (mobile)
# may not create a file there, saving would fail. Documents itself belongs to the app, the drop file needs no folder.
#
# Usage:   scripts/ios_push_save.sh [--source FILE] [--bundle-id ID] [--reimport] [--dry-run]
#          --reimport  resets the memo file: even the same file replaces the slot on the next "Continue" (progress gone, backup stays)
#          scripts/ios_push_save.sh --pull [--dest FOLDER]     fetches Saves/main (SaveData.bin, Backup.bin) from the device
# Environment (optional):
#   SAVE_SRC     source file (default: Ryujinx/bis/user/save/0000000000000006/0/SaveData.bin in the repo folder, gitignored)
#   BUNDLE_ID    bundle ID of the app (default: dev.local.xnum0)
#   DEVICE_NAME  part of the device name (default: first connected iPad)
# Flow: check the source (read only; size, SHA-256) → back up the slot on the device (if present) to work/ipad-save-backup/<time>/ →
#   copy the file → fetch it back and compare the SHA-256. The same file is not imported twice (hash memo file of the app),
#   so progress in the slot is kept when called again. Only paths, sizes and hashes are printed, never contents.
#   The team ID is not needed and not printed.
# Prerequisite: device unlocked, paired, app installed (container exists). Sound and volume stay untouched.
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
[[ -n "${COREID:-}" ]] || { echo "No connected, unlocked iPad found." >&2; exit 3; }
echo "Device: ${NAME//_/ }, app: $BUNDLE_ID"

dev_copy_from() { # $1 source in the container, $2 local target (file)
  xcrun devicectl device copy from --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "$1" --destination "$2" --timeout 60 >"$WORK/last.log" 2>&1
}

STAMP="$(date +%Y%m%dT%H%M%S)"

if [[ $PULL -eq 1 ]]; then
  OUT="${DEST:-$ROOT/work/ipad-save-pull/$STAMP}"
  mkdir -p "$OUT"
  for f in SaveData.bin Backup.bin; do
    if dev_copy_from "$SLOT_DIR/$f" "$OUT/$f"; then echo "geholt: $f $(size "$OUT/$f") Byte sha256 $(sha "$OUT/$f")"
    else echo "not present: $SLOT_DIR/$f"; rm -f "$OUT/$f"; fi
  done
  echo "Stored in: $OUT (only under work/, never in the repo)"
  exit 0
fi

[[ -f "$SRC" ]] || { echo "Source missing: $SRC" >&2; exit 2; }
SZ="$(size "$SRC")"
(( SZ > 0 && SZ <= MAX_SIZE )) || { echo "Source has an implausible size: $SZ bytes" >&2; exit 2; }
H="$(sha "$SRC")"
echo "Source: $SZ bytes sha256 $H (read only)"

BK="$ROOT/work/ipad-save-backup/$STAMP"
mkdir -p "$BK"
if dev_copy_from "$SLOT_DIR/SaveData.bin" "$BK/SaveData.bin"; then
  echo "Slot on the device: $(size "$BK/SaveData.bin") bytes sha256 $(sha "$BK/SaveData.bin") (backed up to $BK)"
else
  echo "Slot on the device: none"
  rm -f "$BK/SaveData.bin"; rmdir "$BK" 2>/dev/null || true
fi
if dev_copy_from "$DROP" "$WORK/prev-drop.bin"; then
  echo "Drop file before: $(size "$WORK/prev-drop.bin") bytes sha256 $(sha "$WORK/prev-drop.bin")"
  rm -f "$WORK/prev-drop.bin"
else
  echo "Drop file before: none"
fi

if [[ $DRY -eq 1 ]]; then echo "Dry run: would copy to $DROP."; exit 0; fi

xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source "$SRC" --destination "$DROP" --timeout 120 >"$WORK/last.log" 2>&1 \
  || { tail -n 12 "$WORK/last.log" >&2; echo "Copy failed (app installed? device unlocked?)" >&2; exit 5; }

CHECK="$WORK/verify-$STAMP.bin"
dev_copy_from "$DROP" "$CHECK" || { tail -n 12 "$WORK/last.log" >&2; echo "Fetching back for verification failed" >&2; exit 6; }
AH="$(sha "$CHECK")"; AS="$(size "$CHECK")"
rm -f "$CHECK"
echo "Drop file after: $AS bytes sha256 $AH"
[[ "$AH" == "$H" && "$AS" == "$SZ" ]] || { echo "Checksum does not match!" >&2; exit 7; }
if [[ $REIMPORT -eq 1 ]]; then
  # Empty memo file: the hash of the drop file counts as "new" again, the app replaces the slot (backup first).
  : > "$WORK/empty-marker.txt"
  xcrun devicectl device copy to --device "$COREID" --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "$WORK/empty-marker.txt" --destination "Documents/ImportedDropIn.sha256" --timeout 60 >"$WORK/last.log" 2>&1 \
    || { tail -n 12 "$WORK/last.log" >&2; echo "Resetting the memo file failed" >&2; exit 8; }
  echo "Memo file reset: the slot is replaced on the next \"Continue\"."
fi
echo "OK: $DROP in the container of $BUNDLE_ID; the app imports it on the next \"Continue\" (slot: $SLOT_DIR)."
