#!/bin/bash
# Schritt 5: main + sdk + subsdk0 (rekompiliert, work/recomp/obj4 aus build_all.sh) bis zum ersten Blocker starten.
# Voraussetzung: gen_all.sh und build_all.sh sind gelaufen. Alles unter work/recomp/ (gitignoriert).
set -euo pipefail
cd "$(dirname "$0")/../../.."
S=work/recomp/spike2/boot
OBJ=${OBJ:-work/recomp/obj4}
mkdir -p $S
declare_base() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; esac; }
rm -f $S/hle.txt
for m in main sdk subsdk0; do python3 scripts/recomp/mkimg.py work/exefs/$m $m --base "$(declare_base $m)" --out $S > /dev/null; done
rm -f $S/hle.txt
for m in main sdk subsdk0; do
  python3 scripts/recomp/mkimg.py work/exefs/$m $m --base "$(declare_base $m)" --out $S \
    --link $S/main.syms.json --link $S/sdk.syms.json --link $S/subsdk0.syms.json
done
clang -O1 -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -c scripts/recomp/test/boot_probe.c -o $S/boot_probe.o
clang -o $S/boot_probe $S/boot_probe.o $OBJ/*.o
START=$(python3 -c "
import json
m = json.load(open('$S/sdk.syms.json'))
print(hex(next(v for k, v in m.items() if k.startswith('_ZN2nn4init5Start'))))")
$S/boot_probe $S "$START"
