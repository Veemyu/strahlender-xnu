#!/bin/bash
# Builds a minimal FFmpeg (VP8/VP9 decoder, Matroska/WebM demuxer, file protocol) as static libraries for iPhoneOS arm64
# to $BDSP_IOS_FFMPEG_DIR (default work/ios/ffmpeg-ios; the installer sets a folder in its data directory so the libraries
# survive between builds). Source from work/ios/ffmpeg-<version>.tar.xz, from ffmpeg.org; none of it in the repo. The movie
# playback of the runtime (nvn/movie_glue.c) needs libavformat/libavcodec/libavutil.
# The folder is reused only when its stamp (source checksum, SDK, compiler, this script) matches; otherwise it is built in a
# temporary sibling folder and renamed, so an interrupted build never leaves a complete-looking folder.
# Usage: build_ffmpeg_ios.sh [--check] [VERSION] [JOBS]     (--check: exit 0 when the libraries are current, builds nothing)
set -euo pipefail
cd "$(dirname "$0")/../../.."
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}
CHECK=0; [ "${1:-}" != --check ] || { CHECK=1; shift; }
VER=${1:-9.0.2}
W=work/ios
SDKP=$(xcrun --sdk iphoneos --show-sdk-path)
mkdir -p "$W"
EXPECTED_SHA=${BDSP_FFMPEG_SHA256:-8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e}
if [ "$VER" != 9.0.2 ] && [ -z "${BDSP_FFMPEG_SHA256:-}" ]; then
  echo "A different FFmpeg version needs an explicit BDSP_FFMPEG_SHA256." >&2; exit 2
fi
FFDIR=$(python3 scripts/install/ffmpeg_cache.py dir)
STAMP=$(python3 scripts/install/ffmpeg_cache.py stamp "$EXPECTED_SHA" "$SDKP" "$(xcrun --sdk iphoneos --show-sdk-version)" "$(/usr/bin/clang --version)" scripts/recomp/ios/build_ffmpeg_ios.sh)
if python3 scripts/install/ffmpeg_cache.py current "$FFDIR" "$STAMP"; then echo "iPhone/iPad movie libraries are current: $FFDIR"; exit 0; fi
[ "$CHECK" = 0 ] || exit 1
JOBS=${2:-$(python3 scripts/recomp/parallel_jobs.py)}
case "$JOBS" in ''|*[!0-9]*) echo "JOBS must be a positive integer" >&2; exit 2;; esac
[ "$JOBS" -ge 1 ] || { echo "JOBS must be at least 1" >&2; exit 2; }
# "FFmpeg step n/4" lines drive the installer's progress display; keep the format.
ARCHIVE="$W/ffmpeg-$VER.tar.xz"
echo "FFmpeg step 1/4: getting the source"
if [ ! -f "$ARCHIVE" ]; then
  DOWNLOAD=$(mktemp "$W/.ffmpeg-download.XXXXXX")
  trap 'rm -f "$DOWNLOAD"' EXIT
  echo "Downloading FFmpeg $VER source for iPhone/iPad movie playback; verifying SHA-256 before extraction."
  /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 --retry 2 \
    "https://ffmpeg.org/releases/ffmpeg-$VER.tar.xz" --output "$DOWNLOAD"
  [ "$(shasum -a 256 "$DOWNLOAD" | cut -c1-64)" = "$EXPECTED_SHA" ] || { echo "FFmpeg source checksum mismatch; nothing extracted." >&2; exit 4; }
  mv "$DOWNLOAD" "$ARCHIVE"
fi
[ "$(shasum -a 256 "$ARCHIVE" | cut -c1-64)" = "$EXPECTED_SHA" ] || { echo "Cached FFmpeg source checksum mismatch; nothing extracted." >&2; exit 4; }
echo "FFmpeg step 2/4: unpacking"
[ -d "$W/ffmpeg-$VER" ] || tar -xf "$W/ffmpeg-$VER.tar.xz" -C "$W"
mkdir -p "$(dirname "$FFDIR")"
rm -rf "$FFDIR".building.*
PREFIX=$(mktemp -d "$FFDIR.building.XXXXXX")
trap 'rm -rf "$PREFIX"' EXIT
cd "$W/ffmpeg-$VER"
# The prefix differs per build, so a configured source tree is always cleaned first.
if [ -f config.h ]; then make distclean > /dev/null; fi
echo "FFmpeg step 3/4: configuring"
./configure --prefix="$PREFIX" --enable-cross-compile --target-os=darwin --arch=arm64 \
  --cc="clang -target arm64-apple-ios17.0 -isysroot $SDKP" --as="clang -target arm64-apple-ios17.0 -isysroot $SDKP" \
  --ar="$(xcrun -f ar)" --ranlib="$(xcrun -f ranlib)" --nm="$(xcrun -f nm)" --strip="$(xcrun -f strip)" \
  --disable-everything --disable-programs --disable-doc --disable-avdevice --disable-swscale --disable-swresample --disable-avfilter \
  --disable-network --disable-iconv --disable-securetransport --disable-videotoolbox --disable-audiotoolbox --disable-autodetect \
  --enable-static --disable-shared --enable-pic \
  --enable-decoder=vp8,vp9 --enable-parser=vp8,vp9 --enable-demuxer=matroska --enable-protocol=file > "../ffmpeg-configure.log" 2>&1
echo "FFmpeg step 4/4: compiling (about 1 minute)"
make -j"$JOBS" > "../ffmpeg-make.log" 2>&1
make install > "../ffmpeg-install.log" 2>&1
# Stamp last, then swap in: the folder looks complete only after the rename.
printf '%s\n' "$STAMP" > "$PREFIX/.bdsp-stamp"
rm -rf "$FFDIR"
mv "$PREFIX" "$FFDIR"
trap - EXIT
ls "$FFDIR/lib"
