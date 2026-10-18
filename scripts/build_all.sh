#!/usr/bin/env bash
# Einstiegspunkt der Build-Pipeline (docs/build-pipeline.md, Ziel: docs/kernziel.md).
# Stufen: tools, extract (weitere Stufen folgen). Das Repo enthält nie Spieldaten oder Keys.
#
# Aufruf:
#   scripts/build_all.sh tools
#   scripts/build_all.sh extract --xci <x.xci> --nsp <update.nsp> --keys <Ordner> [--work <Ordner>] [--force]
#   scripts/build_all.sh --stage tools,extract <Optionen>      (auch: --stage all)
# Optionen für extract:
#   --xci DATEI         Basisspiel (XCI)
#   --nsp DATEI         Update (NSP), optional
#   --keys ORDNER       Ordner mit prod.keys und title.keys
#   --prod-keys DATEI   statt --keys: prod.keys einzeln
#   --title-keys DATEI  statt --keys: title.keys einzeln (optional)
#   --work ORDNER       Ziel (Standard: work/build)
#   --force             Stufe neu erzeugen, auch wenn manifest.json passt
#   --keep-nca          entpackte NCAs (mehrere GB) behalten
# Umgebung: TOOLS_DIR (Standard tools/), MIN_FREE_GB (Standard 25), UNITY_HUB, UNITY_EDITOR_ROOT.
#
# Exit-Codes: 0 ok, 2 Aufruf, 3 Eingabe fehlt, 4 Werkzeug fehlt/Build, 5 hactool-Fehler,
#             6 Schlüssel/Titlekey, 7 NCA nicht gefunden, 8 zu wenig Platz, 9 Prüfung, 10 Stufe fehlt
# hactool gibt Schlüsselwerte aus: stdout/stderr gehen nie ins Log (nur gefilterte Felder).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HELPERS="$ROOT/scripts/build_helpers.py"
TOOLS_DIR="${TOOLS_DIR:-$ROOT/tools}"
HACTOOL_DIR="$TOOLS_DIR/hactool"
HACTOOL="$HACTOOL_DIR/hactool"
HACTOOL_REPO="https://github.com/SciresM/hactool"
UNITY_VERSION="6000.3.26f1"
UNITY_HUB="${UNITY_HUB:-/Applications/Unity Hub.app/Contents/MacOS/Unity Hub}"
UNITY_EDITOR_ROOT="${UNITY_EDITOR_ROOT:-/Applications/Unity/Hub/Editor}"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
MIN_FREE_GB="${MIN_FREE_GB:-25}"
ALL_STAGES="tools extract"
FUTURE_STAGES="masterdata assets video audio unity deploy"

XCI="" NSP="" KEYS_DIR="" PROD_KEYS="" TITLE_KEYS="" WORK="$ROOT/work/build"
FORCE=0 KEEP_NCA=0 STAGES=""
EXTRACT_ACTIVE=0

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { local code="$1"; shift; echo "FEHLER: $*" >&2; exit "$code"; }
usage() { sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; }

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

check_unity() {
  local bad=0 editor="$UNITY_EDITOR_ROOT/$UNITY_VERSION"
  if [ -x "$UNITY_HUB" ]; then
    ok "Unity Hub CLI ($UNITY_HUB)"
  else
    miss "Unity Hub CLI ($UNITY_HUB); Installation: brew install --cask unity-hub"; bad=1
  fi
  if [ -d "$editor/Unity.app" ]; then
    ok "Unity Editor $UNITY_VERSION ($editor)"
    if [ -d "$editor/PlaybackEngines/iOSSupport" ]; then
      ok "  Modul iOS Build Support"
    else
      miss "  Modul iOS Build Support für $UNITY_VERSION"; bad=1
    fi
  else
    miss "Unity Editor $UNITY_VERSION unter $UNITY_EDITOR_ROOT (nur geprüft, nicht installiert; Hub-CLI: 'Unity Hub -- --headless install --version $UNITY_VERSION')"
    bad=1
  fi
  return $bad
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
  local bad=0
  check_python || bad=1
  check_hactool || bad=1
  check_ffmpeg || bad=1
  check_unity || bad=1
  check_xcode || bad=1
  [ "$bad" -eq 0 ] || die 4 "Werkzeuge unvollständig (siehe FEHLT oben)"
  log "Stufe tools fertig"
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
  [ -n "$XCI" ] || die 2 "--xci fehlt"
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
  hactool_runs || die 4 "hactool fehlt: zuerst 'scripts/build_all.sh tools'"

  mkdir -p "$WORK"
  WORK="$(cd "$WORK" && pwd)"
  local xci_size nsp_size=0
  xci_size="$(file_size "$XCI")"
  [ -z "$NSP" ] || nsp_size="$(file_size "$NSP")"

  if [ "$FORCE" -eq 0 ] && python3 "$HELPERS" check-manifest --work "$WORK" --xci-size "$xci_size" --nsp-size "$nsp_size"; then
    log "extract: manifest.json passt, übersprungen (--force zum Neu-Erzeugen)"
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
  ctl_nca="$(pick "$vtsv" Control)"
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

  rm -rf "$WORK/exefs" "$WORK/romfs" "$WORK/manifest.json"
  mv "$stage/exefs" "$WORK/exefs"
  mv "$stage/romfs" "$WORK/romfs"
  python3 "$HELPERS" write-manifest --work "$WORK" --title-id "$base_tid" --title-version "$ver" \
    --display-version "$dver" --update-applied "$([ -n "$upd_nca" ] && echo 1 || echo 0)" \
    --xci-size "$xci_size" --nsp-size "$nsp_size" || die 9 "manifest.json konnte nicht geschrieben werden"
  extract_cleanup
  EXTRACT_ACTIVE=0
  log "Stufe extract fertig in $((SECONDS - t0)) s: $WORK/exefs, $WORK/romfs, $WORK/manifest.json"
}

# ---------- Aufruf ----------
run_stage() {
  case "$1" in
    tools) stage_tools ;;
    extract) stage_extract ;;
    *) case " $FUTURE_STAGES " in
         *" $1 "*) die 10 "Stufe '$1' ist noch nicht implementiert" ;;
         *) die 2 "Unbekannte Stufe: $1 (bekannt: $ALL_STAGES $FUTURE_STAGES)" ;;
       esac ;;
  esac
}

need_val() { [ "$1" -ge 2 ] || die 2 "$2 braucht einen Wert"; }
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --stage) need_val $# "$1"; STAGES="$STAGES ${2//,/ }"; shift 2 ;;
    --xci) need_val $# "$1"; XCI="$2"; shift 2 ;;
    --nsp) need_val $# "$1"; NSP="$2"; shift 2 ;;
    --keys) need_val $# "$1"; KEYS_DIR="$2"; shift 2 ;;
    --prod-keys) need_val $# "$1"; PROD_KEYS="$2"; shift 2 ;;
    --title-keys) need_val $# "$1"; TITLE_KEYS="$2"; shift 2 ;;
    --work) need_val $# "$1"; WORK="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --keep-nca) KEEP_NCA=1; shift ;;
    -*) die 2 "Unbekannte Option: $1 (--help zeigt die Hilfe)" ;;
    *) STAGES="$STAGES $1"; shift ;;
  esac
done
[ -n "${STAGES// /}" ] || { usage; exit 2; }
case " $STAGES " in *" all "*) STAGES="$ALL_STAGES" ;; esac
for s in $STAGES; do run_stage "$s"; done
