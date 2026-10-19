#!/bin/bash
# Baut die NVN-Schicht (LAS-Quellen aus prepare.sh + nvn_glue.c) zu Objekten in $RT/nvn. Inkrementell.
# Aufruf: build_nvn.sh [-DMakro ...]      Umgebung: RT=work/recomp/rt-bdsp  NVN_SRC=work/recomp/nvn-src
set -euo pipefail
cd "$(dirname "$0")/../../../.."
RT=${RT:-work/recomp/rt-bdsp}
SRC=${NVN_SRC:-work/recomp/nvn-src}
HERE=scripts/recomp/rt-bdsp/nvn
mkdir -p "$RT/nvn"
if [ -z "${NVN_KEEP:-}" ] && { [ ! -d "$SRC/nvn" ] || [ -n "$(find "$HERE/shim" "$HERE/prepare.sh" "$HERE/las-nvn.patch" "$HERE/fixes.patch" "$HERE/debug.patch" -newer "$SRC/nvn/nvn.h" -print -quit 2>/dev/null)" ]; }; then
  "$HERE/prepare.sh" > /dev/null
fi
INC="-I $SRC -I $SRC/nvn -I scripts/recomp/rt -I research/LASRecomp/runtime -I scripts/recomp/rt-bdsp $(pkg-config --cflags sdl3)"
W="-w"
build() {  # Quelle Objekt [Zusatzflags]
  local f=$1 o=$2; shift 2
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ -n "$(find "$SRC" "$HERE/shim" -name '*.h' -newer "$o" -print -quit)" ]; then
    # Objective-C mit dem Apple-Compiler: der Homebrew-LLVM erzeugt Klassen-Stubs, die der Apple-Linker nicht auflöst
    local cc=clang; case "$f" in *.m) cc=/usr/bin/clang;; esac
    $cc -O1 -g $W $INC "$@" -c "$f" -o "$o"
  fi
}
for f in objects cmdbuf formats tegra astc; do build "$SRC/nvn/$f.c" "$RT/nvn/$f.o" "$@"; done
build "$SRC/nvn/maxwell/translate.c" "$RT/nvn/translate.o" "$@"
build "$SRC/nvn/renderer.m" "$RT/nvn/renderer.o" -fobjc-arc "$@"
build "$SRC/nvn/metal.m" "$RT/nvn/metal.o" -fobjc-arc "$@"
build "$HERE/nvn_glue.c" "$RT/nvn/nvn_glue.o" -Wall -Wextra -Wno-unused-parameter "$@"
