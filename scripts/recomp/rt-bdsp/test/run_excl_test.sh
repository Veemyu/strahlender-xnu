#!/bin/bash
# Compiles and runs the test of the exclusive-pair helpers (synthetic, without game code).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
clang -O1 -Wall -I scripts/recomp/rt -I scripts/recomp/upstream/runtime scripts/recomp/rt-bdsp/test/excl_pair_test.c -o work/recomp/test/excl_pair_test
work/recomp/test/excl_pair_test
