#!/bin/bash
# Starts the Vulkan build on the Linux host (lane b, job vk-run-<tag>) and shows the end of the log. No sound, no window (default: --headless).
# Usage: vk_run.sh [--tag=NAME] [--detach] [NAME=WERT ...] [options of bdsp_boot_vk]
#   Examples: vk_run.sh --tag=t1 --headless --timeout 90 --screenshot-after 300
#              vk_run.sh BDSP_NVN_STATS=1 BDSP_VK_VALIDATION=1 --headless --timeout 60
#   A window only briefly and on purpose: without --headless (needs DISPLAY/WAYLAND_DISPLAY of the session; ssh does not have them) – not intended here.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
TAG=run; ARGS=()
for a in "$@"; do
  case "$a" in
    --tag=*) TAG=${a#--tag=};;
    --detach) RZ_DETACH=1;;
    -h|--help) sed -n 2,6p "$0"; exit 0;;
    *) ARGS+=("$a");;
  esac
done
RZ_TAIL=${RZ_TAIL:-60} rz_run "$RZ_LANE_B" "vk-run-$TAG" vk_run.sh ${ARGS[@]+"${ARGS[@]}"}
