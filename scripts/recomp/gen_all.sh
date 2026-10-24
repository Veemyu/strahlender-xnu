#!/bin/bash
# Generates the C for all four modules of the dump (standard layout of the spike) to work/recomp/gen4/<module> and
# measures the generation time. Local only under work/ (gitignored). Usage: gen_all.sh [module ...] [-- further eh_gen arguments]
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=${OUT:-work/recomp/gen4}
EXEFS_DIR=${BDSP_EXEFS_DIR:-work/exefs}
mods=()
while [ $# -gt 0 ] && [ "$1" != "--" ]; do mods+=("$1"); shift; done
[ "${1:-}" = "--" ] && shift
[ ${#mods[@]} -eq 0 ] && mods=(rtld main sdk subsdk0)
[ ! -f "$EXEFS_DIR/subsdk1" ] || [[ " ${mods[*]} " = *" subsdk1 "* ]] || mods+=(subsdk1)
base_of() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; rtld) echo 0x7008000000;; subsdk1) echo 0x7005708000;; *) return 2;; esac; }
mkdir -p "$OUT" work/recomp/spike2
for m in "${mods[@]}"; do
  extra=()
  [ ! -f "$EXEFS_DIR/$m.entries" ] || extra+=(--entry-offsets "$EXEFS_DIR/$m.entries")
  /usr/bin/time -l python3 scripts/recomp/eh_gen.py gen "$m" "$EXEFS_DIR/$m" "$(base_of "$m")" "$OUT/$m" --simd asm ${extra[@]+"${extra[@]}"} "$@" \
    > "work/recomp/spike2/gen4_$m.log" 2>&1
  grep -E "real|eh_gen:|wrote|maximum resident" "work/recomp/spike2/gen4_$m.log" | tail -4
done
