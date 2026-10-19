#!/bin/bash
# Erzeugt (LAS-Lifter, c-Modus) und übersetzt die vier Module auf dem Ryzen (Bahn a), Log: ~/xnu-recomp/logs/build.log.
# Aufruf: build.sh [--neu] [--nur-gen] [--nur-compile] [--sync] [--detach]
#   --neu          alle Objekte verwerfen (vollständiger Neubau); Standard: inkrementell (nur geänderte Chunks)
#   --tag=NAME     Vergleichslauf in eigenem Objektordner obj4-c-NAME; --schwelle=BYTES: -O0-Schwelle für Einzelfunktionsdateien (Standard 300000)
#   --jobs=N       parallele Compiler (Standard 10)
#   --inkrementell misst Neubauten nach kleinen Änderungen an einer Kopie des fertigen Builds (Job 'incr')
#   --las-runtime  baut den Linux-Pfad der LAS-Laufzeit (platform/linux.c, Kern, Dienste) ohne Grafik und meldet fehlende Pakete
#   --sync         vorher sync.sh --ohne-setup ausführen
#   --detach       nicht auf das Ende warten (Stand: fetch.sh status)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
ARGS=(); SYNC=0; SCRIPT=build_all.sh; JOB=build
for a in "$@"; do
  case "$a" in
    --neu|--nur-gen|--nur-compile|--tag=*|--schwelle=*|--jobs=*) ARGS+=("$a");;
    --inkrementell) SCRIPT=incr_test.sh; JOB=incr;;
    --las-runtime) SCRIPT=las_runtime.sh; JOB=las-runtime;;
    --sync) SYNC=1;;
    --detach) RZ_DETACH=1;;
    -h|--help) sed -n 2,9p "$0"; exit 0;;
    *) rz_die "Unbekannte Option '$a'. Siehe: $0 --help";;
  esac
done
[ "$SYNC" = 1 ] && "$(dirname "$0")/sync.sh" --ohne-setup
rz_require
rz_ssh "test -f ~/$RZ_DIR/work/exefs/main -a -f ~/$RZ_DIR/scripts/recomp/eh_gen.py" || rz_die "Eingaben fehlen auf dem Ryzen. Erst sync.sh ausführen."
RZ_TAIL=${RZ_TAIL:-30} rz_run "$RZ_LANE_A" "$JOB" "$SCRIPT" ${ARGS[@]+"${ARGS[@]}"}
