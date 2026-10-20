#!/bin/bash
# Baut die C++-Qt-Hülle auf dem Ryzen (Bahn a, Job vk-qt-build). Voraussetzung: Qt6-Entwicklungspakete (Liste und Befehl: rt-bdsp/app/linux/deps.txt).
# Aufruf: vk_qt_build.sh [--detach] [--check]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
ARGS=()
for a in "$@"; do
  case "$a" in
    --detach) RZ_DETACH=1;;
    -h|--help) sed -n 2,3p "$0"; exit 0;;
    *) ARGS+=("$a");;
  esac
done
RZ_TAIL=${RZ_TAIL:-30} rz_run "$RZ_LANE_A" "vk-qt-build" vk_qt_build.sh ${ARGS[@]+"${ARGS[@]}"}
