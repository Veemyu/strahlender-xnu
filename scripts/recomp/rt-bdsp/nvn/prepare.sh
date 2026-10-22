#!/bin/bash
# Prepares the Metal version of the NVN layer for the build. The sources live in the repo under nvn/src
# (origin LASRecomp, MIT, commit 09f8e5e; modified, see NOTICE.md). No patching any more.
# The translator comes from shader_translator/ (single source) and is copied in here.
# Writes $DST/.stamp (SHA-256 over nvn/src, translate.c, shader.h, prepare.sh) and copies only if the stamp differs.
# Usage: prepare.sh [--check]      Environment: NVN_SRC=work/recomp/nvn-src
# --check: copies nothing, exit 0 if the stamp matches the source, otherwise 1.
# --print: prints only the source hash (single definition; build_stages.py uses it for the recomp stage).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
SRC=scripts/recomp/rt-bdsp/nvn/src
DST=${NVN_SRC:-work/recomp/nvn-src}
HERE=scripts/recomp/rt-bdsp/nvn
. "$HERE/hash.inc.sh"
want=$({ find "$SRC" -type f ! -name .DS_Store; echo shader_translator/translate.c; echo shader_translator/shader.h; echo "$HERE/prepare.sh"; } \
  | LC_ALL=C sort | while IFS= read -r f; do sha256 "$f"; done | sha256 | cut -d' ' -f1)
if [ "${1:-}" = "--print" ]; then
  echo "$want"
  exit 0
fi
have=$(cat "$DST/.stamp" 2>/dev/null || true)
if [ "${1:-}" = "--check" ]; then
  [ -d "$DST/nvn" ] && [ "$want" = "$have" ] && exit 0
  echo "NVN stamp does not match: $DST" >&2
  exit 1
fi
if [ -d "$DST/nvn" ] && [ "$want" = "$have" ]; then
  echo "NVN sources up to date: $DST"
  exit 0
fi
rm -rf "$DST"
mkdir -p "$DST"
cp -R "$SRC/." "$DST/"
mkdir -p "$DST/nvn/maxwell"
cp shader_translator/translate.c "$DST/nvn/maxwell/translate.c"
cp shader_translator/shader.h "$DST/nvn/maxwell/shader.h"
echo "$want" > "$DST/.stamp"
echo "NVN sources: $DST"
