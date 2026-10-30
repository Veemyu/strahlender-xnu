#!/bin/bash
# Compiles and runs the keyboard logic test against the user's firmware layouts (BDSP_FIRMWARE_DATA=<folder with swkbd/lyt/*.szs>);
# skipped when they are not there. Optional argument: PPM file for a software rendering of the keyboard.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
R=scripts/recomp/runtime
FW=""
[ "$(uname -s)" != Darwin ] || FW="-framework AudioToolbox"
export BDSP_SWKBD_SOUND=0   # the test must not make noise
clang -O1 -g -Wall -Wextra -Wno-unused-function -I $R $R/test/swkbd_ui_test.c $R/swkbd_ui.c $R/lyt.c $R/lyt_tex.c $R/lyt_scene.c $R/swkbd_snd.c $R/swkbd_ime.c -lm -lpthread $FW -o work/recomp/test/swkbd_ui_test
work/recomp/test/swkbd_ui_test "$@"
