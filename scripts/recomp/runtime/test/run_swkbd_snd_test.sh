#!/bin/bash
# Compiles and runs the keyboard sound reader test (BDSP_FIRMWARE_DATA=<folder with swkbd/sound/swkbd.bfsar> for the firmware part).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
R=scripts/recomp/runtime
FW=""
[ "$(uname -s)" != Darwin ] || FW="-framework AudioToolbox"
clang -O1 -g -Wall -Wextra -I $R $R/test/swkbd_snd_test.c $R/swkbd_snd.c -lm -lpthread $FW -o work/recomp/test/swkbd_snd_test
work/recomp/test/swkbd_snd_test "$@"
