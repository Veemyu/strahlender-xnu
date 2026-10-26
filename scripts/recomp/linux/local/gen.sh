#!/bin/bash
# Runs locally on Linux: generates the C of all four modules with the native C generator and measures time/RAM/size.
# Usage: gen.sh [c|asm] [modul ...]      Default: c, all four modules in turn (like gen_all.sh on the Mac)
#   c   = portable C (simd.h), the path for x86 hosts
#   asm = inline asm for AArch64 hosts; on x86 Linux only producible for comparison (not compilable)
# Output: work/recomp/gen4-<modus>/<modul>/*.c, logs/gen-<modus>.stats (numbers), work/recomp/gen4-<modus>.sha256 (tree checksum)
set -euo pipefail
source "$(dirname "$0")/common.sh"
MODE=${1:-c}
if [ "$#" -gt 0 ]; then shift; fi
case "$MODE" in c|asm) ;; *) die "Mode must be c or asm, not '$MODE'.";; esac
mods=("$@"); [ ${#mods[@]} -eq 0 ] && mods=(rtld main sdk subsdk0)
OUT=$W/gen4-$MODE
EXEFS_DIR=${BDSP_EXEFS_DIR:-work/exefs}
[ ! -f "$EXEFS_DIR/subsdk1" ] || [[ " ${mods[*]} " = *" subsdk1 "* ]] || mods+=(subsdk1)
CODEGEN="$(python3 scripts/recomp/native-generator/build.py --require-unicorn)"
ST=logs/gen-$MODE.stats
mkdir -p "$OUT" logs
for m in "${mods[@]}"; do [ -f "$EXEFS_DIR/$m" ] || die "$EXEFS_DIR/$m is missing (extract it first, see docs/BUILD.md section 4.1)."; done
: > "$ST"
tot0=$(date +%s.%N)
for m in "${mods[@]}"; do
  glog=logs/gen-$MODE-$m.log
  extra=()
  [ ! -f "$EXEFS_DIR/$m.entries" ] || extra+=(--entry-offsets "$EXEFS_DIR/$m.entries")
  /usr/bin/time -f "TIME %e %U %S %M" "$CODEGEN" gen "$m" "$EXEFS_DIR/$m" "$(base_of "$m")" "$OUT/$m" --simd "$MODE" ${extra[@]+"${extra[@]}"} 2>&1 | tee "$glog" \
    || { tail -20 "$glog"; die "Generator for $m failed (log: $glog)."; }
  tm=$(grep '^TIME' "$glog" | tail -1)
  fn=$(sed -n 's/^eh_gen: functions=\([0-9]*\).*/\1/p' "$glog" | tail -1)
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
