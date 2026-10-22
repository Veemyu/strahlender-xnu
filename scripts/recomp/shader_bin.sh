#!/usr/bin/env bash
# Übersetzt den lokal erzeugten MSL-Shader-Cache (work/recomp/cache/shaders) mit dem Metal-Compiler des Ziel-SDK
# in einzelne .metallib-Dateien. Die Laufzeit lädt sie statt den Quelltext zu kompilieren.
# Eigener Code; die Eingaben und Ausgaben liegen nur in work/ (gitignoriert), nichts davon gehört ins Repo.
#
# Aufruf: shader_bin.sh <iphoneos|macosx> [Quellordner] [Zielordner]
#   Standard: Quelle work/recomp/cache/shaders, Ziel work/recomp/cache/shaders-bin-<sdk>
# Vertex-Shader (v_*) mit -fpreserve-invariance, wie die Laufzeit (MTLCompileOptions.preserveInvariance).
set -euo pipefail
cd "$(dirname "$0")/../.."
SDK="${1:?Aufruf: shader_bin.sh <iphoneos|macosx> [Quelle] [Ziel]}"
SRC="${2:-work/recomp/cache/shaders}"
OUT="${3:-work/recomp/cache/shaders-bin-$SDK}"
[[ -d "$SRC" ]] || { echo "Shader-Cache fehlt: $SRC (erst einen Lauf mit BDSP machen)" >&2; exit 2; }
command -v xcrun >/dev/null || { echo "xcrun fehlt" >&2; exit 2; }
if ! xcrun -sdk "$SDK" metal --version >/dev/null 2>&1; then
  echo "Metal-Toolchain fehlt für $SDK: xcodebuild -downloadComponent MetalToolchain" >&2; exit 3
fi
mkdir -p "$OUT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

one() {
  local src="$1" sdk="$2" out="$3" tmp="$4"
  local base; base="$(basename "$src" .metal)"
  local flags=()
  [[ "$base" == v_* ]] && flags+=(-fpreserve-invariance)
  # Ziel-OS fest auf 26.0: ohne -target erzeugt Xcode 27 AIR v29 für iOS 27.1, das iPadOS 26 nicht lädt (die Laufzeit würde
  # solche Bibliotheken still verwerfen). 26.0 läuft auch unter Xcode 26.
  case "$sdk" in
    iphoneos) flags+=(-target air64-apple-ios26.0) ;;
    macosx)   flags+=(-target air64-apple-macos26.0) ;;
  esac
  if xcrun -sdk "$sdk" metal -c "${flags[@]}" "$src" -o "$tmp/$base.air" 2>"$tmp/$base.err" \
     && xcrun -sdk "$sdk" metallib "$tmp/$base.air" -o "$out/$base.metallib" 2>>"$tmp/$base.err"; then
    rm -f "$tmp/$base.air" "$tmp/$base.err"
  else
    echo "FEHLER $base: $(head -c 300 "$tmp/$base.err")" >&2
    rm -f "$out/$base.metallib"
    return 1
  fi
}
export -f one

# Parallel (Metal-Compiler wie Zeitlimit: höchstens 8 gleichzeitig)
find "$SRC" -maxdepth 1 -name '[vf]_*.metal' -print0 \
  | xargs -0 -P 8 -I{} bash -c 'one "$@"' _ {} "$SDK" "$OUT" "$TMP"
echo "Shader-Bibliotheken ($SDK): $(ls "$OUT"/*.metallib 2>/dev/null | wc -l | tr -d ' ') in $OUT"
