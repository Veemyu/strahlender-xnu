#!/bin/sh
# Copy only platform-identified iPhoneOS libraries. Never retain stale resources
# from a previous incremental Xcode build, or substitute macOS metallibs.
set -eu
SRC="${BDSP_SHADER_CACHE_DIR:-${SRCROOT}/../../../../work/recomp/cache}"
DST="${TARGET_BUILD_DIR}/${UNLOCALIZED_RESOURCES_FOLDER_PATH}"
rm -rf "$DST/shaders" "$DST/shaders-bin"
rm -f "$DST/pipelines.bin"
if [ -d "$SRC/shaders" ]; then
  cp -R "$SRC/shaders" "$DST/shaders"
fi
if [ "${PLATFORM_NAME:-iphoneos}" = iphoneos ] && [ -f "$SRC/shaders-bin-iphoneos/.sdk" ] &&
   [ "$(cat "$SRC/shaders-bin-iphoneos/.sdk")" = iphoneos ]; then
  mkdir -p "$DST/shaders-bin"
  # Copy just libraries for current source hashes, never orphaned cache entries.
  for source in "$SRC"/shaders/[vf]_*.metal; do
    [ -f "$source" ] || continue
    name=$(basename "$source" .metal)
    test -s "$SRC/shaders-bin-iphoneos/$name.metallib"
    cp "$SRC/shaders-bin-iphoneos/$name.metallib" "$DST/shaders-bin/"
  done
  echo "Bundled iPhoneOS Metal libraries: $(find "$DST/shaders-bin" -name '*.metallib' | wc -l | tr -d ' ')"
else
  echo "No compatible prebuilt Metal libraries; runtime compilation remains available."
fi
if [ -f "$SRC/pipelines.bin" ]; then cp "$SRC/pipelines.bin" "$DST/pipelines.bin"; fi
