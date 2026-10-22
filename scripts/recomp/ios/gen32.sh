#!/bin/bash
# Memory model B (--rebase32): generates the C of all modules with base addresses below 4 GiB and C SIMD (--simd c) to
# work/recomp/gen32/<module>, builds the module images (relocations to the new bases) to work/recomp/img32 and
# compiles everything for iPhoneOS arm64 to work/recomp/obj32 (target iOS, afterwards platformless via vtool for the Mac test).
# Everything under work/ (gitignored). The bases must match the B values in scripts/recomp/rt-bdsp/bdsp.h.
# Usage: gen32.sh gen | img | build [JOBS] | hot | all [JOBS]   (hot: only the -O2 files of scripts/recomp/hot_o2.txt)
set -euo pipefail
cd "$(dirname "$0")/../../.."
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
GEN=${GEN:-work/recomp/gen32}
IMG=${IMG:-work/recomp/img32}
OBJ=${OBJ:-work/recomp/obj32}
base_of() { case "$1" in main) echo 0x01000000;; sdk) echo 0x07000000;; subsdk0) echo 0x08000000;; rtld) echo 0x09000000;; esac; }
# Toolchain stamp of the guest objects: SDKs, compiler, compile script and headers of the runtime. If one of them changes, everything is recompiled.
obj_stamp() {
  . scripts/recomp/rt-bdsp/nvn/hash.inc.sh
  { xcrun --sdk iphoneos --show-sdk-version; xcrun --sdk iphoneos --show-sdk-path; xcode-select -p; clang --version; sha256 scripts/recomp/ios/compile_chunk_ios.sh
    find scripts/recomp/rt32 scripts/recomp/rt scripts/recomp/upstream/runtime -name '*.h' | LC_ALL=C sort | while IFS= read -r h; do sha256 "$h"; done; } | sha256 | cut -d' ' -f1
}

do_gen() {
  mkdir -p "$GEN" work/recomp/spike2
  for m in rtld main sdk subsdk0; do
    # The base only enters the adrp/adr constants, the rest is unchanged compared to variant A.
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

# Compilation: like build_all.sh (single functions above 300 KB with -O0, otherwise -O1), but for iPhoneOS and with REBASE32
do_build() {
  local jobs=${1:-3}
  [ "$jobs" -gt 4 ] && jobs=4
  local sdk; sdk=$(xcrun --sdk iphoneos --show-sdk-path)
  mkdir -p "$OBJ"
  local stamp; stamp=$(obj_stamp)
  if [ "$(cat "$OBJ/.stamp" 2>/dev/null || true)" != "$stamp" ]; then
    rm -f "$OBJ"/*.o; echo "$stamp" > "$OBJ/.stamp"; echo "Toolchain stamp missing or does not match: all objects in $OBJ are recompiled"
  fi
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
  echo "Total compile time: $(( $(date +%s) - start )) s"
  do_hot
}

# Hot functions (scripts/recomp/hot_o2.txt, Mac names of module main, base 0x7000000000) with -O2, like scripts/recomp/build_all.sh.
# In model B the function name is the offset plus the main base 0x1000000. An object that already is -O2 (marker *.o2) is kept.
do_hot() {
  local sdk; sdk=$(xcrun --sdk iphoneos --show-sdk-path)
  mkdir -p "$OBJ"
  export OBJ sdk
  local fn n f o
  while read -r fn; do
    case "$fn" in ""|"#"*) continue ;; esac
    n=$(printf 'f_%x' $(( 0x${fn#f_} - 0x7000000000 + 0x1000000 )))
    for f in $(grep -l "^void $n(.*{\$" "$GEN"/main/*.c); do
      o="$OBJ/main_$(basename "$f" .c).o"
      [ -e "$o.o2" ] && [ "$o.o2" -nt "$f" ] && continue
      rm -f "$o"; OPT=-O2 scripts/recomp/ios/compile_chunk_ios.sh "$f" && : > "$o.o2"
      echo "-O2: $n in $(basename "$f")"
    done
  done < scripts/recomp/hot_o2.txt
}

case "${1:-all}" in
  gen) do_gen ;;
  img) do_img ;;
  build) do_build "${2:-3}" ;;
  hot) do_hot ;;
  all) do_gen; do_img; do_build "${2:-3}" ;;
  *) echo "Usage: gen32.sh gen|img|build [JOBS]|hot|all [JOBS]" >&2; exit 2 ;;
esac
