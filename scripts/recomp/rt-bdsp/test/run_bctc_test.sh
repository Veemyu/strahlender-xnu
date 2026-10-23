#!/bin/bash
# Compiles and runs the test of the BC conversion for GPUs without BC (synthetic blocks, needs an Apple silicon Mac).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
N=scripts/recomp/rt-bdsp/nvn/src/nvn
/usr/bin/clang -O2 -Wall -fobjc-arc -I "$N" "$N/bctc.c" scripts/recomp/rt-bdsp/test/bctc_test.m -framework Metal -framework Foundation \
  -o work/recomp/test/bctc_test
work/recomp/test/bctc_test
