#!/bin/bash
# Installiert einen bestehenden Spielstand (Ryujinx-Layout) in den Speicherstand-Ordner der BDSP-Laufzeit.
# Quelle: BDSP_SAVE_SRC (Ordner mit SaveData.bin/Backup.bin, z. B. <Ryujinx>/bis/user/save/<id>/0) oder die Zeile
#   BDSP_SAVE_SRC=... in work/local.env. Optional BDSP_SAVE_EXTRA (der Ordner <id> mit ExtraData0): daraus wird die Benutzer-ID
#   gelesen (user_id.hex), die acc:u0 der Laufzeit meldet. Ziel: work/recomp/save (oder BDSP_SAVE_DST) – nie im Repository.
# Ausgabe nur Größen und Hashes. Ein vorhandener Spielstand wandert nach <Ziel>/backup-<Zeit>/.
# Aufruf: install_save.sh
set -euo pipefail
cd "$(dirname "$0")/../../.."
[ -f work/local.env ] && while IFS='=' read -r k v; do
  case "$k" in BDSP_SAVE_SRC|BDSP_SAVE_EXTRA|BDSP_SAVE_DST) [ -n "${!k:-}" ] || export "$k=$v" ;; esac
done < work/local.env
SRC=${BDSP_SAVE_SRC:?BDSP_SAVE_SRC fehlt (Umgebungsvariable oder work/local.env)}
DST=${BDSP_SAVE_DST:-work/recomp/save}
case "$(cd "$(dirname "$DST")" && pwd)/$(basename "$DST")" in
  "$PWD"/work/*) ;;
  *) echo "Ziel muss unter work/ liegen: $DST" >&2; exit 2 ;;
esac
[ -f "$SRC/SaveData.bin" ] || { echo "$SRC/SaveData.bin fehlt" >&2; exit 2; }
hash() { shasum -a 256 "$1" | cut -c1-12; }
mkdir -p "$DST"
if [ -d "$DST/save_1" ] && [ -n "$(ls -A "$DST/save_1" 2>/dev/null)" ]; then
  B="$DST/backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$B"
  mv "$DST/save_1" "$B/save_1"
  echo "Vorgänger gesichert: $B"
fi
mkdir -p "$DST/save_1"
for f in SaveData.bin Backup.bin; do
  [ -f "$SRC/$f" ] || continue
  cp "$SRC/$f" "$DST/save_1/$f"
  echo "$f: $(wc -c < "$DST/save_1/$f") Byte, sha256 $(hash "$DST/save_1/$f")"
done
if [ -n "${BDSP_SAVE_EXTRA:-}" ] && [ -f "$BDSP_SAVE_EXTRA/ExtraData0" ]; then
  # SaveDataExtraData: Attribut ab 0; die Benutzer-ID liegt bei Byte 8..23 (wie im Gast-Attribut)
  dd if="$BDSP_SAVE_EXTRA/ExtraData0" bs=1 skip=8 count=16 2>/dev/null | xxd -p | tr -d '\n' > "$DST/user_id.hex"
  echo "Benutzer-ID aus ExtraData0: sha256 $(printf '%s' "$(cat "$DST/user_id.hex")" | shasum -a 256 | cut -c1-12)"
fi
echo "installiert nach $DST (Option: bdsp_boot --save $DST)"
