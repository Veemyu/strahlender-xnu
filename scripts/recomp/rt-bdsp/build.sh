#!/bin/bash
# Builds the BDSP runtime (scripts/recomp/rt-bdsp/*.c) and links it with the translated guest modules (work/recomp/obj4/*.o)
# into work/recomp/bdsp_boot. Incremental: runtime files only when changed, link only if an input is newer.
# Usage: build.sh [-DMacro ...]      Environment: OBJ=work/recomp/obj4  RT=work/recomp/rt-bdsp  OUT=work/recomp/bdsp_boot
set -euo pipefail
cd "$(dirname "$0")/../../.."
OBJ=${OBJ:-work/recomp/obj4}
RT=${RT:-work/recomp/rt-bdsp}
OUT=${OUT:-work/recomp/bdsp_boot}
mkdir -p "$RT"
SRC=scripts/recomp/rt-bdsp
INC="-I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I $SRC"
# Graphics backend at build time: metal (macOS, default), vulkan (Linux/Windows: nvn/vulkan/, output work/recomp/bdsp_boot_vk, objects rt-bdsp-vk; see
# docs/recomp-linux.md), none (no graphics: the SDK's NVN driver stays,
# behavior as in gate 1; default on Linux until the Vulkan backend exists). Linux: Mach replacement from scripts/recomp/linux/compat.
NVN_BACKEND=${NVN_BACKEND:-$([ "$(uname -s)" = Darwin ] && echo metal || echo none)}
EXTRA=""
FW=""
nvnobjs=()
case "$NVN_BACKEND" in
  metal)
    # NVN_RT: object folder of the NVN layer (independent of RT, so the app version uses the same objects)
    RT="${NVN_RT:-$RT}" scripts/recomp/rt-bdsp/nvn/build_nvn.sh "$@"
    nvnobjs=("${NVN_RT:-$RT}"/nvn/*.o)
    FW="-framework AudioToolbox -framework Metal -framework MetalFX -framework AppKit -framework QuartzCore -framework CoreText -framework CoreGraphics -framework ImageIO -framework CoreServices -framework UniformTypeIdentifiers -framework Foundation $(pkg-config --libs sdl3) $([ -n "${BDSP_NO_MOVIE:-}" ] || pkg-config --libs libavcodec libavformat libavutil)" ;;
  none) EXTRA="-DBDSP_NVN_NONE"; RT="${RT}-none"; mkdir -p "$RT"
    [ "$(uname -s)" != Darwin ] || FW="-framework AudioToolbox" ;;
  vulkan) RT="${RT}-vk"; OUT="${OUT}_vk"; mkdir -p "$RT"   # Linux/Windows: Vulkan version of the LAS NVN layer (nvn/vulkan/), runtime libraries by full path
    source scripts/recomp/linux/deps.sh
    linux_require_runtime
    RT="$RT" scripts/recomp/rt-bdsp/nvn/vulkan/build_vk.sh "$@"
    nvnobjs=("$RT"/nvnvk/*.o)
    FW="$(linux_vulkan_libs) -lstdc++ -lm -lpthread -ldl"
    [ -n "${BDSP_NO_MOVIE:-}" ] || FW="$FW $(pkg-config --libs libavformat libavcodec libavutil)"
    if [ -n "${BDSP_QT:-}" ]; then   # Qt shell in-process (menu bar, Vulkan surface from Qt): app/linux/qt_ui.cpp, output bdsp_boot_vk_qt; Windows only prepared (not built)
      OUT="${OUT}_qt"; mkdir -p "$RT/qt"
      linux_require_qt
      QTCF=$(pkg-config --cflags Qt6Widgets sdl3)
      QTS=scripts/recomp/rt-bdsp/app/linux
      if [ ! -f "$RT/qt/qt_ui.o" ] || [ "$QTS/qt_ui.cpp" -nt "$RT/qt/qt_ui.o" ] || [ "$QTS/bdsp_l10n.h" -nt "$RT/qt/qt_ui.o" ] || [ "$QTS/bdsp_icons.h" -nt "$RT/qt/qt_ui.o" ]; then
        clang++ -std=c++17 -O1 -g -fPIC -Wall -Wextra -Wno-unused-parameter $QTCF -I "$QTS" -DBDSP_LPROJ_DIR="\"$PWD/$QTS/lproj\"" -c "$QTS/qt_ui.cpp" -o "$RT/qt/qt_ui.o"
      fi
      nvnobjs+=("$RT/qt/qt_ui.o")
      FW="$FW $(pkg-config --libs Qt6Widgets)"
    fi ;;
  *) echo "unbekanntes NVN_BACKEND=$NVN_BACKEND (metal|vulkan|none)" >&2; exit 2 ;;
esac
if [ "$(uname -s)" = Linux ]; then INC="$INC -I scripts/recomp/linux/compat"; fi
rm -f "$RT/nvn_null.o"
# macOS app (BDSP_APP=1): additionally the shell from app/ (configuration, save, menu, input); objects and output kept separate (RT, OUT)
if [ -n "${BDSP_APP:-}" ]; then
  [ "$NVN_BACKEND" = metal ] || { echo "BDSP_APP=1 braucht NVN_BACKEND=metal" >&2; exit 2; }
  EXTRA="$EXTRA -DBDSP_APP"
  FW="$FW -framework GameController"
fi
objs=()
for f in "$SRC"/*.c; do
  o="$RT/$(basename "$f" .c).o"
  objs+=("$o")
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ "$SRC/bdsp.h" -nt "$o" ] || [ "$SRC/guestmem.h" -nt "$o" ] || [ "$SRC/audio_output.h" -nt "$o" ] || { [ -n "${BDSP_APP:-}" ] && [ "$SRC/app/app.h" -nt "$o" ]; }; then
    clang -O1 -g -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function $INC $EXTRA "$@" -c "$f" -o "$o"
  fi
done
if [ -n "${BDSP_APP:-}" ]; then
  for f in "$SRC"/app/*.c "$SRC"/app/*.m; do
    [ -e "$f" ] || continue
    o="$RT/app_$(basename "${f%.*}").o"
    objs+=("$o")
    if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ "$SRC/app/app.h" -nt "$o" ] || [ scripts/recomp/app/icon_variants.h -nt "$o" ]; then
      case "$f" in
        *.m) /usr/bin/clang -O1 -g -Wall -Wno-unused-parameter -fobjc-arc $INC $(pkg-config --cflags sdl3) -c "$f" -o "$o" ;;
        *) clang -O1 -g -Wall -Wextra -Wno-unused-parameter $INC -c "$f" -o "$o" ;;
      esac
    fi
  done
fi
objs+=(${nvnobjs[@]+"${nvnobjs[@]}"})
newest=$(ls -t "${objs[@]}" | head -1)
if [ ! -x "$OUT" ] || [ "$newest" -nt "$OUT" ] || [ -n "$(find "$OBJ" -name '*.o' -newer "$OUT" -print -quit)" ]; then
  clang -o "$OUT" "${objs[@]}" "$OBJ"/*.o $FW
  echo "gelinkt: $OUT"
else
  echo "up to date: $OUT"
fi
