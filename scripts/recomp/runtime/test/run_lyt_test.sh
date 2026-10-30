#!/bin/bash
# Compiles and runs the layout reader test. The synthetic part always runs; the firmware part runs when BDSP_FIRMWARE_DATA
# points at a folder containing swkbd/lyt/*.szs (the user's own firmware files), otherwise it is skipped.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
clang -O1 -g -Wall -Wextra -I scripts/recomp/runtime scripts/recomp/runtime/test/lyt_test.c scripts/recomp/runtime/lyt.c scripts/recomp/runtime/lyt_tex.c -lm -o work/recomp/test/lyt_test
work/recomp/test/lyt_test "$@"
