#!/bin/bash
# Setzt BDSP.app zusammen: Programm, Modulbilder (Spielcode aus dem eigenen Dump), main.npdm, Symbol, Info.plist, gebündelte
# Bibliotheken; danach ad-hoc-Signatur und Prüfung. Alles unter work/ (nie im Repo).
# Aufruf: make_app.sh --bin <bdsp_app> --img <Bilderordner> --npdm <main.npdm> --out <BDSP.app> [--hardened] [--version V]
set -euo pipefail
cd "$(dirname "$0")/../../.."
HERE=scripts/recomp/app
BIN="" IMG="" NPDM="" OUT="" HARDENED=0 VERSION="0.1"
while [ $# -gt 0 ]; do
  case "$1" in
    --bin) BIN="$2"; shift 2 ;;
    --img) IMG="$2"; shift 2 ;;
    --npdm) NPDM="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --hardened) HARDENED=1; shift ;;
    --version) VERSION="$2"; shift 2 ;;
    *) echo "unbekannte Option $1" >&2; exit 2 ;;
  esac
done
[ -x "$BIN" ] || { echo "FEHLER: Programm fehlt: $BIN" >&2; exit 4; }
[ -f "$IMG/main.img" ] || { echo "FEHLER: Modulbilder fehlen in $IMG (mkimages.sh)" >&2; exit 4; }
[ -f "$NPDM" ] || { echo "FEHLER: main.npdm fehlt: $NPDM (Stufe extract)" >&2; exit 4; }
case "$OUT" in *.app) ;; *) echo "FEHLER: --out muss auf .app enden" >&2; exit 2 ;; esac
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
git check-ignore -q "$OUT" 2>/dev/null || [ "${OUT#"$PWD"/}" = "$OUT" ] || { echo "FEHLER: $OUT liegt im Repo und ist nicht gitignoriert" >&2; exit 2; }

NEW="$OUT.new"
rm -rf "$NEW"
mkdir -p "$NEW/Contents/MacOS" "$NEW/Contents/Resources" "$NEW/Contents/Frameworks"
cp "$BIN" "$NEW/Contents/MacOS/BDSP"
cp -c -R "$IMG" "$NEW/Contents/Resources/img" 2>/dev/null || cp -R "$IMG" "$NEW/Contents/Resources/img"
cp -R "$HERE/lproj/." "$NEW/Contents/Resources/"
cp "$NPDM" "$NEW/Contents/Resources/main.npdm"
# Shader-Cache (lokal erzeugt, gitignoriert) ins Bundle, falls vorhanden
if [[ -d work/recomp/cache/shaders ]]; then cp -R work/recomp/cache/shaders "$NEW/Contents/Resources/shaders"; fi
# vorübersetzte Metal-Bibliotheken (scripts/recomp/shader_bin.sh macosx)
if [[ -d work/recomp/cache/shaders-bin-macosx ]]; then cp -R work/recomp/cache/shaders-bin-macosx "$NEW/Contents/Resources/shaders-bin"; fi
if [[ -f work/recomp/cache/pipelines.bin ]]; then cp work/recomp/cache/pipelines.bin "$NEW/Contents/Resources/pipelines.bin"; fi
sed -e "s/@VERSION@/$VERSION/" -e "s/@BUILD@/$(date +%Y%m%d%H%M)/" "$HERE/Info.plist.in" > "$NEW/Contents/Info.plist"
plutil -lint "$NEW/Contents/Info.plist" > /dev/null
python3 "$HERE/make_icon.py" "$NEW/Contents/Resources/BDSP.icns" > /dev/null
python3 "$HERE/bundle_dylibs.py" "$NEW/Contents/MacOS/BDSP" "$NEW/Contents/Frameworks"

# Signatur: Bibliotheken zuerst, dann das Bundle. Ad hoc ("-"): lokal startbar, kein Entwicklerkonto nötig.
SIGN=(codesign --force --sign -)
if [ "$HARDENED" -eq 1 ]; then SIGN+=(--options runtime --entitlements "$HERE/BDSP.entitlements"); fi
for f in "$NEW"/Contents/Frameworks/*.dylib; do codesign --force --sign - "$f" 2>/dev/null; done
"${SIGN[@]}" "$NEW"
codesign --verify --deep --strict "$NEW"
if otool -L "$NEW/Contents/MacOS/BDSP" "$NEW"/Contents/Frameworks/*.dylib | grep -q "/opt/homebrew"; then
  echo "FEHLER: Verweise auf /opt/homebrew im Bundle" >&2; exit 4
fi
rm -rf "$OUT"
mv "$NEW" "$OUT"
echo "BDSP.app: $OUT ($(du -sh "$OUT" | cut -f1), Signatur: $([ "$HARDENED" -eq 1 ] && echo 'ad hoc + Hardened Runtime' || echo 'ad hoc'))"
