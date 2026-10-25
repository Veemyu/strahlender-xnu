#!/bin/bash
# Memory model B (--rebase32): generates the C of all modules with base addresses below 4 GiB and C SIMD (--simd c) to
# work/recomp/gen32/<module>, builds the module images (relocations to the new bases) to work/recomp/img32 and
# compiles everything for iPhoneOS arm64 to work/recomp/obj32 (target iOS, afterwards platformless via vtool for the Mac test).
# MODEL=a selects memory model A-low: the same compact layout shifted to the fixed host address ORG (default 0x800000000, free on iPad and iPhone), guest address ==
# host address, NEON inline assembler (--simd asm); folders gen4i, img4i, obj4i (the runtime is built with -DBDSP_COMPACT_BASE=ORG).
# Everything under work/ (gitignored). The bases must match the compact layout in scripts/recomp/rt-bdsp/bdsp.h.
# Usage: [MODEL=a] gen32.sh gen | img | build [JOBS] | hot | all [JOBS]   (hot: only the -O2 files of scripts/recomp/hot_o2.txt)
set -euo pipefail
cd "$(dirname "$0")/../../.."
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
MODEL=${MODEL:-b}
if [ "$MODEL" = a ]; then ORG=${ORG:-0x800000000}; SIMD=asm; D=4i; else ORG=0; SIMD=c; D=32; fi
export MODEL
GEN=${GEN:-work/recomp/gen$D}
IMG=${IMG:-work/recomp/img$D}
OBJ=${OBJ:-work/recomp/obj$D}
EXEFS_DIR=${BDSP_EXEFS_DIR:-work/exefs}
base_of() { local o; case "$1" in main) o=0x01000000;; sdk) o=0x07000000;; subsdk0) o=0x08000000;; rtld) o=0x09000000;; subsdk1) o=0x06708000;; *) return 2;; esac; printf '0x%x' $(( ORG + o )); }
modules=(main sdk subsdk0)
[ ! -f "$EXEFS_DIR/subsdk1" ] || modules+=(subsdk1)
HLE_BASE=$(printf '0x%x' $(( ORG + 0x0A000000 )))
# Toolchain stamp of the guest objects: SDKs, compiler, compile script and headers of the runtime. If one of them changes, everything is recompiled.
obj_stamp() {
  . scripts/recomp/rt-bdsp/nvn/hash.inc.sh
  { echo "model $MODEL $ORG"; xcrun --sdk iphoneos --show-sdk-version; xcrun --sdk iphoneos --show-sdk-path; xcode-select -p; clang --version; sha256 scripts/recomp/ios/compile_chunk_ios.sh
    find $([ "$MODEL" = a ] || echo scripts/recomp/rt32) scripts/recomp/rt scripts/recomp/upstream/runtime -name '*.h' | LC_ALL=C sort | while IFS= read -r h; do sha256 "$h"; done; } | sha256 | cut -d' ' -f1
}

do_gen() {
  mkdir -p "$GEN" work/recomp/spike2
  for m in rtld "${modules[@]}"; do
    extra=()
    [ ! -f "$EXEFS_DIR/$m.entries" ] || extra+=(--entry-offsets "$EXEFS_DIR/$m.entries")
    # The base only enters the adrp/adr constants, the rest is unchanged compared to variant A.
    python3 scripts/recomp/eh_gen.py gen "$m" "$EXEFS_DIR/$m" "$(base_of "$m")" "$GEN/$m" --simd $SIMD ${extra[@]+"${extra[@]}"} > "$GEN/gen_$m.log" 2>&1 \
      || { tail -n 25 "$GEN/gen_$m.log" >&2; return 4; }
    tail -1 "$GEN/gen_$m.log"
    echo "module=$m generated"
  done
}

do_img() {
  mkdir -p "$IMG"
  rm -f "$IMG/hle.txt"
  links=()
  for m in "${modules[@]}"; do links+=(--link "$IMG/$m.syms.json"); done
  for pass in 1 2; do
    for m in "${modules[@]}"; do
      if [ $pass = 1 ]; then
        python3 scripts/recomp/mkimg.py "$EXEFS_DIR/$m" "$m" --base "$(base_of $m)" --hle-base $HLE_BASE --out "$IMG" > /dev/null
      else
        python3 scripts/recomp/mkimg.py "$EXEFS_DIR/$m" "$m" --base "$(base_of $m)" --hle-base $HLE_BASE --out "$IMG" \
          "${links[@]}" \
          --interpose-from "$IMG/main.syms.json" --hle-list scripts/recomp/rt-bdsp/hle_nvn.txt
      fi
    done
    if [ "$pass" = 1 ]; then rm -f "$IMG/hle.txt"; fi
  done
}

# Compilation: like build_all.sh (single functions above 300 KB with -O0, otherwise -O1), but for iPhoneOS and with REBASE32
do_build() {
  local jobs=${1:-$(python3 scripts/recomp/parallel_jobs.py)}
  case "$jobs" in ''|*[!0-9]*) echo "JOBS must be a positive integer" >&2; return 2;; esac
  [ "$jobs" -ge 1 ] || { echo "JOBS must be at least 1" >&2; return 2; }
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
  rm -f "$OBJ/.compile-total"
  : > "$OBJ/list_O0.txt"; : > "$OBJ/list_O1.txt"
  for f in "$GEN"/*/*.c; do
    size=$(stat -f %z "$f")
    if [ "$size" -gt 300000 ] && [ "$(grep -c '^void f_.*) {$' "$f")" = "1" ]; then echo "$f" >> "$OBJ/list_O0.txt"; else echo "$f" >> "$OBJ/list_O1.txt"; fi
  done
  printf '%s\n' "$(( $(wc -l < "$OBJ/list_O0.txt") + $(wc -l < "$OBJ/list_O1.txt") ))" > "$OBJ/.compile-total.tmp"
  mv "$OBJ/.compile-total.tmp" "$OBJ/.compile-total"
  echo "O1: $(wc -l < "$OBJ/list_O1.txt"), O0: $(wc -l < "$OBJ/list_O0.txt"), Jobs $jobs"
  export OBJ sdk
  local start; start=$(date +%s)
  tr '\n' '\000' < "$OBJ/list_O0.txt" | OPT=-O0 xargs -0 -P "$jobs" -I{} scripts/recomp/ios/compile_chunk_ios.sh {}
  tr '\n' '\000' < "$OBJ/list_O1.txt" | OPT=-O1 xargs -0 -P "$jobs" -I{} scripts/recomp/ios/compile_chunk_ios.sh {}
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
    n=$(printf 'f_%x' $(( 0x${fn#f_} - 0x7000000000 + $(base_of main) )))
    while IFS= read -r f; do
      o="$OBJ/main_$(basename "$f" .c).o"
      [ -e "$o.o2" ] && [ "$o.o2" -nt "$f" ] && continue
      rm -f "$o"; OPT=-O2 scripts/recomp/ios/compile_chunk_ios.sh "$f" && : > "$o.o2"
      echo "-O2: $n in $(basename "$f")"
    done < <(grep -l "^void $n(.*{\$" "$GEN"/main/*.c || true)
  done < scripts/recomp/hot_o2.txt
}

case "${1:-all}" in
  gen) do_gen ;;
  img) do_img ;;
  build) do_build "${2:-}" ;;
  hot) do_hot ;;
  all) do_gen; do_img; do_build "${2:-}" ;;
  *) echo "Usage: gen32.sh gen|img|build [JOBS]|hot|all [JOBS]" >&2; exit 2 ;;
esac
