#!/bin/bash
# Runs locally on Linux: builds runtime with the Vulkan NVN backend and links translated guest modules.
# Uses installed development packages through pkg-config; no header copies or fixed SONAMEs.
# Usage: vk_build.sh [-Dmacro ...]
source "$(dirname "$0")/common.sh"
source scripts/recomp/linux/deps.sh
linux_require_runtime
[ -d "$W/obj4-c" ] || die "$W/obj4-c is missing (run scripts/recomp/linux/local/build_all.sh first)."
export NVN_BACKEND=vulkan OBJ=$W/obj4-c
BARGS=()
for a in "$@"; do [ "$a" = --qt ] && export BDSP_QT=1 || BARGS+=("$a"); done
python3 scripts/recomp/app/game_icons.py linux --source "${BDSP_ICON_SOURCE:-work/recomp/icons/source}" \
  --output work/recomp/icons/linux --executable "work/recomp/bdsp_boot_vk${BDSP_QT:+_qt}" || die "Icon conversion failed."
"${TIMEV[@]}" scripts/recomp/runtime/build.sh ${BARGS[@]+"${BARGS[@]}"} || die "Build failed."
ls -la "$W/bdsp_boot_vk"* | head
