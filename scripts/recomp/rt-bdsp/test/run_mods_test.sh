#!/bin/bash
# Compiles and runs the synthetic test of the mod support (invented folders and files under work/recomp/test).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
clang -O1 -g -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/rt-bdsp scripts/recomp/rt-bdsp/test/mods_test.c scripts/recomp/rt-bdsp/mods.c -o work/recomp/test/mods_test
work/recomp/test/mods_test
