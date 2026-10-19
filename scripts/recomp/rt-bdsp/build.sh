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
INC="-I scripts/recomp/rt -I research/LASRecomp/runtime -I $SRC"
# Grafik-Backend zur Bauzeit: metal (macOS, Standard), vulkan (Linux/Windows: nvn/vulkan/, Ausgabe work/recomp/bdsp_boot_vk, Objekte rt-bdsp-vk; siehe
# docs/recomp-vulkan.md), none (keine Grafik: der NVN-Treiber des SDK bleibt,
# Verhalten wie Gate 1; Standard unter Linux bis das Vulkan-Backend steht). Linux: Mach-Ersatz aus scripts/recomp/ryzen/compat.
NVN_BACKEND=${NVN_BACKEND:-$([ "$(uname -s)" = Darwin ] && echo metal || echo none)}
EXTRA=""
FW=""
nvnobjs=()
case "$NVN_BACKEND" in
  metal)
    scripts/recomp/rt-bdsp/nvn/build_nvn.sh "$@"
    nvnobjs=("$RT"/nvn/*.o)
    FW="-framework Metal -framework MetalFX -framework AppKit -framework QuartzCore -framework CoreGraphics -framework ImageIO -framework CoreServices -framework UniformTypeIdentifiers -framework Foundation $(pkg-config --libs sdl3)" ;;
  none) EXTRA="-DBDSP_NVN_NONE"; RT="${RT}-none"; mkdir -p "$RT" ;;
  vulkan) RT="${RT}-vk"; OUT="${OUT}_vk"; mkdir -p "$RT"   # Linux/Windows: Vulkan-Fassung der LAS-NVN-Schicht (nvn/vulkan/), Laufzeitbibliotheken per Vollpfad
    RT="$RT" scripts/recomp/rt-bdsp/nvn/vulkan/build_vk.sh "$@"
    nvnobjs=("$RT"/nvnvk/*.o)
    FW="-l:libvulkan.so.1 -l:libSDL3.so.0 -l:libshaderc_shared.so.1 -lstdc++ -lm -lpthread -ldl" ;;
  *) echo "unbekanntes NVN_BACKEND=$NVN_BACKEND (metal|vulkan|none)" >&2; exit 2 ;;
esac
if [ "$(uname -s)" = Linux ]; then INC="$INC -I scripts/recomp/ryzen/compat"; fi
rm -f "$RT/nvn_null.o"
objs=()
for f in "$SRC"/*.c; do
  o="$RT/$(basename "$f" .c).o"
  objs+=("$o")
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ "$SRC/bdsp.h" -nt "$o" ] || [ "$SRC/guestmem.h" -nt "$o" ]; then
    clang -O1 -g -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function $INC $EXTRA "$@" -c "$f" -o "$o"
  fi
done
objs+=(${nvnobjs[@]+"${nvnobjs[@]}"})
newest=$(ls -t "${objs[@]}" | head -1)
if [ ! -x "$OUT" ] || [ "$newest" -nt "$OUT" ] || [ -n "$(find "$OBJ" -name '*.o' -newer "$OUT" -print -quit)" ]; then
  clang -o "$OUT" "${objs[@]}" "$OBJ"/*.o $FW
  echo "gelinkt: $OUT"
else
  echo "aktuell: $OUT"
fi
