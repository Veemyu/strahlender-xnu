#!/bin/bash
# Speichermodell B (--rebase32): erzeugt das C aller Module mit Basisadressen unter 4 GiB und C-SIMD (--simd c) nach
# work/recomp/gen32/<modul>, baut die Modulbilder (Relokationen auf die neuen Basen) nach work/recomp/img32 und
# übersetzt alles für iPhoneOS arm64 nach work/recomp/obj32 (Ziel iOS, danach mit vtool plattformlos für den Mac-Test).
# Alles unter work/ (gitignoriert). Die Basen müssen zu den B-Werten in scripts/recomp/rt-bdsp/bdsp.h passen.
# Aufruf: gen32.sh gen | img | build [JOBS] | all [JOBS]
set -euo pipefail
cd "$(dirname "$0")/../../.."
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
GEN=${GEN:-work/recomp/gen32}
IMG=${IMG:-work/recomp/img32}
OBJ=${OBJ:-work/recomp/obj32}
base_of() { case "$1" in main) echo 0x01000000;; sdk) echo 0x07000000;; subsdk0) echo 0x08000000;; rtld) echo 0x09000000;; esac; }

do_gen() {
  mkdir -p "$GEN" work/recomp/spike2
  for m in rtld main sdk subsdk0; do
    # Die Basis geht nur in die adrp/adr-Konstanten ein, der Rest ist gegenüber Variante A unverändert.
    python3 scripts/recomp/eh_gen.py gen "$m" "work/exefs/$m" "$(base_of "$m")" "$GEN/$m" --simd c > "work/recomp/spike2/gen32_$m.log" 2>&1
    tail -1 "work/recomp/spike2/gen32_$m.log"
  done
}

do_img() {
  mkdir -p "$IMG"
  rm -f "$IMG/hle.txt"
  for pass in 1 2; do
    for m in main sdk subsdk0; do
      if [ $pass = 1 ]; then
        python3 scripts/recomp/mkimg.py "work/exefs/$m" "$m" --base "$(base_of $m)" --hle-base 0x0A000000 --out "$IMG" > /dev/null
      else
        python3 scripts/recomp/mkimg.py "work/exefs/$m" "$m" --base "$(base_of $m)" --hle-base 0x0A000000 --out "$IMG" \
          --link "$IMG/main.syms.json" --link "$IMG/sdk.syms.json" --link "$IMG/subsdk0.syms.json" \
          --interpose-from "$IMG/main.syms.json" --hle-list scripts/recomp/rt-bdsp/hle_nvn.txt
      fi
    done
    [ $pass = 1 ] && rm -f "$IMG/hle.txt"
  done
}

# Übersetzung: wie build_all.sh (Einzelfunktionen über 300 KB mit -O0, sonst -O1), aber für iPhoneOS und mit REBASE32
do_build() {
  local jobs=${1:-3}
  [ "$jobs" -gt 4 ] && jobs=4
  local sdk; sdk=$(xcrun --sdk iphoneos --show-sdk-path)
  mkdir -p "$OBJ"
  for o in "$OBJ"/*.o; do
    [ -e "$o" ] || continue
    b=$(basename "$o" .o); m=${b%%_*}; rest=${b#*_}
    [ -f "$GEN/$m/$rest.c" ] || rm -f "$o"
  done
  : > "$OBJ/list_O0.txt"; : > "$OBJ/list_O1.txt"
  for f in "$GEN"/*/*.c; do
    size=$(stat -f %z "$f")
    if [ "$size" -gt 300000 ] && [ "$(grep -c '^void f_.*) {$' "$f")" = "1" ]; then echo "$f" >> "$OBJ/list_O0.txt"; else echo "$f" >> "$OBJ/list_O1.txt"; fi
  done
  echo "O1: $(wc -l < "$OBJ/list_O1.txt"), O0: $(wc -l < "$OBJ/list_O0.txt"), Jobs $jobs"
  export OBJ sdk
  local start; start=$(date +%s)
  OPT=-O0 xargs -P "$jobs" -n 1 scripts/recomp/ios/compile_chunk_ios.sh < "$OBJ/list_O0.txt"
  OPT=-O1 xargs -P "$jobs" -n 1 scripts/recomp/ios/compile_chunk_ios.sh < "$OBJ/list_O1.txt"
  echo "Gesamtzeit Übersetzung: $(( $(date +%s) - start )) s"
}

case "${1:-all}" in
  gen) do_gen ;;
  img) do_img ;;
  build) do_build "${2:-3}" ;;
  all) do_gen; do_img; do_build "${2:-3}" ;;
  *) echo "Aufruf: gen32.sh gen|img|build [JOBS]|all [JOBS]" >&2; exit 2 ;;
esac
