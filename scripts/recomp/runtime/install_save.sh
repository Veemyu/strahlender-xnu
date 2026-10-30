#!/bin/bash
# Installs an existing save (Ryujinx layout) into the save folder of the BDSP runtime.
# Source: BDSP_SAVE_SRC (folder with SaveData.bin/Backup.bin, e.g. <Ryujinx>/bis/user/save/<id>/0) or the line
#   BDSP_SAVE_SRC=... in work/local.env. Optional BDSP_SAVE_EXTRA (the folder <id> with ExtraData0): the user ID that the
#   runtime's acc:u0 reports is read from it (user_id.hex). Target: work/recomp/save (or BDSP_SAVE_DST), never in the repository.
# Output only sizes and hashes. An existing save is moved to <target>/backup-<time>/.
# Usage: install_save.sh
set -euo pipefail
cd "$(dirname "$0")/../../.."
[ -f work/local.env ] && while IFS='=' read -r k v; do
  case "$k" in BDSP_SAVE_SRC|BDSP_SAVE_EXTRA|BDSP_SAVE_DST) [ -n "${!k:-}" ] || export "$k=$v" ;; esac
done < work/local.env
SRC=${BDSP_SAVE_SRC:?BDSP_SAVE_SRC missing (environment variable or work/local.env)}
DST=${BDSP_SAVE_DST:-work/recomp/save}
case "$(cd "$(dirname "$DST")" && pwd)/$(basename "$DST")" in
  "$PWD"/work/*) ;;
  *) echo "Target must be under work/: $DST" >&2; exit 2 ;;
esac
[ -f "$SRC/SaveData.bin" ] || { echo "$SRC/SaveData.bin missing" >&2; exit 2; }
hash() { shasum -a 256 "$1" | cut -c1-12; }
mkdir -p "$DST"
if [ -d "$DST/save_1" ] && [ -n "$(ls -A "$DST/save_1" 2>/dev/null)" ]; then
  B="$DST/backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$B"
  mv "$DST/save_1" "$B/save_1"
  echo "Previous save backed up: $B"
fi
mkdir -p "$DST/save_1"
for f in SaveData.bin Backup.bin; do
  [ -f "$SRC/$f" ] || continue
  cp "$SRC/$f" "$DST/save_1/$f"
  echo "$f: $(wc -c < "$DST/save_1/$f") bytes, sha256 $(hash "$DST/save_1/$f")"
done
if [ -n "${BDSP_SAVE_EXTRA:-}" ] && [ -f "$BDSP_SAVE_EXTRA/ExtraData0" ]; then
  # SaveDataExtraData: attribute from 0; the user ID is at bytes 8..23 (as in the guest attribute)
  dd if="$BDSP_SAVE_EXTRA/ExtraData0" bs=1 skip=8 count=16 2>/dev/null | xxd -p | tr -d '\n' > "$DST/user_id.hex"
  echo "User ID from ExtraData0: sha256 $(printf '%s' "$(cat "$DST/user_id.hex")" | shasum -a 256 | cut -c1-12)"
fi
echo "installed to $DST (option: bdsp_boot --save $DST)"
