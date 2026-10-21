#!/bin/bash
# Runs on the Linux host: starts work/recomp/bdsp_boot_vk (Vulkan build of rt-bdsp), by default without window (--headless: offscreen rendering into
# images of their own size, no display needed, nothing on the user's desktop) and silent (the runtime has no audio path).
# Usage: vk_run.sh [NAME=WERT ...] [options of bdsp_boot_vk]   (words of the form NAME=WERT with uppercase names are environment variables)
#   Default: --headless --timeout 60 (belongs to the runtime; environment BDSP_IMG=work/recomp/img_gfx)
# Images: work/recomp/shots/frame_NNNNN.png (BDSP_SHOT_DIR changes the folder), shader cache: work/recomp/cache/spirv
source "$(dirname "$0")/common.sh"
[ -x "$W/bdsp_boot_vk" ] || die "$W/bdsp_boot_vk is missing (run scripts/recomp/linux/host/vk_build.sh)."
[ -d work/romfs ] || die "work/romfs is missing (run the extract stage described in docs/BUILD.md first)."
export BDSP_IMG=${BDSP_IMG:-$W/img_gfx}
ARGS=()
for a in "$@"; do
  case "$a" in [A-Z]*=*) export "$a";; *) ARGS+=("$a");; esac
done
[ ${#ARGS[@]} -gt 0 ] || ARGS=(--headless --timeout 60)
export SDL_AUDIODRIVER=dummy
echo "# Start: ${ARGS[*]}"
"${TIMEV[@]}" "$W/bdsp_boot_vk" "${ARGS[@]}"
echo "# End, code $?"
ls -la "${BDSP_SHOT_DIR:-$W/shots}" 2>/dev/null | tail -20
