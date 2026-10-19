#!/bin/bash
# Baut die Speicherbilder der Module (Relokationen angewandt, Importe zwischen den Modulen gebunden, übrige Importe
# als HLE-Slots) nach work/recomp/img. Die Basisadressen müssen zu den Adressen passen, mit denen eh_gen.py das C
# erzeugt hat (gen_all.sh, Variante A). Aufruf: mkimages.sh   (Ausgabeordner per IMG=... änderbar,
# HLE_LIST=<Datei> erzwingt HLE-Bindung für die genannten Symbole)
set -euo pipefail
cd "$(dirname "$0")/../../.."
O=${IMG:-work/recomp/img}
mkdir -p "$O"
base_of() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; rtld) echo 0x7008000000;; esac; }
rm -f "$O/hle.txt"
# erster Durchlauf: nur die Exporte sammeln; zweiter: Importe über die Module binden
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
