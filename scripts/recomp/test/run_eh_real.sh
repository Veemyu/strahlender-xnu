#!/bin/bash
# Throw test with real LSDA functions from main (docs/architecture.md, section exceptions).
# Prerequisite: run_eh_test.sh ran (SDK objects, test module). Everything under work/recomp/, none of it in the repo.
set -euo pipefail
cd "$(dirname "$0")/../../.."
S=work/recomp/spike2
G=work/recomp/gen
JOBS=${JOBS:-3}
MAINBASE=0x7040000000
PER_KIND=${PER_KIND:-15}

python3 scripts/recomp/mkimg.py work/exefs/main main --base $MAINBASE --out $S --link $S/sdk.syms.json
python3 scripts/recomp/eh_pick.py --base $MAINBASE --per-kind "$PER_KIND"
python3 scripts/recomp/eh_gen.py gen main work/exefs/main $MAINBASE $G/mainsub --only $S/real_only.txt --simd asm
mkdir -p $S/obj_real
for f in $G/mainsub/*.c; do scripts/recomp/test/compile_chunk.sh "$f" $S/obj_real; done
clang -o $S/eh_real $S/obj/sdk_*.o $S/obj/eht_*.o $S/obj/test_eh_harness.o $S/obj_real/*.o

sym() { python3 -c "import json,sys; print(hex(json.load(open('$S/sdk.syms.json'))[sys.argv[1]]))" "$1"; }
RUN=$(python3 -c "import json; print(hex(0x7008000000 + json.load(open('$S/eht.json'))['syms']['test_run']))")
$S/eh_real $S $S/sdk.img $S/eht.img real=$S/real_spec.txt mainimg=$S/main.img \
  alloc=$(sym __cxa_allocate_exception) throw=$(sym __cxa_throw) zti=$(sym _ZTIi) test_run=$RUN
