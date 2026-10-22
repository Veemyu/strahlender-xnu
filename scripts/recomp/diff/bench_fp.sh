#!/bin/bash
# Runs locally on Linux (from the repo root): float benchmark with different fusion settings for guest code and native
# reference (docs/recomp-diff.md, section 6). Everything under work/recomp/diff/bench. Usage: bench_fp.sh [n]
set -uo pipefail
cd "$(dirname "$0")/../../.."
N=${1:-2000000}
S=work/recomp/diff/bench
mkdir -p $S
echo '{}' > $S/empty.json
T=scripts/recomp/test
LAS=scripts/recomp/upstream
run() { # name, guest flags, native flags, C flags of the recompilation
  local name=$1 gf=$2 nf=$3 cf=$4 D=$S/$1
  mkdir -p $D/gen && rm -f $D/gen/*
  clang --target=aarch64-linux-gnu -O2 $gf -ffreestanding -fno-pic -fno-asynchronous-unwind-tables -funwind-tables -c $T/bench_guest.c -o $D/g.o
  python3 scripts/recomp/mini_link.py $D/g.o $D/gbn --base 0x7008000000 --syms $S/empty.json > /dev/null
  python3 scripts/recomp/eh_gen.py gen gbn $D/gbn.nso 0x7008000000 $D/gen --simd c > /dev/null 2>&1
  for f in $D/gen/*.c; do clang -O1 $cf -fno-strict-aliasing -w -march=x86-64-v3 -I scripts/recomp/rt -I $LAS/runtime -c $f -o ${f%.c}.o; done
  clang -O2 $nf -w -march=x86-64-v3 -I scripts/recomp/rt -I $LAS/runtime -I $T -I scripts/recomp/diff -c scripts/recomp/diff/bench_fp.c -o $D/bench_fp.o
  clang -o $D/bench_fp $D/bench_fp.o $D/gen/*.o -lm
  off=$(python3 -c "import json; print(hex(json.load(open('$D/gbn.json'))['syms']['bench_float']))")
  echo "== $name (guest: $gf | native: $nf | recompilation: $cf)"
  clang --target=aarch64-linux-gnu -O2 $gf -S -o - $T/bench_guest.c 2>/dev/null | awk '/^bench_float:/,/\.size\tbench_float/' | grep -E "fm|fn" | head -6
  GIMG=$D/gbn.img OFF_FLOAT=$off $D/bench_fp $N
  python3 scripts/recomp/diff/bench_fp_uc.py $D/gbn.img $off $N
}
run a_default "" "" ""
run b_guest_off"-ffp-contract=off" "" ""
run c_alles_off "-ffp-contract=off" "-ffp-contract=off" "-ffp-contract=off"
run d_nat_off "" "-ffp-contract=off" ""
