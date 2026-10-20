#!/bin/bash
# Baut die Laufzeit in Speichermodell B (--rebase32) und bindet sie mit den Gastobjekten aus work/recomp/obj32 (gen32.sh):
#   build_rt32.sh mac     -> work/recomp/bdsp_boot32 (macOS arm64, Metal + SDL3 + FFmpeg wie die Variante A; Testlauf für den Bildvergleich)
#   build_rt32.sh ios     -> work/recomp/ios-rt/*.o und work/recomp/ios-rt/libbdsp_rt.a (iPhoneOS, ohne SDL/FFmpeg; Eingabe und Fenster
#                            liefert die App, scripts/recomp/ios/app)
# Die NVN-Quellen (work/recomp/nvn-src, prepare.sh) werden mit nvn_rebase32.py in eine Kopie nvn-src32 umgeschrieben.
set -euo pipefail
cd "$(dirname "$0")/../../.."
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
TARGET=${1:-mac}
SRC=scripts/recomp/rt-bdsp
NVN32=work/recomp/nvn-src32
OBJ=${OBJ:-work/recomp/obj32}
BASEINC="-I scripts/recomp/rt32 -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I $SRC"
# Kopie neu anlegen, wenn sie fehlt oder die Repo-Quellen neuer sind (sonst läuft das iPad mit veraltetem Renderer)
scripts/recomp/rt-bdsp/nvn/prepare.sh > /dev/null   # kopiert nur bei abweichendem Stempel
# nvn-src32: Stempel aus dem Quellstempel plus nvn_rebase32.py und movie_glue.c
. scripts/recomp/rt-bdsp/nvn/hash.inc.sh
want32=$({ cat work/recomp/nvn-src/.stamp; sha256 scripts/recomp/ios/nvn_rebase32.py "$SRC/nvn/movie_glue.c"; } | sha256 | cut -d' ' -f1)
if [ ! -d "$NVN32/nvn" ] || [ "$(cat "$NVN32/.stamp32" 2>/dev/null || true)" != "$want32" ]; then
  python3 scripts/recomp/ios/nvn_rebase32.py work/recomp/nvn-src "$NVN32" > /dev/null
  echo "$want32" > "$NVN32/.stamp32"
fi

case "$TARGET" in
  mac)
    RT=work/recomp/rt-bdsp32; OUT=work/recomp/bdsp_boot32
    CCFLAGS=""; MCC=/usr/bin/clang
    NVINC="-I $NVN32 -I $NVN32/nvn $BASEINC $(pkg-config --cflags sdl3)"
    FFINC=$(pkg-config --cflags libavcodec libavformat libavutil)
    FW="-framework Metal -framework MetalFX -framework AppKit -framework QuartzCore -framework CoreGraphics -framework ImageIO -framework CoreServices -framework UniformTypeIdentifiers -framework Foundation $(pkg-config --libs sdl3) $(pkg-config --libs libavcodec libavformat libavutil)"
    ;;
  ios)
    RT=work/recomp/ios-rt; OUT=
    SDKP=$(xcrun --sdk iphoneos --show-sdk-path)
    CCFLAGS="-target arm64-apple-ios17.0 -isysroot $SDKP -DBDSP_IOS"; MCC="/usr/bin/clang $CCFLAGS"
    NVINC="-I scripts/recomp/ios/shim -I $NVN32 -I $NVN32/nvn $BASEINC"
    FFINC=""; [ -d work/ios/ffmpeg-ios/include ] && FFINC="-I work/ios/ffmpeg-ios/include"
    ;;
  *) echo "Aufruf: build_rt32.sh mac|ios" >&2; exit 2 ;;
esac
mkdir -p "$RT/nvn"
. scripts/recomp/rt-bdsp/nvn/flags.inc.sh
DEFS="-DBDSP_REBASE32"
[ "$TARGET" = ios ] && SDLINC="-I scripts/recomp/ios/shim" || SDLINC=""

compile() {  # Quelle Objekt Compiler Flags...
  local f=$1 o=$2 cc=$3; shift 3
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ -n "$(find "$SRC" "$NVN32" scripts/recomp/rt32 -name '*.h' -newer "$o" -print -quit)" ]; then
    $cc "$@" -c "$f" -o "$o"
  fi
}
CC="clang"; [ "$TARGET" = ios ] && CC="clang $CCFLAGS"
for f in "$SRC"/*.c; do
  b=$(basename "$f" .c)
  [ "$TARGET" = ios ] && [ "$b" = main ] && extra="-Dmain=bdsp_runtime_main" || extra=""
  compile "$f" "$RT/$b.o" "$CC" $BDSP_OPT $BDSP_WARN_GLUE -Wno-sign-compare -Wno-unused-function $DEFS $SDLINC $BASEINC $extra "${@:2}"
done
W="$BDSP_NOWARN $BDSP_OPT $DEFS"
for f in objects cmdbuf formats tegra astc; do compile "$NVN32/nvn/$f.c" "$RT/nvn/$f.o" "$CC" $W $NVINC; done
compile "$NVN32/nvn/maxwell/translate.c" "$RT/nvn/translate.o" "$CC" $W $NVINC
if [ "$TARGET" = mac ]; then
  compile "$NVN32/nvn/renderer.m" "$RT/nvn/renderer.o" "$MCC" $W $NVINC -fobjc-arc
  compile "$NVN32/nvn/metal.m" "$RT/nvn/metal.o" "$MCC" $W $NVINC -fobjc-arc
else
  # iOS: Fenster und Eingabe liefert die App; metal.m wird mit ui_ios.inc statt des SDL-Teils übersetzt (siehe scripts/recomp/ios/ui_ios.inc)
  if [ ! -f "$NVN32/nvn/metal_ios.m" ] || [ "$NVN32/nvn/metal.m" -nt "$NVN32/nvn/metal_ios.m" ] || [ scripts/recomp/ios/ui_ios.inc -nt "$NVN32/nvn/metal_ios.m" ] || [ scripts/recomp/ios/nvn_ios.py -nt "$NVN32/nvn/metal_ios.m" ]; then
    python3 scripts/recomp/ios/nvn_ios.py "$NVN32" > /dev/null
  fi
  compile "$NVN32/nvn/renderer_ios.m" "$RT/nvn/renderer.o" "$MCC" $W $NVINC -fobjc-arc
  compile "$NVN32/nvn/metal_ios.m" "$RT/nvn/metal.o" "$MCC" $W $NVINC -fobjc-arc
fi
compile "$SRC/nvn/nvn_glue.c" "$RT/nvn/nvn_glue.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS $NVINC
compile "$SRC/nvn/debug_thread.c" "$RT/nvn/debug_thread.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS $NVINC
if [ "$TARGET" = mac ] || [ -n "$FFINC" ]; then
  compile "$NVN32/movie_glue32.c" "$RT/nvn/movie_glue.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS $NVINC $FFINC
fi

if [ "$TARGET" = mac ]; then
  # Gastobjekte: plattformlose Kopien (die Objekte sind für iOS übersetzt; vtool entfernt die Plattform, dann bindet sie auch der Mac)
  MOBJ=work/recomp/obj32m
  mkdir -p "$MOBJ"
  ls "$OBJ"/*.o | xargs -P 4 -n 20 bash -c 'for o in "$@"; do m='"$MOBJ"'/$(basename "$o"); [ "$m" -nt "$o" ] || xcrun vtool -remove-build-version ios -output "$m" "$o" 2>/dev/null; done' _
  objs=("$RT"/*.o "$RT"/nvn/*.o)
  if [ ! -x "$OUT" ] || [ -n "$(find "$RT" "$MOBJ" -name '*.o' -newer "$OUT" -print -quit)" ]; then
    clang -o "$OUT" "${objs[@]}" "$MOBJ"/*.o $FW
    echo "gelinkt: $OUT"
  else
    echo "aktuell: $OUT"
  fi
else
  rm -f "$RT/libbdsp_rt.a"
  libtool -static -o "$RT/libbdsp_rt.a" "$RT"/*.o "$RT"/nvn/*.o 2>/dev/null
  echo "Bibliothek: $RT/libbdsp_rt.a"
fi
