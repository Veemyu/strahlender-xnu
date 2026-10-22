#!/bin/sh
# Xcode build phase: puts the shader cache, pre-built metallibs and pipelines.bin into the app bundle. The sources live only in work/
# (gitignored). If a source is missing, the runtime starts by compiling from the source text (slower, but runnable).
set -eu
SRC="${SRCROOT}/../../../../work/recomp/cache"
DST="${TARGET_BUILD_DIR}/${UNLOCALIZED_RESOURCES_FOLDER_PATH}"

if [ -d "$SRC/shaders" ]; then
  rm -rf "$DST/shaders"
  cp -R "$SRC/shaders" "$DST/shaders"
  echo "Shader cache: $(ls "$DST/shaders" | wc -l | tr -d ' ') files"
else
  echo "Shader cache missing ($SRC/shaders)"
fi

if [ -d "$SRC/shaders-bin-iphoneos" ]; then
  rm -rf "$DST/shaders-bin"
  cp -R "$SRC/shaders-bin-iphoneos" "$DST/shaders-bin"
  echo "Metallibs: $(ls "$DST/shaders-bin" | wc -l | tr -d ' ') files"
fi

if [ -f "$SRC/pipelines.bin" ]; then
  cp "$SRC/pipelines.bin" "$DST/pipelines.bin"
fi
