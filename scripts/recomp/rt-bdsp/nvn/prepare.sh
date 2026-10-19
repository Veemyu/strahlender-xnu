#!/bin/bash
# Bereitet die Metal-Fassung der NVN-Schicht für den Bau vor. Die Quellen liegen im Repo unter nvn/src
# (Herkunft LASRecomp, MIT, Commit 09f8e5e; geändert, siehe NOTICE.md). Kein Patchen mehr.
# Der Übersetzer kommt aus shader_translator/ (einzige Quelle) und wird hier hineinkopiert.
# Aufruf: prepare.sh      Umgebung: NVN_SRC=work/recomp/nvn-src
set -euo pipefail
cd "$(dirname "$0")/../../../.."
SRC=scripts/recomp/rt-bdsp/nvn/src
DST=${NVN_SRC:-work/recomp/nvn-src}
rm -rf "$DST"
mkdir -p "$DST"
cp -R "$SRC/." "$DST/"
mkdir -p "$DST/nvn/maxwell"
cp shader_translator/translate.c "$DST/nvn/maxwell/translate.c"
cp shader_translator/shader.h "$DST/nvn/maxwell/shader.h"
echo "NVN-Quellen: $DST"
