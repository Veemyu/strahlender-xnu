#!/bin/bash
# Runs the Vulkan game with the in-process Qt frontend (runtime/app/linux/qt_ui.cpp, built by vk_build.sh --qt).
# Usage: vk_qt.sh [NAME=VALUE ...] [bdsp_boot_vk options]; uppercase NAME=VALUE arguments are exported as environment variables.
source "$(dirname "$0")/common.sh"
[ -d work/romfs ] || die "work/romfs is missing (run the extract stage described in docs/BUILD.md first)."
# UI overlay for any aspect ratio (work/romfs-patch, found by the runtime next to the RomFS); a failure only leaves gaps around the UI on non-16:9 shapes
python3 scripts/recomp/ui_aspect_patch.py --if-needed --romfs work/romfs --out work/romfs-patch > "${W:-work}/ui-overlay.log" 2>&1 || echo "# UI overlay not generated (see ${W:-work}/ui-overlay.log)"
export BDSP_IMG=${BDSP_IMG:-$W/img_gfx}
ARGS=()
for a in "$@"; do
  case "$a" in [A-Z]*=*) export "$a";; *) ARGS+=("$a");; esac
done
export SDL_AUDIODRIVER=dummy
[ -x "$W/bdsp_boot_vk_qt" ] || die "$W/bdsp_boot_vk_qt is missing (build it with scripts/recomp/linux/local/vk_build.sh --qt; Qt 6 development files required)."
echo "# Start (in-process Qt): ${ARGS[*]}"
"${TIMEV[@]}" "$W/bdsp_boot_vk_qt" ${ARGS[@]+"${ARGS[@]}"}
rc=$?
echo "# End, exit code $rc"
exit "$rc"
