#!/bin/bash
# Fetches images (PNG) and the log of a Vulkan run from the Linux host into work/recomp/linux/shots/ (gitignored; never into the repo).
# Usage: vk_fetch.sh [shots|logs|alles]     (default: alles)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
what=${1:-alles}
rz_require
mkdir -p "$RZ_LOCAL_OUT/shots" "$RZ_LOCAL_OUT/logs"
case "$what" in shots|logs|alles) ;; *) rz_die "Usage: vk_fetch.sh [shots|logs|alles]";; esac
if [ "$what" = shots ] || [ "$what" = alles ]; then
  rsync -a --max-size=30m --include='*.png' --exclude='*' "$RZ_HOST:$RZ_DIR/work/recomp/shots/" "$RZ_LOCAL_OUT/shots/" || rz_info "no images on the Linux host"
  ls -la "$RZ_LOCAL_OUT/shots" | tail -20
fi
if [ "$what" = logs ] || [ "$what" = alles ]; then
  rsync -a --max-size=3m --include='vk-*.log' --include='vk-*.rc' --include='vk-*.sec' --exclude='*' "$RZ_HOST:$RZ_DIR/logs/" "$RZ_LOCAL_OUT/logs/"
  ls -1 "$RZ_LOCAL_OUT/logs" | grep '^vk-' | head -30
fi
