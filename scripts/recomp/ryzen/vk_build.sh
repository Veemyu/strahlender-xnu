#!/bin/bash
# Baut rt-bdsp mit dem Vulkan-Backend auf dem Ryzen (Bahn a, Job vk-build; Log ~/xnu-recomp/logs/vk-build.log). Überträgt vorher den Arbeitsstand (vk_sync.sh).
# Aufruf: vk_build.sh [--ohne-sync] [--detach] [-DMakro ...]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
SYNC=1; ARGS=()
for a in "$@"; do
  case "$a" in
    --ohne-sync) SYNC=0;;
    --detach) RZ_DETACH=1;;
    -h|--help) sed -n 2,4p "$0"; exit 0;;
    *) ARGS+=("$a");;
  esac
done
[ "$SYNC" = 1 ] && "$(dirname "$0")/vk_sync.sh"
RZ_TAIL=${RZ_TAIL:-40} rz_run "$RZ_LANE_A" vk-build vk_build.sh ${ARGS[@]+"${ARGS[@]}"}
