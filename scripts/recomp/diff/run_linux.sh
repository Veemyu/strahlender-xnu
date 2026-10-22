#!/bin/bash
# Runs locally on Linux (from the repo root): builds the c variants of the differential test and runs it
# (docs/recomp-diff.md). Usage: scripts/recomp/diff/run_linux.sh <set> [ids]   set = name of the variant list below.
# Results: work/recomp/diff/rep_<set>.json, log work/recomp/diff/run_<set>.log. At most 4 parallel processes.
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
  base)   # baseline: flags like the full build (clang -O1, standard contract), plus the comparison variants
    VAR=("o1_v3_default:-O1 $V3" "o1_v3_off:-O1 $V3 -ffp-contract=off" "o2_v3_off:-O2 $V3 -ffp-contract=off"
         "o2_v3_default:-O2 $V3" "o1_x86_off:-O1 -ffp-contract=off");;
  neg)    # negative control: runtime without the FENV_ACCESS pragma (OVERLAY), -ffp-contract=fast
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
