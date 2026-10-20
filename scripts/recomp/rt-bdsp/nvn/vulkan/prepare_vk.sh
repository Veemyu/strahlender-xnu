#!/bin/bash
# Vulkan-Fassung der NVN-Schicht (Linux x86-64, später Windows): Metal-Quellen (nvn/src) plus die Vulkan-Abweichungen
# (vulkan/src). Herkunft LASRecomp (MIT, Commit 09f8e5e); geändert, siehe NOTICE.md. Kein Patchen mehr.
# Schreibt $DST/.stamp (SHA-256 über nvn/src, nvn/vulkan/src, translate.c, shader.h, prepare_vk.sh) und kopiert nur bei abweichendem Stempel.
# Aufruf: prepare_vk.sh [--check|--print]      Umgebung: NVN_SRC_VK=work/recomp/nvn-src-vk
# --check: kopiert nichts, Exit 0 wenn der Stempel zur Quelle passt, sonst 1.   --print: gibt nur den Quell-Hash aus.
set -euo pipefail
cd "$(dirname "$0")/../../../../.."
HERE=scripts/recomp/rt-bdsp/nvn
. "$HERE/hash.inc.sh"
DST=${NVN_SRC_VK:-work/recomp/nvn-src-vk}
want=$({ find "$HERE/src" "$HERE/vulkan/src" -type f ! -name .DS_Store; echo shader_translator/translate.c; echo shader_translator/shader.h; echo "$HERE/vulkan/prepare_vk.sh"; } \
  | LC_ALL=C sort | while IFS= read -r f; do sha256 "$f"; done | sha256 | cut -d' ' -f1)
if [ "${1:-}" = "--print" ]; then
  echo "$want"
  exit 0
fi
have=$(cat "$DST/.stamp" 2>/dev/null || true)
if [ "${1:-}" = "--check" ]; then
  [ -d "$DST/nvn" ] && [ "$want" = "$have" ] && exit 0
  echo "Vulkan-NVN-Stempel passt nicht: $DST" >&2
  exit 1
fi
if [ -d "$DST/nvn" ] && [ "$want" = "$have" ]; then
  echo "Vulkan-NVN-Quellen aktuell: $DST"
  exit 0
fi
rm -rf "$DST"
mkdir -p "$DST"
cp -R "$HERE/src/." "$DST/"
cp -R "$HERE/vulkan/src/." "$DST/"
mkdir -p "$DST/nvn/maxwell"
cp shader_translator/translate.c "$DST/nvn/maxwell/translate.c"
cp shader_translator/shader.h "$DST/nvn/maxwell/shader.h"
echo "$want" > "$DST/.stamp"
echo "Vulkan-NVN-Quellen: $DST"
