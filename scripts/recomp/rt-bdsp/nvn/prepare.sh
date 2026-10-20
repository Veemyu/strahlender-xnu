#!/bin/bash
# Bereitet die Metal-Fassung der NVN-Schicht für den Bau vor. Die Quellen liegen im Repo unter nvn/src
# (Herkunft LASRecomp, MIT, Commit 09f8e5e; geändert, siehe NOTICE.md). Kein Patchen mehr.
# Der Übersetzer kommt aus shader_translator/ (einzige Quelle) und wird hier hineinkopiert.
# Schreibt $DST/.stamp (SHA-256 über nvn/src, translate.c, shader.h, prepare.sh) und kopiert nur bei abweichendem Stempel.
# Aufruf: prepare.sh [--check]      Umgebung: NVN_SRC=work/recomp/nvn-src
# --check: kopiert nichts, Exit 0 wenn der Stempel zur Quelle passt, sonst 1.
# --print: gibt nur den Quell-Hash aus (einzige Definition; build_stages.py nutzt ihn für die Stufe recomp).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
SRC=scripts/recomp/rt-bdsp/nvn/src
DST=${NVN_SRC:-work/recomp/nvn-src}
HERE=scripts/recomp/rt-bdsp/nvn
want=$({ find "$SRC" -type f ! -name .DS_Store; echo shader_translator/translate.c; echo shader_translator/shader.h; echo "$HERE/prepare.sh"; } \
  | LC_ALL=C sort | while IFS= read -r f; do shasum -a 256 "$f"; done | shasum -a 256 | cut -d' ' -f1)
if [ "${1:-}" = "--print" ]; then
  echo "$want"
  exit 0
fi
have=$(cat "$DST/.stamp" 2>/dev/null || true)
if [ "${1:-}" = "--check" ]; then
  [ -d "$DST/nvn" ] && [ "$want" = "$have" ] && exit 0
  echo "NVN-Stempel passt nicht: $DST" >&2
  exit 1
fi
if [ -d "$DST/nvn" ] && [ "$want" = "$have" ]; then
  echo "NVN-Quellen aktuell: $DST"
  exit 0
fi
rm -rf "$DST"
mkdir -p "$DST"
cp -R "$SRC/." "$DST/"
mkdir -p "$DST/nvn/maxwell"
cp shader_translator/translate.c "$DST/nvn/maxwell/translate.c"
cp shader_translator/shader.h "$DST/nvn/maxwell/shader.h"
echo "$want" > "$DST/.stamp"
echo "NVN-Quellen: $DST"
