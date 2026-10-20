#!/usr/bin/env bash
# Einstiegspunkt der Build-Pipeline (docs/build-pipeline.md, Anleitung: docs/bauen.md, Ziel: docs/kernziel.md).
# Das Repo enthält nie Spieldaten oder Keys.
#
# Stufen (feste Reihenfolge): tools extract il2cpp recomp masterdata shaders video audio
#   Vorab läuft ein Preflight (nur Prüfung, keine Installation).
#
# Aufruf (alles in einem Befehl):
#   scripts/build_all.sh all --xci <x.xci> --nsp <update.nsp> --keys <Ordner> [--target macos|ios|all]
#   scripts/build_all.sh --dry-run all --xci ... --keys ...     zeigt Plan und Kommandos, ändert nichts
#   scripts/build_all.sh --from masterdata --to video           nur ein Bereich der Reihenfolge
#   scripts/build_all.sh --only shaders,video                   genau diese Stufen
#   scripts/build_all.sh preflight                              nur Voraussetzungen prüfen
# Eingaben (nur für extract): --xci DATEI, --nsp DATEI (optional), --keys ORDNER | --prod-keys DATEI [--title-keys DATEI]
# Steuerung:
#   --work ORDNER       Arbeitsordner (Standard: work/, gitignoriert)
#   --target T          macos, ios oder all (Standard: all) für recomp
#   --dry-run           nichts ausführen, nur Plan, Marker-Status und Kommandos zeigen
#   --from S / --to S   Bereich der Stufenreihenfolge;  --only S[,S]  genau diese Stufen
#   --force             gewählte Stufen neu erzeugen, auch wenn der Marker passt
#   --no-preflight      Preflight überspringen;  --min-free-gb N  Mindestplatz im Preflight (Standard 60)
#   --keep-nca          entpackte NCAs (mehrere GB) behalten
#   --video-profile P   h265-crf18 (Standard) oder h265-crf14
#   --movie-src ORDNER  Videoquelle statt romfs/.../Movie (Stichproben)
#   --shader-only NAME  nur ein Shader (Test);  --launch  iOS-App nach der Installation starten
#   --bundle-platform P macos|ios|keep: Zielplattform in den Bundles (Standard aus --target; bei all: macos).
#                       Ein Player lädt nur Bundles mit passender Kennung (Switch-Kennung 38 wird abgelehnt).
#   --bundle-subset F   nur die in F aufgeführten Bundles (plus Katalog) in den Player legen (iPad: Platz/Speicher)
#   --texture-format F  BC-Texturen der Bundles nach ASTC umwandeln (scripts/texture_transcode.py): 6x6|4x4|8x8|off.
#                       Standard: 6x6 bei Bundle-Plattform ios (Apple-GPUs kennen kein BC), sonst off.
#   Stufe recomp (macOS-App aus der Rekompilation, work/builds/macos-recomp/BDSP.app; nur für --target macos|all):
#   --recomp-jobs N     Zahl der Compiler (Standard 4, höchstens 4);  --recomp-o0-kb N  Ausreißer ab N KB mit -O0 (Standard 300)
#   --hardened          App mit Hardened Runtime signieren (Standard: nur ad hoc);  --no-install-data  RomFS nicht nach Application Support klonen
# Umgebung: TOOLS_DIR, MIN_FREE_GB (Reserve in extract, Standard 25), DEVELOPER_DIR,
#   SHADER_USED
#
# Exit-Codes: 0 ok, 2 Aufruf, 3 Eingabe fehlt, 4 Werkzeug fehlt/Build, 5 hactool-Fehler,
#   6 Schlüssel/Titlekey, 7 NCA nicht gefunden, 8 zu wenig Platz, 9 Prüfung, 10 Voraussetzung/Stufe fehlt,
#   14 Stufe il2cpp/masterdata/video fehlgeschlagen (11 bis 13 entfallen mit den Unity-Stufen)
# hactool gibt Schlüsselwerte aus: stdout/stderr gehen nie ins Log (nur gefilterte Felder).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HELPERS="$ROOT/scripts/build_helpers.py"
STAGEPY="$ROOT/scripts/build_stages.py"
TOOLS_DIR="${TOOLS_DIR:-$ROOT/tools}"
HACTOOL_DIR="$TOOLS_DIR/hactool"
HACTOOL="$HACTOOL_DIR/hactool"
HACTOOL_REPO="https://github.com/SciresM/hactool"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
MIN_FREE_GB="${MIN_FREE_GB:-25}"
PREFLIGHT_FREE_GB="${PREFLIGHT_MIN_FREE_GB:-60}"
ALL_STAGES="tools extract il2cpp recomp masterdata shaders video audio"

XCI="" NSP="" KEYS_DIR="" PROD_KEYS="" TITLE_KEYS="" WORK="$ROOT/work"
FORCE=0 KEEP_NCA=0 STAGES="" FROM="" TO="" ONLY=""
DRY=0 NO_PREFLIGHT=0 PREFLIGHT_ONLY=0 TARGET=all VIDEO_PROFILE="h265-crf18" MOVIE_SRC=""
SHADER_ONLY="" LAUNCH=0 BUNDLE_PLATFORM="" BUNDLE_SUBSET="" TEXTURE_FORMAT=""
EXTRACT_ACTIVE=0
RECOMP_JOBS=4 RECOMP_O0_KB=300 RECOMP_HARDENED=0 RECOMP_DATA=1
SELECTED="" RESULTS="" UPSTREAM_DIRTY=0 NOT_IMPL=""

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { local code="$1"; shift; echo "FEHLER: $*" >&2; exit "$code"; }
usage() { awk 'NR > 1 && /^set -euo/ {exit} NR > 1 {sub(/^# ?/, ""); print}' "$0"; }

# ---------- Stufe tools ----------
ok() { echo "  OK     $*"; }
miss() { echo "  FEHLT  $*"; }

hactool_runs() {
  local out
  [ -x "$HACTOOL" ] || return 1
  out="$("$HACTOOL" --help 2>&1 || true)"
  case "$out" in *Usage*) return 0 ;; *) return 1 ;; esac
}

check_hactool() {
  if hactool_runs; then ok "hactool ($HACTOOL)"; return 0; fi
  local c
  for c in git make cc; do
    command -v "$c" >/dev/null 2>&1 || { miss "hactool: '$c' fehlt (Xcode Command Line Tools?)"; return 1; }
  done
  if [ ! -f "$HACTOOL_DIR/Makefile" ]; then
    if [ -e "$HACTOOL_DIR" ] && [ -n "$(ls -A "$HACTOOL_DIR")" ]; then
      miss "hactool: $HACTOOL_DIR ist kein hactool-Quellordner"; return 1
    fi
    log "hactool: klone $HACTOOL_REPO"
    mkdir -p "$TOOLS_DIR"
    git clone --quiet --recursive "$HACTOOL_REPO" "$HACTOOL_DIR" >/dev/null 2>&1 || { miss "hactool: git clone fehlgeschlagen (Netz?)"; return 1; }
  elif [ ! -f "$HACTOOL_DIR/mbedtls/Makefile" ] && [ -e "$HACTOOL_DIR/.git" ]; then
    git -C "$HACTOOL_DIR" submodule update --init --recursive >/dev/null 2>&1 || { miss "hactool: Submodul mbedtls fehlt"; return 1; }
  fi
  [ -f "$HACTOOL_DIR/config.mk" ] || cp "$HACTOOL_DIR/config.mk.template" "$HACTOOL_DIR/config.mk"
  log "hactool: baue (make, Log: $HACTOOL_DIR/build.log)"
  if ! make -C "$HACTOOL_DIR" -j "$(sysctl -n hw.ncpu 2>/dev/null || echo 4)" >"$HACTOOL_DIR/build.log" 2>&1; then
    tail -n 15 "$HACTOOL_DIR/build.log" >&2
    miss "hactool: make fehlgeschlagen"
    return 1
  fi
  hactool_runs || { miss "hactool: Binary läuft nicht"; return 1; }
  ok "hactool gebaut ($HACTOOL)"
}

check_ffmpeg() {
  if command -v ffmpeg >/dev/null 2>&1; then
    ok "ffmpeg ($(ffmpeg -version 2>&1 | sed -n '1s/ Copyright.*//p'))"
  else
    miss "ffmpeg (brew install ffmpeg)"; return 1
  fi
}

check_xcode() {
  local v
  [ -d /Applications/Xcode.app ] || { miss "Xcode unter /Applications/Xcode.app"; return 1; }
  [ -d "$DEVELOPER_DIR" ] || { miss "DEVELOPER_DIR=$DEVELOPER_DIR existiert nicht"; return 1; }
  v="$(xcodebuild -version 2>/dev/null | sed -n '1,2p' | tr '\n' ' ')" || true
  [ -n "$v" ] || { miss "Xcode: xcodebuild läuft nicht (Lizenz akzeptiert? 'xcodebuild -license')"; return 1; }
  ok "Xcode ($v, DEVELOPER_DIR=$DEVELOPER_DIR)"
}

check_python() {
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
    ok "python3 ($(python3 --version 2>&1))"
  else
    miss "python3 >= 3.9"; return 1
  fi
}

stage_tools() {
  log "Stufe tools"
  if [ "$DRY" -eq 1 ]; then
    if hactool_runs; then ok "hactool vorhanden ($HACTOOL)"; else echo "    [dry-run] würde hactool klonen und bauen: $HACTOOL_REPO nach $HACTOOL_DIR (make, ohne sudo)"; fi
    echo "    [dry-run] würde python3, ffmpeg und Xcode prüfen (nur Prüfung)"
    stage_result tools "Plan"; return 0
  fi
  local bad=0
  check_python || bad=1
  check_hactool || bad=1
  check_ffmpeg || bad=1
  check_xcode || bad=1
  [ "$bad" -eq 0 ] || die 4 "Werkzeuge unvollständig (siehe FEHLT oben)"
  log "Stufe tools fertig"
  stage_result tools "ausgeführt"
}

# ---------- Stufe extract ----------
abspath() { local d; d="$(cd "$(dirname "$1")" && pwd)" && echo "$d/$(basename "$1")"; }
file_size() { stat -f %z "$1"; }
free_gb() { df -k "$1" | awk 'NR==2 {print int($4 / 1048576)}'; }

# Alle NCAs eines Ordners klassifizieren: eine TSV-Zeile je NCA (nur unkritische Felder)
classify_dir() {
  local dir="$1" out="$2" f line
  : >"$out"
  for f in "$dir"/*.nca; do
    [ -e "$f" ] || continue
    line="$("$HACTOOL" -k "$PROD_KEYS" -i "$f" 2>/dev/null | python3 "$HELPERS" nca-info --path "$f" 2>/dev/null)" || {
      echo "  Hinweis: $(basename "$f") nicht lesbar (übersprungen)" >&2; continue; }
    echo "$line" >>"$out"
  done
  [ -s "$out" ] || die 6 "Keine NCA in $dir lesbar: prod.keys passend zur Firmware/Master-Key-Revision?"
}

pick() { python3 "$HELPERS" pick --tsv "$1" --type "$2" ${3:+--title-id "$3"} || true; }
tsv_field() { awk -F'\t' -v p="$2" -v c="$3" '$1 == p {print $c}' "$1"; }

extract_cleanup() {
  [ "$EXTRACT_ACTIVE" -eq 1 ] || return 0
  rm -rf "$WORK/.stage"
  [ "$KEEP_NCA" -eq 1 ] || rm -rf "$WORK/nca-base" "$WORK/nca-update"
  return 0
}

# hactool-Aufruf ohne Ausgabe (stdout und stderr können Schlüsselwerte enthalten)
hq() { "$HACTOOL" -k "$PROD_KEYS" "$@" >/dev/null 2>&1; }

stage_extract() {
  log "Stufe extract"
  if [ -z "$XCI" ] && [ "$FORCE" -eq 0 ] && [ -s "$WORK/manifest.json" ] && [ -s "$WORK/exefs/main" ] && [ -d "$WORK/romfs" ]; then
    log "extract: keine --xci angegeben, vorhandenes Ergebnis in $WORK wird verwendet"
    stage_result extract "vorhanden"; return 0
  fi
  [ -n "$XCI" ] || die 2 "--xci fehlt (die Stufe extract braucht die eigene XCI; Aufruf siehe docs/bauen.md)"
  [ -f "$XCI" ] || die 3 "XCI nicht gefunden: $XCI"
  [ -z "$NSP" ] || [ -f "$NSP" ] || die 3 "NSP nicht gefunden: $NSP"
  if [ -n "$KEYS_DIR" ]; then
    [ -n "$PROD_KEYS" ] || PROD_KEYS="$KEYS_DIR/prod.keys"
    [ -n "$TITLE_KEYS" ] || TITLE_KEYS="$KEYS_DIR/title.keys"
  fi
  [ -n "$PROD_KEYS" ] || die 2 "--keys <Ordner> oder --prod-keys <Datei> fehlt"
  [ -f "$PROD_KEYS" ] || die 3 "prod.keys nicht gefunden: $PROD_KEYS"
  [ -z "$TITLE_KEYS" ] || [ -f "$TITLE_KEYS" ] || TITLE_KEYS=""
  PROD_KEYS="$(abspath "$PROD_KEYS")"
  [ -z "$TITLE_KEYS" ] || TITLE_KEYS="$(abspath "$TITLE_KEYS")"
  XCI="$(abspath "$XCI")"
  [ -z "$NSP" ] || NSP="$(abspath "$NSP")"

  if [ "$DRY" -eq 1 ]; then
    local dxs dns=0
    dxs="$(file_size "$XCI")"; [ -z "$NSP" ] || dns="$(file_size "$NSP")"
    if [ "$FORCE" -eq 0 ] && [ -d "$WORK" ] && python3 "$HELPERS" check-manifest --work "$WORK" --xci-size "$dxs" --nsp-size "$dns"; then
      echo "    [dry-run] manifest.json passt: würde übersprungen"
      stage_result extract "übersprungen (Plan)"
    else
      echo "    [dry-run] würde extrahieren: hactool -t xci/pfs0, NCAs klassifizieren, Update anwenden -> $WORK/exefs, $WORK/romfs (Schlüssel werden nie ausgegeben)"
      UPSTREAM_DIRTY=1; stage_result extract "würde ausgeführt"
    fi
    return 0
  fi
  hactool_runs || die 4 "hactool fehlt: zuerst 'scripts/build_all.sh tools'"

  mkdir -p "$WORK"
  WORK="$(cd "$WORK" && pwd)"
  local xci_size nsp_size=0
  xci_size="$(file_size "$XCI")"
  [ -z "$NSP" ] || nsp_size="$(file_size "$NSP")"

  if [ "$FORCE" -eq 0 ] && python3 "$HELPERS" check-manifest --work "$WORK" --xci-size "$xci_size" --nsp-size "$nsp_size"; then
    log "extract: manifest.json passt, übersprungen (--force zum Neu-Erzeugen)"
    stage_result extract "übersprungen"
    return 0
  fi

  # Platzbedarf: XCI + NSP + RomFS (grob so groß wie die XCI) plus Reserve
  local need free
  need=$(( MIN_FREE_GB + (xci_size * 2 + nsp_size) / 1073741824 + 1 ))
  free="$(free_gb "$WORK")"
  [ "$free" -ge "$need" ] || die 8 "Zu wenig Platz: ${free} GB frei, benötigt ca. ${need} GB (inkl. ${MIN_FREE_GB} GB Reserve)"

  EXTRACT_ACTIVE=1
  trap extract_cleanup EXIT
  rm -rf "$WORK/.stage" "$WORK/nca-base" "$WORK/nca-update"
  mkdir -p "$WORK/.stage"
  local stage="$WORK/.stage" t0=$SECONDS

  log "1/6 XCI: secure-Partition entpacken"
  hq -t xci --securedir="$WORK/nca-base" "$XCI" || die 5 "XCI lässt sich nicht entpacken (Datei defekt oder Keys fehlen)"
  if [ -n "$NSP" ]; then
    log "2/6 NSP entpacken"
    hq -t pfs0 --pfs0dir="$WORK/nca-update" "$NSP" || die 5 "NSP lässt sich nicht entpacken"
  else
    log "2/6 kein NSP angegeben: nur Basisspiel"
  fi

  log "3/6 NCAs klassifizieren (hactool -i: Content Type, Titel-ID)"
  classify_dir "$WORK/nca-base" "$stage/base.tsv"
  local base_nca base_tid upd_nca="" upd_rights="" tk=""
  base_nca="$(pick "$stage/base.tsv" Program)"
  [ -n "$base_nca" ] || die 7 "Keine Program-NCA in der XCI gefunden"
  base_tid="$(tsv_field "$stage/base.tsv" "$base_nca" 2)"
  log "    Basisspiel: Titel-ID $base_tid"
  if [ -n "$NSP" ]; then
    classify_dir "$WORK/nca-update" "$stage/update.tsv"
    upd_nca="$(pick "$stage/update.tsv" Program "$base_tid")"
    [ -n "$upd_nca" ] || die 7 "Keine Update-Program-NCA zu Titel-ID $base_tid im NSP (falsches Update?)"
    upd_rights="$(tsv_field "$stage/update.tsv" "$upd_nca" 6)"
    if [ -n "$upd_rights" ]; then
      log "4/6 Titlekey aus Ticket bzw. title.keys"
      tk="$(python3 "$HELPERS" titlekey --rights-id "$upd_rights" --tik-dir "$WORK/nca-update" ${TITLE_KEYS:+--title-keys "$TITLE_KEYS"})" \
        || die 6 "Kein Titlekey für das Update gefunden (Ticket im NSP oder Eintrag in title.keys nötig)"
    else
      log "4/6 Update verwendet Standard-Crypto, kein Titlekey nötig"
    fi
  else
    log "4/6 entfällt (kein Update)"
  fi

  log "5/6 exefs und romfs extrahieren (Update auf Basis-NCA anwenden)"
  if [ -n "$upd_nca" ]; then
    hq ${tk:+--titlekey="$tk"} --basenca="$base_nca" --exefsdir="$stage/exefs" --romfsdir="$stage/romfs" "$upd_nca" \
      || die 5 "Update-NCA lässt sich nicht anwenden (Master-Key-Revision des Updates in prod.keys?)"
  else
    hq --exefsdir="$stage/exefs" --romfsdir="$stage/romfs" "$base_nca" || die 5 "Base-NCA lässt sich nicht extrahieren"
  fi
  tk=""
  [ -s "$stage/exefs/main" ] || die 9 "exefs/main fehlt nach der Extraktion"
  [ -n "$(find "$stage/romfs" -type f -print -quit 2>/dev/null)" ] || die 9 "romfs ist leer nach der Extraktion"

  # Version: Titelversion aus der cnmt, Anzeigeversion aus control.nacp (best effort)
  log "6/6 Version und Manifest"
  local vtsv="$stage/base.tsv" meta_nca ctl_nca ctl_rights ver=0 dver="" tkc=""
  [ -z "$NSP" ] || vtsv="$stage/update.tsv"
  meta_nca="$(pick "$vtsv" Meta)"
  if [ -n "$meta_nca" ] && hq --section0dir="$stage/cnmt" "$meta_nca"; then
    ver="$(python3 "$HELPERS" cnmt-version "$stage/cnmt" 2>/dev/null || echo 0)"
  fi
  ctl_nca="$(python3 "$ROOT/scripts/recomp/app/game_icons.py" pick-control --tsv "$vtsv" --title-id "$base_tid")"
  if [ -n "$ctl_nca" ]; then
    ctl_rights="$(tsv_field "$vtsv" "$ctl_nca" 6)"
    if [ -n "$ctl_rights" ]; then
      tkc="$(python3 "$HELPERS" titlekey --rights-id "$ctl_rights" --tik-dir "$WORK/nca-update" ${TITLE_KEYS:+--title-keys "$TITLE_KEYS"} 2>/dev/null || true)"
    fi
    if hq ${tkc:+--titlekey="$tkc"} --romfsdir="$stage/control" "$ctl_nca"; then
      dver="$(python3 "$HELPERS" nacp-version "$stage/control" 2>/dev/null || true)"
    fi
  fi
  tkc=""

  # Preserve all original icon variants outside Git; fill missing update languages from the base Control NCA.
  local base_ctl base_ctl_rights base_ctl_key=""
  base_ctl="$(python3 "$ROOT/scripts/recomp/app/game_icons.py" pick-control --tsv "$stage/base.tsv" --title-id "$base_tid")"
  if [ -n "$base_ctl" ]; then
    base_ctl_rights="$(tsv_field "$stage/base.tsv" "$base_ctl" 6)"
    if [ -n "$base_ctl_rights" ]; then
      base_ctl_key="$(python3 "$HELPERS" titlekey --rights-id "$base_ctl_rights" --tik-dir "$WORK/nca-base" ${TITLE_KEYS:+--title-keys "$TITLE_KEYS"} 2>/dev/null || true)"
    fi
    hq ${base_ctl_key:+--titlekey="$base_ctl_key"} --romfsdir="$stage/control-base" "$base_ctl" || true
  fi
  base_ctl_key=""
  python3 "$ROOT/scripts/recomp/app/game_icons.py" ingest --base-control "$stage/control-base" \
    --update-control "$stage/control" --title-id "$base_tid" --output "$WORK/recomp/icons/source"

  rm -rf "$WORK/exefs" "$WORK/romfs" "$WORK/manifest.json"
  mv "$stage/exefs" "$WORK/exefs"
  mv "$stage/romfs" "$WORK/romfs"
  python3 "$HELPERS" write-manifest --work "$WORK" --title-id "$base_tid" --title-version "$ver" \
    --display-version "$dver" --update-applied "$([ -n "$upd_nca" ] && echo 1 || echo 0)" \
    --xci-size "$xci_size" --nsp-size "$nsp_size" || die 9 "manifest.json konnte nicht geschrieben werden"
  extract_cleanup
  EXTRACT_ACTIVE=0
  log "Stufe extract fertig in $((SECONDS - t0)) s: $WORK/exefs, $WORK/romfs, $WORK/manifest.json"
  stage_result extract "ausgeführt"
}

# ---------- Gemeinsame Hilfen der weiteren Stufen ----------
stage_result() { RESULTS="$RESULTS$1|$2"$'\n'; }
human() { awk -v b="$1" 'BEGIN { printf "%.1f GB", b / 1073741824 }'; }
sp() { python3 "$STAGEPY" "$@"; }
want_target() { [ "$TARGET" = all ] || [ "$TARGET" = "$1" ]; }

# Kommando ausführen, Ausgabe in work/logs/<Stufe>.log; bei --dry-run nur anzeigen.
logrun() {
  local st="$1" rc=0; shift
  if [ "$DRY" -eq 1 ]; then
    printf '    [dry-run]'; printf ' %q' "$@"; printf '   (Log: %s)\n' "$WORK/logs/$st.log"
    return 0
  fi
  mkdir -p "$WORK/logs"
  "$@" </dev/null >"$WORK/logs/$st.log" 2>&1 || rc=$?
  if [ "$rc" -ne 0 ] && [ "${QUIET_FAIL:-0}" -eq 0 ]; then tail -n 20 "$WORK/logs/$st.log" >&2; fi
  return "$rc"
}

# Plan-Ausgabe für einzelne Kommandos (nur bei --dry-run), sonst ausführen.
run() {
  if [ "$DRY" -eq 1 ]; then printf '    [dry-run]'; printf ' %q' "$@"; printf '\n'; return 0; fi
  "$@"
}

# Marker prüfen: 0 = überspringen. Argumente: Stufe [Ausgabepfade, die existieren müssen]
stage_cached() {
  local st="$1" p present=1; shift
  STAGE_HASH="$(sp stage-hash --stage "$st" --root "$ROOT" --work "$WORK" --target "$TARGET" --profile "$VIDEO_PROFILE" | tail -n 1)"
  for p in "$@"; do [ -e "$p" ] || present=0; done
  if [ "$FORCE" -eq 0 ] && [ "$present" -eq 1 ] && { [ "$DRY" -eq 0 ] || [ "$UPSTREAM_DIRTY" -eq 0 ]; } \
     && sp marker-check --work "$WORK" --stage "$st" --hash "$STAGE_HASH"; then
    log "$st: Marker passt (Eingaben unverändert), übersprungen (--force zum Neu-Erzeugen)"
    stage_result "$st" "übersprungen (Marker passt)"
    return 0
  fi
  if [ "$DRY" -eq 1 ]; then UPSTREAM_DIRTY=1; echo "    [dry-run] Stufe $st würde ausgeführt:"; fi
  return 1
}

# Stufe als erledigt markieren (Notizen K=V, nur Zählwerte/Größen). Bei --dry-run nur Ergebnis vermerken.
stage_done() {
  local st="$1" n args=(); shift
  if [ "$DRY" -eq 1 ]; then stage_result "$st" "würde ausgeführt"; return 0; fi
  for n in "$@"; do args+=(--note "$n"); done
  sp marker-write --work "$WORK" --stage "$st" --hash "$STAGE_HASH" ${args[@]+"${args[@]}"}
  stage_result "$st" "ausgeführt"
}

need_extract() {
  [ -s "$WORK/exefs/main" ] && [ -d "$WORK/romfs/Data" ] && return 0
  case " $SELECTED " in *" extract "*) return 0 ;; esac
  if [ "$DRY" -eq 1 ]; then echo "    [dry-run] Hinweis: $WORK/exefs und romfs fehlen (Stufe extract nicht gewählt)"; return 0; fi
  die 10 "exefs/romfs fehlen in $WORK: zuerst 'scripts/build_all.sh extract --xci <Datei> --nsp <Datei> --keys <Ordner>' (docs/bauen.md)"
}

need_pydeps() {
  [ "$DRY" -eq 1 ] && return 0
  [ -d "$TOOLS_DIR/pydeps/UnityPy" ] || die 4 "Python-Pakete fehlen (UnityPy, lz4): python3 -m pip install --target tools/pydeps UnityPy lz4"
}

AA_REL="romfs/Data/StreamingAssets/AssetAssistant"
MOVIE_REL="romfs/Data/StreamingAssets/Movie"

# ---------- Stufe il2cpp ----------
stage_il2cpp() {
  log "Stufe il2cpp"
  need_extract
  stage_cached il2cpp "$WORK/il2cpp/dump.cs" && return 0
  local meta="$WORK/romfs/Data/Managed/Metadata/global-metadata.dat" dll="$TOOLS_DIR/il2cppdumper-bin/Il2CppDumper.dll"
  local out="$WORK/il2cpp" stg="$WORK/il2cpp.stage"
  if [ "$DRY" -eq 0 ]; then
    command -v dotnet >/dev/null 2>&1 || die 4 "dotnet fehlt (brew install dotnet, ohne sudo)"
    [ -f "$dll" ] || die 4 "Il2CppDumper fehlt: $dll (Bauanleitung: docs/extraktion.md, Abschnitt IL2CPP-Dump)"
    [ -f "$meta" ] || die 10 "global-metadata.dat fehlt: $meta (Stufe extract unvollständig?)"
    rm -rf "$stg"; mkdir -p "$stg"
  fi
  export DOTNET_ROLL_FORWARD=Major
  # Der Dumper wartet am Ende auf eine Taste und wirft ohne Terminal eine harmlose Ausnahme: Erfolg zählt am Ergebnis.
  QUIET_FAIL=1 logrun il2cpp dotnet "$dll" "$WORK/exefs/main" "$meta" "$stg" || true
  if [ "$DRY" -eq 0 ]; then
    [ -s "$stg/dump.cs" ] && [ -s "$stg/script.json" ] || die 14 "Il2CppDumper lieferte kein dump.cs/script.json (Log: $WORK/logs/il2cpp.log)"
    rm -rf "$out"; mv "$stg" "$out"
  else
    echo "    [dry-run] danach: $stg nach $out verschieben (dump.cs, script.json, il2cpp.h, DummyDll)"
  fi
  stage_done il2cpp
}

# ---------- Stufe recomp ----------
# macOS-App aus der Rekompilation des eigenen Dumps (Generator -> C -> Übersetzen -> Laufzeit/Metal -> BDSP.app); Technik und
# Teilschritte: scripts/recomp/app/recomp_build.sh, Anleitung: docs/bauen.md, docs/recomp-macapp.md
recomp_out() { echo "$WORK/builds/macos-recomp/BDSP.app"; }

stage_recomp() {
  log "Stufe recomp (macOS-App aus der Rekompilation, Metal, ohne Ton)"
  if ! want_target macos; then
    echo "  recomp: nur für --target macos oder all (iPadOS: scripts/recomp/ios, docs/recomp-ios.md); übersprungen"
    stage_result recomp "übersprungen (Ziel $TARGET)"; return 0
  fi
  need_extract
  case "$RECOMP_JOBS$RECOMP_O0_KB" in ''|*[!0-9]*) die 2 "--recomp-jobs und --recomp-o0-kb brauchen ganze Zahlen" ;; esac
  local out; out="$(recomp_out)"
  export XNU_RECOMP_OPTS="o0kb=$RECOMP_O0_KB hardened=$RECOMP_HARDENED data=$RECOMP_DATA"
  stage_cached recomp "$out/Contents/MacOS/BDSP" && return 0
  local args=(--jobs "$RECOMP_JOBS" --o0-kb "$RECOMP_O0_KB" --out "$out")
  [ "$RECOMP_HARDENED" -eq 0 ] || args+=(--hardened)
  [ "$RECOMP_DATA" -eq 1 ] || args+=(--no-install-data)
  [ "$FORCE" -eq 0 ] || args+=(--force)
  if [ "$DRY" -eq 1 ]; then
    if [ -s "$WORK/exefs/main" ]; then
      ensure_legacy_links
      WORK="$WORK" "$ROOT/scripts/recomp/app/recomp_build.sh" --dry-run "${args[@]}"
    else
      echo "    [dry-run] würde ausführen: Generator -> C (work/recomp/gen4, rund 1 GB) -> Übersetzen (4 Jobs, -O0 ab ${RECOMP_O0_KB} KB) -> Modulbilder -> Laufzeit/NVN-Metal -> $out (ad hoc signiert)$([ "$RECOMP_DATA" -eq 1 ] && echo ' -> RomFS nach Application Support')"
    fi
    stage_done recomp; return 0
  fi
  ensure_legacy_links
  local rc=0 t0=$SECONDS
  WORK="$WORK" "$ROOT/scripts/recomp/app/recomp_build.sh" "${args[@]}" || rc=$?
  [ "$rc" -eq 0 ] || die "$rc" "Stufe recomp fehlgeschlagen (Meldungen oben; Logs: $WORK/logs/recomp-*.log). Wiederholung setzt dort fort, wo es stehen blieb."
  log "Stufe recomp fertig in $((SECONDS - t0)) s: $out"
  # Teilmarker (recomp-gen, recomp-obj) sind jetzt geschrieben und gehören zum Eingabe-Hash der Stufe: neu berechnen
  STAGE_HASH="$(sp stage-hash --stage recomp --root "$ROOT" --work "$WORK" --target "$TARGET" --profile "$VIDEO_PROFILE" | tail -n 1)"
  local sz; sz="$(sp tree-size --path "$out" | cut -d' ' -f2)"
  stage_done recomp "app=${out#"$ROOT"/}" "bytes=$sz"
}

# ---------- Stufe masterdata ----------
stage_masterdata() {
  log "Stufe masterdata"
  need_extract; need_pydeps
  stage_cached masterdata "$WORK/masterdata/_counts.json" && return 0
  local aa="$WORK/$AA_REL" out="$WORK/masterdata"
  [ "$DRY" -eq 1 ] || [ -d "$aa" ] || die 10 "AssetAssistant fehlt: $aa (Stufe extract unvollständig?)"
  PYTHONPATH="$TOOLS_DIR/pydeps" logrun masterdata python3 "$ROOT/scripts/masterdata_export.py" export \
    --assets "$aa" --out "$out" --dump "$WORK/il2cpp/dump.cs" --set all --messages \
    || die 14 "Stammdaten-Export fehlgeschlagen (Log: $WORK/logs/masterdata.log)"
  PYTHONPATH="$TOOLS_DIR/pydeps" logrun masterdata-counts python3 "$ROOT/scripts/masterdata_export.py" counts \
    --assets "$aa" --out "$out" || die 14 "Stammdaten-Zählung fehlgeschlagen"
  local n="0 0"
  [ "$DRY" -eq 1 ] || n="$(sp tree-size --path "$out")"
  stage_done masterdata "dateien=${n% *}" "bytes=${n#* }"
}

# ---------- Stufe shaders ----------
# Die Hilfsskripte lesen fest work/romfs; bei einem anderen --work wird dorthin verlinkt.
ensure_legacy_links() {
  local n real_have real_want
  [ "$WORK" != "$ROOT/work" ] || return 0
  for n in romfs exefs; do
    [ -e "$WORK/$n" ] || continue
    if [ -L "$ROOT/work/$n" ] || [ ! -e "$ROOT/work/$n" ]; then
      run ln -sfn "$WORK/$n" "$ROOT/work/$n"
    else
      real_have="$(cd "$ROOT/work/$n" && pwd -P)"; real_want="$(cd "$WORK/$n" && pwd -P)"
      [ "$real_have" = "$real_want" ] || die 10 "$ROOT/work/$n ist ein echter Ordner, die Hilfsskripte lesen ihn aber fest. Entweder --work work verwenden oder den Ordner umbenennen (mv work/$n work/$n.alt)"
    fi
  done
}

stage_shaders() {
  log "Stufe shaders"
  need_extract; need_pydeps
  local out="$WORK/build/shaders" rc=0 args=()
  if stage_cached shaders "$out"; then
    if [ -z "$SHADER_ONLY" ]; then return 0; fi
  fi
  command -v make >/dev/null 2>&1 || [ "$DRY" -eq 1 ] || die 4 "make/cc fehlen (xcode-select --install)"
  ensure_legacy_links
  args=(--out "$out")
  [ -z "${SHADER_USED:-}" ] || args+=(--used "$SHADER_USED")
  [ -z "$SHADER_ONLY" ] || args+=(--shader "$SHADER_ONLY")
  [ "$FORCE" -eq 0 ] || args+=(--force)
  logrun shaders "$ROOT/scripts/shader_build.sh" "${args[@]}" || rc=$?
  case "$rc" in
    0) ;;
    9) echo "  Hinweis: nicht alle Varianten verpackbar (derzeit 16 mit Subgroup-Shuffle, Liste in variants.json); die Stufe läuft weiter." ;;
    *) die 14 "shader_build.sh fehlgeschlagen (Exit $rc, Log: $WORK/logs/shaders.log)" ;;
  esac
  if [ -n "$SHADER_ONLY" ]; then
    stage_result shaders "Stichprobe ($SHADER_ONLY), kein Marker"; return 0
  fi
  local n="0 0"
  [ "$DRY" -eq 1 ] || n="$(sp tree-size --path "$out")"
  stage_done shaders "dateien=${n% *}" "bytes=${n#* }" "ausgabe=${out#"$ROOT"/}"
}

# ---------- Stufe video ----------
stage_video() {
  log "Stufe video (H.265, $VIDEO_PROFILE)"
  local src="$WORK/$MOVIE_REL" dst="$WORK/video"
  [ -z "$MOVIE_SRC" ] || src="$MOVIE_SRC"
  [ -n "$MOVIE_SRC" ] || need_extract
  command -v ffmpeg >/dev/null 2>&1 || [ "$DRY" -eq 1 ] || die 4 "ffmpeg fehlt (brew install ffmpeg)"
  if [ -z "$MOVIE_SRC" ]; then stage_cached video "$dst/video-manifest.json" && return 0
  elif [ "$DRY" -eq 1 ]; then echo "    [dry-run] Stufe video (Stichprobe, ohne Marker) würde ausgeführt:"; fi
  if [ "$DRY" -eq 0 ] && [ -z "$(find "$src" -type f -name '*.webm' -print -quit 2>/dev/null)" ]; then
    echo "  Hinweis: keine .webm-Videos unter $src; Stufe übernimmt nichts."
    stage_result video "übersprungen (keine Quelle)"; return 0
  fi
  logrun video "$ROOT/scripts/video_convert.sh" "$src" "$dst" "$VIDEO_PROFILE" \
    || die 14 "Videoumwandlung fehlgeschlagen (Log: $WORK/logs/video.log)"
  if [ -n "$MOVIE_SRC" ]; then stage_result video "Stichprobe, kein Marker"; return 0; fi
  local n="0 0"
  [ "$DRY" -eq 1 ] || n="$(sp tree-size --path "$dst")"
  stage_done video "dateien=${n% *}" "bytes=${n#* }" "profil=$VIDEO_PROFILE"
}

# ---------- Stufe audio ----------
stage_audio() {
  log "Stufe audio"
  echo "  NICHT IMPLEMENTIERT: Ton wird erforscht (docs/shader-audio-machbarkeit.md, todo/neustart.md Todo rc-audio)."
  echo "  Das Spiel läuft bis dahin stumm."
  NOT_IMPL="$NOT_IMPL audio"
  stage_result audio "nicht implementiert"
}

# ---------- Aufruf ----------
run_stage() {
  case "$1" in
    tools) stage_tools ;;
    extract) stage_extract ;;
    il2cpp) stage_il2cpp ;;
    recomp) stage_recomp ;;
    masterdata) stage_masterdata ;;
    shaders) stage_shaders ;;
    video) stage_video ;;
    audio) stage_audio ;;
    *) die 2 "Unbekannte Stufe: $1 (bekannt: $ALL_STAGES)" ;;
  esac
}

need_val() { [ "$1" -ge 2 ] || die 2 "$2 braucht einen Wert"; }
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --stage) need_val $# "$1"; STAGES="$STAGES ${2//,/ }"; shift 2 ;;
    --from) need_val $# "$1"; FROM="$2"; shift 2 ;;
    --to) need_val $# "$1"; TO="$2"; shift 2 ;;
    --only) need_val $# "$1"; ONLY="$ONLY ${2//,/ }"; shift 2 ;;
    --target) need_val $# "$1"; TARGET="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --no-preflight) NO_PREFLIGHT=1; shift ;;
    --min-free-gb) need_val $# "$1"; PREFLIGHT_FREE_GB="$2"; shift 2 ;;
    --video-profile) need_val $# "$1"; VIDEO_PROFILE="$2"; shift 2 ;;
    --movie-src) need_val $# "$1"; MOVIE_SRC="$2"; shift 2 ;;
    --shader-only) need_val $# "$1"; SHADER_ONLY="$2"; shift 2 ;;
    --launch) LAUNCH=1; shift ;;
    --bundle-platform) need_val $# "$1"; BUNDLE_PLATFORM="$2"; shift 2 ;;
    --bundle-subset) need_val $# "$1"; BUNDLE_SUBSET="$2"; shift 2 ;;
    --texture-format) need_val $# "$1"; TEXTURE_FORMAT="$2"; shift 2 ;;
    --xci) need_val $# "$1"; XCI="$2"; shift 2 ;;
    --nsp) need_val $# "$1"; NSP="$2"; shift 2 ;;
    --keys) need_val $# "$1"; KEYS_DIR="$2"; shift 2 ;;
    --prod-keys) need_val $# "$1"; PROD_KEYS="$2"; shift 2 ;;
    --title-keys) need_val $# "$1"; TITLE_KEYS="$2"; shift 2 ;;
    --work) need_val $# "$1"; WORK="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --keep-nca) KEEP_NCA=1; shift ;;
    --recomp-jobs) need_val $# "$1"; RECOMP_JOBS="$2"; shift 2 ;;
    --recomp-o0-kb) need_val $# "$1"; RECOMP_O0_KB="$2"; shift 2 ;;
    --hardened) RECOMP_HARDENED=1; shift ;;
    --no-install-data) RECOMP_DATA=0; shift ;;
    -*) die 2 "Unbekannte Option: $1 (--help zeigt die Hilfe)" ;;
    preflight) PREFLIGHT_ONLY=1; shift ;;
    *) STAGES="$STAGES $1"; shift ;;
  esac
done
case "$TARGET" in macos|ios|all) ;; *) die 2 "--target: macos, ios oder all erwartet (nicht '$TARGET')" ;; esac
case "$PREFLIGHT_FREE_GB" in ''|*[!0-9]*) die 2 "--min-free-gb braucht eine ganze Zahl" ;; esac
if [ -z "$BUNDLE_PLATFORM" ]; then
  case "$TARGET" in ios) BUNDLE_PLATFORM=ios ;; *) BUNDLE_PLATFORM=macos ;; esac
fi
case "$BUNDLE_PLATFORM" in macos|ios|keep) ;; *) die 2 "--bundle-platform: macos, ios oder keep erwartet (nicht '$BUNDLE_PLATFORM')" ;; esac
[ -z "$BUNDLE_SUBSET" ] || [ -f "$BUNDLE_SUBSET" ] || die 3 "--bundle-subset: Datei fehlt: $BUNDLE_SUBSET"
if [ -z "$TEXTURE_FORMAT" ]; then
  case "$BUNDLE_PLATFORM" in ios) TEXTURE_FORMAT=6x6 ;; *) TEXTURE_FORMAT=off ;; esac
fi
case "$TEXTURE_FORMAT" in 4x4|6x6|8x8|off) ;; *) die 2 "--texture-format: 4x4, 6x6, 8x8 oder off erwartet (nicht '$TEXTURE_FORMAT')" ;; esac
export XNU_BUNDLE_PLATFORM="$BUNDLE_PLATFORM" XNU_BUNDLE_SUBSET="$BUNDLE_SUBSET" XNU_TEXTURE_FORMAT="$TEXTURE_FORMAT"
if [ -z "${STAGES// /}" ] && [ -z "$FROM" ] && [ -z "$TO" ] && [ -z "${ONLY// /}" ] && [ "$PREFLIGHT_ONLY" -eq 0 ]; then usage; exit 2; fi
SELECTED="$(sp stages --stage "$STAGES" ${FROM:+--from "$FROM"} ${TO:+--to "$TO"} --only "$ONLY")" || exit 2
case "$WORK" in /*) ;; *) WORK="$PWD/$WORK" ;; esac
[ "$DRY" -eq 1 ] || mkdir -p "$WORK"
[ "$DRY" -eq 1 ] && [ ! -d "$WORK" ] || WORK="$(cd "$WORK" && pwd)"

[ "$DRY" -eq 0 ] || log "DRY-RUN: es wird nichts ausgeführt, geschrieben oder installiert"
log "Stufen: $SELECTED (Ziel: $TARGET, Arbeitsordner: $WORK)"
if [ "$NO_PREFLIGHT" -eq 0 ]; then
  log "Preflight"
  PRE_RC=0
  sp preflight --stages "$SELECTED" --target "$TARGET" --root "$ROOT" --work "$WORK" --tools-dir "$TOOLS_DIR" \
    --min-free-gb "$PREFLIGHT_FREE_GB" || PRE_RC=$?
  if [ "$PRE_RC" -ne 0 ]; then
    if [ "$DRY" -eq 1 ] && [ "$PREFLIGHT_ONLY" -eq 0 ]; then
      echo "  (Dry-run: der echte Lauf würde hier mit Exit-Code $PRE_RC enden; mit --no-preflight bzw. --min-free-gb N lässt sich das umgehen)"
    else
      echo "FEHLER: Preflight nicht bestanden (Exit-Code $PRE_RC); bitte die Liste oben abarbeiten." >&2
      exit "$PRE_RC"
    fi
  else
    log "Preflight bestanden"
  fi
  [ "$PREFLIGHT_ONLY" -eq 0 ] || exit 0
fi
[ "$PREFLIGHT_ONLY" -eq 0 ] || { log "Preflight ausgeschaltet (--no-preflight)"; exit 0; }

for s in $SELECTED; do run_stage "$s"; done

log "Zusammenfassung"
printf '%s' "$RESULTS" | while IFS='|' read -r s r; do [ -z "$s" ] || printf '  %-12s %s\n' "$s" "$r"; done
[ -z "$NOT_IMPL" ] || log "Nicht implementierte Stufen (Platzhalter):$NOT_IMPL"
exit 0
