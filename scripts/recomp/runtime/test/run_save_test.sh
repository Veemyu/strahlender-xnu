#!/bin/bash
# Builds and runs save_test.c (save functions of the app, synthetic data) under work/recomp/save-test.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp
clang -O1 -g -Wall -Wno-unused-result -Wno-deprecated-declarations scripts/recomp/runtime/test/save_test.c scripts/recomp/runtime/app/app_save.c -o work/recomp/save_test
work/recomp/save_test
