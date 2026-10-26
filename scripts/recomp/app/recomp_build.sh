#!/bin/bash
# Stage recomp: from your own dump (work/exefs, work/romfs) to the macOS app work/builds/macos-recomp/BDSP.app.
#   1 generator -> C (about 1 GB, work/recomp/gen4), only if inputs/generator changed (otherwise skipped;
#                  with existing C only files with changed content are replaced)
#   2 compile   -> work/recomp/obj4 (incremental, CPU/RAM-based compiler count, outliers -O0 from 300 KB)
#   3 module images (mkimages.sh), 4 build runtime/NVN-Metal and link with libgame (obj4/*.o) into bdsp_app
#   5 assemble BDSP.app, sign ad hoc; 6 provide data (RomFS as an APFS clone into Application Support)
# The sub-steps carry their own markers (work/.stages/recomp-*.json). Everything under work/ (never in the repo), messages in English.
# Usage: recomp_build.sh [--dry-run] [--force] [--jobs N] [--o0-kb N] [--hardened] [--no-install-data] [--out BDSP.app]
# Environment: RECOMP_DIR (default work/recomp), BDSP_HOME (data target, default ~/Library/Application Support/dev.local.xnubdsp)
# Exit codes like build_all.sh: 2 usage, 4 tool/build, 8 space, 10 prerequisite missing
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
WORK="${WORK:-$ROOT/work}"
R="${RECOMP_DIR:-$WORK/recomp}"
EXEFS_DIR="${BDSP_EXEFS_DIR:-$ROOT/work/exefs}"
case "$R" in /*) ;; *) R="$PWD/$R" ;; esac
JOBS=auto O0_KB=300 DRY=0 FORCE=0 HARDENED=0 INSTALL_DATA=1 OUT="$WORK/builds/macos-recomp/BDSP.app"
SP=(python3 "$ROOT/scripts/build_stages.py")
log() { echo "[$(date +%H:%M:%S)] recomp: $*"; }
die() { local c="$1"; shift; echo "ERROR: $*" >&2; exit "$c"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --force) FORCE=1; shift ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --o0-kb) O0_KB="$2"; shift 2 ;;
    --hardened) HARDENED=1; shift ;;
    --no-install-data) INSTALL_DATA=0; shift ;;
    --out) OUT="$2"; shift 2 ;;
    *) die 2 "Unknown option: $1" ;;
  esac
done
if [ "$JOBS" = auto ]; then JOBS=$(python3 "$ROOT/scripts/recomp/parallel_jobs.py"); fi
case "$JOBS" in ''|*[!0-9]*) die 2 "--jobs needs a number >= 1" ;; esac
[ "$JOBS" -ge 1 ] || die 2 "--jobs needs a number >= 1"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac

GEN="$R/gen4" OBJ="$R/obj4" IMG="$R/img_app" RTO="$R/rt-bdsp-app" NVNRT="$R/rt-bdsp" NVNSRC="$R/nvn-src" BIN="$R/bdsp_app"
O0_BYTES=$((O0_KB * 1000))
# The mod build uses an isolated ExeFS staging directory; the base RomFS stays shared.
[ -s "$EXEFS_DIR/main" ] || die 10 "$EXEFS_DIR/main missing: run the extract stage first"
[ -d "$ROOT/work/romfs/Data" ] || die 10 "work/romfs/Data missing: run the extract stage first"
[ -f "$ROOT/work/exefs/main.npdm" ] || die 10 "work/exefs/main.npdm missing: extract stage incomplete"
[ -f "$ROOT/scripts/recomp/native-generator/src/generator.c" ] \
  || die 10 "Native generator sources missing: restore scripts/recomp/native-generator"

hash_of() { "${SP[@]}" stage-hash --stage "$1" --root "$ROOT" --work "$WORK" | tail -n 1; }
marker_ok() { "${SP[@]}" marker-check --work "$WORK" --stage "$1" --hash "$2"; }
marker_put() { local st="$1" h="$2" args=() n; shift 2; for n in "$@"; do args+=(--note "$n"); done; "${SP[@]}" marker-write --work "$WORK" --stage "$st" --hash "$h" ${args[@]+"${args[@]}"}; }
doit() {  # description, command…  (with --dry-run only show)
  local what="$1"; shift
  if [ "$DRY" -eq 1 ]; then printf '    [dry-run] %s:' "$what"; printf ' %q' "$@"; printf '\n'; return 0; fi
  "$@"
}
[ "$DRY" -eq 1 ] || mkdir -p "$WORK/logs"

# ---------- 1 Generator ----------
H_GEN="$(hash_of recomp-gen)"
if [ -n "${BDSP_EXEFS_DIR:-}" ]; then
  sources=("$EXEFS_DIR"/{rtld,main,sdk,subsdk0})
  [ ! -f "$EXEFS_DIR/subsdk1" ] || sources+=("$EXEFS_DIR/subsdk1" "$EXEFS_DIR/"*.entries)
  H_GEN="$(printf '%s:%s' "$H_GEN" "$(shasum -a 256 "${sources[@]}" | shasum -a 256 | cut -c1-64)" | shasum -a 256 | cut -c1-64)"
fi
if [ "$FORCE" -eq 0 ] && [ -d "$GEN/main" ] && marker_ok recomp-gen "$H_GEN"; then
  log "1/6 generator: marker matches, C present ($(ls "$GEN"/*/*.c | wc -l | tr -d ' ') files), skipped"
else
  log "1/6 generator: generating C with native workers (about 1 GB generated source)"
  if [ -d "$GEN/main" ] && [ "$FORCE" -eq 0 ]; then
    # incremental: regenerate and transfer only files with changed content (timestamps stay, the compiler runs only for changes)
    NEW="$R/gen4.new"
    doit "delete old intermediate folder" rm -rf "$NEW"
    doit "generator" env OUT="$NEW" "$ROOT/scripts/recomp/gen_all.sh"
    if [ "$DRY" -eq 0 ]; then
      for d in "$NEW"/*/; do
        m=$(basename "$d"); mkdir -p "$GEN/$m"
        n=$(rsync -rc --delete --itemize-changes "$d" "$GEN/$m/" | { grep -c '^>f' || true; })
        log "    $m: $n changed files"
      done
      rm -rf "$NEW"
    fi
  else
    doit "generator" env OUT="$GEN" "$ROOT/scripts/recomp/gen_all.sh"
  fi
  [ "$DRY" -eq 1 ] || { [ -d "$GEN/main" ] || die 4 "Generator produced no C (log: work/recomp/spike2/gen4_*.log)"; marker_put recomp-gen "$H_GEN" "files=$(ls "$GEN"/*/*.c | wc -l | tr -d ' ')"; }
fi

# ---------- 2 Compile ----------
H_HOT="$(shasum -a 256 < "$ROOT/scripts/recomp/hot_o2.txt" | cut -c1-16)"   # list of the functions built with -O2
H_OBJ="$(printf '%s|%s|%s|%s|%s' "$H_GEN" "$O0_BYTES" "$(clang --version | head -n 1)" "$H_HOT" "file-prefix-map-v1" | shasum -a 256 | cut -c1-64)"
if [ "$FORCE" -eq 0 ] && [ -d "$OBJ" ] && marker_ok recomp-obj "$H_OBJ"; then
  log "2/6 compile: marker matches ($(ls "$OBJ"/*.o | wc -l | tr -d ' ') objects), skipped"
else
  log "2/6 compile: $JOBS parallel compilers, outliers from ${O0_KB} KB with -O0 (progress: $WORK/logs/recomp-compile.log)"
  if [ "$FORCE" -eq 1 ] && [ "$DRY" -eq 0 ]; then rm -rf "$OBJ"; fi
  # changed -O0 threshold: discard the objects of the affected files (compile_chunk.sh skips existing ones)
  if [ "$DRY" -eq 0 ] && [ -f "$OBJ/.o0_bytes" ] && [ "$(cat "$OBJ/.o0_bytes")" != "$O0_BYTES" ]; then
    old=$(cat "$OBJ/.o0_bytes")
    for f in "$GEN"/*/*.c; do
      s=$(stat -f %z "$f")
      lo=$(( old < O0_BYTES ? old : O0_BYTES )); hi=$(( old > O0_BYTES ? old : O0_BYTES ))
      if [ "$s" -gt "$lo" ] && [ "$s" -le "$hi" ]; then rm -f "$OBJ/$(basename "$(dirname "$f")")_$(basename "$f" .c).o"; fi
    done
  fi
  if [ "$DRY" -eq 1 ]; then
    printf '    [dry-run] compile: env GEN=%q OBJ=%q O0_BYTES=%q scripts/recomp/build_all.sh %q\n' "$GEN" "$OBJ" "$O0_BYTES" "$JOBS"
  else
    mkdir -p "$OBJ"
    if ! GEN="$GEN" OBJ="$OBJ" O0_BYTES="$O0_BYTES" "$ROOT/scripts/recomp/build_all.sh" "$JOBS" > "$WORK/logs/recomp-compile.log" 2>&1; then
      tail -n 20 "$WORK/logs/recomp-compile.log" >&2
      die 4 "Compile failed (log: $WORK/logs/recomp-compile.log). Check memory, disk space, or retry with --jobs N"
    fi
    grep -q "^ERROR" "$WORK/logs/recomp-compile.log" && die 4 "Compile reports errors (log: $WORK/logs/recomp-compile.log)"
    echo "$O0_BYTES" > "$OBJ/.o0_bytes"
    expected=$(ls "$GEN"/*/*.c | wc -l | tr -d ' '); have=$(ls "$OBJ"/*.o | wc -l | tr -d ' ')
    [ "$expected" = "$have" ] || die 4 "Objects incomplete: $have of $expected (log: $WORK/logs/recomp-compile.log)"
    tail -n 2 "$WORK/logs/recomp-compile.log" | sed 's/^/    /'
    marker_put recomp-obj "$H_OBJ" "objects=$have"
  fi
fi

# ---------- 3 Module images ----------
log "3/6 module images (relocations, imports, HLE slots)"
if [ "$DRY" -eq 1 ]; then
  printf '    [dry-run] module images: env IMG=%q HLE_LIST=hle_nvn.txt scripts/recomp/rt-bdsp/mkimages.sh\n' "$IMG"
else
  IMG="$IMG" HLE_LIST="$ROOT/scripts/recomp/rt-bdsp/hle_nvn.txt" "$ROOT/scripts/recomp/rt-bdsp/mkimages.sh" > "$WORK/logs/recomp-images.log" 2>&1 \
    || { tail -n 10 "$WORK/logs/recomp-images.log" >&2; die 4 "mkimages.sh failed (log: $WORK/logs/recomp-images.log)"; }
fi

# ---------- 4 Runtime and NVN/Metal ----------
log "4/6 building runtime and NVN/Metal, linking with libgame into bdsp_app"
if [ "$DRY" -eq 1 ]; then
  printf '    [dry-run] runtime: env BDSP_APP=1 OBJ=%q RT=%q NVN_RT=%q NVN_SRC=%q OUT=%q scripts/recomp/rt-bdsp/build.sh\n' "$OBJ" "$RTO" "$NVNRT" "$NVNSRC" "$BIN"
else
  mkdir -p "$RTO" "$NVNRT"
  BDSP_APP=1 OBJ="$OBJ" RT="$RTO" NVN_RT="$NVNRT" NVN_SRC="$NVNSRC" OUT="$BIN" "$ROOT/scripts/recomp/rt-bdsp/build.sh" > "$WORK/logs/recomp-runtime.log" 2>&1 \
    || { tail -n 20 "$WORK/logs/recomp-runtime.log" >&2; die 4 "Runtime build failed (log: $WORK/logs/recomp-runtime.log). Prerequisite: brew install sdl3 ffmpeg pkg-config llvm; Xcode Command Line Tools"; }
  tail -n 1 "$WORK/logs/recomp-runtime.log" | sed 's/^/    /'
fi

# ---------- 5 App ----------
log "5/6 assembling and signing BDSP.app (ad hoc$([ "$HARDENED" -eq 1 ] && echo ', hardened runtime'))"
APPARGS=(--bin "$BIN" --img "$IMG" --npdm "$ROOT/work/exefs/main.npdm" --out "$OUT")
if [ -n "${BDSP_MOD_NAME:-}" ]; then
  [ -n "${BDSP_MODS_DIR:-}" ] && [ -n "${BDSP_MOD_ROOT:-}" ] && [ -n "${BDSP_MOD_BUNDLE_ID:-}" ] || die 2 "mod app metadata is incomplete"
  APPARGS+=(--mod-name "$BDSP_MOD_NAME" --mods-dir "$BDSP_MODS_DIR" --mod-root "$BDSP_MOD_ROOT" --bundle-id "$BDSP_MOD_BUNDLE_ID" --display-name "${BDSP_MOD_DISPLAY_NAME:-$BDSP_MOD_NAME}")
fi
if [ -n "${BDSP_EXEFS_DIR:-}" ]; then
  export BDSP_ICON_SOURCE="${BDSP_ICON_SOURCE:-$WORK/recomp/icons/source}"
else
  export BDSP_ICON_SOURCE="${BDSP_ICON_SOURCE:-$R/icons/source}"
fi
[ "$HARDENED" -eq 0 ] || APPARGS+=(--hardened)
doit "app" "$ROOT/scripts/recomp/app/make_app.sh" "${APPARGS[@]}"

# ---------- 6 Data ----------
HOME_DIR="${BDSP_HOME:-$HOME/Library/Application Support/dev.local.xnubdsp}"
if [ "$INSTALL_DATA" -eq 0 ]; then
  log "6/6 data: skipped (--no-install-data); the app expects the RomFS at $HOME_DIR/romfs or via romfs = … in config.ini"
else
  # Identifier of the dump: main hash plus the RomFS file count (manifest.json does not exist in every work folder)
  STAMP="$(shasum -a 256 "$ROOT/work/exefs/main" | cut -c1-16) $(find "$ROOT/work/romfs" -type f | wc -l | tr -d ' ')"
  if [ -f "$HOME_DIR/romfs.stamp" ] && [ "$(cat "$HOME_DIR/romfs.stamp")" = "$STAMP" ] && [ -d "$HOME_DIR/romfs/Data" ] && [ "$FORCE" -eq 0 ]; then
    log "6/6 data: RomFS at $HOME_DIR/romfs is up to date, skipped"
  else
    log "6/6 data: RomFS to $HOME_DIR/romfs (APFS clone, needs no extra space; otherwise a copy)"
    if [ "$DRY" -eq 0 ]; then
      mkdir -p "$HOME_DIR"
      rm -rf "$HOME_DIR/romfs.new"
      cp -cR "$ROOT/work/romfs" "$HOME_DIR/romfs.new" 2>/dev/null || cp -R "$ROOT/work/romfs" "$HOME_DIR/romfs.new" \
        || die 8 "RomFS cannot be copied to $HOME_DIR (space?)"
      rm -rf "$HOME_DIR/romfs"
      mv "$HOME_DIR/romfs.new" "$HOME_DIR/romfs"
      printf '%s' "$STAMP" > "$HOME_DIR/romfs.stamp"
    else
      echo "    [dry-run] cp -cR $ROOT/work/romfs $HOME_DIR/romfs"
    fi
  fi
fi
[ "$DRY" -eq 1 ] || log "done: $OUT ($(du -sh "$OUT" | cut -f1))"
