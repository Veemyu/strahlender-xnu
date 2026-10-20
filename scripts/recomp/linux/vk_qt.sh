#!/bin/bash
# Startet die Qt-Hülle (Menüleiste) mit dem Vulkan-Spiel auf dem Linux host (Bahn b, Job vk-qt-<tag>), Fenster in der Sitzung des Desktops.
# Aufruf: vk_qt.sh [--tag=NAME] [--detach] [NAME=WERT ...] [Optionen von bdsp_boot_vk]
#   Beispiel: vk_qt.sh --tag=q1 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 BDSP_QT_SCRIPT=20:fps30,30:fps120,40:grab,45:quit --timeout 60
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
