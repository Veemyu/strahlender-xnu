#!/bin/bash
# Builds rt-bdsp with the Vulkan backend on the Linux host (lane a, job vk-build; log ~/xnu-recomp/logs/vk-build.log). Transfers the working state beforehand (vk_sync.sh).
# Usage: vk_build.sh [--ohne-sync] [--detach] [--qt] [-DMakro ...]   (--qt: additionally bdsp_boot_vk_qt with the Qt shell, needs qt6-qtbase-devel)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
SYNC=1; ARGS=()
for a in "$@"; do
  case "$a" in
    --ohne-sync) SYNC=0;;
    --detach) RZ_DETACH=1;;
    --qt) ARGS+=(--qt);;
    -h|--help) sed -n 2,4p "$0"; exit 0;;
    *) ARGS+=("$a");;
  esac
done
[ "$SYNC" = 1 ] && "$(dirname "$0")/vk_sync.sh"
RZ_TAIL=${RZ_TAIL:-40} rz_run "$RZ_LANE_A" vk-build vk_build.sh ${ARGS[@]+"${ARGS[@]}"}
