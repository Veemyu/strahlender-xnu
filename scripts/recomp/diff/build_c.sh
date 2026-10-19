#!/bin/bash
# Baut die Bibliotheken des Differenzialtests (docs/recomp-diff.md). Alles unter work/recomp/diff (nicht im Repo).
# Aufruf: build_c.sh base            -> libcases.so (+ libnative.dylib auf dem Mac)
#         build_c.sh c <name> [clang-Flags ...]   -> lib_<name>.so aus ctest.c + lifted.c
# Umgebung: OVERLAY=<Ordner> setzt zusätzlich -I <Ordner> vor die Original-Laufzeit (c_exact-Fixes), CC=clang.
set -euo pipefail
cd "$(dirname "$0")/../../.."
D=${D:-work/recomp/diff}
CC=${CC:-clang}
mkdir -p "$D"
EXT=so; LINK=""
[ "$(uname)" = Darwin ] && { EXT=dylib; LINK="-undefined dynamic_lookup"; }
case "${1:-}" in
  base)
    $CC -O2 -shared -fPIC -w scripts/recomp/diff/cases.c -I scripts/recomp/diff -o "$D/libcases.so"
    [ "$(uname)" = Darwin ] && $CC -O2 -shared -fPIC -w scripts/recomp/diff/native.c -I scripts/recomp/diff -o "$D/libnative.dylib"
    ;;
  c)
    name=$2; shift 2
    inc=""; [ -n "${OVERLAY:-}" ] && inc="-I $OVERLAY"
    $CC "$@" -fno-strict-aliasing -fvisibility=default -shared -fPIC -w $LINK $inc -I research/LASRecomp/runtime -I scripts/recomp/c_exact -I scripts/recomp/diff \
      scripts/recomp/diff/ctest.c "${LIFTED:-$D/lifted.c}" -lm -o "$D/lib_$name.so"
    ;;
  *) echo "Aufruf: build_c.sh base | c <name> [Flags]"; exit 2;;
esac
