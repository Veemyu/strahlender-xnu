#!/bin/bash
# Vulkan-Fassung der NVN-Schicht (Linux x86-64, später Windows): Metal-Quellen (nvn/src) plus die Vulkan-Abweichungen
# (vulkan/src). Herkunft LASRecomp (MIT, Commit 09f8e5e); geändert, siehe NOTICE.md. Kein Patchen mehr.
# Aufruf: prepare_vk.sh      Umgebung: NVN_SRC_VK=work/recomp/nvn-src-vk
set -euo pipefail
cd "$(dirname "$0")/../../../../.."
HERE=scripts/recomp/rt-bdsp/nvn
DST=${NVN_SRC_VK:-work/recomp/nvn-src-vk}
rm -rf "$DST"
mkdir -p "$DST"
cp -R "$HERE/src/." "$DST/"
cp -R "$HERE/vulkan/src/." "$DST/"
mkdir -p "$DST/nvn/maxwell"
cp shader_translator/translate.c "$DST/nvn/maxwell/translate.c"
cp shader_translator/shader.h "$DST/nvn/maxwell/shader.h"
echo "Vulkan-NVN-Quellen: $DST"
