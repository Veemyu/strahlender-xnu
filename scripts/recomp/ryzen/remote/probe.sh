#!/bin/bash
# Läuft auf dem Ryzen: Linux-Gegenstücke der Spike-Tests aus scripts/recomp/test/ (x86-Host, c-Modus, `weak_import` → `weak`).
# Aufruf: probe.sh <test>   mit test = eh | eh-real | rebase32 | gc | bench | boot | boot-las | alle
#   eh        Exception-Test (T0-T6) mit dem echten SDK-Modul          (Mac: run_eh_test.sh)
#   eh-real   Wurf-Test mit echten LSDA-Funktionen aus main (PER_KIND, Standard 60)   (run_eh_real.sh; nach eh)
#   rebase32  32-Bit-Gastadressen (rt32)                               (run_eh_rebase32.sh)
#   gc        Anhalten eines Gastthreads an beliebiger Stelle (Linux: Signal statt Mach)   (run_gc_proof.sh)
#   bench     Mikro-Benchmarks rekompiliert gegen nativ                (run_bench.sh)
#   boot      Boot-Probe: main+sdk+subsdk0 bis zum ersten Blocker      (run_boot_probe.sh; braucht compile.sh)
#   boot-las  wie boot, mit der IPC-/Dienstschicht von LASRecomp       (run_boot_probe_las.sh; nach boot)
#   bdsp      Gate-1-Laufzeit scripts/recomp/rt-bdsp (ap-recomp-3) unter Linux bauen und starten; endet am RomFS (nicht auf dem Ryzen)
# Alles unter work/recomp/probe/. Nichts wird abgespielt, keine Grafik.
source "$(dirname "$0")/common.sh"
T=scripts/recomp/test
P=$W/probe
CF="-fno-strict-aliasing -fvisibility=hidden -w -fPIC -march=x86-64-v3 -I scripts/recomp/rt -I $LAS/runtime"
export CF
mkdir -p "$P"

# cc_all <objdir> <opt> <dateien...>: parallel übersetzen (Objektname <ordner>_<datei>.o), Fehler abbrechen
cc_all() {
  local out=$1 opt=$2; shift 2
  rm -rf "$out"   # keine Altlasten aus Läufen mit anderer Chunk-Einteilung (doppelte Symbole)
  mkdir -p "$out"
  export out opt
  printf '%s\n' "$@" | xargs -P "$JOBS" -I{} bash -c 'o="$out/$(basename "$(dirname "{}")")_$(basename "{}" .c).o"; op=$opt; [ "$(stat -c %s "{}")" -gt 300000 ] && [ "$(grep -c "^void f_.*) {\$" "{}")" = 1 ] && op=-O0; [ "$o" -nt "{}" ] || clang $op $EXTRA $CF -c "{}" -o "$o"' \
    || die "Übersetzung fehlgeschlagen."
}
tm() { echo "--- $*"; "${TIMEV[@]}" "$@"; }
sym() { python3 -c "import json,sys; print(hex(json.load(open('$1'))[sys.argv[1]]))" "$2"; }
eh_list() {   # <json> <basis>: test_*=<Adresse> des Testmoduls (EXCL=name schließt einen Test aus)
  python3 -c "
import json, os, sys
m = json.load(open(sys.argv[1]))['syms']
print(' '.join(f'{k}={int(sys.argv[2], 16) + v:#x}' for k, v in m.items() if k.startswith('test_') and k != os.environ.get('EXCL')))" "$1" "$2"
}

guest_aarch64() {   # <quelle.cpp> <ausgabe.s>   (synthetisches Gastprogramm, sdata4-EH wie die Switch-ABI)
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
  local S=$W/spike2; EXTRA=""   # eh_lsda.py/eh_pick.py schreiben fest nach work/recomp/spike2
  build_eh_common "$S" 0x7004000000 0x7008000000
  clang -o "$S/eh_test" "$S"/obj/sdk_*.o "$S"/obj/eht_*.o "$S/obj/test_eh_harness.o" -lm -lpthread || die "Link des Exception-Tests fehlgeschlagen."
  local TESTS; TESTS=$(eh_list "$S/eht.json" 0x7008000000)
  tm "$S/eh_test" "$S" "$S/sdk.img" "$S/eht.img" $TESTS || {
    echo "HINWEIS: Lauf mit allen Tests fehlgeschlagen; Wiederholung ohne test_longjmp (T7), um T0-T6 und den Durchsatz zu messen"
    tm "$S/eh_test" "$S" "$S/sdk.img" "$S/eht.img" $(EXCL=test_longjmp eh_list "$S/eht.json" 0x7008000000)
  }
}

probe_eh_real() {
  local S=$W/spike2 G=$W/spike2/gen MAINBASE=0x7040000000 PER=${PER_KIND:-60}
  [ -f "$S/eh_test" ] || die "Zuerst 'probe.sh eh' ausführen (SDK-Objekte, Testmodul)."
  python3 scripts/recomp/mkimg.py work/exefs/main main --base $MAINBASE --out "$S" --link "$S/sdk.syms.json" > /dev/null
  python3 scripts/recomp/eh_pick.py --base $MAINBASE --per-kind "$PER"
  python3 scripts/recomp/eh_gen.py gen main work/exefs/main $MAINBASE "$G/mainsub" --only "$S/real_only.txt" --simd c 2>&1 | grep -E "wrote|eh_gen"
  export EXTRA="-Dweak_import=weak"
  cc_all "$S/obj_real" -O1 "$G"/mainsub/*.c
  clang -o "$S/eh_real" "$S"/obj/sdk_*.o "$S"/obj/eht_*.o "$S/obj/test_eh_harness.o" "$S"/obj_real/*.o -lm -lpthread || die "Link fehlgeschlagen."
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
  clang -o "$S/eh_test32" "$S"/obj/*.o -lm -lpthread || die "Link fehlgeschlagen."
  local TESTS; TESTS=$(eh_list "$S/eht.json" 0x02000000)
  tm "$S/eh_test32" "$S" "$S/sdk.img" "$S/eht.img" $TESTS || {
    echo "HINWEIS: Lauf mit allen Tests fehlgeschlagen; Wiederholung ohne test_longjmp (T7)"
    tm "$S/eh_test32" "$S" "$S/sdk.img" "$S/eht.img" $(EXCL=test_longjmp eh_list "$S/eht.json" 0x02000000)
  }
}

probe_gc() {
  local S=$P/gc; mkdir -p "$S/gen"; echo '{}' > "$S/empty.json"
  clang --target=aarch64-linux-gnu -O1 -ffreestanding -fno-pic -fno-asynchronous-unwind-tables -funwind-tables -c $T/gc_guest.c -o "$S/gc_guest.o"
  python3 scripts/recomp/mini_link.py "$S/gc_guest.o" "$S/gct" --base 0x7008000000 --syms "$S/empty.json" > /dev/null
  python3 scripts/recomp/eh_gen.py gen gct "$S/gct.nso" 0x7008000000 "$S/gen" --simd c 2>&1 | grep -E "wrote|eh_gen"
  EXTRA="" cc_all "$S/obj" -O1 "$S"/gen/*.c scripts/recomp/ryzen/gc_prove_linux.c
  clang -o "$S/gc_prove" "$S"/obj/*.o -lpthread || die "Link fehlgeschlagen."
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
  echo "Erzeugtes C mit $OPT (x86-c-Modus), Gastcode aarch64 -O2, native Vergleichsversion -O2 -march=x86-64-v3"
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
  ls "$OBJ"/*.o > /dev/null 2>&1 || die "Keine Objekte in $OBJ (erst compile.sh/build.sh)."
  boot_images
  clang -O1 $CF -Dweak_import=weak -c $T/boot_probe.c -o "$S/boot_probe.o"
  clang -o "$S/boot_probe" "$S/boot_probe.o" "$OBJ"/*.o -lm -lpthread || die "Link der Boot-Probe fehlgeschlagen."
  tm "$S/boot_probe" "$S" "$(START_ADDR)"
}

probe_boot_las() {
  local S=$P/boot OBJ=$W/obj4-c L=$LAS/runtime
  [ -f "$S/boot_probe.o" ] || die "Zuerst 'probe.sh boot' ausführen."
  clang -O1 $CF -DUSE_LAS_IPC -c $T/boot_probe.c -o "$S/boot_probe_las.o"
  for f in $L/ipc.c $L/services/am.c $L/services/misc.c $L/services/acc.c $L/services/hid_set.c $L/services/time.c $T/las_shim.c; do
    clang -O1 -w -fPIC -I $L -c "$f" -o "$S/las_$(basename "$f" .c).o" || die "LAS-Dienstquelle $f lässt sich unter Linux nicht übersetzen."
  done
  clang -o "$S/boot_probe_las" "$S/boot_probe_las.o" "$S"/las_*.o "$OBJ"/*.o -lm -lpthread || die "Link fehlgeschlagen."
  tm "$S/boot_probe_las" "$S" "$(START_ADDR)"
}

probe_bdsp() {   # Gate-1-Laufzeit von ap-recomp-3 (scripts/recomp/rt-bdsp, nur mit sync.sh --mit-rt-bdsp), Mach-API über ryzen/compat
  local RTD=scripts/recomp/rt-bdsp OBJ=$W/obj4-c O=$W/rt-bdsp-x86
  [ -d "$RTD" ] || die "scripts/recomp/rt-bdsp fehlt auf dem Ryzen (sync.sh --mit-rt-bdsp)."
  ls "$OBJ"/*.o > /dev/null 2>&1 || die "Keine Objekte in $OBJ (erst build.sh)."
  mkdir -p "$O"
  export O CF2="-O1 -g -w -fPIC -march=x86-64-v3 -Wno-error=implicit-function-declaration -I scripts/recomp/ryzen/compat -I scripts/recomp/rt -I $LAS/runtime -I $RTD"
  ls "$RTD"/*.c scripts/recomp/ryzen/compat/nvn_stub.c | xargs -P "$JOBS" -I{} bash -c 'clang $CF2 -c "{}" -o "$O/$(basename "{}" .c).o"' || die "Übersetzung der Laufzeit fehlgeschlagen (Arbeitsstand von ap-recomp-3 oder Mach-Ersatz in ryzen/compat unvollständig; Fehler oben). Ab Gate 2 (NVN/Metal) ist die Linux-Probe nicht mehr vorgesehen."
  clang -o "$O/bdsp_boot" "$O"/*.o "$OBJ"/*.o -lm -lpthread -ldl || die "Link fehlgeschlagen (Laufzeit braucht Symbole, die es unter Linux nicht gibt)."
  bash "$RTD/mkimages.sh" > /dev/null
  echo "--- bdsp_boot (Zeitlimit ${BDSP_TIMEOUT:-30} s; RomFS und NPDM sind absichtlich nicht auf dem Ryzen: Lauf endet dort)"
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
  alle) for t in eh eh_real rebase32 gc bench boot boot_las; do run "$t" "$t" || true; done;;
  *) die "Aufruf: probe.sh eh|eh-real|rebase32|gc|bench|boot|boot-las|bdsp|alle";;
esac
