#!/bin/bash
# Builds the Vulkan version of the NVN layer (LAS sources from prepare_vk.sh + nvn_glue.c + vk_glue.c) into objects in $RT/nvnvk. Incremental.
# Usage: build_vk.sh [-Dmacro ...]      Environment: RT=work/recomp/runtime-vk  NVN_SRC_VK=work/recomp/nvn-src-vk
#   Linux uses installed development packages through pkg-config; no copied headers.
#   VK_INC explicitly adds an include prefix for manual/macOS syntax checks.
#   VK_SYNTAX=1  syntax check only (clang -fsyntax-only), no objects (Mac with Homebrew headers)
# The runtime links against installed development libraries through pkg-config.
set -euo pipefail
cd "$(dirname "$0")/../../../../.."
RT=${RT:-work/recomp/runtime-vk}
SRC=${NVN_SRC_VK:-work/recomp/nvn-src-vk}
HERE=scripts/recomp/runtime/nvn
mkdir -p "$RT/nvnvk"
if [ -z "${NVN_KEEP:-}" ]; then
  NVN_SRC_VK="$SRC" "$HERE/vulkan/prepare_vk.sh" > /dev/null   # copies only when the stamp differs
fi
. "$HERE/flags.inc.sh"
INCV=""
if [ "$(uname -s)" = Linux ]; then
  source scripts/recomp/linux/deps.sh
  linux_require_runtime
  INCV="$(linux_vulkan_cflags)"
elif [ -z "${VK_INC:-}" ]; then
  VK_INC="/opt/homebrew/opt/vulkan-headers/include /opt/homebrew/opt/sdl3/include /opt/homebrew/opt/shaderc/include"
fi
for d in ${VK_INC:-}; do case "$d" in -I) ;; *) INCV="$INCV -I $d";; esac; done
INC="-I $SRC -I $SRC/nvn -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/runtime $INCV"
if [ "$(uname -s)" = Linux ]; then INC="$INC -I scripts/recomp/linux/compat"; fi
CC=${CC:-clang}
ARCHF=""
CPU_REBUILD=0
if [ "$(uname -s)" = Linux ]; then
  source scripts/recomp/linux/cpu_flags.sh
  ARCHF=$(bdsp_cpu_flags)
fi
# Include both compilers: native CPU features and compiler versions affect objects.
CPU_STAMP=$( (printf '%s\n' "$ARCHF"; "$CC" --version; "${CXX:-clang++}" --version
  if [ "$(uname -s)" = Linux ]; then
    bdsp_cpu_signature "$CC"
    bdsp_cpu_signature "${CXX:-clang++}"
  fi) | cksum)
if [ ! -f "$RT/nvnvk/.cpu-flags" ] || [ "$(cat "$RT/nvnvk/.cpu-flags")" != "$CPU_STAMP" ]; then CPU_REBUILD=1; fi
build() {  # Quelle Objekt [Zusatzflags]
  local f=$1 o=$2; shift 2
  local cc=$CC lang=""
  case "$f" in *.cpp) cc=${CXX:-clang++}; lang="-std=c++17";; esac
  if [ -n "${VK_SYNTAX:-}" ]; then $cc -fsyntax-only $ARCHF $BDSP_NOWARN $lang $INC "$@" "$f"; return; fi
  if [ "$CPU_REBUILD" = 1 ] || [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ -n "$(find "$SRC" "$HERE" -name '*.h' -newer "$o" -print -quit)" ]; then
    $cc -O2 -g $BDSP_NOWARN -fno-strict-aliasing $ARCHF $lang $INC "$@" -c "$f" -o "$o"
  fi
}
O=$RT/nvnvk
for f in objects cmdbuf formats tegra astc; do build "$SRC/nvn/$f.c" "$O/$f.o" "$@"; done
build "$SRC/nvn/maxwell/translate.c" "$O/translate.o" "$@"
for f in device exec shaders textures; do build "$SRC/nvn/vulkan/$f.c" "$O/vk_$f.o" "$@"; done
build "$SRC/nvn/vulkan/vma.cpp" "$O/vk_vma.o" "$@"
build "$HERE/nvn_glue.c" "$O/nvn_glue.o" -Dg_debug_frame=bdsp_glue_debug_frame -include SDL3/SDL.h -include stdatomic.h -include string.h -include strings.h "$@"  # (exec.c defines g_debug_frame itself; nvn_glue.c includes SDL/stdatomic/string only under __APPLE__, but needs them here too for the input layer)
build "$HERE/vulkan/vk_glue.c" "$O/vk_glue.o" "$@"
build "$HERE/vulkan/swkbd_overlay_vk.c" "$O/swkbd_overlay_vk.o" "$@"   # on-screen keyboard (drawn over the frame, Vulkan)
# Movie playback uses FFmpeg headers from the same installed development packages as the link step.
if [ -z "${BDSP_NO_MOVIE:-}" ]; then
  FFI=$(pkg-config --cflags libavcodec libavformat libavutil)
  build "$HERE/movie_glue.c" "$O/movie_glue.o" $FFI $BDSP_WARN_GLUE "$@"
fi
# Publish only after every object succeeds; a failed rebuild must be retried.
if [ -z "${VK_SYNTAX:-}" ]; then
  printf '%s\n' "$CPU_STAMP" > "$O/.cpu-flags.tmp.$$"
  mv "$O/.cpu-flags.tmp.$$" "$O/.cpu-flags"
fi
