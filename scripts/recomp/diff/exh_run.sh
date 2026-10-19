#!/bin/bash
# Erschöpfender Einzelbefehlstest (exh.c): baut und läuft für alle Befehle und mehrere FPCR-Werte.
# Aufruf: exh_run.sh m1            (Mac, nativ, Referenz)  oder  exh_run.sh c "<clang-Flags>" [Jobs]   (erzeugtes C)
# Ergebnis: work/recomp/diff/exh_<m1|c>.txt (eine Zeile je Befehl und FPCR-Wert: Nr|Name|FPCR|Schritt|Hash|Fälle)
set -euo pipefail
cd "$(dirname "$0")/../../.."
D=work/recomp/diff
mode=$1
python3 scripts/recomp/diff/exh_gen.py $D/exh_ops.h > /dev/null
# FPCR 0 vollständig; Rundungsmodi, FZ, FZ+DN+RZ mit Schritt 16 (jedes 16. Bitmuster)
CFG=("0 1" "400000 16" "800000 16" "c00000 16" "1000000 16" "2000000 16" "1c00000 16")
if [ "$mode" = m1 ]; then
  clang -O2 -w -DREF_ASM -I $D scripts/recomp/diff/exh.c -o $D/exh_m1
  : > $D/exh_m1.txt
  for c in "${CFG[@]}"; do set -- $c; ./$D/exh_m1 -1 $1 $2 >> $D/exh_m1.txt; done
else
  flags=$2; jobs=${3:-4}
  clang $flags -w -I research/LASRecomp/runtime -I $D scripts/recomp/diff/exh.c -lm -o $D/exh_c
  rm -f $D/exh_c.part.*
  for c in "${CFG[@]}"; do set -- $c; for k in $(seq 0 43); do echo "$k $1 $2"; done; done \
    | xargs -P "$jobs" -L 1 bash -c './'$D'/exh_c $0 $1 $2 >> '$D'/exh_c.part.$$' 
  cat $D/exh_c.part.* | sort -t'|' -k3,3 -k1,1n > $D/exh_c.txt
fi
