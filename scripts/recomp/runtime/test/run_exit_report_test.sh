#!/bin/bash
# Compiles and runs the test of the "[exit] game stopped at launch" line (exit_report.c). No game files, no GPU.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
OUT=${OUT:-work/recomp/test}
mkdir -p "$OUT"
clang -O1 -g -Wall -Wextra -Werror -I scripts/recomp/runtime scripts/recomp/runtime/test/exit_report_test.c scripts/recomp/runtime/exit_report.c -o "$OUT/exit_report_test"
(cd "$OUT" && ./exit_report_test)
