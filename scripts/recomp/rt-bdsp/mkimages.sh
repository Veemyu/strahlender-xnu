#!/bin/bash
# Builds the memory images of the modules (relocations applied, imports between the modules bound, remaining imports
# as HLE slots) into work/recomp/img. The base addresses must match the addresses with which eh_gen.py generated the C
# (gen_all.sh, variant A). Usage: mkimages.sh   (output folder changeable via IMG=...,
# HLE_LIST=<file> forces HLE binding for the listed symbols)
set -euo pipefail
cd "$(dirname "$0")/../../.."
O=${IMG:-work/recomp/img}
mkdir -p "$O"
base_of() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; rtld) echo 0x7008000000;; esac; }
rm -f "$O/hle.txt"
# first pass: only collect the exports; second: bind imports across the modules
for m in main sdk subsdk0; do
  python3 scripts/recomp/mkimg.py "work/exefs/$m" "$m" --base "$(base_of $m)" --out "$O" > /dev/null
done
rm -f "$O/hle.txt"
for m in main sdk subsdk0; do
  python3 scripts/recomp/mkimg.py "work/exefs/$m" "$m" --base "$(base_of $m)" --out "$O" \
    --link "$O/main.syms.json" --link "$O/sdk.syms.json" --link "$O/subsdk0.syms.json" \
    --interpose-from "$O/main.syms.json" \
    ${HLE_LIST:+--hle-list "$HLE_LIST"}
done
echo "HLE-Importe: $(grep -c . "$O/hle.txt" || true)"
