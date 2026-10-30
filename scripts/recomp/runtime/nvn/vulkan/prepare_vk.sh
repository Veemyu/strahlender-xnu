#!/bin/bash
# Vulkan version of the NVN layer (Linux x86-64, later Windows): Metal sources (nvn/src) plus the Vulkan deviations
# (vulkan/src). Origin LASRecomp (MIT, commit 09f8e5e); modified, see NOTICE.md. No patching any more.
# Writes $DST/.stamp (SHA-256 over nvn/src, nvn/vulkan/src, translate.c, shader.h, prepare_vk.sh) and copies only if the stamp differs.
# Usage: prepare_vk.sh [--check|--print]      Environment: NVN_SRC_VK=work/recomp/nvn-src-vk
# --check: copies nothing, exit 0 if the stamp matches the source, otherwise 1.   --print: prints only the source hash.
set -euo pipefail
cd "$(dirname "$0")/../../../../.."
HERE=scripts/recomp/runtime/nvn
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
  echo "Vulkan NVN stamp does not match: $DST" >&2
  exit 1
fi
if [ -d "$DST/nvn" ] && [ "$want" = "$have" ]; then
  echo "Vulkan NVN sources up to date: $DST"
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
echo "Vulkan NVN sources: $DST"
