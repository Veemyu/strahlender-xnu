#!/bin/bash
# Runs locally on Linux: generates the C of all four modules with the LAS lifter (eh_gen.py) and measures time/RAM/size.
# Usage: gen.sh [c|asm] [modul ...]      Default: c, all four modules in turn (like gen_all.sh on the Mac)
#   c   = portable C (simd.h), the path for x86 hosts
#   asm = inline asm for AArch64 hosts; on x86 Linux only producible for comparison (not compilable)
# Output: work/recomp/gen4-<modus>/<modul>/*.c, logs/gen-<modus>.stats (numbers), work/recomp/gen4-<modus>.sha256 (tree checksum)
source "$(dirname "$0")/common.sh"
MODE=${1:-c}; shift
case "$MODE" in c|asm) ;; *) die "Mode must be c or asm, not '$MODE'.";; esac
mods=("$@"); [ ${#mods[@]} -eq 0 ] && mods=(rtld main sdk subsdk0)
OUT=$W/gen4-$MODE
ST=logs/gen-$MODE.stats
mkdir -p "$OUT" logs
for m in "${mods[@]}"; do [ -f "work/exefs/$m" ] || die "work/exefs/$m is missing (extract it first, see docs/BUILD.md section 4.1)."; done
: > "$ST"
tot0=$(date +%s.%N)
for m in "${mods[@]}"; do
  glog=logs/gen-$MODE-$m.log
  /usr/bin/time -f "TIME %e %U %S %M" python3 scripts/recomp/eh_gen.py gen "$m" "work/exefs/$m" "$(base_of "$m")" "$OUT/$m" --simd "$MODE" > "$glog" 2>&1 \
    || { tail -20 "$glog"; die "Generator for $m failed (log: $glog)."; }
  tm=$(grep '^TIME' "$glog" | tail -1)
  fn=$(grep -o "[0-9]* functions" "$glog" | head -1 | cut -d' ' -f1)
  ch=$(ls "$OUT/$m"/*.c | wc -l)
  bytes=$(cat "$OUT/$m"/*.c | wc -c)
  echo "module=$m functions=$fn files=$ch c_bytes=$bytes $tm" | tee -a "$ST"
done
tot1=$(date +%s.%N)
echo "gesamt_wall_s=$(awk -v a="$tot1" -v b="$tot0" 'BEGIN{printf "%.1f", a-b}')" | tee -a "$ST"
echo "c_bytes_gesamt=$(cat "$OUT"/*/*.c | wc -c)" | tee -a "$ST"
# Checksum of the tree (names + content) for comparison with the Mac run
(cd "$OUT" && for f in $(ls */*.c | sort); do echo "$f $(sha256sum < "$f" | cut -c1-16)"; done) > "$W/gen4-$MODE.sha256"
echo "baum_sha256=$(sha256sum < "$W/gen4-$MODE.sha256" | cut -c1-16)" | tee -a "$ST"
