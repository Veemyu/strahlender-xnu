#!/bin/bash
# Builds the libraries of the differential test (docs/recomp-diff.md). Everything under work/recomp/diff (not in the repo).
# Usage: build_c.sh base            -> libcases.so (+ libnative.dylib on the Mac)
#        build_c.sh c <name> [clang flags ...]   -> lib_<name>.so from ctest.c + lifted.c
# Environment: OVERLAY=<folder> additionally puts -I <folder> before the original runtime (c_exact fixes), CC=clang.
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
    $CC "$@" -fno-strict-aliasing -fvisibility=default -shared -fPIC -w $LINK $inc     -I scripts/recomp/upstream/runtime -I scripts/recomp/c_exact -I scripts/recomp/diff \      scripts/recomp/diff/ctest.c "${LIFTED:-$D/lifted.c}" -lm -o "$D/lib_$name.so"
    ;;
  *) echo "Usage: build_c.sh base | c <name> [flags]"; exit 2;;
esac
