#!/bin/bash
# Mac → Linux host for the Vulkan path (idempotent, rsync). Transfers the working state needed to build rt-bdsp with NVN_BACKEND=vulkan:
#   scripts/recomp (including rt-bdsp and scripts/recomp/upstream, unlike sync.sh), shader_translator (without build/tests),
#   work/recomp/img_gfx (memory images from your own NSOs, created on the Mac with mkimages.sh; if the Linux host has the NSOs, mkimages.sh also works there)
# Usage: vk_sync.sh [--daten]
#   --daten   additionally main.npdm and the RomFS (work/romfs) of your own dump to the Linux host (only into ~/xnu-recomp/work, never into the repo);
#             needed so the game runs there up to the first draw calls. Without the switch, RomFS and NPDM stay on the Mac.
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
[ -d scripts/recomp/rt-bdsp ] && [ -d shader_translator ] || rz_die "scripts/recomp/rt-bdsp or shader_translator is missing."
big=$(find scripts/recomp shader_translator -type f -size +2M -not -path '*/build/*' | head -3)
[ -z "$big" ] || rz_die "Unexpectedly large files (no game content transferred!): $big"
rz_require
rz_ssh "mkdir -p ~/$RZ_DIR/scripts ~/$RZ_DIR/shader_translator ~/$RZ_DIR/work/recomp"
EXCL=(--exclude='__pycache__' --exclude='*.o' --exclude='*.nso' --exclude='*.img' --exclude='*.keys')
rsync -a --delete "${EXCL[@]}" scripts/recomp/ "$RZ_HOST:$RZ_DIR/scripts/recomp/"
# Only the generated source manifest and original variants, never icons from Git or keys.
if [ -f work/recomp/icons/source/icons.json ]; then
  rz_ssh "mkdir -p ~/$RZ_DIR/work/recomp/icons/source"
  rsync -a --delete work/recomp/icons/source/ "$RZ_HOST:$RZ_DIR/work/recomp/icons/source/"
fi
rsync -a --delete --exclude=build --exclude=tests --exclude='__pycache__' shader_translator/ "$RZ_HOST:$RZ_DIR/shader_translator/"
if [ -d work/recomp/img_gfx ]; then
  rz_ssh "mkdir -p ~/$RZ_DIR/work/recomp/img_gfx"
  rsync -a --delete work/recomp/img_gfx/ "$RZ_HOST:$RZ_DIR/work/recomp/img_gfx/"
else
  rz_info "work/recomp/img_gfx is missing (IMG=work/recomp/img_gfx HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh)"
fi
if [ "$DATA" = 1 ]; then
  [ -f work/exefs/main.npdm ] || rz_die "work/exefs/main.npdm is missing."
  [ -d work/romfs ] || rz_die "work/romfs is missing."
  rsync -a work/exefs/main.npdm "$RZ_HOST:$RZ_DIR/work/exefs/"
  rz_info "RomFS (your own dump, $(du -sh work/romfs | cut -f1)) → ~/$RZ_DIR/work/romfs …"
  rsync -a work/romfs/ "$RZ_HOST:$RZ_DIR/work/romfs/"
fi
rz_info "Transferred state: $(rz_ssh "cd ~/$RZ_DIR && find scripts/recomp/rt-bdsp shader_translator -type f -name '*.[ch]' | sort | xargs sha256sum | sha256sum | cut -c1-10")"
