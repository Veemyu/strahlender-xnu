#!/bin/bash
# Baut die BDSP-Laufzeit (scripts/recomp/rt-bdsp/*.c) und bindet sie mit den übersetzten Gastmodulen (work/recomp/obj4/*.o)
# zu work/recomp/bdsp_boot. Inkrementell: Laufzeitdateien nur bei Änderung, Link nur wenn eine Eingabe neuer ist.
# Aufruf: build.sh [-DMakro ...]      Umgebung: OBJ=work/recomp/obj4  RT=work/recomp/rt-bdsp  OUT=work/recomp/bdsp_boot
set -euo pipefail
cd "$(dirname "$0")/../../.."
OBJ=${OBJ:-work/recomp/obj4}
RT=${RT:-work/recomp/rt-bdsp}
OUT=${OUT:-work/recomp/bdsp_boot}
mkdir -p "$RT"
SRC=scripts/recomp/rt-bdsp
INC="-I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I $SRC"
# Grafik-Backend zur Bauzeit: metal (macOS, Standard), vulkan (Linux/Windows: nvn/vulkan/, Ausgabe work/recomp/bdsp_boot_vk, Objekte rt-bdsp-vk; siehe
# docs/recomp-vulkan.md), none (keine Grafik: der NVN-Treiber des SDK bleibt,
# Verhalten wie Gate 1; Standard unter Linux bis das Vulkan-Backend steht). Linux: Mach-Ersatz aus scripts/recomp/ryzen/compat.
NVN_BACKEND=${NVN_BACKEND:-$([ "$(uname -s)" = Darwin ] && echo metal || echo none)}
EXTRA=""
FW=""
nvnobjs=()
case "$NVN_BACKEND" in
  metal)
    # NVN_RT: Objektordner der NVN-Schicht (unabhängig von RT, damit die App-Fassung dieselben Objekte nutzt)
    RT="${NVN_RT:-$RT}" scripts/recomp/rt-bdsp/nvn/build_nvn.sh "$@"
    nvnobjs=("${NVN_RT:-$RT}"/nvn/*.o)
    FW="-framework AudioToolbox -framework Metal -framework MetalFX -framework AppKit -framework QuartzCore -framework CoreText -framework CoreGraphics -framework ImageIO -framework CoreServices -framework UniformTypeIdentifiers -framework Foundation $(pkg-config --libs sdl3) $([ -n "${BDSP_NO_MOVIE:-}" ] || pkg-config --libs libavcodec libavformat libavutil)" ;;
  none) EXTRA="-DBDSP_NVN_NONE"; RT="${RT}-none"; mkdir -p "$RT"
    [ "$(uname -s)" != Darwin ] || FW="-framework AudioToolbox" ;;
  vulkan) RT="${RT}-vk"; OUT="${OUT}_vk"; mkdir -p "$RT"   # Linux/Windows: Vulkan-Fassung der LAS-NVN-Schicht (nvn/vulkan/), Laufzeitbibliotheken per Vollpfad
    RT="$RT" scripts/recomp/rt-bdsp/nvn/vulkan/build_vk.sh "$@"
    nvnobjs=("$RT"/nvnvk/*.o)
    FW="-l:libvulkan.so.1 -l:libSDL3.so.0 -l:libshaderc_shared.so.1 -lstdc++ -lm -lpthread -ldl"
    [ -n "${BDSP_NO_MOVIE:-}" ] || FW="$FW -l:libavformat.so.62 -l:libavcodec.so.62 -l:libavutil.so.60"
    if [ -n "${BDSP_QT:-}" ]; then   # Qt-Hülle im Prozess (Menüleiste, Vulkan-Fläche von Qt): app/linux/qt_ui.cpp, Ausgabe bdsp_boot_vk_qt; Windows nur vorbereitet (nicht gebaut)
      OUT="${OUT}_qt"; mkdir -p "$RT/qt"
      QTCF=$(pkg-config --cflags Qt6Widgets) || { echo "Qt6 Widgets fehlt (Liste: scripts/recomp/rt-bdsp/app/linux/deps.txt)" >&2; exit 3; }
      QTI=""; [ -d include-vk/SDL3 ] && QTI="-I $PWD/include-vk"
      QTS=scripts/recomp/rt-bdsp/app/linux
      if [ ! -f "$RT/qt/qt_ui.o" ] || [ "$QTS/qt_ui.cpp" -nt "$RT/qt/qt_ui.o" ] || [ "$QTS/bdsp_l10n.h" -nt "$RT/qt/qt_ui.o" ]; then
        clang++ -std=c++17 -O1 -g -fPIC -Wall -Wextra -Wno-unused-parameter $QTCF $QTI -I "$QTS" -DBDSP_LPROJ_DIR="\"$PWD/$QTS/lproj\"" -c "$QTS/qt_ui.cpp" -o "$RT/qt/qt_ui.o"
      fi
      nvnobjs+=("$RT/qt/qt_ui.o")
      FW="$FW $(pkg-config --libs Qt6Widgets)"
    fi ;;
  *) echo "unbekanntes NVN_BACKEND=$NVN_BACKEND (metal|vulkan|none)" >&2; exit 2 ;;
esac
if [ "$(uname -s)" = Linux ]; then INC="$INC -I scripts/recomp/ryzen/compat"; fi
rm -f "$RT/nvn_null.o"
# macOS-App (BDSP_APP=1): zusätzlich die Hülle aus app/ (Konfiguration, Spielstand, Menü, Eingabe); Objekte und Ausgabe getrennt (RT, OUT)
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
    if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ "$SRC/app/app.h" -nt "$o" ]; then
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
  echo "aktuell: $OUT"
fi
