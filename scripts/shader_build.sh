#!/usr/bin/env bash
# Stage "shaders" of the build pipeline (integration in scripts/build_all.sh: docs/shader-unity-integration.md, section 13).
# Bundle shaders -> blobs -> inventory -> maxwell2msl --lang hlsl -> shader_wrap -> Unity project output.
# Uses only data from your own NSP/XCI (the bundles unpacked by build_all.sh extract), never the Ryujinx caches.
# Everything is deterministic: same input -> same files (names from the SHA-1 of the keyword set, sorted enumeration).
#
# Usage:
#   scripts/shader_build.sh [--romfs DIR] [--out DIR] [--used FILE] [--shader NAME] [--force]
#   --romfs DIR   unpacked RomFS (default: work/romfs); contains Data/StreamingAssets/AssetAssistant/...
#   --out DIR     output of the .shader files (default: work/build/shaders; for the main Unity project:
#                 unity/Assets/GameData/Shaders, gitignored)
#   --used FILE   JSON [{"shader","keywords"}]: generate only these keyword sets (stripping)
#   --shader N    only one shader (test)
#   --force       regenerate the intermediate stages
# Exit codes: 0 ok, 2 usage, 3 input missing, 4 tool/build, 9 not all variants wrappable (list in variants.json)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ROMFS="$ROOT/work/romfs" OUT="$ROOT/work/build/shaders" USED="" ONLY="" FORCE=0
PYDEPS="${PYDEPS:-$ROOT/tools/pydeps}"
SH="$ROOT/work/shaders"

log() { echo "[$(date +%H:%M:%S)] shaders: $*"; }
die() { local code="$1"; shift; echo "ERROR: $*" >&2; exit "$code"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --romfs) ROMFS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --used) USED="$2"; shift 2 ;;
    --shader) ONLY="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die 2 "Unknown option: $1" ;;
  esac
done

BUNDLE_DIR="$ROMFS/Data/StreamingAssets/AssetAssistant"
[ "$ROMFS" = "$ROOT/work/romfs" ] || die 2 "--romfs: the helper scripts read work/romfs hard-coded (output of build_all.sh extract); link the folder there"
[ -f "$BUNDLE_DIR/Dpr/shaders" ] || die 3 "Shader bundle missing: $BUNDLE_DIR/Dpr/shaders (first: scripts/build_all.sh extract ...)"
[ -f "$BUNDLE_DIR/Effects/fxparticle" ] || die 3 "Shader bundle missing: $BUNDLE_DIR/Effects/fxparticle"
if [ "${BDSP_INSTALLER_PRIVATE_RUNTIME:-0}" != 1 ]; then
  [ -d "$PYDEPS" ] || die 4 "Python dependencies missing ($PYDEPS: UnityPy, lz4); scripts/build_all.sh tools"
fi
mkdir -p "$SH"

shader_python() {
  if [ "${BDSP_INSTALLER_PRIVATE_RUNTIME:-0}" = 1 ]; then
    python3 -I -B "$@"
  else
    PYTHONPATH="$PYDEPS${PYTHONPATH:+:$PYTHONPATH}" python3 "$@"
  fi
}

# 1. Translator
if [ "$FORCE" = 1 ] || [ ! -x "$ROOT/shader_translator/build/maxwell2msl" ]; then
  log "building maxwell2msl"
  make -C "$ROOT/shader_translator" >/dev/null || die 4 "make in shader_translator failed"
fi

cd "$ROOT"
# 2. Blobs (unique Maxwell programs)  3. Inventory (properties, state, layouts)  4. Program -> blob hash
if [ "$FORCE" = 1 ] || [ ! -f "$SH/blobs/index.json" ]; then
  log "extracting blobs"
  shader_python scripts/shader_extract_blobs.py --out work/shaders/blobs --extra >/dev/null
fi
if [ "$FORCE" = 1 ] || [ ! -f "$SH/inventory.json" ]; then
  log "generating inventory"
  shader_python scripts/shader_inventory.py --out work/shaders/inventory.json >/dev/null
fi
if [ "$FORCE" = 1 ] || [ ! -f "$SH/prog_blob.json" ]; then
  log "mapping programs to blobs"
  shader_python scripts/shader_fidelity.py index >/dev/null
fi

# 5. Wrapper: one .shader per shader/pass/keyword set (output gitignored)
ARGS=(--out "$OUT")
[ -n "$USED" ] && ARGS+=(--used "$USED")
[ -n "$ONLY" ] && ARGS+=(--shader "$ONLY")
log "wrapping variants to $OUT"
set +e
python3 scripts/shader_wrap_all.py "${ARGS[@]}"
RC=$?
set -e
[ "$RC" = 0 ] || { log "not all variants wrappable (variants.json)"; exit 9; }
log "done"
