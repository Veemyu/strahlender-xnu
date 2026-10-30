#!/bin/bash
# Synthetic native checks of optional code modules, without a game instance.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
OUT=work/recomp/test/code-mod
mkdir -p "$OUT"
for enabled in 0 1; do
  clang -O1 -g -Wall -Wextra -Wno-unused-function -Wno-unused-parameter -DBDSP_HAS_SUBSDK1="$enabled" \
    -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/runtime \
    scripts/recomp/runtime/test/code_mod_test.c scripts/recomp/runtime/{loader,dispatch}.c -o "$OUT/test-$enabled"
  directory=$(mktemp -d "$OUT/fixture.XXXXXX")
  "$OUT/test-$enabled" "$directory"
done
directory=$(mktemp -d "$OUT/overlap.XXXXXX")
set +e
"$OUT/test-1" "$directory" overlap > "$OUT/overlap.log" 2>&1
status=$?
set -e
[ "$status" = 3 ] && grep -q 'overlaps main' "$OUT/overlap.log"
echo "Overlapping mod module: rejected"
