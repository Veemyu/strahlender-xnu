#!/bin/bash
# Runs on the Linux host: builds the C++ Qt shell (rt-bdsp/app/linux, CMake) into work/recomp/qt-host. If Qt6 development packages are missing, the script ends with
# code 3 and names the install command (the user runs it themselves; nothing is installed here).
source "$(dirname "$0")/common.sh"
"${TIMEV[@]}" bash scripts/recomp/rt-bdsp/app/linux/build_qt.sh "$@"
