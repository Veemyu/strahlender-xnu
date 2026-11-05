#!/bin/bash
# Compiles and runs the test of the nn::Result names (issue 57).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
out=${BDSP_TEST_OUT:-work/recomp/test}
mkdir -p "$out"
clang -O1 -g -Wall -Werror -I scripts/recomp/runtime scripts/recomp/runtime/test/result_names_test.c -o "$out/result_names_test"
"$out/result_names_test"
