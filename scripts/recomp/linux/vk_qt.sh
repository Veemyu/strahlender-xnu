#!/bin/bash
# Starts the Qt shell (menu bar) with the Vulkan game on the Linux host (lane b, job vk-qt-<tag>), window in the desktop session.
# Usage: vk_qt.sh [--tag=NAME] [--detach] [NAME=WERT ...] [options of bdsp_boot_vk]
#   Example: vk_qt.sh --tag=q1 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 BDSP_QT_SCRIPT=20:fps30,30:fps120,40:grab,45:quit --timeout 60
set -euo pipefail
source "$(dirname "$0")/lib.sh"
TAG=run; ARGS=()
for a in "$@"; do
  case "$a" in
    --tag=*) TAG=${a#--tag=};;
    --detach) RZ_DETACH=1;;
    -h|--help) sed -n 2,5p "$0"; exit 0;;
    *) ARGS+=("$a");;
  esac
done
RZ_TAIL=${RZ_TAIL:-60} rz_run "$RZ_LANE_B" "vk-qt-$TAG" vk_qt.sh ${ARGS[@]+"${ARGS[@]}"}
