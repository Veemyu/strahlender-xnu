#!/bin/bash
# Compiles and runs the test of the executable-folder defaults (issue 26).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
clang -O1 -g -Wall -Werror -I scripts/recomp/runtime scripts/recomp/runtime/test/exe_paths_test.c scripts/recomp/runtime/exe_paths.c scripts/recomp/runtime/exit_report.c -o work/recomp/test/exe_paths_test
work/recomp/test/exe_paths_test
