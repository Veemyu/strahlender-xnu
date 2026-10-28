#!/bin/bash
# No firmware or game data required; exercise returned scene text under ASan.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
R=scripts/recomp/rt-bdsp
mkdir -p work/recomp/test
FW=()
[ "$(uname -s)" != Darwin ] || FW=(-framework AudioToolbox)
clang -O1 -g -fsanitize=address,undefined -fsanitize-address-use-after-return=always -I "$R" \
  "$R/test/swkbd_scene_lifetime_test.c" "$R/swkbd_ui.c" "$R/lyt.c" "$R/lyt_tex.c" "$R/lyt_scene.c" \
  "$R/swkbd_snd.c" "$R/swkbd_ime.c" -lm -lpthread "${FW[@]}" -o work/recomp/test/swkbd_scene_lifetime_test
work/recomp/test/swkbd_scene_lifetime_test

clang -O1 -g -fsanitize=address,undefined -DBDSP_SWKBD_NATIVE_TEST -I "$R" \
  "$R/test/swkbd_native_input_test.c" "$R/swkbd_ui.c" "$R/lyt.c" "$R/lyt_tex.c" "$R/lyt_scene.c" \
  "$R/swkbd_snd.c" "$R/swkbd_ime.c" -lm -lpthread "${FW[@]}" -o work/recomp/test/swkbd_native_input_test
work/recomp/test/swkbd_native_input_test
