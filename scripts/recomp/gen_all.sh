#!/bin/bash
# Erzeugt das C für alle vier Module des Dumps (Standard-Layout des Spikes) nach work/recomp/gen4/<modul> und
# misst die Generierungszeit. Nur lokal unter work/ (gitignoriert). Aufruf: gen_all.sh [modul ...] [-- weitere eh_gen-Argumente]
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=${OUT:-work/recomp/gen4}
mods=()
while [ $# -gt 0 ] && [ "$1" != "--" ]; do mods+=("$1"); shift; done
[ "${1:-}" = "--" ] && shift
[ ${#mods[@]} -eq 0 ] && mods=(rtld main sdk subsdk0)
base_of() { case "$1" in main) echo 0x7000000000;; sdk) echo 0x7006000000;; subsdk0) echo 0x7007000000;; rtld) echo 0x7008000000;; esac; }
mkdir -p "$OUT" work/recomp/spike2
for m in "${mods[@]}"; do
  /usr/bin/time -l python3 scripts/recomp/eh_gen.py gen "$m" "work/exefs/$m" "$(base_of "$m")" "$OUT/$m" --simd asm "$@" \
    > "work/recomp/spike2/gen4_$m.log" 2>&1
  grep -E "real|eh_gen:|wrote|maximum resident" "work/recomp/spike2/gen4_$m.log" | tail -4
done
