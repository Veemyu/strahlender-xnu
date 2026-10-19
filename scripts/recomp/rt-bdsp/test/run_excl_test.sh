#!/bin/bash
# Übersetzt und führt den Test der Exklusiv-Paar-Hilfen aus (synthetisch, ohne Spielcode).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
clang -O1 -Wall -I scripts/recomp/rt -I scripts/recomp/upstream/runtime scripts/recomp/rt-bdsp/test/excl_pair_test.c -o work/recomp/test/excl_pair_test
work/recomp/test/excl_pair_test
