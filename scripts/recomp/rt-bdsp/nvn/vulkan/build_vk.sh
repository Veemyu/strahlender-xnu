#!/bin/bash
# Baut die Vulkan-Fassung der NVN-Schicht (LAS-Quellen aus prepare_vk.sh + nvn_glue.c + vk_glue.c) zu Objekten in $RT/nvnvk. Inkrementell.
# Aufruf: build_vk.sh [-DMakro ...]      Umgebung: RT=work/recomp/rt-bdsp-vk  NVN_SRC_VK=work/recomp/nvn-src-vk
#   VK_INC   Ordner mit vulkan/, SDL3/, shaderc/, vk_mem_alloc.h (Standard: ./include-vk auf dem Ryzen, sonst Homebrew auf dem Mac, siehe
#            scripts/recomp/ryzen/vk_sync_deps.sh; kein -devel-Paket nötig)
#   VK_SYNTAX=1  nur Syntaxprüfung (clang -fsyntax-only), keine Objekte (Mac mit Homebrew-Headern)
# Gelinkt wird gegen die Laufzeitbibliotheken (siehe vk_libs): libvulkan.so.1, libSDL3.so.0, libshaderc_shared.so.1 per Vollpfad.
set -euo pipefail
cd "$(dirname "$0")/../../../../.."
RT=${RT:-work/recomp/rt-bdsp-vk}
SRC=${NVN_SRC_VK:-work/recomp/nvn-src-vk}
HERE=scripts/recomp/rt-bdsp/nvn
mkdir -p "$RT/nvnvk"
if [ -z "${NVN_KEEP:-}" ] && { [ ! -d "$SRC/nvn/vulkan" ] || [ -n "$(find "$HERE" -type f \( -name '*.h' -o -name '*.patch' -o -name 'prepare*.sh' \) -newer "$SRC/nvn/nvn.h" -print -quit 2>/dev/null)" ]; }; then
  "$HERE/vulkan/prepare_vk.sh" > /dev/null
fi
if [ -z "${VK_INC:-}" ]; then
  if [ -d include-vk/vulkan ]; then VK_INC=$PWD/include-vk
  else VK_INC="/opt/homebrew/opt/vulkan-headers/include -I work/recomp/deps-vk -I /opt/homebrew/opt/sdl3/include -I /opt/homebrew/opt/shaderc/include"; fi
fi
INCV=""
for d in $VK_INC; do case "$d" in -I) ;; *) INCV="$INCV -I $d";; esac; done
INC="-I $SRC -I $SRC/nvn -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I scripts/recomp/rt-bdsp $INCV"
if [ "$(uname -s)" = Linux ]; then INC="$INC -I scripts/recomp/ryzen/compat"; fi
CC=${CC:-clang}
[ "$(uname -s)" = Linux ] && ARCHF="-march=x86-64-v3" || ARCHF=""
build() {  # Quelle Objekt [Zusatzflags]
  local f=$1 o=$2; shift 2
  local cc=$CC lang=""
  case "$f" in *.cpp) cc=${CXX:-clang++}; lang="-std=c++17";; esac
  if [ -n "${VK_SYNTAX:-}" ]; then $cc -fsyntax-only -w $lang $INC "$@" "$f"; return; fi
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ -n "$(find "$SRC" "$HERE" -name '*.h' -newer "$o" -print -quit)" ]; then
    $cc -O2 -g -w -fno-strict-aliasing $ARCHF $lang $INC "$@" -c "$f" -o "$o"
  fi
}
O=$RT/nvnvk
for f in objects cmdbuf formats tegra astc; do build "$SRC/nvn/$f.c" "$O/$f.o" "$@"; done
build "$SRC/nvn/maxwell/translate.c" "$O/translate.o" "$@"
for f in device exec shaders textures; do build "$SRC/nvn/vulkan/$f.c" "$O/vk_$f.o" "$@"; done
build "$SRC/nvn/vulkan/vma.cpp" "$O/vk_vma.o" "$@"
build "$HERE/nvn_glue.c" "$O/nvn_glue.o" -Dg_debug_frame=bdsp_glue_debug_frame -include SDL3/SDL.h -include stdatomic.h -include string.h -include strings.h "$@"  # (exec.c definiert g_debug_frame selbst; nvn_glue.c bindet SDL/stdatomic/string nur unter __APPLE__ ein, braucht sie aber auch hier für die Eingabeschicht)
build "$HERE/vulkan/vk_glue.c" "$O/vk_glue.o" "$@"
