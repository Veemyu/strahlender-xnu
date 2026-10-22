#!/bin/bash
# Runs the Qt host (C++, rt-bdsp/app/linux, built by vk_qt_build.sh) with the Vulkan game in an embedded window.
# Usage: vk_qt.sh [NAME=VALUE ...] [bdsp_boot_vk options]; uppercase NAME=VALUE arguments are exported as environment variables.
source "$(dirname "$0")/common.sh"
[ -x "$W/bdsp_boot_vk" ] || die "$W/bdsp_boot_vk is missing (run vk_build.sh)."
[ -d work/romfs ] || die "work/romfs is missing (run the extract stage described in docs/BUILD.md first)."
export BDSP_IMG=${BDSP_IMG:-$W/img_gfx}
ARGS=()
for a in "$@"; do
  case "$a" in [A-Z]*=*) export "$a";; *) ARGS+=("$a");; esac
done
export SDL_AUDIODRIVER=dummy
if [ -x "$W/bdsp_boot_vk_qt" ] && [ -z "${BDSP_QT_PROCESS:-}" ]; then  # In-process Qt host (vk_build.sh --qt): X11 and native Wayland.
  echo "# Start (in-process Qt): ${ARGS[*]}"
  "${TIMEV[@]}" "$W/bdsp_boot_vk_qt" ${ARGS[@]+"${ARGS[@]}"}
  echo "# End, exit code $?"
  exit 0
fi
QT_BIN=$W/qt-host/bdsp_qt_host
[ -x "$QT_BIN" ] || die "$QT_BIN is missing (build with scripts/recomp/linux/local/vk_qt_build.sh; Qt 6 development files required)."
echo "# Start Qt host: ${ARGS[*]}"
"${TIMEV[@]}" "$QT_BIN" --game "$W/bdsp_boot_vk" -- ${ARGS[@]+"${ARGS[@]}"}
echo "# End, exit code $?"
