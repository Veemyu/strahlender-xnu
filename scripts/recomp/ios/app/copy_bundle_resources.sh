#!/bin/sh
# Xcode-Build-Phase: legt Shader-Cache, vorgefertigte Metallibs und pipelines.bin ins App-Bundle. Die Quellen liegen nur in work/
# (gitignoriert). Fehlt eine Quelle, startet die Laufzeit mit dem Kompilieren aus dem Quelltext (langsamer, aber lauffähig).
set -eu
SRC="${SRCROOT}/../../../../work/recomp/cache"
DST="${TARGET_BUILD_DIR}/${UNLOCALIZED_RESOURCES_FOLDER_PATH}"

if [ -d "$SRC/shaders" ]; then
  rm -rf "$DST/shaders"
  cp -R "$SRC/shaders" "$DST/shaders"
  echo "Shader-Cache: $(ls "$DST/shaders" | wc -l | tr -d ' ') Dateien"
else
  echo "Shader-Cache fehlt ($SRC/shaders)"
fi

if [ -d "$SRC/shaders-bin-iphoneos" ]; then
  rm -rf "$DST/shaders-bin"
  cp -R "$SRC/shaders-bin-iphoneos" "$DST/shaders-bin"
  echo "Metallibs: $(ls "$DST/shaders-bin" | wc -l | tr -d ' ') Dateien"
fi

if [ -f "$SRC/pipelines.bin" ]; then
  cp "$SRC/pipelines.bin" "$DST/pipelines.bin"
fi
