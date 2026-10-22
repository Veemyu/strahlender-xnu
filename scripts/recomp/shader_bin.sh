#!/usr/bin/env bash
# Compiles the locally generated MSL shader cache (work/recomp/cache/shaders) with the Metal compiler of the target SDK
# into individual .metallib files. The runtime loads them instead of compiling the source text.
# Own code; inputs and outputs live only in work/ (gitignored), none of it belongs in the repo.
#
# Usage: shader_bin.sh <iphoneos|macosx> [source folder] [target folder]
#   Default: source work/recomp/cache/shaders, target work/recomp/cache/shaders-bin-<sdk>
# Vertex shaders (v_*) with -fpreserve-invariance, like the runtime (MTLCompileOptions.preserveInvariance).
set -euo pipefail
cd "$(dirname "$0")/../.."
SDK="${1:?Usage: shader_bin.sh <iphoneos|macosx> [source] [target]}"
SRC="${2:-work/recomp/cache/shaders}"
OUT="${3:-work/recomp/cache/shaders-bin-$SDK}"
[[ -d "$SRC" ]] || { echo "Shader cache missing: $SRC (do a run with BDSP first)" >&2; exit 2; }
command -v xcrun >/dev/null || { echo "xcrun missing" >&2; exit 2; }
if ! xcrun -sdk "$SDK" metal --version >/dev/null 2>&1; then
  echo "Metal toolchain missing for $SDK: xcodebuild -downloadComponent MetalToolchain" >&2; exit 3
fi
mkdir -p "$OUT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

one() {
  local src="$1" sdk="$2" out="$3" tmp="$4"
  local base; base="$(basename "$src" .metal)"
  local flags=()
  [[ "$base" == v_* ]] && flags+=(-fpreserve-invariance)
  # Target OS fixed to 26.0: without -target Xcode 27 produces AIR v29 for iOS 27.1, which iPadOS 26 does not load (the runtime would
  # silently discard such libraries). 26.0 also works under Xcode 26.
  case "$sdk" in
    iphoneos) flags+=(-target air64-apple-ios26.0) ;;
    macosx)   flags+=(-target air64-apple-macos26.0) ;;
  esac
  if xcrun -sdk "$sdk" metal -c "${flags[@]}" "$src" -o "$tmp/$base.air" 2>"$tmp/$base.err" \
     && xcrun -sdk "$sdk" metallib "$tmp/$base.air" -o "$out/$base.metallib" 2>>"$tmp/$base.err"; then
    rm -f "$tmp/$base.air" "$tmp/$base.err"
  else
    echo "ERROR $base:$(head -c 300 "$tmp/$base.err")" >&2
    rm -f "$out/$base.metallib"
    return 1
  fi
}
export -f one

# Parallel (Metal compiler, like the time limit: at most 8 at once)
find "$SRC" -maxdepth 1 -name '[vf]_*.metal' -print0 \
  | xargs -0 -P 8 -I{} bash -c 'one "$@"' _ {} "$SDK" "$OUT" "$TMP"
echo "Shader libraries ($SDK):$(ls "$OUT"/*.metallib 2>/dev/null | wc -l | tr -d ' ') in $OUT"
