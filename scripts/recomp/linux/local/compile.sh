#!/bin/bash
# Runs locally on Linux: compiles the generated C (work/recomp/gen4-<modus>) with JOBS parallel clang calls and measures
# wall clock/CPU/RAM per chunk, total peak RAM (sampler on /proc/meminfo) and links the target library.
# As scripts/recomp/build_all.sh on the Mac: -O1; single-function files > 1 MB with -O0.
# Usage: [TAG=name] [THRESH_O0=bytes] compile.sh [c] [--force]   --force: discard objects (full rebuild); otherwise only newer/missing sources
#   TAG stores objects/numbers in obj4-c-<TAG>/ and build-c-<TAG>.* (comparison runs); THRESH_O0 default 1000000
# Output: work/recomp/obj4-<modus>/*.o, logs/build-<modus>.times (per chunk: name wall user sys maxrss_KB c_bytes opt), logs/build-<modus>.stats
source "$(dirname "$0")/common.sh"
MODE=c; FORCE=0
for a in "$@"; do case "$a" in c) MODE=c;; --force) FORCE=1;; *) die "Unknown argument '$a'.";; esac; done
GEN=${GEN:-$W/gen4-$MODE}
OBJ=$W/obj4-$MODE${TAG:+-$TAG}
TIMES=logs/build-$MODE${TAG:+-$TAG}.times
ST=logs/build-$MODE${TAG:+-$TAG}.stats
THRESH_O0=${THRESH_O0:-300000}   # single-function files above this size (bytes of C) with -O0 (Mac spike: 1000000; see docs/recomp-linux.md)
[ -d "$GEN" ] || die "$GEN is missing (run gen.sh $MODE first)."
mkdir -p "$OBJ" logs
[ "$FORCE" = 1 ] && rm -f "$OBJ"/*.o "$OBJ"/*.so
: > "$TIMES"
FLAGS=$(cflags_x86)
export FLAGS OBJ TIMES
# Headers and flags are not dependencies of the individual chunks: change → full rebuild
STAMP=$( (cat scripts/recomp/rt/cpu.h $LAS/runtime/cpu.h $LAS/runtime/simd.h $LAS/runtime/simd_fp.h 2>/dev/null; echo "$FLAGS $THRESH_O0") | sha256sum | cut -c1-16)
if [ -f "$OBJ/.stamp" ] && [ "$(cat "$OBJ/.stamp")" != "$STAMP" ]; then echo "Header or flags changed: full rebuild"; rm -f "$OBJ"/*.o "$OBJ"/*.so; fi
echo "$STAMP" > "$OBJ/.stamp"

: > "$OBJ/list_O0.txt"; : > "$OBJ/list_O1.txt"
for f in "$GEN"/*/*.c; do
  size=$(stat -c %s "$f")
  if [ "$size" -gt "$THRESH_O0" ] && [ "$(grep -c '^void f_.*) {$' "$f")" = "1" ]; then echo "$size $f" >> "$OBJ/list_O0.txt"; else echo "$size $f" >> "$OBJ/list_O1.txt"; fi
done
sort -rn -o "$OBJ/list_O0.txt" "$OBJ/list_O0.txt"; sort -rn -o "$OBJ/list_O1.txt" "$OBJ/list_O1.txt"
# Remove objects without source (chunk renumbering after a generator change), otherwise they end up in the library
cat "$OBJ/list_O0.txt" "$OBJ/list_O1.txt" | cut -d' ' -f2 | while read -r f; do echo "$(basename "$(dirname "$f")")_$(basename "$f" .c).o"; done | sort > "$OBJ/expected.txt"
ls "$OBJ" | grep '\.o$' | sort | comm -23 - "$OBJ/expected.txt" | while read -r stale; do echo "removing stale object $stale"; rm -f "$OBJ/$stale"; done
echo "O1: $(wc -l < "$OBJ/list_O1.txt") files, O0: $(wc -l < "$OBJ/list_O0.txt") files, Jobs $JOBS, rebuild=$FORCE"

one() {   # <opt> <size> <source>
  local opt=$1 size=$2 src=$3
  local o="$OBJ/$(basename "$(dirname "$src")")_$(basename "$src" .c).o"
  [ "$o" -nt "$src" ] && exit 0
  /usr/bin/time -f "%e %U %S %M" -o "$o.t" clang $opt $FLAGS -c "$src" -o "$o" 2> "$o.err" || { echo "ERROR $src"; head -20 "$o.err"; exit 1; }
  echo "$(basename "$o") $(cat "$o.t") $size $opt" >> "$TIMES"
  rm -f "$o.t" "$o.err"
}
export -f one

base_avail=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
( min=$base_avail; while :; do a=$(awk '/MemAvailable/ {print $2}' /proc/meminfo); [ "$a" -lt "$min" ] && { min=$a; echo "$((base_avail - min))" > "$OBJ/peak_ram_kb.txt"; }; sleep 1; done ) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT
echo 0 > "$OBJ/peak_ram_kb.txt"

t0=$(date +%s.%N)
rc=0
# Large single functions first (-O0), then everything else by size, descending (better utilization at the end)
cut -d' ' -f1,2 "$OBJ/list_O0.txt" | xargs -r -P "$JOBS" -L 1 bash -c 'one -O0 "$0" "$1"' || rc=1
cut -d' ' -f1,2 "$OBJ/list_O1.txt" | xargs -r -P "$JOBS" -L 1 bash -c 'one -O1 "$0" "$1"' || rc=1
t1=$(date +%s.%N)
[ "$rc" = 0 ] || die "At least one file was not compiled (see above)."

wall=$(awk -v a="$t1" -v b="$t0" 'BEGIN{printf "%.1f", a-b}')
{
  echo "mode=$MODE tag=${TAG:-} jobs=$JOBS force=$FORCE threshold_O0=$THRESH_O0"
  echo "compiled_files=$(wc -l < "$TIMES")  of=$(cat "$OBJ/list_O0.txt" "$OBJ/list_O1.txt" | wc -l)"
  echo "wall_s=$wall"
  awk '{w+=$2; u+=$3; s+=$4; if ($5>m) m=$5; n++} END {printf "sum_wall_s=%.1f sum_user_s=%.1f sum_sys_s=%.1f max_chunk_rss_mb=%d\n", w, u, s, m/1024}' "$TIMES"
  echo "peak_ram_total_mb=$(( $(cat "$OBJ/peak_ram_kb.txt") / 1024 ))"
  echo "slowest_chunks (name wall_s user_s maxrss_mb c_bytes opt):"
  sort -k2 -rn "$TIMES" | head -8 | awk '{printf "  %s %.1f %.1f %d %d %s\n", $1, $2, $3, $5/1024, $6, $7}'
  echo "largest_ram_chunks:"
  sort -k5 -rn "$TIMES" | head -4 | awk '{printf "  %s %.1f s %d MB %d B %s\n", $1, $2, $5/1024, $6, $7}'
  awk '{ if ($2>10) a++; if ($2>60) b++ } END {printf "over_10s=%d over_60s=%d\n", a, b}' "$TIMES"
  sort -k2 -n "$TIMES" | awk '{v[NR]=$2} END {if (NR) printf "median_wall_s=%.2f\n", v[int((NR+1)/2)]}'
} | tee "$ST"

# Link to the target library (Linux counterpart of libgame.dylib)
l0=$(date +%s.%N)
clang -shared -o "$OBJ/libgame.so" "$OBJ"/*.o -Wl,-z,notext 2> "$OBJ/link.err" || { head -20 "$OBJ/link.err"; die "Link failed."; }
l1=$(date +%s.%N)
{
  echo "link_s=$(awk -v a="$l1" -v b="$l0" 'BEGIN{printf "%.1f", a-b}')"
  echo "objekte_mb=$(du -sm --apparent-size "$OBJ" | cut -f1)  (without library approx. $(cat "$OBJ"/*.o | wc -c | awk '{printf "%d", $1/1048576}'))"
  echo "libgame_so_bytes=$(stat -c %s "$OBJ/libgame.so")"
  size "$OBJ/libgame.so" | tail -1
} | tee -a "$ST"
