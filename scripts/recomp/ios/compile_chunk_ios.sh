#!/bin/bash
# Übersetzt eine erzeugte C-Datei (Speichermodell B) für iPhoneOS arm64 nach $OBJ/<modul>_<chunk>.o, nur wenn die Quelle
# neuer ist. Umgebung: OBJ, sdk (iPhoneOS-SDK), OPT (-O0/-O1). Aufruf: compile_chunk_ios.sh <datei.c>
set -u
cd "$(dirname "$0")/../../.."
src=$1
o="$OBJ/$(basename "$(dirname "$src")")_$(basename "$src" .c).o"
[ "$o" -nt "$src" ] && exit 0
t0=$(date +%s)
# -ffp-contract=off und -fno-fast-math: bitgenaue Gleitkomma-Semantik (docs/recomp-diff.md)
clang -target arm64-apple-ios17.0 -isysroot "$sdk" ${OPT:--O1} -fno-strict-aliasing -fvisibility=hidden -fno-fast-math -ffp-contract=off -w \
  -DREBASE32 -DRT32_GEN -I scripts/recomp/rt32 -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -c "$src" -o "$o.tmp" || { echo "FEHLER $src"; rm -f "$o.tmp"; exit 1; }
mv "$o.tmp" "$o"
echo "$(basename "$o") $(( $(date +%s) - t0 ))s" >> "$OBJ/compile_times.txt"
