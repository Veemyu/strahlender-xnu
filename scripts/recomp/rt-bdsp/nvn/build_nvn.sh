#!/bin/bash
# Builds the NVN layer (LAS sources from prepare.sh + nvn_glue.c) into objects in $RT/nvn. Incremental.
# Usage: build_nvn.sh [-Dmacro ...]      Environment: RT=work/recomp/rt-bdsp  NVN_SRC=work/recomp/nvn-src
set -euo pipefail
cd "$(dirname "$0")/../../../.."
RT=${RT:-work/recomp/rt-bdsp}
SRC=${NVN_SRC:-work/recomp/nvn-src}
HERE=scripts/recomp/rt-bdsp/nvn
mkdir -p "$RT/nvn"
if [ -z "${NVN_KEEP:-}" ]; then
  NVN_SRC="$SRC" "$HERE/prepare.sh" > /dev/null   # copies only when the stamp differs
fi
INC="-I $SRC -I $SRC/nvn -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/rt-bdsp $(pkg-config --cflags sdl3)"
. "$HERE/flags.inc.sh"
W="$BDSP_NOWARN"
build() {  # Quelle Objekt [Zusatzflags]
  local f=$1 o=$2; shift 2
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ -n "$(find "$SRC" "$HERE/src" \( -name '*.h' -o -name '*.inc' \) -newer "$o" -print -quit)" ]; then
    # Objective-C with the Apple compiler: the Homebrew LLVM generates class stubs that the Apple linker does not resolve
    local cc=clang; case "$f" in *.m) cc=/usr/bin/clang;; esac
    $cc $BDSP_OPT $W $INC "$@" -c "$f" -o "$o"
  fi
}
for f in objects cmdbuf formats tegra astc bctc; do build "$SRC/nvn/$f.c" "$RT/nvn/$f.o" "$@"; done
build "$SRC/nvn/maxwell/translate.c" "$RT/nvn/translate.o" "$@"
build "$SRC/nvn/renderer.m" "$RT/nvn/renderer.o" -fobjc-arc "$@"
build "$SRC/nvn/metal.m" "$RT/nvn/metal.o" -fobjc-arc "$@"
build "$HERE/nvn_glue.c" "$RT/nvn/nvn_glue.o" $BDSP_WARN_GLUE "$@"
build "$HERE/debug_thread.c" "$RT/nvn/debug_thread.o" -Wall -Wextra "$@"
# Movie playback (movie:: of the SDK with FFmpeg); without FFmpeg: BDSP_NO_MOVIE=1 (the SDK path then stays, which aborts without a decoder)
if [ -z "${BDSP_NO_MOVIE:-}" ]; then
  build "$HERE/movie_glue.c" "$RT/nvn/movie_glue.o" $(pkg-config --cflags libavcodec libavformat libavutil) $BDSP_WARN_GLUE "$@"
fi
