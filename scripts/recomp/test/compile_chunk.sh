#!/bin/bash
# Compiles a generated C file to work/recomp/spike2/obj (only if newer); measures the time per file.
# Usage: compile_chunk.sh <file.c> [output folder]
set -euo pipefail
cd "$(dirname "$0")/../../.."
src=$1
S=${2:-work/recomp/spike2/obj}
OPT=${3:-${OPT:--O1}}
case "$OPT" in -O0|-O1|-O2) ;; *) echo "Invalid optimization level" >&2; exit 2;; esac
mkdir -p "$S"
o="$S/$(basename "$(dirname "$src")")_$(basename "$src" .c).o"
if [ -f "$o" ]; then
  [ "$o" -nt "$src" ] && exit 0
  # macOS Bash 3.2 truncates -nt comparisons to whole seconds. BSD find
  # compares nanoseconds too, so fast builds do not repeatedly rebuild a chunk.
  newer=$(find "$src" -newer "$o" -print -quit)
  [ -n "$newer" ] || exit 0
fi
t0=$(date +%s)
tmp="$o.tmp.$$"
trap 'rm -f "$tmp"' EXIT
/usr/bin/time -l clang ${OPT:--O1} ${EXTRA:-} "-ffile-prefix-map=$PWD=." -fno-strict-aliasing -fvisibility=hidden -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -c "$src" -o "$tmp" 2> "$o.time" || { rm -f "$tmp"; echo "ERROR $src"; cat "$o.time"; exit 1; }
mv "$tmp" "$o"
t1=$(date +%s)
rss=$(awk '/maximum resident/ {print int($1/1048576)}' "$o.time")
echo "$(basename "$o") $((t1 - t0))s ${rss}MB" >> "$S/compile_times.txt"
rm -f "$o.time"
