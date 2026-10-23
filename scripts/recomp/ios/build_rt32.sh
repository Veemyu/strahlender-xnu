#!/bin/bash
# Builds the runtime in memory model B (--rebase32) and links it with the guest objects from work/recomp/obj32 (gen32.sh):
#   build_rt32.sh mac     -> work/recomp/bdsp_boot32 (macOS arm64, Metal + SDL3 + FFmpeg like variant A; test run for the image comparison)
#   build_rt32.sh ios     -> work/recomp/ios-rt/*.o and work/recomp/ios-rt/libbdsp_rt.a (iPhoneOS, without SDL/FFmpeg; input and window
#                            are provided by the app, scripts/recomp/ios/app)
# The NVN sources (work/recomp/nvn-src, prepare.sh) are rewritten by nvn_rebase32.py into a copy nvn-src32.
# MODEL=a (ios only) builds memory model A-low instead: guest address == host address at the fixed window ORG (default 0x800000000, must match
# gen32.sh), the NVN sources are used unchanged (copy nvn-src-a, only the UI part is replaced), objects from work/recomp/obj4i, output
# work/recomp/ios-rt-a.
set -euo pipefail
cd "$(dirname "$0")/../../.."
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
TARGET=${1:-mac}
SRC=scripts/recomp/rt-bdsp
MODEL=${MODEL:-b}
ORG=${ORG:-0x800000000}
if [ "$MODEL" = a ]; then
  [ "$TARGET" = ios ] || { echo "MODEL=a: only the ios target" >&2; exit 2; }
  NVN32=work/recomp/nvn-src-a
  OBJ=${OBJ:-work/recomp/obj4i}
  BASEINC="-I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I $SRC"
else
  NVN32=work/recomp/nvn-src32
  OBJ=${OBJ:-work/recomp/obj32}
  BASEINC="-I scripts/recomp/rt32 -I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I $SRC"
fi
# Recreate the copy if it is missing or the repo sources are newer (otherwise the iPad runs with an outdated renderer)
scripts/recomp/rt-bdsp/nvn/prepare.sh > /dev/null   # copies only if the stamp differs
# nvn-src32: stamp from the source stamp plus nvn_rebase32.py and movie_glue.c (model A-low: nvn_ios.py and ui_ios.inc instead)
. scripts/recomp/rt-bdsp/nvn/hash.inc.sh
if [ "$MODEL" = a ]; then
  want32=$({ cat work/recomp/nvn-src/.stamp; sha256 scripts/recomp/ios/nvn_ios.py scripts/recomp/ios/ui_ios.inc; } | sha256 | cut -d' ' -f1)
  if [ ! -d "$NVN32/nvn" ] || [ "$(cat "$NVN32/.stamp32" 2>/dev/null || true)" != "$want32" ]; then
    rm -rf "$NVN32"; cp -R work/recomp/nvn-src "$NVN32"
    python3 scripts/recomp/ios/nvn_ios.py "$NVN32" > /dev/null
    echo "$want32" > "$NVN32/.stamp32"
  fi
else
  want32=$({ cat work/recomp/nvn-src/.stamp; sha256 scripts/recomp/ios/nvn_rebase32.py "$SRC/nvn/movie_glue.c"; } | sha256 | cut -d' ' -f1)
  if [ ! -d "$NVN32/nvn" ] || [ "$(cat "$NVN32/.stamp32" 2>/dev/null || true)" != "$want32" ]; then
    python3 scripts/recomp/ios/nvn_rebase32.py work/recomp/nvn-src "$NVN32" > /dev/null
    echo "$want32" > "$NVN32/.stamp32"
  fi
fi

case "$TARGET" in
  mac)
    RT=work/recomp/rt-bdsp32; OUT=work/recomp/bdsp_boot32
    CCFLAGS=""; MCC=/usr/bin/clang
    NVINC="-I $NVN32 -I $NVN32/nvn $BASEINC $(pkg-config --cflags sdl3)"
    FFINC=$(pkg-config --cflags libavcodec libavformat libavutil)
    FW="-framework AudioToolbox -framework Metal -framework MetalFX -framework AppKit -framework QuartzCore -framework CoreText -framework CoreGraphics -framework ImageIO -framework CoreServices -framework UniformTypeIdentifiers -framework Foundation $(pkg-config --libs sdl3) $(pkg-config --libs libavcodec libavformat libavutil)"
    ;;
  ios)
    RT=work/recomp/ios-rt; [ "$MODEL" = a ] && RT=work/recomp/ios-rt-a; OUT=
    SDKP=$(xcrun --sdk iphoneos --show-sdk-path)
    CCFLAGS="-target arm64-apple-ios17.0 -isysroot $SDKP -DBDSP_IOS"; MCC="/usr/bin/clang $CCFLAGS"
    NVINC="-I scripts/recomp/ios/shim -I $NVN32 -I $NVN32/nvn $BASEINC"
    FFINC=""; [ -d work/ios/ffmpeg-ios/include ] && FFINC="-I work/ios/ffmpeg-ios/include"
    ;;
  *) echo "Usage: build_rt32.sh mac|ios" >&2; exit 2 ;;
esac
mkdir -p "$RT/nvn"
# Toolchain stamp: reuse objects only with the compiler and SDKs they were built with
TC_STAMP=$({ xcrun --sdk macosx --show-sdk-version; xcrun --sdk iphoneos --show-sdk-version; xcode-select -p; clang --version; echo "model ${MODEL:-b} ${ORG:-}"; } | sha256 | cut -d' ' -f1)
if [ "$(cat "$RT/.stamp" 2>/dev/null || true)" != "$TC_STAMP" ]; then rm -f "$RT"/*.o "$RT"/nvn/*.o; echo "$TC_STAMP" > "$RT/.stamp"; fi
. scripts/recomp/rt-bdsp/nvn/flags.inc.sh
DEFS="-DBDSP_REBASE32"; [ "$MODEL" = a ] && DEFS="-DBDSP_COMPACT_BASE=${ORG}ull"
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
  # iOS: window and input are provided by the app; metal.m is compiled with ui_ios.inc instead of the SDL part (see scripts/recomp/ios/ui_ios.inc)
  if [ ! -f "$NVN32/nvn/metal_ios.m" ] || [ "$NVN32/nvn/metal.m" -nt "$NVN32/nvn/metal_ios.m" ] || [ scripts/recomp/ios/ui_ios.inc -nt "$NVN32/nvn/metal_ios.m" ] || [ scripts/recomp/ios/nvn_ios.py -nt "$NVN32/nvn/metal_ios.m" ]; then
    python3 scripts/recomp/ios/nvn_ios.py "$NVN32" > /dev/null
  fi
  compile "$NVN32/nvn/renderer_ios.m" "$RT/nvn/renderer.o" "$MCC" $W $NVINC -fobjc-arc
  compile "$NVN32/nvn/metal_ios.m" "$RT/nvn/metal.o" "$MCC" $W $NVINC -fobjc-arc
fi
compile "$SRC/nvn/nvn_glue.c" "$RT/nvn/nvn_glue.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS $NVINC
compile "$SRC/nvn/debug_thread.c" "$RT/nvn/debug_thread.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS $NVINC
if [ "$TARGET" = mac ] || [ -n "$FFINC" ]; then
  MG="$NVN32/movie_glue32.c"; [ "$MODEL" = a ] && MG="$SRC/nvn/movie_glue.c"
  compile "$MG" "$RT/nvn/movie_glue.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS $NVINC $FFINC
fi

if [ "$TARGET" = mac ]; then
  # Guest objects: platformless copies (the objects are compiled for iOS; vtool removes the platform, then the Mac can link them too)
  MOBJ=work/recomp/obj32m
  mkdir -p "$MOBJ"
  ls "$OBJ"/*.o | xargs -P 4 -n 20 bash -c 'for o in "$@"; do m='"$MOBJ"'/$(basename "$o"); [ "$m" -nt "$o" ] || xcrun vtool -remove-build-version ios -output "$m" "$o" 2>/dev/null; done' _
  objs=("$RT"/*.o "$RT"/nvn/*.o)
  if [ ! -x "$OUT" ] || [ -n "$(find "$RT" "$MOBJ" -name '*.o' -newer "$OUT" -print -quit)" ]; then
    clang -o "$OUT" "${objs[@]}" "$MOBJ"/*.o $FW
    echo "linked: $OUT"
  else
    echo "up to date: $OUT"
  fi
else
  rm -f "$RT/libbdsp_rt.a"
  libtool -static -o "$RT/libbdsp_rt.a" "$RT"/*.o "$RT"/nvn/*.o 2>/dev/null
  echo "Library:$RT/libbdsp_rt.a"
fi
