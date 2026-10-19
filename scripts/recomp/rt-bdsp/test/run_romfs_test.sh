#!/bin/bash
# Übersetzt und führt den synthetischen Test des virtuellen RomFS-Abbildes aus (erfundene Dateien unter work/recomp/test).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
clang -O1 -g -w -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/rt-bdsp scripts/recomp/rt-bdsp/test/romfs_test.c -o work/recomp/test/romfs_test
work/recomp/test/romfs_test
