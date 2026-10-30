#!/bin/bash
# Compiles and runs the test of the Korean / Japanese text composition (no firmware data needed).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
R=scripts/recomp/runtime
clang -O1 -g -Wall -Wextra -I $R $R/test/swkbd_ime_test.c $R/swkbd_ime.c -o work/recomp/test/swkbd_ime_test
work/recomp/test/swkbd_ime_test
