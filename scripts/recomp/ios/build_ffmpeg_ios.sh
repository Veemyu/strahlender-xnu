#!/bin/bash
# Baut ein minimales FFmpeg (VP8/VP9-Decoder, Matroska/WebM-Demuxer, Datei-Protokoll) als statische Bibliotheken für iPhoneOS arm64
# nach work/ios/ffmpeg-ios (Quelltext aus work/ios/ffmpeg-<Version>.tar.xz, von ffmpeg.org; nichts davon im Repo). Die Filmwiedergabe der
# Laufzeit (nvn/movie_glue.c) braucht libavformat/libavcodec/libavutil. Aufruf: build_ffmpeg_ios.sh [VERSION] [JOBS]
set -euo pipefail
cd "$(dirname "$0")/../../.."
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
VER=${1:-9.0.2}
JOBS=${2:-3}
W=work/ios
SDKP=$(xcrun --sdk iphoneos --show-sdk-path)
[ -d "$W/ffmpeg-$VER" ] || tar -xf "$W/ffmpeg-$VER.tar.xz" -C "$W"
PREFIX=$PWD/$W/ffmpeg-ios
cd "$W/ffmpeg-$VER"
if [ ! -f config.h ]; then
  ./configure --prefix="$PREFIX" --enable-cross-compile --target-os=darwin --arch=arm64 \
    --cc="clang -target arm64-apple-ios17.0 -isysroot $SDKP" --as="clang -target arm64-apple-ios17.0 -isysroot $SDKP" \
    --ar="$(xcrun -f ar)" --ranlib="$(xcrun -f ranlib)" --nm="$(xcrun -f nm)" --strip="$(xcrun -f strip)" \
    --disable-everything --disable-programs --disable-doc --disable-avdevice --disable-swscale --disable-swresample --disable-avfilter \
    --disable-network --disable-iconv --disable-securetransport --disable-videotoolbox --disable-audiotoolbox --disable-autodetect \
    --enable-static --disable-shared --enable-pic \
    --enable-decoder=vp8,vp9 --enable-parser=vp8,vp9 --enable-demuxer=matroska --enable-protocol=file > "../ffmpeg-configure.log" 2>&1
fi
make -j"$JOBS" > "../ffmpeg-make.log" 2>&1
make install > "../ffmpeg-install.log" 2>&1
ls "$PREFIX/lib"
