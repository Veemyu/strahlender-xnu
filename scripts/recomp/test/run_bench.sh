#!/bin/bash
# Leistungsvergleich rekompiliert gegen nativ (docs/recomp-spike-2.md, Abschnitt 6). Alles unter work/recomp/spike2/bench.
# Aufruf: run_bench.sh [-O1|-O2]   (Optimierungsstufe für das erzeugte C, Standard -O1 wie im Gesamtbau)
set -euo pipefail
cd "$(dirname "$0")/../../.."
S=work/recomp/spike2/bench
OPT=${1:--O1}
mkdir -p $S/gen
echo '{}' > $S/empty.json
clang --target=aarch64-linux-gnu -O2 -ffreestanding -fno-pic -fno-asynchronous-unwind-tables -funwind-tables -c scripts/recomp/test/bench_guest.c -o $S/bench_guest.o
python3 scripts/recomp/mini_link.py $S/bench_guest.o $S/gbn --base 0x7008000000 --syms $S/empty.json
python3 scripts/recomp/eh_gen.py gen gbn $S/gbn.nso 0x7008000000 $S/gen --simd asm 2>&1 | grep -E "wrote|eh_gen"
rm -f $S/gen/*.o
for f in $S/gen/*.c; do clang $OPT -fno-strict-aliasing -w -I scripts/recomp/rt -I research/LASRecomp/runtime -c $f -o ${f%.c}.o; done
clang -O2 -w -I scripts/recomp/rt -I research/LASRecomp/runtime -I scripts/recomp/test -c scripts/recomp/test/bench_prove.c -o $S/bench_prove.o
clang -o $S/bench_prove $S/bench_prove.o $S/gen/*.o
off() { python3 -c "import json,sys; print(hex(json.load(open('$S/gbn.json'))['syms'][sys.argv[1]]))" "$1"; }
echo "Erzeugtes C mit $OPT, Gastcode aarch64 mit -O2, native Vergleichsversion -O2"
GIMG=$S/gbn.img OFF_INT=$(off bench_int) OFF_CALLS=$(off bench_calls) OFF_FLOAT=$(off bench_float) OFF_IND=$(off bench_indirect) $S/bench_prove
