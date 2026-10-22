#!/usr/bin/env bash
# Entry point of the build pipeline (guide: docs/BUILD.md).
# The repo never contains game data or keys.
#
# Stages (fixed order): tools extract recomp shaders
#   A preflight runs first (check only, no installation).
#
# Usage (everything in one command):
#   scripts/build_all.sh all --xci <x.xci> --nsp <update.nsp> --keys <folder> [--target macos|ios|all]
#   scripts/build_all.sh --dry-run all --xci ... --keys ...     shows plan and commands, changes nothing
#   scripts/build_all.sh --from extract --to recomp            only a range of the order
#   scripts/build_all.sh --only tools,extract                   exactly these stages
#   scripts/build_all.sh preflight                              only check the prerequisites
# Inputs (extract only): --xci FILE, --nsp FILE (optional), --keys FOLDER | --prod-keys FILE [--title-keys FILE]
# Control:
#   --work FOLDER       working folder (default: work/, gitignored)
#   --target T          macos, ios or all (default: all) for recomp
#   --dry-run           run nothing, only show plan, marker status and commands
#   --from S / --to S   range of the stage order;  --only S[,S]  exactly these stages
#   --force             regenerate the selected stages even if the marker matches
#   --no-preflight      skip the preflight;  --min-free-gb N  minimum free space in the preflight (default 60)
#   --keep-nca          keep the unpacked NCAs (several GB)
#   --shader-only NAME  only one shader (test, stage shaders)
#   Stage recomp (macOS app from the recompilation, work/builds/macos-recomp/BDSP.app; only for --target macos|all):
#   --recomp-jobs N     number of compilers (default 4, at most 4);  --recomp-o0-kb N  outliers from N KB compiled with -O0 (default 300)
#   --hardened          sign the app with the hardened runtime (default: ad hoc only);  --no-install-data  do not clone the RomFS to Application Support
# Environment: TOOLS_DIR, MIN_FREE_GB (reserve in extract, default 25), DEVELOPER_DIR,
#   SHADER_USED
#
# Exit codes: 0 ok, 2 usage, 3 input missing, 4 tool missing/build, 5 hactool error,
#   6 key/titlekey, 7 NCA not found, 8 not enough space, 9 check, 10 prerequisite/stage missing,
#   14 stage shaders failed
# hactool prints key values: stdout/stderr never go into the log (only filtered fields).
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
ALL_STAGES="tools extract recomp shaders"

XCI="" NSP="" KEYS_DIR="" PROD_KEYS="" TITLE_KEYS="" WORK="$ROOT/work"
FORCE=0 KEEP_NCA=0 STAGES="" FROM="" TO="" ONLY=""
DRY=0 NO_PREFLIGHT=0 PREFLIGHT_ONLY=0 TARGET=all
SHADER_ONLY=""
EXTRACT_ACTIVE=0
RECOMP_JOBS=4 RECOMP_O0_KB=300 RECOMP_HARDENED=0 RECOMP_DATA=1
SELECTED="" RESULTS="" UPSTREAM_DIRTY=0

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { local code="$1"; shift; echo "ERROR: $*" >&2; exit "$code"; }
usage() { awk 'NR > 1 && /^set -euo/ {exit} NR > 1 {sub(/^# ?/, ""); print}' "$0"; }

# ---------- Stage tools ----------
ok() { echo "  OK     $*"; }
miss() { echo "  MISSING  $*"; }

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
    command -v "$c" >/dev/null 2>&1 || { miss "hactool: '$c' missing (Xcode Command Line Tools?)"; return 1; }
  done
  if [ ! -f "$HACTOOL_DIR/Makefile" ]; then
    if [ -e "$HACTOOL_DIR" ] && [ -n "$(ls -A "$HACTOOL_DIR")" ]; then
      miss "hactool: $HACTOOL_DIR is not a hactool source folder"; return 1
    fi
    log "hactool: cloning $HACTOOL_REPO"
    mkdir -p "$TOOLS_DIR"
    git clone --quiet --recursive "$HACTOOL_REPO" "$HACTOOL_DIR" >/dev/null 2>&1 || { miss "hactool: git clone failed (network?)"; return 1; }
  elif [ ! -f "$HACTOOL_DIR/mbedtls/Makefile" ] && [ -e "$HACTOOL_DIR/.git" ]; then
    git -C "$HACTOOL_DIR" submodule update --init --recursive >/dev/null 2>&1 || { miss "hactool: submodule mbedtls missing"; return 1; }
  fi
  [ -f "$HACTOOL_DIR/config.mk" ] || cp "$HACTOOL_DIR/config.mk.template" "$HACTOOL_DIR/config.mk"
  log "hactool: building (make, log: $HACTOOL_DIR/build.log)"
  if ! make -C "$HACTOOL_DIR" -j "$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)" >"$HACTOOL_DIR/build.log" 2>&1; then
    tail -n 15 "$HACTOOL_DIR/build.log" >&2
    miss "hactool: make failed"
    return 1
  fi
  hactool_runs || { miss "hactool: binary does not run"; return 1; }
  ok "hactool built ($HACTOOL)"
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
  [ -d /Applications/Xcode.app ] || { miss "Xcode at /Applications/Xcode.app"; return 1; }
  [ -d "$DEVELOPER_DIR" ] || { miss "DEVELOPER_DIR=$DEVELOPER_DIR does not exist"; return 1; }
  v="$(xcodebuild -version 2>/dev/null | sed -n '1,2p' | tr '\n' ' ')" || true
  [ -n "$v" ] || { miss "Xcode: xcodebuild does not run (license accepted? 'xcodebuild -license')"; return 1; }
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
  log "Stage tools"
  if [ "$DRY" -eq 1 ]; then
    if hactool_runs; then ok "hactool present ($HACTOOL)"; else echo "    [dry-run] would clone and build hactool: $HACTOOL_REPO to $HACTOOL_DIR (make, without sudo)"; fi
    echo "    [dry-run] would check python3, ffmpeg and Xcode (check only)"
    stage_result tools "plan"; return 0
  fi
  local bad=0
  check_python || bad=1
  check_hactool || bad=1
  # ffmpeg and Xcode are needed for the macOS stages only (the Linux build uses its own scripts, docs/BUILD.md section 6)
  if [ "$(uname -s)" = Darwin ]; then check_ffmpeg || bad=1; check_xcode || bad=1; fi
  [ "$bad" -eq 0 ] || die 4 "Tools incomplete (see MISSING above)"
  log "Stage tools done"
  stage_result tools "executed"
}

# ---------- Stage extract ----------
abspath() { local d; d="$(cd "$(dirname "$1")" && pwd)" && echo "$d/$(basename "$1")"; }
file_size() { wc -c < "$1" | tr -d ' '; }   # (portable: stat -f %z is BSD only)
free_gb() { df -k "$1" | awk 'NR==2 {print int($4 / 1048576)}'; }

# Classify all NCAs of a folder: one TSV line per NCA (non-critical fields only)
classify_dir() {
  local dir="$1" out="$2" f line
  : >"$out"
  for f in "$dir"/*.nca; do
    [ -e "$f" ] || continue
    line="$("$HACTOOL" -k "$PROD_KEYS" -i "$f" 2>/dev/null | python3 "$HELPERS" nca-info --path "$f" 2>/dev/null)" || {
      echo "  Note: $(basename "$f") not readable (skipped)" >&2; continue; }
    echo "$line" >>"$out"
  done
  [ -s "$out" ] || die 6 "No NCA readable in $dir: does prod.keys match the firmware/master key revision?"
}

pick() { python3 "$HELPERS" pick --tsv "$1" --type "$2" ${3:+--title-id "$3"} || true; }
tsv_field() { awk -F'\t' -v p="$2" -v c="$3" '$1 == p {print $c}' "$1"; }

extract_cleanup() {
  [ "$EXTRACT_ACTIVE" -eq 1 ] || return 0
  rm -rf "$WORK/.stage"
  [ "$KEEP_NCA" -eq 1 ] || rm -rf "$WORK/nca-base" "$WORK/nca-update"
  return 0
}

# hactool call without output (stdout and stderr may contain key values)
hq() { "$HACTOOL" -k "$PROD_KEYS" "$@" >/dev/null 2>&1; }

stage_extract() {
  log "Stage extract"
  if [ -z "$XCI" ] && [ "$FORCE" -eq 0 ] && [ -s "$WORK/manifest.json" ] && [ -s "$WORK/exefs/main" ] && [ -d "$WORK/romfs" ]; then
    log "extract: no --xci given, using the existing result in $WORK"
    stage_result extract "present"; return 0
  fi
  [ -n "$XCI" ] || die 2 "--xci missing (the extract stage needs your own XCI; usage see docs/BUILD.md)"
  [ -f "$XCI" ] || die 3 "XCI not found: $XCI"
  [ -z "$NSP" ] || [ -f "$NSP" ] || die 3 "NSP not found: $NSP"
  if [ -n "$KEYS_DIR" ]; then
    [ -n "$PROD_KEYS" ] || PROD_KEYS="$KEYS_DIR/prod.keys"
    [ -n "$TITLE_KEYS" ] || TITLE_KEYS="$KEYS_DIR/title.keys"
  fi
  [ -n "$PROD_KEYS" ] || die 2 "--keys <folder> or --prod-keys <file> missing"
  [ -f "$PROD_KEYS" ] || die 3 "prod.keys not found: $PROD_KEYS"
  [ -z "$TITLE_KEYS" ] || [ -f "$TITLE_KEYS" ] || TITLE_KEYS=""
  PROD_KEYS="$(abspath "$PROD_KEYS")"
  [ -z "$TITLE_KEYS" ] || TITLE_KEYS="$(abspath "$TITLE_KEYS")"
  XCI="$(abspath "$XCI")"
  [ -z "$NSP" ] || NSP="$(abspath "$NSP")"

  if [ "$DRY" -eq 1 ]; then
    local dxs dns=0
    dxs="$(file_size "$XCI")"; [ -z "$NSP" ] || dns="$(file_size "$NSP")"
    if [ "$FORCE" -eq 0 ] && [ -d "$WORK" ] && python3 "$HELPERS" check-manifest --work "$WORK" --xci-size "$dxs" --nsp-size "$dns"; then
      echo "    [dry-run] manifest.json matches: would be skipped"
      stage_result extract "skipped (plan)"
    else
      echo "    [dry-run] would extract: hactool -t xci/pfs0, classify NCAs, apply update -> $WORK/exefs, $WORK/romfs (keys are never printed)"
      UPSTREAM_DIRTY=1; stage_result extract "would run"
    fi
    return 0
  fi
  hactool_runs || die 4 "hactool missing: run 'scripts/build_all.sh tools' first"

  mkdir -p "$WORK"
  WORK="$(cd "$WORK" && pwd)"
  local xci_size nsp_size=0
  xci_size="$(file_size "$XCI")"
  [ -z "$NSP" ] || nsp_size="$(file_size "$NSP")"

  if [ "$FORCE" -eq 0 ] && python3 "$HELPERS" check-manifest --work "$WORK" --xci-size "$xci_size" --nsp-size "$nsp_size"; then
    log "extract: manifest.json matches, skipped (--force to regenerate)"
    stage_result extract "skipped"
    return 0
  fi

  # Space needed: XCI + NSP + RomFS (roughly as large as the XCI) plus reserve
  local need free
  need=$(( MIN_FREE_GB + (xci_size * 2 + nsp_size) / 1073741824 + 1 ))
  free="$(free_gb "$WORK")"
  [ "$free" -ge "$need" ] || die 8 "Not enough space: ${free} GB free, about ${need} GB needed (incl. ${MIN_FREE_GB} GB reserve)"

  EXTRACT_ACTIVE=1
  trap extract_cleanup EXIT
  rm -rf "$WORK/.stage" "$WORK/nca-base" "$WORK/nca-update"
  mkdir -p "$WORK/.stage"
  local stage="$WORK/.stage" t0=$SECONDS

  log "1/6 XCI: unpack the secure partition"
  hq -t xci --securedir="$WORK/nca-base" "$XCI" || die 5 "XCI cannot be unpacked (file damaged or keys missing)"
  if [ -n "$NSP" ]; then
    log "2/6 unpack NSP"
    hq -t pfs0 --pfs0dir="$WORK/nca-update" "$NSP" || die 5 "NSP cannot be unpacked"
  else
    log "2/6 no NSP given: base game only"
  fi

  log "3/6 classify NCAs (hactool -i: content type, title ID)"
  classify_dir "$WORK/nca-base" "$stage/base.tsv"
  local base_nca base_tid upd_nca="" upd_rights="" tk=""
  base_nca="$(pick "$stage/base.tsv" Program)"
  [ -n "$base_nca" ] || die 7 "No Program NCA found in the XCI"
  base_tid="$(tsv_field "$stage/base.tsv" "$base_nca" 2)"
  log "    base game: title ID $base_tid"
  if [ -n "$NSP" ]; then
    classify_dir "$WORK/nca-update" "$stage/update.tsv"
    upd_nca="$(pick "$stage/update.tsv" Program "$base_tid")"
    [ -n "$upd_nca" ] || die 7 "No update Program NCA for title ID $base_tid in the NSP (wrong update?)"
    upd_rights="$(tsv_field "$stage/update.tsv" "$upd_nca" 6)"
    if [ -n "$upd_rights" ]; then
      log "4/6 titlekey from ticket or title.keys"
      tk="$(python3 "$HELPERS" titlekey --rights-id "$upd_rights" --tik-dir "$WORK/nca-update" ${TITLE_KEYS:+--title-keys "$TITLE_KEYS"})" \
        || die 6 "No titlekey found for the update (ticket in the NSP or entry in title.keys required)"
    else
      log "4/6 update uses standard crypto, no titlekey needed"
    fi
  else
    log "4/6 not applicable (no update)"
  fi

  log "5/6 extract exefs and romfs (apply the update to the base NCA)"
  if [ -n "$upd_nca" ]; then
    hq ${tk:+--titlekey="$tk"} --basenca="$base_nca" --exefsdir="$stage/exefs" --romfsdir="$stage/romfs" "$upd_nca" \
      || die 5 "Update NCA cannot be applied (master key revision of the update in prod.keys?)"
  else
    hq --exefsdir="$stage/exefs" --romfsdir="$stage/romfs" "$base_nca" || die 5 "Base NCA cannot be extracted"
  fi
  tk=""
  [ -s "$stage/exefs/main" ] || die 9 "exefs/main missing after the extraction"
  [ -n "$(find "$stage/romfs" -type f -print -quit 2>/dev/null)" ] || die 9 "romfs is empty after the extraction"

  # Version: title version from the cnmt, display version from control.nacp (best effort)
  log "6/6 version and manifest"
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
    --xci-size "$xci_size" --nsp-size "$nsp_size" || die 9 "manifest.json could not be written"
  extract_cleanup
  EXTRACT_ACTIVE=0
  log "Stage extract done in $((SECONDS - t0)) s: $WORK/exefs, $WORK/romfs, $WORK/manifest.json"
  stage_result extract "executed"
}

# ---------- Shared helpers of the further stages ----------
stage_result() { RESULTS="$RESULTS$1|$2"$'\n'; }
human() { awk -v b="$1" 'BEGIN { printf "%.1f GB", b / 1073741824 }'; }
sp() { python3 "$STAGEPY" "$@"; }
want_target() { [ "$TARGET" = all ] || [ "$TARGET" = "$1" ]; }

# Run a command, output to work/logs/<stage>.log; with --dry-run only show it.
logrun() {
  local st="$1" rc=0; shift
  if [ "$DRY" -eq 1 ]; then
    printf '    [dry-run]'; printf ' %q' "$@"; printf '   (log: %s)\n' "$WORK/logs/$st.log"
    return 0
  fi
  mkdir -p "$WORK/logs"
  "$@" </dev/null >"$WORK/logs/$st.log" 2>&1 || rc=$?
  if [ "$rc" -ne 0 ] && [ "${QUIET_FAIL:-0}" -eq 0 ]; then tail -n 20 "$WORK/logs/$st.log" >&2; fi
  return "$rc"
}

# Plan output for single commands (only with --dry-run), otherwise run them.
run() {
  if [ "$DRY" -eq 1 ]; then printf '    [dry-run]'; printf ' %q' "$@"; printf '\n'; return 0; fi
  "$@"
}

# Check the marker: 0 = skip. Arguments: stage [output paths that must exist]
stage_cached() {
  local st="$1" p present=1; shift
  STAGE_HASH="$(sp stage-hash --stage "$st" --root "$ROOT" --work "$WORK" --target "$TARGET" | tail -n 1)"
  for p in "$@"; do [ -e "$p" ] || present=0; done
  if [ "$FORCE" -eq 0 ] && [ "$present" -eq 1 ] && { [ "$DRY" -eq 0 ] || [ "$UPSTREAM_DIRTY" -eq 0 ]; } \
     && sp marker-check --work "$WORK" --stage "$st" --hash "$STAGE_HASH"; then
    log "$st: marker matches (inputs unchanged), skipped (--force to regenerate)"
    stage_result "$st" "skipped (marker matches)"
    return 0
  fi
  if [ "$DRY" -eq 1 ]; then UPSTREAM_DIRTY=1; echo "    [dry-run] Stage $st would run:"; fi
  return 1
}

# Mark a stage as done (notes K=V, counts/sizes only). With --dry-run only record the result.
stage_done() {
  local st="$1" n args=(); shift
  if [ "$DRY" -eq 1 ]; then stage_result "$st" "would run"; return 0; fi
  for n in "$@"; do args+=(--note "$n"); done
  sp marker-write --work "$WORK" --stage "$st" --hash "$STAGE_HASH" ${args[@]+"${args[@]}"}
  stage_result "$st" "executed"
}

need_extract() {
  [ -s "$WORK/exefs/main" ] && [ -d "$WORK/romfs/Data" ] && return 0
  case " $SELECTED " in *" extract "*) return 0 ;; esac
  if [ "$DRY" -eq 1 ]; then echo "    [dry-run] Note: $WORK/exefs and romfs are missing (stage extract not selected)"; return 0; fi
  die 10 "exefs/romfs missing in $WORK: run 'scripts/build_all.sh extract --xci <file> --nsp <file> --keys <folder>' first (docs/BUILD.md)"
}

need_pydeps() {
  [ "$DRY" -eq 1 ] && return 0
  [ -d "$TOOLS_DIR/pydeps/UnityPy" ] || die 4 "Python packages missing (UnityPy, lz4): python3 -m pip install --target tools/pydeps UnityPy lz4"
}

# ---------- Stage recomp ----------
# macOS app from the recompilation of your own dump (generator -> C -> compile -> runtime/Metal -> BDSP.app); technique and
# sub-steps: scripts/recomp/app/recomp_build.sh, guide: docs/BUILD.md, docs/recomp-macapp.md
recomp_out() { echo "$WORK/builds/macos-recomp/BDSP.app"; }

stage_recomp() {
  log "Stage recomp (macOS app from the recompilation, Metal)"
  if ! want_target macos; then
    echo "  recomp: only for --target macos or all (iPadOS: scripts/recomp/ios, docs/recomp-ios.md); skipped"
    stage_result recomp "skipped (target $TARGET)"; return 0
  fi
  need_extract
  case "$RECOMP_JOBS$RECOMP_O0_KB" in ''|*[!0-9]*) die 2 "--recomp-jobs and --recomp-o0-kb need whole numbers" ;; esac
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
      echo "    [dry-run] would run: generator -> C (work/recomp/gen4, about 1 GB) -> compile (4 jobs, -O0 from ${RECOMP_O0_KB} KB) -> module images -> runtime/NVN-Metal -> $out (ad hoc signed)$([ "$RECOMP_DATA" -eq 1 ] && echo ' -> RomFS into Application Support')"
    fi
    stage_done recomp; return 0
  fi
  ensure_legacy_links
  local rc=0 t0=$SECONDS
  WORK="$WORK" "$ROOT/scripts/recomp/app/recomp_build.sh" "${args[@]}" || rc=$?
  [ "$rc" -eq 0 ] || die "$rc" "Stage recomp failed (messages above; logs: $WORK/logs/recomp-*.log). A rerun resumes where it stopped."
  log "Stage recomp done in $((SECONDS - t0)) s: $out"
  # The partial markers (recomp-gen, recomp-obj) are written now and belong to the input hash of the stage: recompute it
  STAGE_HASH="$(sp stage-hash --stage recomp --root "$ROOT" --work "$WORK" --target "$TARGET" | tail -n 1)"
  local sz; sz="$(sp tree-size --path "$out" | cut -d' ' -f2)"
  stage_done recomp "app=${out#"$ROOT"/}" "bytes=$sz"
}

# ---------- Stage shaders ----------
# The helper scripts read work/romfs hard-coded; with another --work it is linked there.
ensure_legacy_links() {
  local n real_have real_want
  [ "$WORK" != "$ROOT/work" ] || return 0
  for n in romfs exefs; do
    [ -e "$WORK/$n" ] || continue
    if [ -L "$ROOT/work/$n" ] || [ ! -e "$ROOT/work/$n" ]; then
      run ln -sfn "$WORK/$n" "$ROOT/work/$n"
    else
      real_have="$(cd "$ROOT/work/$n" && pwd -P)"; real_want="$(cd "$WORK/$n" && pwd -P)"
      [ "$real_have" = "$real_want" ] || die 10 "$ROOT/work/$n is a real folder, but the helper scripts read it hard-coded. Either use --work work or rename the folder (mv work/$n work/$n.alt)"
    fi
  done
}

stage_shaders() {
  log "Stage shaders"
  need_extract; need_pydeps
  local out="$WORK/build/shaders" rc=0 args=()
  if stage_cached shaders "$out"; then
    if [ -z "$SHADER_ONLY" ]; then return 0; fi
  fi
  command -v make >/dev/null 2>&1 || [ "$DRY" -eq 1 ] || die 4 "make/cc missing (xcode-select --install)"
  ensure_legacy_links
  args=(--out "$out")
  [ -z "${SHADER_USED:-}" ] || args+=(--used "$SHADER_USED")
  [ -z "$SHADER_ONLY" ] || args+=(--shader "$SHADER_ONLY")
  [ "$FORCE" -eq 0 ] || args+=(--force)
  logrun shaders "$ROOT/scripts/shader_build.sh" "${args[@]}" || rc=$?
  case "$rc" in
    0) ;;
    9) echo "  Note: not all variants can be packed (currently 16 with subgroup shuffle, list in variants.json); the stage continues." ;;
    *) die 14 "shader_build.sh failed (exit $rc, log: $WORK/logs/shaders.log)" ;;
  esac
  if [ -n "$SHADER_ONLY" ]; then
    stage_result shaders "sample ($SHADER_ONLY), no marker"; return 0
  fi
  local n="0 0"
  [ "$DRY" -eq 1 ] || n="$(sp tree-size --path "$out")"
  stage_done shaders "files=${n% *}" "bytes=${n#* }" "output=${out#"$ROOT"/}"
}

# ---------- Invocation ----------
run_stage() {
  case "$1" in
    tools) stage_tools ;;
    extract) stage_extract ;;
    recomp) stage_recomp ;;
    shaders) stage_shaders ;;
    *) die 2 "Unknown stage: $1 (known: $ALL_STAGES)" ;;
  esac
}

need_val() { [ "$1" -ge 2 ] || die 2 "$2 needs a value"; }
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
    --shader-only) need_val $# "$1"; SHADER_ONLY="$2"; shift 2 ;;
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
    -*) die 2 "Unknown option: $1 (--help shows the help)" ;;
    preflight) PREFLIGHT_ONLY=1; shift ;;
    *) STAGES="$STAGES $1"; shift ;;
  esac
done
case "$TARGET" in macos|ios|all) ;; *) die 2 "--target: macos, ios or all expected (not '$TARGET')" ;; esac
case "$PREFLIGHT_FREE_GB" in ''|*[!0-9]*) die 2 "--min-free-gb needs a whole number" ;; esac
if [ -z "${STAGES// /}" ] && [ -z "$FROM" ] && [ -z "$TO" ] && [ -z "${ONLY// /}" ] && [ "$PREFLIGHT_ONLY" -eq 0 ]; then usage; exit 2; fi
SELECTED="$(sp stages --stage "$STAGES" ${FROM:+--from "$FROM"} ${TO:+--to "$TO"} --only "$ONLY")" || exit 2
case "$WORK" in /*) ;; *) WORK="$PWD/$WORK" ;; esac
[ "$DRY" -eq 1 ] || mkdir -p "$WORK"
[ "$DRY" -eq 1 ] && [ ! -d "$WORK" ] || WORK="$(cd "$WORK" && pwd)"

[ "$DRY" -eq 0 ] || log "DRY-RUN: nothing is executed, written or installed"
log "Stages: $SELECTED (target: $TARGET, work folder: $WORK)"
if [ "$NO_PREFLIGHT" -eq 0 ]; then
  log "Preflight"
  PRE_RC=0
  sp preflight --stages "$SELECTED" --target "$TARGET" --root "$ROOT" --work "$WORK" --tools-dir "$TOOLS_DIR" \
    --min-free-gb "$PREFLIGHT_FREE_GB" || PRE_RC=$?
  if [ "$PRE_RC" -ne 0 ]; then
    if [ "$DRY" -eq 1 ] && [ "$PREFLIGHT_ONLY" -eq 0 ]; then
      echo "  (Dry-run: the real run would end here with exit code $PRE_RC; --no-preflight or --min-free-gb N works around it)"
    else
      echo "ERROR: preflight failed (exit code $PRE_RC); please work through the list above." >&2
      exit "$PRE_RC"
    fi
  else
    log "Preflight passed"
  fi
  [ "$PREFLIGHT_ONLY" -eq 0 ] || exit 0
fi
[ "$PREFLIGHT_ONLY" -eq 0 ] || { log "Preflight ausgeschaltet (--no-preflight)"; exit 0; }

for s in $SELECTED; do run_stage "$s"; done

log "Summary"
printf '%s' "$RESULTS" | while IFS='|' read -r s r; do [ -z "$s" ] || printf '  %-12s %s\n' "$s" "$r"; done
exit 0
