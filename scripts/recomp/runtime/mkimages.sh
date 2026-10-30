#!/bin/bash
# Builds the memory images of the modules (relocations applied, imports between the modules bound, remaining imports
# as HLE slots) into work/recomp/img. The base addresses must match the addresses with which the native generator generated the C
# (gen_all.sh, variant A). Usage: mkimages.sh   (output folder changeable via IMG=...,
# HLE_LIST=<file> forces HLE binding for the listed symbols)
set -euo pipefail
cd "$(dirname "$0")/../../.."
O=${IMG:-work/recomp/img}
EXEFS_DIR=${BDSP_EXEFS_DIR:-work/exefs}
CODEGEN="$(python3 scripts/recomp/native-generator/build.py)"
mkdir -p "$O"
source scripts/recomp/module_bases.sh
modules=(main sdk subsdk0)
[ ! -f "$EXEFS_DIR/subsdk1" ] || modules+=(subsdk1)
links=()
for m in "${modules[@]}"; do links+=(--link "$O/$m.syms.json"); done
rm -f "$O/hle.txt"
# first pass: only collect the exports; second: bind imports across the modules
for m in "${modules[@]}"; do
  "$CODEGEN" image "$EXEFS_DIR/$m" "$m" --base "$(base_of $m)" --out "$O" > /dev/null
done
rm -f "$O/hle.txt"
for m in "${modules[@]}"; do
  "$CODEGEN" image "$EXEFS_DIR/$m" "$m" --base "$(base_of $m)" --out "$O" \
    "${links[@]}" \
    --interpose-from "$O/main.syms.json" \
    ${HLE_LIST:+--hle-list "$HLE_LIST"}
done
echo "HLE-Importe: $(grep -c . "$O/hle.txt" || true)"
