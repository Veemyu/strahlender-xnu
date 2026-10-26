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
export OBJ
# remove stale objects (the chunk file no longer exists, e.g. after a changed window split), otherwise duplicate symbols at link time
for o in "$OBJ"/*.o; do
  [ -e "$o" ] || continue
  b=$(basename "$o" .o)
  m=${b%%_*}
  rest=${b#*_}
  [ -f "$GEN/$m/$rest.c" ] || rm -f "$o"
done
rm -f "$OBJ/.compile-total"
: > "$OBJ/list_O1.txt"; : > "$OBJ/list_O0.txt"
for f in "$GEN"/*/*.c; do
  size=$(stat -f %z "$f")
  if [ "$size" -gt "${O0_BYTES:-1000000}" ] && [ "$(grep -c '^void f_.*) {$' "$f")" = "1" ]; then echo "$f" >> "$OBJ/list_O0.txt"; else echo "$f" >> "$OBJ/list_O1.txt"; fi
done
echo "O1: $(wc -l < "$OBJ/list_O1.txt") files, O0: $(wc -l < "$OBJ/list_O0.txt") files, jobs $JOBS"
# One bounded queue keeps all slots busy across optimization levels.
# The outer app stage also hashes these inputs; this stamp protects direct CLI use.
SIGNATURE=$( { cat scripts/recomp/rt/cpu.h scripts/recomp/upstream/runtime/{cpu,simd,simd_fp}.h scripts/recomp/hot_o2.txt scripts/recomp/test/compile_chunk.sh; clang --version; printf '%s\n' "${EXTRA:-}" "${O0_BYTES:-1000000}" "$PWD" "$GEN"; } | shasum -a 256 | cut -d' ' -f1)
if [ ! -f "$OBJ/.compile-signature" ] || [ "$(cat "$OBJ/.compile-signature")" != "$SIGNATURE" ]; then
  for object in "$OBJ"/*.o "$OBJ"/*.o.o2; do [ ! -f "$object" ] || rm -f "$object"; done
fi
printf '%s\n' "$(( $(wc -l < "$OBJ/list_O0.txt") + $(wc -l < "$OBJ/list_O1.txt") ))" > "$OBJ/.compile-total.tmp"
mv "$OBJ/.compile-total.tmp" "$OBJ/.compile-total"
start=$(date +%s)
{
  while IFS= read -r f; do printf '%s\0%s\0' "$f" -O0; done < "$OBJ/list_O0.txt"
  while IFS= read -r f; do printf '%s\0%s\0' "$f" -O1; done < "$OBJ/list_O1.txt"
} | xargs -0 -P "$JOBS" -n 2 bash -c 'scripts/recomp/test/compile_chunk.sh "$1" "$OBJ" "$2"' _
# Hot functions (hot_o2.txt): recompile their files with -O2 if the object is not already -O2 (marker *.o2)
while read -r fn; do
  case "$fn" in ""|"#"*) continue ;; esac
  while IFS= read -r f; do
    o="$OBJ/$(basename "$(dirname "$f")")_$(basename "$f" .c).o"
    [ -e "$o.o2" ] && [ "$o.o2" -nt "$f" ] && continue
    rm -f "$o"; OPT=-O2 scripts/recomp/test/compile_chunk.sh "$f" "$OBJ" && : > "$o.o2"
  done < <(grep -l "^void $fn(.*{\$" "$GEN"/*/*.c || true)
done < scripts/recomp/hot_o2.txt
printf '%s\n' "$SIGNATURE" > "$OBJ/.compile-signature"
echo "Total compile time: $(( $(date +%s) - start )) s"
du -sh "$OBJ"
