#!/bin/bash
# Compiles and runs the synthetic test of the virtual RomFS image (invented files under work/recomp/test).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
clang -O1 -g -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/runtime scripts/recomp/runtime/test/romfs_test.c scripts/recomp/runtime/mods.c -o work/recomp/test/romfs_test
work/recomp/test/romfs_test
