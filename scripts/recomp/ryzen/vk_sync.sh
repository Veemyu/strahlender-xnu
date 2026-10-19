#!/bin/bash
# Mac → Ryzen für den Vulkan-Pfad (idempotent, rsync). Überträgt den Arbeitsstand, der für den Bau von rt-bdsp mit NVN_BACKEND=vulkan nötig ist:
#   scripts/recomp (einschließlich rt-bdsp und scripts/recomp/upstream, anders als sync.sh), shader_translator (ohne build/tests),
#   work/recomp/img_gfx (Speicherbilder aus den eigenen NSOs, auf dem Mac mit mkimages.sh erzeugt; hat der Ryzen die NSOs, geht auch dort mkimages.sh)
# Aufruf: vk_sync.sh [--daten]
#   --daten   zusätzlich main.npdm und das RomFS (work/romfs) des eigenen Dumps auf den Ryzen (nur nach ~/xnu-recomp/work, nie ins Repo);
#             nötig, damit das Spiel dort bis zu den ersten Zeichenaufrufen läuft. Ohne Schalter bleiben RomFS und NPDM auf dem Mac.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd "$RZ_REPO"
DATA=0
for a in "$@"; do
  case "$a" in
    --daten) DATA=1;;
    -h|--help) sed -n 2,9p "$0"; exit 0;;
    *) rz_die "Unbekannte Option '$a' (erlaubt: --daten).";;
  esac
done
[ -d scripts/recomp/rt-bdsp ] && [ -d shader_translator ] || rz_die "scripts/recomp/rt-bdsp oder shader_translator fehlt."
big=$(find scripts/recomp shader_translator -type f -size +2M -not -path '*/build/*' | head -3)
[ -z "$big" ] || rz_die "Unerwartet große Dateien (kein Spielinhalt übertragen!): $big"
rz_require
rz_ssh "mkdir -p ~/$RZ_DIR/scripts ~/$RZ_DIR/shader_translator ~/$RZ_DIR/work/recomp"
EXCL=(--exclude='__pycache__' --exclude='*.o' --exclude='*.nso' --exclude='*.img' --exclude='*.keys')
rsync -a --delete "${EXCL[@]}" scripts/recomp/ "$RZ_HOST:$RZ_DIR/scripts/recomp/"
rsync -a --delete --exclude=build --exclude=tests --exclude='__pycache__' shader_translator/ "$RZ_HOST:$RZ_DIR/shader_translator/"
if [ -d work/recomp/img_gfx ]; then
  rz_ssh "mkdir -p ~/$RZ_DIR/work/recomp/img_gfx"
  rsync -a --delete work/recomp/img_gfx/ "$RZ_HOST:$RZ_DIR/work/recomp/img_gfx/"
else
  rz_info "work/recomp/img_gfx fehlt (IMG=work/recomp/img_gfx HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh)"
fi
if [ "$DATA" = 1 ]; then
  [ -f work/exefs/main.npdm ] || rz_die "work/exefs/main.npdm fehlt."
  [ -d work/romfs ] || rz_die "work/romfs fehlt."
  rsync -a work/exefs/main.npdm "$RZ_HOST:$RZ_DIR/work/exefs/"
  rz_info "RomFS (eigener Dump, $(du -sh work/romfs | cut -f1)) → ~/$RZ_DIR/work/romfs …"
  rsync -a work/romfs/ "$RZ_HOST:$RZ_DIR/work/romfs/"
fi
rz_info "Stand übertragen: $(rz_ssh "cd ~/$RZ_DIR && find scripts/recomp/rt-bdsp shader_translator -type f -name '*.[ch]' | sort | xargs sha256sum | sha256sum | cut -c1-10")"
