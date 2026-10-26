#!/bin/bash
# Memory model B (32-bit guest addresses): the same exception test as run_eh_test.sh, but with the real SDK module
# in C SIMD mode (--simd c) and all guest addresses < 4 GiB, access through g_base (scripts/recomp/rt32).
# Everything under work/recomp/ (gen32, spike2/r32). Prerequisite: work/exefs.
set -euo pipefail
cd "$(dirname "$0")/../../.."
S=work/recomp/spike2/r32
G=work/recomp/gen32
JOBS=${JOBS:-3}
mkdir -p $S/obj $G
rm -f $S/hle.txt
SDKB=0x01000000; EHTB=0x02000000; HLEB=0x08000000
bash scripts/recomp/codegen.sh image work/exefs/sdk sdk --base $SDKB --out $S --hle-base $HLEB
bash scripts/recomp/codegen.sh gen sdk work/exefs/sdk $SDKB $G/sdk --simd c --hle scripts/recomp/test/hle_symbols.txt
clang --target=aarch64-linux-gnu -O1 -fexceptions -fno-rtti -fno-pic -fno-asynchronous-unwind-tables -nostdinc++ -S scripts/recomp/test/eh_guest.cpp -o - \
  | python3 scripts/recomp/test/eh_sdata4.py > $S/eh_guest.s
clang --target=aarch64-linux-gnu -c $S/eh_guest.s -o $S/eh_guest.o
python3 scripts/recomp/mini_link.py $S/eh_guest.o $S/eht --base $EHTB --syms $S/sdk.syms.json
bash scripts/recomp/codegen.sh gen eht $S/eht.nso $EHTB $G/eht --simd c

export EXTRA="-DREBASE32 -I scripts/recomp/rt32"
for f in $G/sdk/*.c $G/eht/*.c scripts/recomp/test/eh_harness.c; do echo "$f"; done | \
  xargs -P "$JOBS" -n 1 -I{} scripts/recomp/test/compile_chunk.sh {} $S/obj
clang -o $S/eh_test32 $S/obj/*.o -Wl,-U,_main_fn_addrs -Wl,-U,_main_fn_ptrs -Wl,-U,_main_fn_count
TESTS=$(python3 -c "
import json
m = json.load(open('$S/eht.json'))['syms']
print(' '.join(f'{k}={0x02000000 + v:#x}' for k, v in m.items() if k.startswith('test_')))")
$S/eh_test32 $S $S/sdk.img $S/eht.img $TESTS
