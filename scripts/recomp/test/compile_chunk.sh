#!/bin/bash
# Übersetzt eine erzeugte C-Datei nach work/recomp/spike2/obj (nur wenn neuer); misst die Zeit je Datei.
# Aufruf: compile_chunk.sh <datei.c> [Ausgabeordner]
set -u
cd "$(dirname "$0")/../../.."
src=$1
S=${2:-work/recomp/spike2/obj}
mkdir -p "$S"
o="$S/$(basename "$(dirname "$src")")_$(basename "$src" .c).o"
[ "$o" -nt "$src" ] && exit 0
t0=$(date +%s)
/usr/bin/time -l clang ${OPT:--O1} ${EXTRA:-} -fno-strict-aliasing -fvisibility=hidden -w -I scripts/recomp/rt -I research/LASRecomp/runtime -c "$src" -o "$o" 2> "$o.time" || { echo "FEHLER $src"; cat "$o.time"; exit 1; }
t1=$(date +%s)
rss=$(awk '/maximum resident/ {print int($1/1048576)}' "$o.time")
echo "$(basename "$o") $((t1 - t0))s ${rss}MB" >> "$S/compile_times.txt"
rm -f "$o.time"
