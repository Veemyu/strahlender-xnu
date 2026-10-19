#!/usr/bin/env bash
# Stufe "shaders" der Build-Pipeline (Integration in scripts/build_all.sh: docs/shader-unity-integration.md, Abschnitt 13).
# Bundle-Shader -> Blobs -> Inventar -> maxwell2msl --lang hlsl -> shader_wrap -> Unity-Projekt-Ausgabe.
# Nutzt nur Daten aus dem eigenen NSP/XCI (die von build_all.sh extract entpackten Bundles), nie die Ryujinx-Caches.
# Alles deterministisch: gleiche Eingabe -> gleiche Dateien (Namen aus SHA-1 der Keyword-Menge, sortierte Aufzaehlung).
#
# Aufruf:
#   scripts/shader_build.sh [--romfs DIR] [--out DIR] [--used FILE] [--shader NAME] [--force]
#   --romfs DIR   entpacktes RomFS (Standard: work/romfs); enthaelt Data/StreamingAssets/AssetAssistant/...
#   --out DIR     Ausgabe der .shader (Standard: work/build/shaders; fuer das Haupt-Unity-Projekt:
#                 unity/Assets/GameData/Shaders, gitignoriert)
#   --used FILE   JSON [{"shader","keywords"}]: nur diese Keyword-Mengen erzeugen (Strippen)
#   --shader N    nur ein Shader (Test)
#   --force       Zwischenstufen neu erzeugen
# Exit-Codes: 0 ok, 2 Aufruf, 3 Eingabe fehlt, 4 Werkzeug/Build, 9 nicht alle Varianten verpackbar (Liste in variants.json)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ROMFS="$ROOT/work/romfs" OUT="$ROOT/work/build/shaders" USED="" ONLY="" FORCE=0
PYDEPS="${PYDEPS:-$ROOT/tools/pydeps}"
SH="$ROOT/work/shaders"

log() { echo "[$(date +%H:%M:%S)] shaders: $*"; }
die() { local code="$1"; shift; echo "FEHLER: $*" >&2; exit "$code"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --romfs) ROMFS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --used) USED="$2"; shift 2 ;;
    --shader) ONLY="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die 2 "Unbekannte Option: $1" ;;
  esac
done

BUNDLE_DIR="$ROMFS/Data/StreamingAssets/AssetAssistant"
[ "$ROMFS" = "$ROOT/work/romfs" ] || die 2 "--romfs: die Hilfsskripte lesen fest work/romfs (Ausgabe von build_all.sh extract); Ordner dorthin verlinken"
[ -f "$BUNDLE_DIR/Dpr/shaders" ] || die 3 "Shader-Bundle fehlt: $BUNDLE_DIR/Dpr/shaders (erst: scripts/build_all.sh extract ...)"
[ -f "$BUNDLE_DIR/Effects/fxparticle" ] || die 3 "Shader-Bundle fehlt: $BUNDLE_DIR/Effects/fxparticle"
[ -d "$PYDEPS" ] || die 4 "Python-Abhaengigkeiten fehlen ($PYDEPS: UnityPy, lz4); scripts/build_all.sh tools"
mkdir -p "$SH"

# 1. Uebersetzer
if [ "$FORCE" = 1 ] || [ ! -x "$ROOT/shader_translator/build/maxwell2msl" ]; then
  log "baue maxwell2msl"
  make -C "$ROOT/shader_translator" >/dev/null || die 4 "make in shader_translator fehlgeschlagen"
fi

cd "$ROOT"
# 2. Blobs (eindeutige Maxwell-Programme)  3. Inventar (Properties, Zustand, Layouts)  4. Programm -> Blob-Hash
if [ "$FORCE" = 1 ] || [ ! -f "$SH/blobs/index.json" ]; then
  log "extrahiere Blobs"
  PYTHONPATH="$PYDEPS" python3 scripts/shader_extract_blobs.py --out work/shaders/blobs --extra >/dev/null
fi
if [ "$FORCE" = 1 ] || [ ! -f "$SH/inventory.json" ]; then
  log "erzeuge Inventar"
  PYTHONPATH="$PYDEPS" python3 scripts/shader_inventory.py --out work/shaders/inventory.json >/dev/null
fi
if [ "$FORCE" = 1 ] || [ ! -f "$SH/prog_blob.json" ]; then
  log "ordne Programme den Blobs zu"
  PYTHONPATH="$PYDEPS" python3 scripts/shader_fidelity.py index >/dev/null
fi

# 5. Wrapper: je Shader/Pass/Keyword-Menge eine .shader (Ausgabe gitignoriert)
ARGS=(--out "$OUT")
[ -n "$USED" ] && ARGS+=(--used "$USED")
[ -n "$ONLY" ] && ARGS+=(--shader "$ONLY")
log "verpacke Varianten nach $OUT"
set +e
python3 scripts/shader_wrap_all.py "${ARGS[@]}"
RC=$?
set -e
[ "$RC" = 0 ] || { log "nicht alle Varianten verpackbar (variants.json)"; exit 9; }
log "fertig"
