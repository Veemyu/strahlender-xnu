#!/usr/bin/env bash
# Release preparation only. The shipped app never invokes pip.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TARGET="${1:?Usage: prepare_runtime.sh HOST-TARGET}"
BUILD="$ROOT/work/installer-runtime-release/$TARGET"
mkdir -p "$BUILD"
ASSET="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["targets"][sys.argv[2]]["python_asset"])' "$HERE/runtime/manifest.json" "$TARGET")"
curl -fL --retry 3 "https://github.com/astral-sh/python-build-standalone/releases/download/20260901/$ASSET" -o "$BUILD/python.tar.gz"
SOURCE_ARGS=(--source-builds "$BUILD/wheels")
python3 "$HERE/scripts/assemble_runtime.py" --target "$TARGET" --profile shaders --python-archive "$BUILD/python.tar.gz" --fetch-wheels --wheelhouse "$BUILD/wheels" --output "$BUILD/runtime" "${SOURCE_ARGS[@]}"
