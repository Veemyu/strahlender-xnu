#!/bin/bash
# Baut die BDSP-Laufzeit (scripts/recomp/rt-bdsp/*.c) und bindet sie mit den übersetzten Gastmodulen (work/recomp/obj4/*.o)
# zu work/recomp/bdsp_boot. Inkrementell: Laufzeitdateien nur bei Änderung, Link nur wenn eine Eingabe neuer ist.
# Aufruf: build.sh [-DMakro ...]      Umgebung: OBJ=work/recomp/obj4  RT=work/recomp/rt-bdsp  OUT=work/recomp/bdsp_boot
set -euo pipefail
cd "$(dirname "$0")/../../.."
OBJ=${OBJ:-work/recomp/obj4}
RT=${RT:-work/recomp/rt-bdsp}
OUT=${OUT:-work/recomp/bdsp_boot}
mkdir -p "$RT"
SRC=scripts/recomp/rt-bdsp
INC="-I scripts/recomp/rt -I research/LASRecomp/runtime -I $SRC"
objs=()
for f in "$SRC"/*.c; do
  o="$RT/$(basename "$f" .c).o"
  objs+=("$o")
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ "$SRC/bdsp.h" -nt "$o" ] || [ "$SRC/guestmem.h" -nt "$o" ]; then
    clang -O1 -g -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function $INC "$@" -c "$f" -o "$o"
  fi
done
newest=$(ls -t "${objs[@]}" | head -1)
if [ ! -x "$OUT" ] || [ "$newest" -nt "$OUT" ] || [ -n "$(find "$OBJ" -name '*.o' -newer "$OUT" -print -quit)" ]; then
  clang -o "$OUT" "${objs[@]}" "$OBJ"/*.o
  echo "gelinkt: $OUT"
else
  echo "aktuell: $OUT"
fi
