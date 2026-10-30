#!/bin/bash
# Compiles and runs the synthetic kernel test. Needs the runtime objects (build.sh), but not main.o.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
RT=${RT:-work/recomp/runtime}
mkdir -p work/recomp/test
INC="-I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/runtime"
clang -O1 -g -w $INC -c scripts/recomp/runtime/test/kernel_test.c -o work/recomp/test/kernel_test.o
objs=()
for o in "$RT"/*.o; do [ "$(basename "$o")" = main.o ] || objs+=("$o"); done
clang -o work/recomp/test/kernel_test work/recomp/test/kernel_test.o "${objs[@]}"
work/recomp/test/kernel_test
