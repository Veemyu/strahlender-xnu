#!/bin/bash
# Builds the runtime for iPhoneOS (memory model A-low) and packs it into work/recomp/ios-rt-a/libbdsp_rt.a, without SDL and FFmpeg: input and
# window are provided by the app (scripts/recomp/ios/app). Memory model A-low: guest address == host address at the fixed window ORG
# (default 0x800000000, must match gen32.sh); the NVN sources are used unchanged (copy nvn-src-a, only the UI part is replaced); the guest
# objects come from work/recomp/obj4i (gen32.sh).
#   build_rt32.sh [ios]
# BDSP_SYNTAX_ONLY=1 only checks that every runtime source compiles (scripts/check.sh runs it).
set -euo pipefail
cd "$(dirname "$0")/../../.."
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
TARGET=${1:-ios}
[ "$TARGET" = ios ] || { echo "Usage: build_rt32.sh [ios]" >&2; exit 2; }
SRC=scripts/recomp/runtime
ORG=${ORG:-0x800000000}
NVN32=${BDSP_IOS_NVN_DIR:-work/recomp/nvn-src-a}
BASEINC=(-I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I "$SRC")
export NVN_SRC=${NVN_SRC:-work/recomp/nvn-src}
# Recreate the copy if it is missing or the repo sources are newer (otherwise the iPad runs with an outdated renderer)
scripts/recomp/runtime/nvn/prepare.sh > /dev/null   # copies only if the stamp differs
# nvn-src-a: stamp from the source stamp plus nvn_ios.py and ui_ios.inc
. scripts/recomp/runtime/nvn/hash.inc.sh
want32=$({ cat "$NVN_SRC/.stamp"; sha256 scripts/recomp/ios/nvn_ios.py scripts/recomp/ios/ui_ios.inc; } | sha256 | cut -d' ' -f1)
if [ ! -d "$NVN32/nvn" ] || [ "$(cat "$NVN32/.stamp32" 2>/dev/null || true)" != "$want32" ]; then
  rm -rf "$NVN32"; cp -R "$NVN_SRC" "$NVN32"
  python3 scripts/recomp/ios/nvn_ios.py "$NVN32" > /dev/null
  echo "$want32" > "$NVN32/.stamp32"
fi

RT=${BDSP_IOS_RT_DIR:-work/recomp/ios-rt-a}
SDKP=$(xcrun --sdk iphoneos --show-sdk-path)
CCFLAGS=(-target arm64-apple-ios17.0 -isysroot "$SDKP" -DBDSP_IOS); MCC=/usr/bin/clang
NVINC=(-I scripts/recomp/ios/shim -I "$NVN32" -I "$NVN32/nvn" "${BASEINC[@]}")
FFDIR=$(python3 scripts/install/ffmpeg_cache.py dir)
FFINC=(); [ ! -d "$FFDIR/include" ] || FFINC=(-I "$FFDIR/include")
[ -z "${BDSP_SYNTAX_ONLY:-}" ] || RT=$(mktemp -d)
mkdir -p "$RT/nvn"
HAS_SUBSDK1=0
[ ! -f "${BDSP_EXEFS_DIR:-work/exefs}/subsdk1" ] || HAS_SUBSDK1=1
# Toolchain stamp: reuse objects only with the compiler and SDKs they were built with
TC_STAMP=$({ xcrun --sdk macosx --show-sdk-version; xcrun --sdk iphoneos --show-sdk-version; xcode-select -p; clang --version; echo "model a ${ORG} subsdk1=$HAS_SUBSDK1"; } | sha256 | cut -d' ' -f1)
if [ "$(cat "$RT/.stamp" 2>/dev/null || true)" != "$TC_STAMP" ]; then rm -f "$RT"/*.o "$RT"/nvn/*.o; echo "$TC_STAMP" > "$RT/.stamp"; fi
. scripts/recomp/runtime/nvn/flags.inc.sh
DEFS="-DBDSP_COMPACT_BASE=${ORG}ull -DBDSP_HAS_SUBSDK1=$HAS_SUBSDK1"
SDLINC=(-I scripts/recomp/ios/shim)

compile() {  # source object compiler flags...
  local f=$1 o=$2 cc=$3; shift 3
  if [ -n "${BDSP_SYNTAX_ONLY:-}" ]; then "$cc" "${CCFLAGS[@]}" "$@" -fsyntax-only "$f"; return; fi
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ -n "$(find "$SRC" "$NVN32" -name '*.h' -newer "$o" -print -quit)" ]; then
    "$cc" "${CCFLAGS[@]}" "$@" -c "$f" -o "$o"
  fi
}
CC=clang
for f in "$SRC"/*.c; do
  b=$(basename "$f" .c)
  [ "$b" = main ] && extra="-Dmain=bdsp_runtime_main" || extra=""
  compile "$f" "$RT/$b.o" "$CC" $BDSP_OPT $BDSP_WARN_GLUE -Wno-sign-compare -Wno-unused-function $DEFS "${SDLINC[@]}" "${BASEINC[@]}" $extra "${@:2}"
done
W="$BDSP_NOWARN $BDSP_OPT $DEFS"
for f in objects cmdbuf formats tegra astc bctc; do compile "$NVN32/nvn/$f.c" "$RT/nvn/$f.o" "$CC" $W "${NVINC[@]}"; done
compile "$NVN32/nvn/maxwell/translate.c" "$RT/nvn/translate.o" "$CC" $W "${NVINC[@]}"
# Window and input are provided by the app; metal.m is compiled with ui_ios.inc instead of the SDL part (see scripts/recomp/ios/ui_ios.inc)
if [ ! -f "$NVN32/nvn/metal_ios.m" ] || [ "$NVN32/nvn/metal.m" -nt "$NVN32/nvn/metal_ios.m" ] || [ scripts/recomp/ios/ui_ios.inc -nt "$NVN32/nvn/metal_ios.m" ] || [ scripts/recomp/ios/nvn_ios.py -nt "$NVN32/nvn/metal_ios.m" ]; then
  python3 scripts/recomp/ios/nvn_ios.py "$NVN32" > /dev/null
fi
compile "$NVN32/nvn/renderer_ios.m" "$RT/nvn/renderer.o" "$MCC" $W "${NVINC[@]}" -fobjc-arc
compile "$NVN32/nvn/metal_ios.m" "$RT/nvn/metal.o" "$MCC" $W "${NVINC[@]}" -fobjc-arc
compile "$SRC/nvn/swkbd_overlay.m" "$RT/nvn/swkbd_overlay.o" "$MCC" $W "${NVINC[@]}" -fobjc-arc   # on-screen keyboard (drawn over the frame, Metal)
compile "$SRC/nvn/nvn_glue.c" "$RT/nvn/nvn_glue.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS "${NVINC[@]}"
compile "$SRC/nvn/debug_thread.c" "$RT/nvn/debug_thread.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS "${NVINC[@]}"
if [ "${#FFINC[@]}" -gt 0 ]; then
  compile "$SRC/nvn/movie_glue.c" "$RT/nvn/movie_glue.o" "$CC" $BDSP_OPT $BDSP_NOWARN $DEFS "${NVINC[@]}" "${FFINC[@]}"
fi

if [ -n "${BDSP_SYNTAX_ONLY:-}" ]; then rm -rf "$RT"; echo "syntax ok: ios model a"; exit 0; fi

rm -f "$RT/libbdsp_rt.a"
libtool -static -o "$RT/libbdsp_rt.a" "$RT"/*.o "$RT"/nvn/*.o 2>/dev/null
echo "Library:$RT/libbdsp_rt.a"
