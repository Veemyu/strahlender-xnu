#!/bin/bash
# Compiles the generated C of all four modules (work/recomp/gen4) in parallel and measures time/memory per file.
# Single functions with more than 1 MB of C are compiled with -O0 (outliers), everything else with -O1.
# Output: work/recomp/obj4/*.o, work/recomp/obj4/compile_times.txt ("<file> <s> <MB RSS>"), total time on stdout.
# Usage: build_all.sh [JOBS]   (default: host CPU/RAM-based; explicit JOBS overrides it)
# O0_BYTES: files with exactly one function and more than this many bytes of C count as outliers and are compiled with -O0 (default 1000000)
set -euo pipefail
cd "$(dirname "$0")/../.."
JOBS=${1:-$(python3 scripts/recomp/parallel_jobs.py)}
case "$JOBS" in ''|*[!0-9]*) echo "JOBS must be a positive integer" >&2; exit 2;; esac
[ "$JOBS" -ge 1 ] || { echo "JOBS must be at least 1" >&2; exit 2; }
GEN=${GEN:-work/recomp/gen4}
OBJ=${OBJ:-work/recomp/obj4}
mkdir -p "$OBJ"
# remove stale objects (the chunk file no longer exists, e.g. after a changed window split), otherwise duplicate symbols at link time
for o in "$OBJ"/*.o; do
  [ -e "$o" ] || continue
  b=$(basename "$o" .o)
  m=${b%%_*}
  rest=${b#*_}
  [ -f "$GEN/$m/$rest.c" ] || rm -f "$o"
done
: > "$OBJ/list_O1.txt"; : > "$OBJ/list_O0.txt"
for f in "$GEN"/*/*.c; do
  size=$(stat -f %z "$f")
  if [ "$size" -gt "${O0_BYTES:-1000000}" ] && [ "$(grep -c '^void f_.*) {$' "$f")" = "1" ]; then echo "$f" >> "$OBJ/list_O0.txt"; else echo "$f" >> "$OBJ/list_O1.txt"; fi
done
echo "O1: $(wc -l < "$OBJ/list_O1.txt") files, O0: $(wc -l < "$OBJ/list_O0.txt") files, jobs $JOBS"
start=$(date +%s)
OPT=-O0 xargs -P "$JOBS" -n 1 -I{} scripts/recomp/test/compile_chunk.sh {} "$OBJ" < "$OBJ/list_O0.txt"
OPT=-O1 xargs -P "$JOBS" -n 1 -I{} scripts/recomp/test/compile_chunk.sh {} "$OBJ" < "$OBJ/list_O1.txt"
# Hot functions (hot_o2.txt): recompile their files with -O2 if the object is not already -O2 (marker *.o2)
while read -r fn; do
  case "$fn" in ""|"#"*) continue ;; esac
  for f in $(grep -l "^void $fn(.*{\$" "$GEN"/*/*.c); do
    o="$OBJ/$(basename "$(dirname "$f")")_$(basename "$f" .c).o"
    [ -e "$o.o2" ] && [ "$o.o2" -nt "$f" ] && continue
    rm -f "$o"; OPT=-O2 scripts/recomp/test/compile_chunk.sh "$f" "$OBJ" && : > "$o.o2"
  done
done < scripts/recomp/hot_o2.txt
echo "Total compile time: $(( $(date +%s) - start )) s"
du -sh "$OBJ"
