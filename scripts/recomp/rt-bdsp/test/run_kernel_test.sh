#!/bin/bash
# Übersetzt und führt den synthetischen Kernel-Test aus. Braucht die Laufzeitobjekte (build.sh), aber nicht main.o.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
RT=${RT:-work/recomp/rt-bdsp}
mkdir -p work/recomp/test
INC="-I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/rt-bdsp"
clang -O1 -g -w $INC -c scripts/recomp/rt-bdsp/test/kernel_test.c -o work/recomp/test/kernel_test.o
objs=()
for o in "$RT"/*.o; do [ "$(basename "$o")" = main.o ] || objs+=("$o"); done
clang -o work/recomp/test/kernel_test work/recomp/test/kernel_test.o "${objs[@]}"
work/recomp/test/kernel_test
