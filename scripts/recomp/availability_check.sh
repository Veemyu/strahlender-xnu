#!/usr/bin/env bash
# Availability check: compiles the runtime and the iOS app sources against the installed SDKs with the app's minimum OS
# (macOS and iOS from macos_target.sh) and fails on any call to an API that is newer than that minimum without an @available guard.
# Syntax only; sources are prepared under work/availability. Own code.
# Usage: availability_check.sh [mac|ios|all]      Environment: DEVELOPER_DIR selects the Xcode (any SDK at least as new as the target)
set -euo pipefail
cd "$(dirname "$0")/../.."
. scripts/recomp/macos_target.sh
IOS_MIN=$BDSP_IOS_MIN
KIND=${1:-all}
WORK=work/availability
SRC=scripts/recomp/runtime
BASEINC=(-I scripts/recomp/rt -I scripts/recomp/upstream/runtime -I "$SRC")
WARN=(-Wno-everything -Wunguarded-availability-new -Wpartial-availability -Wunguarded-availability)
HAS_SUBSDK1=0
[ ! -f "${BDSP_EXEFS_DIR:-work/exefs}/subsdk1" ] || HAS_SUBSDK1=1
mkdir -p "$WORK"
NVN=$WORK/nvn-src
NVN_SRC="$NVN" scripts/recomp/runtime/nvn/prepare.sh > /dev/null

check() {  # compiler, flags... source: availability warnings and compile errors both fail the check
  local log rc=0
  log=$("$@" -fsyntax-only 2>&1) || rc=$?
  printf '%s\n' "$log" | grep -E "availability|introduced|only available|error:" || true
  [ "$rc" -eq 0 ] || echo "compile failed: ${*: -1}"
}
run_mac() {
  local T=(-mmacosx-version-min="$BDSP_MACOS_MIN" "${WARN[@]}") D=(-DBDSP_HAS_SUBSDK1=$HAS_SUBSDK1 -DBDSP_APP) f
  local SDL=($(pkg-config --cflags sdl3)) FF=($(pkg-config --cflags libavcodec libavformat libavutil))
  local N=(-I "$NVN" -I "$NVN/nvn" "${BASEINC[@]}" "${SDL[@]}")
  for f in "$SRC"/*.c "$SRC"/app/*.c; do check clang "${T[@]}" "${BASEINC[@]}" "${D[@]}" "$f"; done
  for f in objects cmdbuf formats tegra astc bctc maxwell/translate; do check clang "${T[@]}" "${D[@]}" "${N[@]}" "$NVN/nvn/$f.c"; done
  for f in "$NVN/nvn/renderer.m" "$NVN/nvn/metal.m" "$SRC/nvn/swkbd_overlay.m"; do check /usr/bin/clang "${T[@]}" "${D[@]}" "${N[@]}" -fobjc-arc "$f"; done
  check /usr/bin/clang "${T[@]}" "${D[@]}" "${BASEINC[@]}" "${SDL[@]}" -fobjc-arc "$SRC/app/app_ui.m"
  for f in nvn_glue debug_thread; do check clang "${T[@]}" "${D[@]}" "${N[@]}" "$SRC/nvn/$f.c"; done
  check clang "${T[@]}" "${D[@]}" "${N[@]}" "${FF[@]}" "$SRC/nvn/movie_glue.c"
}
run_ios() {
  local SDKP; SDKP=$(xcrun --sdk iphoneos --show-sdk-path)
  local T=(-target "arm64-apple-ios$IOS_MIN" -isysroot "$SDKP" -DBDSP_IOS "${WARN[@]}") f x
  local A=$WORK/nvn-src-a D=(-DBDSP_COMPACT_BASE=0x800000000ull -DBDSP_HAS_SUBSDK1=$HAS_SUBSDK1)
  rm -rf "$A"; cp -R "$NVN" "$A"; python3 scripts/recomp/ios/nvn_ios.py "$A" > /dev/null
  local N=(-I scripts/recomp/ios/shim -I "$A" -I "$A/nvn" "${BASEINC[@]}")
  for f in "$SRC"/*.c; do
    x=(); [ "$(basename "$f")" != main.c ] || x=(-Dmain=bdsp_runtime_main)
    check clang "${T[@]}" "${D[@]}" -I scripts/recomp/ios/shim "${BASEINC[@]}" ${x[@]+"${x[@]}"} "$f"
  done
  for f in objects cmdbuf formats tegra astc bctc maxwell/translate; do check clang "${T[@]}" "${D[@]}" "${N[@]}" "$A/nvn/$f.c"; done
  for f in "$A/nvn/renderer_ios.m" "$A/nvn/metal_ios.m" "$SRC/nvn/swkbd_overlay.m"; do check /usr/bin/clang "${T[@]}" "${D[@]}" "${N[@]}" -fobjc-arc "$f"; done
  for f in nvn_glue debug_thread; do check clang "${T[@]}" "${D[@]}" "${N[@]}" "$SRC/nvn/$f.c"; done
  for f in scripts/recomp/ios/app/*.m; do
    [ "$(basename "$f")" != test_data_store.m ] || continue
    check /usr/bin/clang "${T[@]}" "${D[@]}" "${N[@]}" -fobjc-arc "$f"
  done
}
OUT=$WORK/report.txt
: > "$OUT"
case "$KIND" in mac|all) run_mac >> "$OUT" ;; esac
case "$KIND" in ios|all) run_ios >> "$OUT" ;; esac
if [ -s "$OUT" ]; then
  cat "$OUT" >&2
  echo "availability check: unguarded newer APIs (macOS $BDSP_MACOS_MIN, iOS $IOS_MIN)" >&2
  exit 1
fi
echo "availability ok: $KIND (macOS $BDSP_MACOS_MIN, iOS $IOS_MIN)"
