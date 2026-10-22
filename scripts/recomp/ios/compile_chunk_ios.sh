#!/bin/bash
# Compiles a generated C file (memory model B) for iPhoneOS arm64 to $OBJ/<module>_<chunk>.o, only if the source
# is newer. Environment: OBJ, sdk (iPhoneOS SDK), OPT (-O0/-O1). Usage: compile_chunk_ios.sh <file.c>
set -u
cd "$(dirname "$0")/../../.."
src=$1
o="$OBJ/$(basename "$(dirname "$src")")_$(basename "$src" .c).o"
[ "$o" -nt "$src" ] && exit 0
t0=$(date +%s)
# -ffp-contract=off und -fno-fast-math: bitgenaue Gleitkomma-Semantik (docs/recomp-diff.md)
clang -target arm64-apple-ios17.0 -isysroot "$sdk" ${OPT:--O1} -fno-strict-aliasing -fvisibility=hidden -fno-fast-math -ffp-contract=off -w \
  -DREBASE32 -DRT32_GEN -I scripts/recomp/rt32 -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -c "$src" -o "$o.tmp" || { echo "ERROR $src"; rm -f "$o.tmp"; exit 1; }
mv "$o.tmp" "$o"
echo "$(basename "$o") $(( $(date +%s) - t0 ))s" >> "$OBJ/compile_times.txt"
