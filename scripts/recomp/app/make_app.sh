#!/bin/bash
# Assembles BDSP.app: program, module images (game code from your own dump), main.npdm, icon, Info.plist, bundled
# libraries; then ad-hoc signature and verification. Everything under work/ (never in the repo).
# Usage: make_app.sh --bin <bdsp_app> --img <image-folder> --npdm <main.npdm> --out <BDSP.app> [--hardened] [--version V]
set -euo pipefail
cd "$(dirname "$0")/../../.."
HERE=scripts/recomp/app
BIN="" IMG="" NPDM="" OUT="" HARDENED=0 VERSION="0.1" MOD_NAME="" MODS_DIR="" MOD_ROOT="" BUNDLE_ID="" DISPLAY_NAME=""
while [ $# -gt 0 ]; do
  case "$1" in
    --bin) BIN="$2"; shift 2 ;;
    --img) IMG="$2"; shift 2 ;;
    --npdm) NPDM="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --hardened) HARDENED=1; shift ;;
    --version) VERSION="$2"; shift 2 ;;
    --mod-name) MOD_NAME="$2"; shift 2 ;;
    --mods-dir) MODS_DIR="$2"; shift 2 ;;
    --mod-root) MOD_ROOT="$2"; shift 2 ;;
    --bundle-id) BUNDLE_ID="$2"; shift 2 ;;
    --display-name) DISPLAY_NAME="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[ -x "$BIN" ] || { echo "ERROR: program missing: $BIN" >&2; exit 4; }
[ -f "$IMG/main.img" ] || { echo "ERROR: module images missing in $IMG (mkimages.sh)" >&2; exit 4; }
[ -f "$NPDM" ] || { echo "ERROR: main.npdm missing: $NPDM (extract stage)" >&2; exit 4; }
case "$OUT" in *.app) ;; *) echo "ERROR: --out must end in .app" >&2; exit 2 ;; esac
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
git check-ignore -q "$OUT" 2>/dev/null || [ "${OUT#"$PWD"/}" = "$OUT" ] || { echo "ERROR: $OUT is inside the repo and not gitignored" >&2; exit 2; }

NEW="$OUT.new"
rm -rf "$NEW"
mkdir -p "$NEW/Contents/MacOS" "$NEW/Contents/Resources" "$NEW/Contents/Frameworks"
cp "$BIN" "$NEW/Contents/MacOS/BDSP"
# Developer build paths live in Mach-O debug symbols and N_OSO records. Keep
# them in local work objects, not in the app users receive.
strip -S "$NEW/Contents/MacOS/BDSP"
cp -c -R "$IMG" "$NEW/Contents/Resources/img" 2>/dev/null || cp -R "$IMG" "$NEW/Contents/Resources/img"
cp -R "$HERE/lproj/." "$NEW/Contents/Resources/"
cp "$NPDM" "$NEW/Contents/Resources/main.npdm"
# Shader cache (generated locally, gitignored) into the bundle, if present
if [[ -d work/recomp/cache/shaders ]]; then cp -R work/recomp/cache/shaders "$NEW/Contents/Resources/shaders"; fi
# precompiled Metal libraries (scripts/recomp/shader_bin.sh macosx)
if [[ -d work/recomp/cache/shaders-bin-macosx ]]; then cp -R work/recomp/cache/shaders-bin-macosx "$NEW/Contents/Resources/shaders-bin"; fi
if [[ -f work/recomp/cache/pipelines.bin ]]; then cp work/recomp/cache/pipelines.bin "$NEW/Contents/Resources/pipelines.bin"; fi
sed -e "s/@VERSION@/$VERSION/" -e "s/@BUILD@/$(date +%Y%m%d%H%M)/" "$HERE/Info.plist.in" > "$NEW/Contents/Info.plist"
if [ -n "$MOD_NAME" ]; then
  [ -n "$MODS_DIR" ] && [ -n "$MOD_ROOT" ] && [ -n "$BUNDLE_ID" ] && [ -n "$DISPLAY_NAME" ] || { echo "ERROR: mod app metadata is incomplete" >&2; exit 2; }
  case "$MOD_NAME$MODS_DIR$MOD_ROOT" in *$'\n'*|*$'\r'*) echo "ERROR: newline in mod name or path" >&2; exit 2 ;; esac
  printf '%s\n%s\n%s\n' "$MOD_NAME" "$MODS_DIR" "$MOD_ROOT" > "$NEW/Contents/Resources/mod-build.txt"
  plutil -replace CFBundleIdentifier -string "$BUNDLE_ID" "$NEW/Contents/Info.plist"
  plutil -replace CFBundleName -string "$DISPLAY_NAME" "$NEW/Contents/Info.plist"
  plutil -replace CFBundleDisplayName -string "$DISPLAY_NAME" "$NEW/Contents/Info.plist"
fi
plutil -lint "$NEW/Contents/Info.plist" > /dev/null
ICONARGS=(mac --source "${BDSP_ICON_SOURCE:-work/recomp/icons/source}" --output "$NEW/Contents/Resources")
[ -z "$MOD_ROOT" ] || ICONARGS+=(--mod-root "$MOD_ROOT" --mod-name "$MOD_NAME")
python3 "$HERE/game_icons.py" "${ICONARGS[@]}"
python3 "$HERE/bundle_dylibs.py" "$NEW/Contents/MacOS/BDSP" "$NEW/Contents/Frameworks"

# Signature: libraries first, then the bundle. Ad hoc ("-"): launchable locally, no developer account needed.
SIGN=(codesign --force --sign -)
if [ "$HARDENED" -eq 1 ]; then SIGN+=(--options runtime --entitlements "$HERE/BDSP.entitlements"); fi
for f in "$NEW"/Contents/Frameworks/*.dylib; do codesign --force --sign - "$f" 2>/dev/null; done
"${SIGN[@]}" "$NEW"
codesign --verify --deep --strict "$NEW"
if otool -L "$NEW/Contents/MacOS/BDSP" "$NEW"/Contents/Frameworks/*.dylib | grep -q "/opt/homebrew"; then
  echo "ERROR: references to /opt/homebrew in the bundle" >&2; exit 4
fi
rm -rf "$OUT"
mv "$NEW" "$OUT"
echo "BDSP.app: $OUT ($(du -sh "$OUT" | cut -f1), signature: $([ "$HARDENED" -eq 1 ] && echo 'ad hoc + hardened runtime' || echo 'ad hoc'))"
