#!/bin/bash
# Compiles a generated C file to work/recomp/spike2/obj (only if newer); measures the time per file.
# Usage: compile_chunk.sh <file.c> [output folder]
set -u
cd "$(dirname "$0")/../../.."
src=$1
S=${2:-work/recomp/spike2/obj}
mkdir -p "$S"
o="$S/$(basename "$(dirname "$src")")_$(basename "$src" .c).o"
[ "$o" -nt "$src" ] && exit 0
t0=$(date +%s)
/usr/bin/time -l clang ${OPT:--O1} ${EXTRA:-} -fno-strict-aliasing -fvisibility=hidden -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -c "$src" -o "$o" 2> "$o.time" || { echo "ERROR $src"; cat "$o.time"; exit 1; }
t1=$(date +%s)
rss=$(awk '/maximum resident/ {print int($1/1048576)}' "$o.time")
echo "$(basename "$o") $((t1 - t0))s ${rss}MB" >> "$S/compile_times.txt"
rm -f "$o.time"
