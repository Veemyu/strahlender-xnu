#!/bin/bash
# Runs locally on Linux: Linux counterparts of the spike tests from scripts/recomp/test/ (x86 host, c mode, `weak_import` → `weak`).
# Usage: probe.sh <test>   with test = eh | eh-real | rebase32 | gc | bench | boot | boot-las | all
#   eh        exception test (T0-T6) with the real SDK module          (Mac: run_eh_test.sh)
#   eh-real   throw test with real LSDA functions from main (PER_KIND, default 60)   (run_eh_real.sh; after eh)
#   rebase32  32-bit guest addresses (rt32)                               (run_eh_rebase32.sh)
#   gc        stopping a guest thread at any point (Linux: signal instead of Mach)   (run_gc_proof.sh)
#   bench     micro benchmarks recompiled against native                (run_bench.sh)
#   boot      boot probe: main+sdk+subsdk0 up to the first blocker      (run_boot_probe.sh; needs compile.sh)
#   boot-las  like boot, with the IPC/service layer of LASRecomp       (run_boot_probe_las.sh; after boot)
#   bdsp      build and start the Gate-1 runtime scripts/recomp/rt-bdsp (ap-recomp-3) under Linux; ends at the RomFS (not available on Linux)
# Everything under work/recomp/probe/. Nothing is played back, no graphics.
source "$(dirname "$0")/common.sh"
T=scripts/recomp/test
P=$W/probe
CF="-fno-strict-aliasing -fvisibility=hidden -w -fPIC -march=x86-64-v3 -I scripts/recomp/rt -I $LAS/runtime"
export CF
mkdir -p "$P"

# cc_all <objdir> <opt> <files...>: compile in parallel (object name <folder>_<file>.o), abort on error
cc_all() {
  local out=$1 opt=$2; shift 2
  rm -rf "$out"   # no leftovers from runs with a different chunk split (duplicate symbols)
  mkdir -p "$out"
  export out opt
  printf '%s\n' "$@" | xargs -P "$JOBS" -I{} bash -c 'o="$out/$(basename "$(dirname "{}")")_$(basename "{}" .c).o"; op=$opt; [ "$(stat -c %s "{}")" -gt 300000 ] && [ "$(grep -c "^void f_.*) {\$" "{}")" = 1 ] && op=-O0; [ "$o" -nt "{}" ] || clang $op $EXTRA $CF -c "{}" -o "$o"' \
    || die "Compilation failed."
}
tm() { echo "--- $*"; "${TIMEV[@]}" "$@"; }
sym() { python3 -c "import json,sys; print(hex(json.load(open('$1'))[sys.argv[1]]))" "$2"; }
eh_list() {   # <json> <basis>: test_*=<address> of the test module (EXCL=name excludes one test)
  python3 -c "
import json, os, sys
m = json.load(open(sys.argv[1]))['syms']
print(' '.join(f'{k}={int(sys.argv[2], 16) + v:#x}' for k, v in m.items() if k.startswith('test_') and k != os.environ.get('EXCL')))" "$1" "$2"
}

guest_aarch64() {   # <source.cpp> <output.s>   (synthetic guest program, sdata4 EH like the Switch ABI)
  clang --target=aarch64-linux-gnu -O1 -fexceptions -fno-rtti -fno-pic -fno-asynchronous-unwind-tables -nostdinc++ -S "$1" -o - | python3 $T/eh_sdata4.py > "$2"
}

build_eh_common() {   # <S> <sdk-basis> <eht-basis> <extra-flags> <rt-pfad-flags>
  local S=$1 SDKB=$2 EHTB=$3
  local G=$S/gen
  mkdir -p "$S/obj" "$G"
  rm -f "$S/hle.txt"
  python3 scripts/recomp/mkimg.py work/exefs/sdk sdk --base "$SDKB" --out "$S" ${HLEB:+--hle-base $HLEB} > /dev/null
  python3 scripts/recomp/eh_gen.py gen sdk work/exefs/sdk "$SDKB" "$G/sdk" --simd c --hle $T/hle_symbols.txt 2>&1 | grep -E "wrote|eh_gen"
  guest_aarch64 $T/eh_guest.cpp "$S/eh_guest.s"
  clang --target=aarch64-linux-gnu -c "$S/eh_guest.s" -o "$S/eh_guest.o"
  python3 scripts/recomp/mini_link.py "$S/eh_guest.o" "$S/eht" --base "$EHTB" --syms "$S/sdk.syms.json" > /dev/null
  python3 scripts/recomp/eh_gen.py gen eht "$S/eht.nso" "$EHTB" "$G/eht" --simd c 2>&1 | grep -E "wrote|eh_gen"
  export EXTRA="${EXTRA:-} -Dweak_import=weak"
  cc_all "$S/obj" -O1 "$G"/sdk/*.c "$G"/eht/*.c $T/eh_harness.c
}

probe_eh() {
  local S=$W/spike2; EXTRA=""   # eh_lsda.py/eh_pick.py write to work/recomp/spike2 (fixed)
  build_eh_common "$S" 0x7004000000 0x7008000000
  clang -o "$S/eh_test" "$S"/obj/sdk_*.o "$S"/obj/eht_*.o "$S/obj/test_eh_harness.o" -lm -lpthread || die "Link of the exception test failed."
  local TESTS; TESTS=$(eh_list "$S/eht.json" 0x7008000000)
  tm "$S/eh_test" "$S" "$S/sdk.img" "$S/eht.img" $TESTS || {
    echo "NOTE: run with all tests failed; repeat without test_longjmp (T7), to measure T0-T6 and the throughput"
    tm "$S/eh_test" "$S" "$S/sdk.img" "$S/eht.img" $(EXCL=test_longjmp eh_list "$S/eht.json" 0x7008000000)
  }
}

probe_eh_real() {
  local S=$W/spike2 G=$W/spike2/gen MAINBASE=0x7040000000 PER=${PER_KIND:-60}
  [ -f "$S/eh_test" ] || die "Run 'probe.sh eh' first (SDK objects, test module)."
  python3 scripts/recomp/mkimg.py work/exefs/main main --base $MAINBASE --out "$S" --link "$S/sdk.syms.json" > /dev/null
  python3 scripts/recomp/eh_pick.py --base $MAINBASE --per-kind "$PER"
  python3 scripts/recomp/eh_gen.py gen main work/exefs/main $MAINBASE "$G/mainsub" --only "$S/real_only.txt" --simd c 2>&1 | grep -E "wrote|eh_gen"
  export EXTRA="-Dweak_import=weak"
  cc_all "$S/obj_real" -O1 "$G"/mainsub/*.c
  clang -o "$S/eh_real" "$S"/obj/sdk_*.o "$S"/obj/eht_*.o "$S/obj/test_eh_harness.o" "$S"/obj_real/*.o -lm -lpthread || die "Link failed."
  local RUN; RUN=$(python3 -c "import json; print(hex(0x7008000000 + json.load(open('$S/eht.json'))['syms']['test_run']))")
  tm "$S/eh_real" "$S" "$S/sdk.img" "$S/eht.img" real="$S/real_spec.txt" mainimg="$S/main.img" \
    alloc=$(sym "$S/sdk.syms.json" __cxa_allocate_exception) throw=$(sym "$S/sdk.syms.json" __cxa_throw) zti=$(sym "$S/sdk.syms.json" _ZTIi) test_run="$RUN"
}

probe_rebase32() {
  local S=$P/r32 G=$P/r32/gen SDKB=0x01000000 EHTB=0x02000000
  mkdir -p "$S/obj" "$G"; rm -f "$S/hle.txt"
  python3 scripts/recomp/mkimg.py work/exefs/sdk sdk --base $SDKB --out "$S" --hle-base 0x08000000 > /dev/null
  python3 scripts/recomp/eh_gen.py gen sdk work/exefs/sdk $SDKB "$G/sdk" --simd c --hle $T/hle_symbols.txt 2>&1 | grep -E "wrote|eh_gen"
  guest_aarch64 $T/eh_guest.cpp "$S/eh_guest.s"
  clang --target=aarch64-linux-gnu -c "$S/eh_guest.s" -o "$S/eh_guest.o"
  python3 scripts/recomp/mini_link.py "$S/eh_guest.o" "$S/eht" --base $EHTB --syms "$S/sdk.syms.json" > /dev/null
  python3 scripts/recomp/eh_gen.py gen eht "$S/eht.nso" $EHTB "$G/eht" --simd c 2>&1 | grep -E "wrote|eh_gen"
  export EXTRA="-DREBASE32 -I scripts/recomp/rt32 -Dweak_import=weak"
  cc_all "$S/obj" -O1 "$G"/sdk/*.c "$G"/eht/*.c $T/eh_harness.c
  clang -o "$S/eh_test32" "$S"/obj/*.o -lm -lpthread || die "Link failed."
  local TESTS; TESTS=$(eh_list "$S/eht.json" 0x02000000)
  tm "$S/eh_test32" "$S" "$S/sdk.img" "$S/eht.img" $TESTS || {
    echo "NOTE: run with all tests failed; repeat without test_longjmp (T7)"
    tm "$S/eh_test32" "$S" "$S/sdk.img" "$S/eht.img" $(EXCL=test_longjmp eh_list "$S/eht.json" 0x02000000)
  }
}

probe_gc() {
  local S=$P/gc; mkdir -p "$S/gen"; echo '{}' > "$S/empty.json"
  clang --target=aarch64-linux-gnu -O1 -ffreestanding -fno-pic -fno-asynchronous-unwind-tables -funwind-tables -c $T/gc_guest.c -o "$S/gc_guest.o"
  python3 scripts/recomp/mini_link.py "$S/gc_guest.o" "$S/gct" --base 0x7008000000 --syms "$S/empty.json" > /dev/null
  python3 scripts/recomp/eh_gen.py gen gct "$S/gct.nso" 0x7008000000 "$S/gen" --simd c 2>&1 | grep -E "wrote|eh_gen"
  EXTRA="" cc_all "$S/obj" -O1 "$S"/gen/*.c scripts/recomp/linux/gc_prove_linux.c
  clang -o "$S/gc_prove" "$S"/obj/*.o -lpthread || die "Link failed."
  CHURN_OFF=$(python3 -c "import json; print(hex(json.load(open('$S/gct.json'))['syms']['churn']))") tm "$S/gc_prove"
}

probe_bench() {
  local S=$P/bench OPT=${OPT:--O1}; mkdir -p "$S/gen"; echo '{}' > "$S/empty.json"
  clang --target=aarch64-linux-gnu -O2 -ffreestanding -fno-pic -fno-asynchronous-unwind-tables -funwind-tables -c $T/bench_guest.c -o "$S/bench_guest.o"
  python3 scripts/recomp/mini_link.py "$S/bench_guest.o" "$S/gbn" --base 0x7008000000 --syms "$S/empty.json" > /dev/null
  python3 scripts/recomp/eh_gen.py gen gbn "$S/gbn.nso" 0x7008000000 "$S/gen" --simd c 2>&1 | grep -E "wrote|eh_gen"
  EXTRA="" cc_all "$S/obj" "$OPT" "$S"/gen/*.c
  clang -O2 -w -march=x86-64-v3 -I scripts/recomp/rt -I $LAS/runtime -I $T -c $T/bench_prove.c -o "$S/bench_prove.o"
  clang -o "$S/bench_prove" "$S/bench_prove.o" "$S"/obj/*.o -lm
  off() { python3 -c "import json,sys; print(hex(json.load(open('$S/gbn.json'))['syms'][sys.argv[1]]))" "$1"; }
  echo "Generated C with $OPT (x86 c mode), guest code aarch64 -O2, native comparison version -O2 -march=x86-64-v3"
  GIMG=$S/gbn.img OFF_INT=$(off bench_int) OFF_CALLS=$(off bench_calls) OFF_FLOAT=$(off bench_float) OFF_IND=$(off bench_indirect) "$S/bench_prove"
}

boot_images() {
  local S=$P/boot; mkdir -p "$S"
  bb() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; esac; }
  rm -f "$S/hle.txt"
  for m in main sdk subsdk0; do python3 scripts/recomp/mkimg.py work/exefs/$m $m --base "$(bb $m)" --out "$S" > /dev/null; done
  rm -f "$S/hle.txt"
  for m in main sdk subsdk0; do
    python3 scripts/recomp/mkimg.py work/exefs/$m $m --base "$(bb $m)" --out "$S" --link "$S/main.syms.json" --link "$S/sdk.syms.json" --link "$S/subsdk0.syms.json" > /dev/null
  done
}
START_ADDR() { python3 -c "
import json
m = json.load(open('$P/boot/sdk.syms.json'))
print(hex(next(v for k, v in m.items() if k.startswith('_ZN2nn4init5Start'))))"; }

probe_boot() {
  local S=$P/boot OBJ=$W/obj4-c
  ls "$OBJ"/*.o > /dev/null 2>&1 || die "No objects in $OBJ (run compile.sh/build.sh first)."
  boot_images
  clang -O1 $CF -Dweak_import=weak -c $T/boot_probe.c -o "$S/boot_probe.o"
  clang -o "$S/boot_probe" "$S/boot_probe.o" "$OBJ"/*.o -lm -lpthread || die "Link of the boot probe failed."
  tm "$S/boot_probe" "$S" "$(START_ADDR)"
}

probe_boot_las() {
  local S=$P/boot OBJ=$W/obj4-c L=$LAS/runtime
  [ -f "$S/boot_probe.o" ] || die "Run 'probe.sh boot' first."
  clang -O1 $CF -DUSE_LAS_IPC -c $T/boot_probe.c -o "$S/boot_probe_las.o"
  for f in $L/ipc.c $L/services/am.c $L/services/misc.c $L/services/acc.c $L/services/hid_set.c $L/services/time.c $T/las_shim.c; do
    clang -O1 -w -fPIC -I $L -c "$f" -o "$S/las_$(basename "$f" .c).o" || die "LAS service source $f cannot be compiled under Linux."
  done
  clang -o "$S/boot_probe_las" "$S/boot_probe_las.o" "$S"/las_*.o "$OBJ"/*.o -lm -lpthread || die "Link failed."
  tm "$S/boot_probe_las" "$S" "$(START_ADDR)"
}

probe_bdsp() {   # Gate-1 runtime (scripts/recomp/rt-bdsp), Mach API via scripts/recomp/linux/compat
  local RTD=scripts/recomp/rt-bdsp OBJ=$W/obj4-c O=$W/rt-bdsp-x86
  [ -d "$RTD" ] || die "scripts/recomp/rt-bdsp is missing."
  ls "$OBJ"/*.o > /dev/null 2>&1 || die "No objects in $OBJ (run build_all.sh first)."
  mkdir -p "$O"
  export O CF2="-O1 -g -w -fPIC -march=x86-64-v3 -Wno-error=implicit-function-declaration -I scripts/recomp/linux/compat -I scripts/recomp/rt -I $LAS/runtime -I $RTD"
  ls "$RTD"/*.c scripts/recomp/linux/compat/nvn_stub.c | xargs -P "$JOBS" -I{} bash -c 'clang $CF2 -c "{}" -o "$O/$(basename "{}" .c).o"' || die "Compilation of the runtime failed (working state of ap-recomp-3 or Mach replacement in linux/compat incomplete; see errors above). From Gate 2 (NVN/Metal) the Linux probe is no longer intended."
  clang -o "$O/bdsp_boot" "$O"/*.o "$OBJ"/*.o -lm -lpthread -ldl || die "Link failed (runtime needs symbols that do not exist under Linux)."
  bash "$RTD/mkimages.sh" > /dev/null
  echo "--- bdsp_boot (time limit ${BDSP_TIMEOUT:-30} s; RomFS and NPDM are intentionally not present on Linux: the run ends there)"
  BDSP_TIMEOUT=${BDSP_TIMEOUT:-30} BDSP_NPDM=${BDSP_NPDM:-/nonexistent} "${TIMEV[@]}" "$O/bdsp_boot" 2>&1 | head -${BDSP_LINES:-80}
}

run() { echo "=================== $1"; "probe_$2"; local rc=$?; echo "=================== $1 beendet, Code $rc"; return $rc; }
case "${1:-}" in
  eh) run eh eh;;
  eh-real) run eh-real eh_real;;
  rebase32) run rebase32 rebase32;;
  gc) run gc gc;;
  bench) run bench bench;;
  boot) run boot boot;;
  boot-las) run boot-las boot_las;;
  bdsp) run bdsp bdsp;;
  all) for t in eh eh_real rebase32 gc bench boot boot_las; do run "$t" "$t" || true; done;;
  *) die "Usage: probe.sh eh|eh-real|rebase32|gc|bench|boot|boot-las|bdsp|all";;
esac
