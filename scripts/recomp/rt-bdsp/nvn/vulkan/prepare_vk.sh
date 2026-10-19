#!/bin/bash
# Bereitet die Vulkan-Fassung der NVN-Schicht vor (Linux x86-64, später Windows): Der gemeinsame Teil kommt wie beim Metal-Weg aus
# nvn/prepare.sh (LAS-Quellen, unser Übersetzer, las-nvn.patch), danach kommt der Vulkan-Teil des Klons
# (research/LASRecomp/runtime/nvn/vulkan, MIT, siehe NOTICE.md) dazu, die Ersatz-Header aus vulkan/shim/ werden darübergelegt und
# vulkan/las-vk.patch angewandt. Alles wird nach work/recomp/nvn-src-vk KOPIERT (nichts davon liegt im Repo, research/ bleibt unverändert).
# Aufruf: prepare_vk.sh      Umgebung: NVN_SRC_VK=work/recomp/nvn-src-vk
set -euo pipefail
cd "$(dirname "$0")/../../../../.."
HERE=scripts/recomp/rt-bdsp/nvn
VK=$HERE/vulkan
DST=${NVN_SRC_VK:-work/recomp/nvn-src-vk}
NVN_SRC="$DST" "$HERE/prepare.sh" > /dev/null
# Der Metal-Teil (renderer.m, metal.m) bleibt als Kopie liegen, damit las-nvn.patch unverändert passt, wird aber nicht gebaut.
mkdir -p "$DST/nvn/vulkan"
for f in device.c exec.c shaders.c shaders.h textures.c vk.h vma.cpp; do
  cp "research/LASRecomp/runtime/nvn/vulkan/$f" "$DST/nvn/vulkan/$f"
done
# Texpatch-Kopf liegt im Klon neben vulkan/ (../texpatch.h), die Metal-Shims legen ihn an die Wurzel
cp "$HERE/shim/texpatch.h" "$DST/nvn/texpatch.h"
cp -R "$VK/shim/." "$DST/"
find "$DST" -type f \( -name '*.c' -o -name '*.h' -o -name '*.m' -o -name '*.inc' -o -name '*.cpp' \) -exec perl -pi -e 's/LARECOMP_/BDSP_/g' {} +
if [ -f "$VK/las-vk.patch" ]; then (cd "$DST" && patch -p1 --quiet < "$OLDPWD/$VK/las-vk.patch"); fi
echo "Vulkan-NVN-Quellen: $DST"
