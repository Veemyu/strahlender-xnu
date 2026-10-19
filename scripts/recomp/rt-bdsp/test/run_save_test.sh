#!/bin/bash
# Baut und startet save_test.c (Spielstand-Funktionen der App, synthetische Daten) unter work/recomp/save-test.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp
clang -O1 -g -Wall -Wno-unused-result -Wno-deprecated-declarations scripts/recomp/rt-bdsp/test/save_test.c scripts/recomp/rt-bdsp/app/app_save.c -o work/recomp/save_test
work/recomp/save_test
