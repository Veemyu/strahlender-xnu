#!/bin/bash
# Mac → Linux host: transfers only the generator inputs (idempotent, rsync) and then checks the checksums on the Linux host.
#   - work/exefs/{rtld,main,sdk,subsdk0}      (only these four files; no keys/NCA/XCI/NSP/saves)
#   - scripts/recomp                          (contains scripts/recomp/upstream = vendored LASRecomp parts; without rt-bdsp = working state of ap-recomp-3, without intermediate states)
# Usage: sync.sh [--mit-rt-bdsp] [--ohne-setup]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd "$RZ_REPO"
WITH_BDSP=0; SETUP=1
for a in "$@"; do
  case "$a" in
    --mit-rt-bdsp) WITH_BDSP=1;;
    --ohne-setup) SETUP=0;;
    -h|--help) sed -n 2,8p "$0"; exit 0;;
    *) rz_die "Unknown option '$a' (allowed: --mit-rt-bdsp, --ohne-setup).";;
  esac
done

MODS="rtld main sdk subsdk0"
for m in $MODS; do [ -f "work/exefs/$m" ] || rz_die "work/exefs/$m is missing. First extract your own dump (docs/…), then run sync.sh."; done
[ -f scripts/recomp/upstream/generator/gen.py ] || rz_die "scripts/recomp/upstream/generator/gen.py is missing (vendored LASRecomp parts)."
[ -f scripts/recomp/eh_gen.py ] || rz_die "scripts/recomp/eh_gen.py is missing."
# Guard: nothing large or game-related may be in scripts/recomp
big=$(find scripts/recomp -type f -size +2M -not -path '*/rt-bdsp/*' | head -3)
[ -z "$big" ] || rz_die "Unexpectedly large files in scripts/recomp (no game content transferred!): $big"

rz_require
mkdir -p "$RZ_LOCAL_OUT"
MAN="$RZ_LOCAL_OUT/exefs.sha256"
: > "$MAN"
for m in $MODS; do (cd work && shasum -a 256 "exefs/$m" | sed 's#  exefs/#  work/exefs/#') >> "$MAN"; done

rz_ssh "mkdir -p ~/$RZ_DIR/work/exefs ~/$RZ_DIR/research ~/$RZ_DIR/scripts ~/$RZ_DIR/manifest ~/$RZ_DIR/logs"
rz_info "Inputs (4 files) …"
rsync -a work/exefs/rtld work/exefs/main work/exefs/sdk work/exefs/subsdk0 "$RZ_HOST:$RZ_DIR/work/exefs/"
rsync -a "$MAN" "$RZ_HOST:$RZ_DIR/manifest/exefs.sha256"
rz_info "scripts/recomp …"
EXCL=(--exclude='__pycache__' --exclude='*.o' --exclude='*.nso' --exclude='*.img' --exclude='*.keys')
[ "$WITH_BDSP" = 1 ] || EXCL+=(--exclude=rt-bdsp)
rsync -a --delete "${EXCL[@]}" scripts/recomp/ "$RZ_HOST:$RZ_DIR/scripts/recomp/"
# eh_lsda.py/eh_pick.py import scripts/recomp_survey.py (overview of the modules, no game content)
[ -f scripts/recomp_survey.py ] && rsync -a scripts/recomp_survey.py "$RZ_HOST:$RZ_DIR/scripts/recomp_survey.py"

if [ "$SETUP" = 1 ]; then
  RZ_TAIL=30 rz_run "$RZ_LANE_A" setup setup.sh
else
  rz_info "Transfer done (setup/checksums skipped)."
fi
