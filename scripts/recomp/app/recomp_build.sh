#!/bin/bash
# Stufe recomp: aus dem eigenen Dump (work/exefs, work/romfs) zur macOS-App work/builds/macos-recomp/BDSP.app.
#   1 Generator  -> C (rund 1 GB, work/recomp/gen4), nur wenn sich Eingaben/Generator geändert haben (sonst übersprungen;
#                   bei vorhandenem C werden nur Dateien mit geändertem Inhalt ersetzt)
#   2 Übersetzen -> work/recomp/obj4 (inkrementell, höchstens 4 Compiler, Ausreißer -O0 ab 300 KB)
#   3 Modulbilder (mkimages.sh), 4 Laufzeit/NVN-Metal bauen und mit libgame (obj4/*.o) zu bdsp_app linken
#   5 BDSP.app zusammensetzen, ad hoc signieren; 6 Daten bereitstellen (RomFS als APFS-Klon nach Application Support)
# Teilschritte tragen eigene Marker (work/.stages/recomp-*.json). Alles unter work/ (nie im Repo), Meldungen auf Deutsch.
# Aufruf: recomp_build.sh [--dry-run] [--force] [--jobs N] [--o0-kb N] [--hardened] [--no-install-data] [--out BDSP.app]
# Umgebung: RECOMP_DIR (Standard work/recomp), BDSP_HOME (Ziel der Daten, Standard ~/Library/Application Support/dev.local.xnubdsp)
# Exit-Codes wie build_all.sh: 2 Aufruf, 4 Werkzeug/Build, 8 Platz, 10 Voraussetzung fehlt
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
WORK="${WORK:-$ROOT/work}"
R="${RECOMP_DIR:-$WORK/recomp}"
case "$R" in /*) ;; *) R="$PWD/$R" ;; esac
JOBS=4 O0_KB=300 DRY=0 FORCE=0 HARDENED=0 INSTALL_DATA=1 OUT="$WORK/builds/macos-recomp/BDSP.app"
SP="python3 $ROOT/scripts/build_stages.py"
log() { echo "[$(date +%H:%M:%S)] recomp: $*"; }
die() { local c="$1"; shift; echo "FEHLER: $*" >&2; exit "$c"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --force) FORCE=1; shift ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --o0-kb) O0_KB="$2"; shift 2 ;;
    --hardened) HARDENED=1; shift ;;
    --no-install-data) INSTALL_DATA=0; shift ;;
    --out) OUT="$2"; shift 2 ;;
    *) die 2 "Unbekannte Option: $1" ;;
  esac
done
[ "$JOBS" -ge 1 ] 2>/dev/null || die 2 "--jobs braucht eine Zahl >= 1"
[ "$JOBS" -le 4 ] || JOBS=4   # die Maschine ist geteilt: höchstens vier Compiler
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac

GEN="$R/gen4" OBJ="$R/obj4" IMG="$R/img_app" RTO="$R/rt-bdsp-app" NVNRT="$R/rt-bdsp" NVNSRC="$R/nvn-src" BIN="$R/bdsp_app"
O0_BYTES=$((O0_KB * 1000))
# Die Hilfsskripte lesen work/exefs fest relativ zum Repo
[ -s "$ROOT/work/exefs/main" ] || die 10 "work/exefs/main fehlt: zuerst die Stufe extract (scripts/build_all.sh extract --xci … --keys …)"
[ -d "$ROOT/work/romfs/Data" ] || die 10 "work/romfs/Data fehlt: zuerst die Stufe extract"
[ -f "$ROOT/work/exefs/main.npdm" ] || die 10 "work/exefs/main.npdm fehlt: Stufe extract unvollständig"
[ -f "$ROOT/scripts/recomp/upstream/generator/gen.py" ] \
  || die 10 "scripts/recomp/upstream fehlt: git checkout -- scripts/recomp/upstream (vendorter Generator, MIT; siehe THIRD_PARTY_NOTICES.md)"

hash_of() { $SP stage-hash --stage "$1" --root "$ROOT" --work "$WORK" | tail -n 1; }
marker_ok() { $SP marker-check --work "$WORK" --stage "$1" --hash "$2"; }
marker_put() { local st="$1" h="$2" args=() n; shift 2; for n in "$@"; do args+=(--note "$n"); done; $SP marker-write --work "$WORK" --stage "$st" --hash "$h" ${args[@]+"${args[@]}"}; }
doit() {  # Beschreibung, Kommando…  (bei --dry-run nur anzeigen)
  local what="$1"; shift
  if [ "$DRY" -eq 1 ]; then printf '    [dry-run] %s:' "$what"; printf ' %q' "$@"; printf '\n'; return 0; fi
  "$@"
}
[ "$DRY" -eq 1 ] || mkdir -p "$WORK/logs"

# ---------- 1 Generator ----------
H_GEN="$(hash_of recomp-gen)"
if [ "$FORCE" -eq 0 ] && [ -d "$GEN/main" ] && marker_ok recomp-gen "$H_GEN"; then
  log "1/6 Generator: Marker passt, C vorhanden ($(ls "$GEN"/*/*.c | wc -l | tr -d ' ') Dateien), übersprungen"
else
  log "1/6 Generator: C aus den vier Modulen erzeugen (rund 75 s, bis 5 GB Arbeitsspeicher, rund 1 GB Platz)"
  if [ -d "$GEN/main" ] && [ "$FORCE" -eq 0 ]; then
    # inkrementell: neu erzeugen und nur Dateien mit geändertem Inhalt übertragen (Zeitstempel bleiben, Compiler läuft nur für Änderungen)
    NEW="$R/gen4.new"
    doit "alte Zwischenablage löschen" rm -rf "$NEW"
    doit "Generator" env OUT="$NEW" "$ROOT/scripts/recomp/gen_all.sh"
    if [ "$DRY" -eq 0 ]; then
      for d in "$NEW"/*/; do
        m=$(basename "$d"); mkdir -p "$GEN/$m"
        n=$(rsync -rc --delete --itemize-changes "$d" "$GEN/$m/" | { grep -c '^>f' || true; })
        log "    $m: $n geänderte Dateien"
      done
      rm -rf "$NEW"
    fi
  else
    doit "Generator" env OUT="$GEN" "$ROOT/scripts/recomp/gen_all.sh"
  fi
  [ "$DRY" -eq 1 ] || { [ -d "$GEN/main" ] || die 4 "Generator lieferte kein C (Log: work/recomp/spike2/gen4_*.log)"; marker_put recomp-gen "$H_GEN" "dateien=$(ls "$GEN"/*/*.c | wc -l | tr -d ' ')"; }
fi

# ---------- 2 Übersetzen ----------
H_HOT="$(shasum -a 256 < "$ROOT/scripts/recomp/hot_o2.txt" | cut -c1-16)"   # Liste der mit -O2 gebauten Funktionen
H_OBJ="$(printf '%s|%s|%s|%s' "$H_GEN" "$O0_BYTES" "$(clang --version | head -n 1)" "$H_HOT" | shasum -a 256 | cut -c1-64)"
if [ "$FORCE" -eq 0 ] && [ -d "$OBJ" ] && marker_ok recomp-obj "$H_OBJ"; then
  log "2/6 Übersetzen: Marker passt ($(ls "$OBJ"/*.o | wc -l | tr -d ' ') Objekte), übersprungen"
else
  log "2/6 Übersetzen: höchstens $JOBS Compiler, Ausreißer ab ${O0_KB} KB mit -O0 (rund 12 bis 16 min kalt; Fortschritt: $WORK/logs/recomp-compile.log)"
  if [ "$FORCE" -eq 1 ] && [ "$DRY" -eq 0 ]; then rm -rf "$OBJ"; fi
  # geänderte -O0-Schwelle: Objekte der betroffenen Dateien verwerfen (compile_chunk.sh überspringt vorhandene)
  if [ "$DRY" -eq 0 ] && [ -f "$OBJ/.o0_bytes" ] && [ "$(cat "$OBJ/.o0_bytes")" != "$O0_BYTES" ]; then
    old=$(cat "$OBJ/.o0_bytes")
    for f in "$GEN"/*/*.c; do
      s=$(stat -f %z "$f")
      lo=$(( old < O0_BYTES ? old : O0_BYTES )); hi=$(( old > O0_BYTES ? old : O0_BYTES ))
      if [ "$s" -gt "$lo" ] && [ "$s" -le "$hi" ]; then rm -f "$OBJ/$(basename "$(dirname "$f")")_$(basename "$f" .c).o"; fi
    done
  fi
  if [ "$DRY" -eq 1 ]; then
    printf '    [dry-run] Übersetzen: env GEN=%q OBJ=%q O0_BYTES=%q scripts/recomp/build_all.sh %q\n' "$GEN" "$OBJ" "$O0_BYTES" "$JOBS"
  else
    mkdir -p "$OBJ"
    if ! GEN="$GEN" OBJ="$OBJ" O0_BYTES="$O0_BYTES" "$ROOT/scripts/recomp/build_all.sh" "$JOBS" > "$WORK/logs/recomp-compile.log" 2>&1; then
      tail -n 20 "$WORK/logs/recomp-compile.log" >&2
      die 4 "Übersetzen fehlgeschlagen (Log: $WORK/logs/recomp-compile.log). Häufige Ursachen: zu wenig Arbeitsspeicher (ein Compiler braucht bis 1,7 GB: --jobs 2), Platte voll"
    fi
    grep -q "^FEHLER" "$WORK/logs/recomp-compile.log" && die 4 "Übersetzen meldet Fehler (Log: $WORK/logs/recomp-compile.log)"
    echo "$O0_BYTES" > "$OBJ/.o0_bytes"
    expected=$(ls "$GEN"/*/*.c | wc -l | tr -d ' '); have=$(ls "$OBJ"/*.o | wc -l | tr -d ' ')
    [ "$expected" = "$have" ] || die 4 "Objekte unvollständig: $have von $expected (Log: $WORK/logs/recomp-compile.log)"
    tail -n 2 "$WORK/logs/recomp-compile.log" | sed 's/^/    /'
    marker_put recomp-obj "$H_OBJ" "objekte=$have"
  fi
fi

# ---------- 3 Modulbilder ----------
log "3/6 Modulbilder (Relokationen, Importe, HLE-Slots)"
if [ "$DRY" -eq 1 ]; then
  printf '    [dry-run] Modulbilder: env IMG=%q HLE_LIST=hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh\n' "$IMG"
else
  IMG="$IMG" HLE_LIST="$ROOT/scripts/recomp/rt-bdsp/hle_nvn.txt" "$ROOT/scripts/recomp/rt-bdsp/mkimages.sh" > "$WORK/logs/recomp-images.log" 2>&1 \
    || { tail -n 10 "$WORK/logs/recomp-images.log" >&2; die 4 "mkimages.sh fehlgeschlagen (Log: $WORK/logs/recomp-images.log)"; }
fi

# ---------- 4 Laufzeit und NVN/Metal ----------
log "4/6 Laufzeit und NVN/Metal bauen, mit libgame zu bdsp_app linken"
if [ "$DRY" -eq 1 ]; then
  printf '    [dry-run] Bau: env BDSP_APP=1 OBJ=%q RT=%q NVN_RT=%q NVN_SRC=%q OUT=%q scripts/recomp/rt-bdsp/build.sh\n' "$OBJ" "$RTO" "$NVNRT" "$NVNSRC" "$BIN"
else
  mkdir -p "$RTO" "$NVNRT"
  BDSP_APP=1 OBJ="$OBJ" RT="$RTO" NVN_RT="$NVNRT" NVN_SRC="$NVNSRC" OUT="$BIN" "$ROOT/scripts/recomp/rt-bdsp/build.sh" > "$WORK/logs/recomp-runtime.log" 2>&1 \
    || { tail -n 20 "$WORK/logs/recomp-runtime.log" >&2; die 4 "Laufzeit-Bau fehlgeschlagen (Log: $WORK/logs/recomp-runtime.log). Voraussetzung: brew install sdl3 ffmpeg pkg-config llvm; Xcode Command Line Tools"; }
  tail -n 1 "$WORK/logs/recomp-runtime.log" | sed 's/^/    /'
fi

# ---------- 5 App ----------
log "5/6 BDSP.app zusammensetzen und signieren (ad hoc$([ "$HARDENED" -eq 1 ] && echo ', Hardened Runtime'))"
APPARGS=(--bin "$BIN" --img "$IMG" --npdm "$ROOT/work/exefs/main.npdm" --out "$OUT")
export BDSP_ICON_SOURCE="${BDSP_ICON_SOURCE:-$R/icons/source}"
[ "$HARDENED" -eq 0 ] || APPARGS+=(--hardened)
doit "App" "$ROOT/scripts/recomp/app/make_app.sh" "${APPARGS[@]}"

# ---------- 6 Daten ----------
HOME_DIR="${BDSP_HOME:-$HOME/Library/Application Support/dev.local.xnubdsp}"
if [ "$INSTALL_DATA" -eq 0 ]; then
  log "6/6 Daten: übersprungen (--no-install-data); die App erwartet das RomFS unter $HOME_DIR/romfs oder per romfs = … in config.ini"
else
  # Kennung des Dumps: main-Hash plus Dateizahl des RomFS (manifest.json ist nicht in jedem Arbeitsordner vorhanden)
  STAMP="$(shasum -a 256 "$ROOT/work/exefs/main" | cut -c1-16) $(find "$ROOT/work/romfs" -type f | wc -l | tr -d ' ')"
  if [ -f "$HOME_DIR/romfs.stamp" ] && [ "$(cat "$HOME_DIR/romfs.stamp")" = "$STAMP" ] && [ -d "$HOME_DIR/romfs/Data" ] && [ "$FORCE" -eq 0 ]; then
    log "6/6 Daten: RomFS unter $HOME_DIR/romfs ist aktuell, übersprungen"
  else
    log "6/6 Daten: RomFS nach $HOME_DIR/romfs (APFS-Klon, braucht keinen zusätzlichen Platz; sonst Kopie)"
    if [ "$DRY" -eq 0 ]; then
      mkdir -p "$HOME_DIR"
      rm -rf "$HOME_DIR/romfs.new"
      cp -cR "$ROOT/work/romfs" "$HOME_DIR/romfs.new" 2>/dev/null || cp -R "$ROOT/work/romfs" "$HOME_DIR/romfs.new" \
        || die 8 "RomFS lässt sich nicht nach $HOME_DIR kopieren (Platz?)"
      rm -rf "$HOME_DIR/romfs"
      mv "$HOME_DIR/romfs.new" "$HOME_DIR/romfs"
      printf '%s' "$STAMP" > "$HOME_DIR/romfs.stamp"
    else
      echo "    [dry-run] cp -cR $ROOT/work/romfs $HOME_DIR/romfs"
    fi
  fi
fi
[ "$DRY" -eq 1 ] || log "fertig: $OUT ($(du -sh "$OUT" | cut -f1))"
