#!/bin/bash
# Compiles a generated C file (memory model A-low) for iPhoneOS arm64 to $OBJ/<module>_<chunk>.o, only if the source
# is newer. Environment: OBJ, sdk (iPhoneOS SDK), OPT (-O0/-O1). Usage: compile_chunk_ios.sh <file.c>
set -u
cd "$(dirname "$0")/../../.."
. scripts/recomp/macos_target.sh
src=$1
o="$OBJ/$(basename "$(dirname "$src")")_$(basename "$src" .c).o"
[ "$o" -nt "$src" ] && exit 0
t0=$(date +%s)
# Memory model A-low: like the Mac build (scripts/recomp/test/compile_chunk.sh), guest address == host address, NEON inline assembler
FLAGS="${OPT:--O1} -fno-strict-aliasing -fvisibility=hidden -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime"
clang -target arm64-apple-ios$BDSP_IOS_MIN -isysroot "$sdk" $FLAGS -c "$src" -o "$o.tmp" || { echo "ERROR $src"; rm -f "$o.tmp"; exit 1; }
mv "$o.tmp" "$o"
echo "$(basename "$o") $(( $(date +%s) - t0 ))s" >> "$OBJ/compile_times.txt"
