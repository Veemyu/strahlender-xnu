#!/bin/bash
# Startet die Vulkan-Fassung auf dem Linux host (Bahn b, Job vk-run-<tag>) und zeigt das Ende des Logs. Kein Ton, kein Fenster (Standard: --headless).
# Aufruf: vk_run.sh [--tag=NAME] [--detach] [NAME=WERT ...] [Optionen von bdsp_boot_vk]
#   Beispiele: vk_run.sh --tag=t1 --headless --timeout 90 --screenshot-after 300
#              vk_run.sh BDSP_NVN_STATS=1 BDSP_VK_VALIDATION=1 --headless --timeout 60
#   Ein Fenster nur kurz und mit Absicht: ohne --headless (braucht DISPLAY/WAYLAND_DISPLAY der Sitzung; ssh hat sie nicht) – hier nicht vorgesehen.
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
