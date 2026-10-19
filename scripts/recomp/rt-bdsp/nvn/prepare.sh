#!/bin/bash
# Bereitet die NVN-Schicht des LAS-Klons (research/LASRecomp/runtime/nvn, MIT, siehe ../NOTICE.md) für den Bau vor:
# Die Quellen werden nach work/recomp/nvn-src KOPIERT (research/ bleibt unverändert, nichts davon liegt im Repo), die Ersatz-
# Header aus shim/ daneben gelegt und las-nvn.patch angewandt. Nicht übernommen: Vulkan-Teil, texpatch.c, output_scale.c, smaa_data.c.
# Aufruf: prepare.sh      Umgebung: NVN_SRC=work/recomp/nvn-src
set -euo pipefail
cd "$(dirname "$0")/../../../.."
SRC=research/LASRecomp/runtime
DST=${NVN_SRC:-work/recomp/nvn-src}
HERE=scripts/recomp/rt-bdsp/nvn
rm -rf "$DST"
mkdir -p "$DST/nvn/maxwell"
for f in objects.c cmdbuf.c formats.c tegra.c tegra.h astc.c astc.h nvn.h renderer.m renderer.h metal.m output_scale.h; do
  cp "$SRC/nvn/$f" "$DST/nvn/$f"
done
cp "$SRC/nvn/maxwell/"* "$DST/nvn/maxwell/"
# Übersetzer: unsere Fassung (shader_translator/, MIT, TEX.B/bindlose Texturen, Treue-Test) statt des Originals; das Original scheitert an allen
# BDSP-Shadern mit „bindless tex“ (siehe docs/recomp-gate2.md). Beide gleiche Schnittstelle (maxwell_translate).
cp shader_translator/translate.c "$DST/nvn/maxwell/translate.c"
cp shader_translator/shader.h "$DST/nvn/maxwell/shader.h"
cp -R "$HERE/shim/." "$DST/"
if [ -f "$HERE/las-nvn.patch" ]; then (cd "$DST" && patch -p1 --quiet < "../../../$HERE/las-nvn.patch"); fi
echo "NVN-Quellen: $DST"
