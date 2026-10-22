#!/bin/bash
# GC proof (docs/architecture.md, section threads and GC): recompiled guest code, suspend a thread asynchronously, check the register state.
# Everything under work/recomp/spike2/gc.
set -euo pipefail
cd "$(dirname "$0")/../../.."
S=work/recomp/spike2/gc
mkdir -p $S/gen
echo '{}' > $S/empty.json
clang --target=aarch64-linux-gnu -O1 -ffreestanding -fno-pic -fno-asynchronous-unwind-tables -funwind-tables -c scripts/recomp/test/gc_guest.c -o $S/gc_guest.o
python3 scripts/recomp/mini_link.py $S/gc_guest.o $S/gct --base 0x7008000000 --syms $S/empty.json
python3 scripts/recomp/eh_gen.py gen gct $S/gct.nso 0x7008000000 $S/gen --simd asm 2>&1 | grep -E "wrote|eh_gen"
for f in $S/gen/*.c; do clang -O1 -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -c $f -o ${f%.c}.o; done
clang -O1 -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -c scripts/recomp/test/gc_prove.c -o $S/gc_prove.o
clang -o $S/gc_prove $S/gc_prove.o $S/gen/*.o
OFF=$(python3 -c "import json; print(hex(json.load(open('$S/gct.json'))['syms']['churn']))")
CHURN_OFF=$OFF $S/gc_prove
