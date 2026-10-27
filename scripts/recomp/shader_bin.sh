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
case "$SDK" in
  iphoneos) AIR_TARGET=air64-apple-ios17.0 ;;
  macosx) AIR_TARGET=air64-apple-macos26.0 ;;
  *) echo "Unsupported shader SDK: $SDK" >&2; exit 2;;
esac
export AIR_TARGET
mkdir -p "$OUT"
# The toolchain and target are part of every incremental compilation stamp.
TOOLCHAIN=$( { xcrun -sdk "$SDK" metal --version; echo "$SDK $AIR_TARGET preserve-invariance=v1"; } | shasum -a 256 | cut -c1-64)
export TOOLCHAIN
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

one() {
  local src="$1" sdk="$2" out="$3" tmp="$4"
  local base; base="$(basename "$src" .metal)"
  local stamp
  stamp=$( { printf '%s\n' "$TOOLCHAIN"; shasum -a 256 "$src"; } | shasum -a 256 | cut -c1-64)
  if [[ -s "$out/$base.metallib" && "$(cat "$out/$base.stamp" 2>/dev/null || true)" == "$stamp" ]]; then return; fi
  local flags=()
  [[ "$base" == v_* ]] && flags+=(-fpreserve-invariance)
  # Pin the deployment target, rather than inheriting the newest Xcode OS.
  # iPhoneOS libraries remain loadable on the app's minimum supported iOS 17.
  flags+=(-target "$AIR_TARGET")
  if xcrun -sdk "$sdk" metal -c "${flags[@]}" "$src" -o "$tmp/$base.air" 2>"$tmp/$base.err" \
     && xcrun -sdk "$sdk" metallib "$tmp/$base.air" -o "$tmp/$base.metallib" 2>>"$tmp/$base.err"; then
    mv "$tmp/$base.metallib" "$out/$base.metallib"
    printf '%s\n' "$stamp" > "$out/$base.stamp"
    rm -f "$tmp/$base.air" "$tmp/$base.err"
  else
    echo "ERROR $base:$(head -c 300 "$tmp/$base.err")" >&2
    rm -f "$out/$base.metallib"
    return 1
  fi
}
export -f one

# Match the CPU/RAM-based compiler concurrency used by the C build.
JOBS=$(python3 scripts/recomp/parallel_jobs.py)
find "$SRC" -maxdepth 1 -name '[vf]_*.metal' -print0 \
  | xargs -0 -P "$JOBS" -I{} bash -c 'one "$@"' _ {} "$SDK" "$OUT" "$TMP"
printf '%s\n' "$SDK" > "$OUT/.sdk"
echo "Shader libraries ($SDK):$(ls "$OUT"/*.metallib 2>/dev/null | wc -l | tr -d ' ') in $OUT"
