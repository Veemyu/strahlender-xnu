#!/bin/bash
# Compiles and runs the window title test (title composition, titles.json parsing, system language matching; invented names only).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
mkdir -p work/recomp/test
R=scripts/recomp/runtime
LIBS=""; [ "$(uname -s)" != Darwin ] || LIBS="-framework CoreFoundation"
${CC:-cc} -O1 -g -Wall -Wextra -I $R $R/test/window_title_test.c $R/window_title.c $LIBS -o work/recomp/test/window_title_test
work/recomp/test/window_title_test
