#!/bin/bash
# Mac → Linux host: überträgt nur die Eingaben des Generators (idempotent, rsync) und prüft danach die Prüfsummen auf dem Linux host.
#   - work/exefs/{rtld,main,sdk,subsdk0}      (nur diese vier Dateien; keine Keys/NCA/XCI/NSP/Saves)
#   - scripts/recomp                          (enthält scripts/recomp/upstream = vendorte LASRecomp-Teile; ohne rt-bdsp = Arbeitsstand von ap-recomp-3, ohne Zwischenstände)
# Aufruf: sync.sh [--mit-rt-bdsp] [--ohne-setup]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd "$RZ_REPO"
WITH_BDSP=0; SETUP=1
for a in "$@"; do
  case "$a" in
    --mit-rt-bdsp) WITH_BDSP=1;;
    --ohne-setup) SETUP=0;;
    -h|--help) sed -n 2,8p "$0"; exit 0;;
    *) rz_die "Unbekannte Option '$a' (erlaubt: --mit-rt-bdsp, --ohne-setup).";;
  esac
done

MODS="rtld main sdk subsdk0"
for m in $MODS; do [ -f "work/exefs/$m" ] || rz_die "work/exefs/$m fehlt. Erst den eigenen Dump entpacken (docs/…), dann sync.sh."; done
[ -f scripts/recomp/upstream/generator/gen.py ] || rz_die "scripts/recomp/upstream/generator/gen.py fehlt (vendorte LASRecomp-Teile)."
[ -f scripts/recomp/eh_gen.py ] || rz_die "scripts/recomp/eh_gen.py fehlt."
# Schutz: in scripts/recomp darf nichts Großes oder Spielartiges liegen
big=$(find scripts/recomp -type f -size +2M -not -path '*/rt-bdsp/*' | head -3)
[ -z "$big" ] || rz_die "Unerwartet große Dateien in scripts/recomp (kein Spielinhalt übertragen!): $big"

rz_require
mkdir -p "$RZ_LOCAL_OUT"
MAN="$RZ_LOCAL_OUT/exefs.sha256"
: > "$MAN"
for m in $MODS; do (cd work && shasum -a 256 "exefs/$m" | sed 's#  exefs/#  work/exefs/#') >> "$MAN"; done

rz_ssh "mkdir -p ~/$RZ_DIR/work/exefs ~/$RZ_DIR/research ~/$RZ_DIR/scripts ~/$RZ_DIR/manifest ~/$RZ_DIR/logs"
rz_info "Eingaben (4 Dateien) …"
rsync -a work/exefs/rtld work/exefs/main work/exefs/sdk work/exefs/subsdk0 "$RZ_HOST:$RZ_DIR/work/exefs/"
rsync -a "$MAN" "$RZ_HOST:$RZ_DIR/manifest/exefs.sha256"
rz_info "scripts/recomp …"
EXCL=(--exclude='__pycache__' --exclude='*.o' --exclude='*.nso' --exclude='*.img' --exclude='*.keys')
[ "$WITH_BDSP" = 1 ] || EXCL+=(--exclude=rt-bdsp)
rsync -a --delete "${EXCL[@]}" scripts/recomp/ "$RZ_HOST:$RZ_DIR/scripts/recomp/"
# eh_lsda.py/eh_pick.py importieren scripts/recomp_survey.py (Überblick über die Module, kein Spielinhalt)
[ -f scripts/recomp_survey.py ] && rsync -a scripts/recomp_survey.py "$RZ_HOST:$RZ_DIR/scripts/recomp_survey.py"

if [ "$SETUP" = 1 ]; then
  RZ_TAIL=30 rz_run "$RZ_LANE_A" setup setup.sh
else
  rz_info "Übertragung fertig (Einrichtung/Prüfsummen übersprungen)."
fi
