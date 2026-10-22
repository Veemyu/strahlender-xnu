#!/bin/bash
# Incremental regeneration: regenerates the C into work/recomp/gen4.new and transfers only files with changed content
# to work/recomp/gen4 (timestamps of unchanged chunks stay, build_all.sh then compiles only the changed ones).
# Usage: regen_inc.sh [module ...]     (default: all four modules). Afterwards: build_all.sh 4
set -euo pipefail
cd "$(dirname "$0")/../.."
NEW=work/recomp/gen4.new
rm -rf "$NEW"
OUT=$NEW scripts/recomp/gen_all.sh "$@"
mkdir -p work/recomp/gen4
# -c (checksum): compare content instead of time/size; --delete: remove stale chunks (only modules that were regenerated)
for d in "$NEW"/*/; do
  m=$(basename "$d")
  mkdir -p "work/recomp/gen4/$m"
  rsync -rc --delete --itemize-changes "$d" "work/recomp/gen4/$m/" | { grep -c '^>f' || true; } | xargs echo "$m: changed files:"
done
rm -rf "$NEW"
