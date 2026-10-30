#!/bin/bash
# Compiles and runs the glyph atlas text test against the user's firmware fonts (BDSP_FIRMWARE_DATA=<folder with fonts/>); skipped when they are not there.
# Optional argument: PGM file with a rendering of a few strings.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
R=scripts/recomp/runtime
clang -O1 -g -Wall -Wextra -Wno-unused-function -I $R $R/test/swkbd_text_test.c $R/swkbd_text.c $R/lyt_scene.c $R/lyt.c $R/lyt_tex.c -lm -lpthread -o work/recomp/test/swkbd_text_test
work/recomp/test/swkbd_text_test "$@"
