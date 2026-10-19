#!/bin/bash
# Läuft auf dem Ryzen (Arbeitsordner ~/xnu-recomp): baut die c-Varianten des Differenzialtests und führt ihn aus
# (docs/recomp-diff.md). Aufruf: run_ryzen.sh <Satz> [ids]   Satz = Name der Variantenliste unten.
# Ergebnisse: work/recomp/diff/rep_<Satz>.json, Log work/recomp/diff/run_<Satz>.log. Höchstens 4 parallele Prozesse.
set -uo pipefail
cd "$(dirname "$0")/../../.."
D=work/recomp/diff
SET=${1:-base}
IDS=${2:-}
B=scripts/recomp/diff/build_c.sh
V3="-march=x86-64-v3"
bash $B base
declare -a VAR
case "$SET" in
  base)   # Ausgangslage: Flags wie der Gesamtbau (clang -O1, Standardvertrag), dazu die Vergleichsvarianten
    VAR=("o1_v3_default:-O1 $V3" "o1_v3_off:-O1 $V3 -ffp-contract=off" "o2_v3_off:-O2 $V3 -ffp-contract=off"
         "o2_v3_default:-O2 $V3" "o1_x86_off:-O1 -ffp-contract=off");;
  neg)    # Negativkontrolle: Laufzeit ohne FENV_ACCESS-Pragma (OVERLAY), -ffp-contract=fast
    mkdir -p $D/neg
    for h in cpu.h simd.h simd_fp.h; do sed '/FENV_ACCESS/d' scripts/recomp/upstream/runtime/$h > $D/neg/$h; done
    export OVERLAY=$D/neg
    VAR=("o2_v3_fast:-O2 $V3 -ffp-contract=fast" "o1_v3_fast:-O1 $V3 -ffp-contract=fast");;
  *) VAR=($SET);;
esac
pids=()
for v in "${VAR[@]}"; do
  n=${v%%:*}; f=${v#*:}
  ( bash $B c "$n" $f ) &
  pids+=($!)
  [ ${#pids[@]} -ge 4 ] && { wait "${pids[0]}"; pids=("${pids[@]:1}"); }
done
wait
srcs=uc
for v in "${VAR[@]}"; do n=${v%%:*}; srcs="$srcs,c:$n=$D/lib_$n.so"; done
python3 scripts/recomp/diff/difftest.py --src "$srcs" --jobs 4 ${IDS:+--ids $IDS} --out "$D/rep_$SET.json"
