#!/bin/bash
# Baut und führt den Exception-Test aus (docs/recomp-spike-2.md, Abschnitt 1). Alles unter work/recomp/.
# Voraussetzung: work/exefs (eigener Dump), scripts/recomp/upstream (vendort), tools/pydeps (capstone, unicorn, lz4).
set -euo pipefail
cd "$(dirname "$0")/../../.."
S=work/recomp/spike2
G=work/recomp/gen
LAS=scripts/recomp/upstream
JOBS=${JOBS:-4}
CFLAGS="-O1 -fno-strict-aliasing -fvisibility=hidden -w -I scripts/recomp/rt -I $LAS/runtime"
mkdir -p $S $G

rm -f $S/hle.txt
python3 scripts/recomp/mkimg.py work/exefs/sdk sdk --base 0x7004000000 --out $S
python3 scripts/recomp/eh_gen.py gen sdk work/exefs/sdk 0x7004000000 $G/sdk --simd asm --hle scripts/recomp/test/hle_symbols.txt
# Die Gast-ABI der Switch nutzt 32-Bit-EH-Kodierungen (sdata4); dieser Clang schreibt sdata8. Umschreiben im Assembler.
clang --target=aarch64-linux-gnu -O1 -fexceptions -fno-rtti -fno-pic -fno-asynchronous-unwind-tables -nostdinc++ -S scripts/recomp/test/eh_guest.cpp -o - \
  | python3 scripts/recomp/test/eh_sdata4.py > $S/eh_guest.s
clang --target=aarch64-linux-gnu -c $S/eh_guest.s -o $S/eh_guest.o
python3 scripts/recomp/mini_link.py $S/eh_guest.o $S/eht --base 0x7008000000 --syms $S/sdk.syms.json
SJ=$(python3 -c "import json; print(json.load(open('$S/eht.json'))['syms']['setjmp'])")
python3 scripts/recomp/eh_gen.py gen eht $S/eht.nso 0x7008000000 $G/eht --simd asm --setjmp-at "$SJ"

rm -rf $S/obj; mkdir -p $S/obj
ls $G/sdk/*.c $G/eht/*.c scripts/recomp/test/eh_harness.c | xargs -P "$JOBS" -n 1 scripts/recomp/test/compile_chunk.sh
clang -o $S/eh_test $S/obj/sdk_*.o $S/obj/eht_*.o $S/obj/test_eh_harness.o -Wl,-U,_main_fn_addrs -Wl,-U,_main_fn_ptrs -Wl,-U,_main_fn_count

TESTS=$(python3 - <<EOF
import json
m = json.load(open("$S/eht.json"))["syms"]
print(" ".join(f"{k}={0x7008000000 + v:#x}" for k, v in m.items() if k.startswith("test_")))
EOF
)
$S/eh_test $S $S/sdk.img $S/eht.img $TESTS
