#!/bin/bash
# Runs locally on Linux: builds runtime with the Vulkan NVN backend and links translated guest modules.
# Uses installed development packages through pkg-config; no header copies or fixed SONAMEs.
# Usage: vk_build.sh [-Dmacro ...]
source "$(dirname "$0")/common.sh"
source scripts/recomp/linux/deps.sh
linux_require_runtime
[ -d "$W/obj4-c" ] || die "$W/obj4-c is missing (run scripts/recomp/linux/local/build_all.sh first)."
# W is work/recomp, or the build folder of a code mod (RECOMP_DIR): runtime objects, executable and icons stay inside it
export NVN_BACKEND=vulkan OBJ=$W/obj4-c RT=$W/runtime OUT=$W/bdsp_boot
BARGS=()
for a in "$@"; do [ "$a" = --qt ] && export BDSP_QT=1 || BARGS+=("$a"); done
MOD_ICONS=()
[ -z "${BDSP_MOD_ROOT:-}" ] || MOD_ICONS=(--mod-root "$BDSP_MOD_ROOT" --mod-name "${BDSP_MOD_NAME:?BDSP_MOD_NAME is missing}")
python3 scripts/recomp/app/game_icons.py linux --source "${BDSP_ICON_SOURCE:-work/recomp/icons/source}" \
  --output "$W/icons/linux" --executable "$W/bdsp_boot_vk${BDSP_QT:+_qt}" ${MOD_ICONS[@]+"${MOD_ICONS[@]}"} || die "Icon conversion failed."
"${TIMEV[@]}" scripts/recomp/runtime/build.sh ${BARGS[@]+"${BARGS[@]}"} || die "Build failed."
ls -la "$W/bdsp_boot_vk"* | head
