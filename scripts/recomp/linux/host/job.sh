#!/bin/bash
# Läuft auf dem Linux host. Aufruf: job.sh <bahn> <job> <skript> [argumente...]  (Skript relativ zu diesem Ordner)
# Schreibt logs/<job>.log, logs/<job>.rc (Rückgabewert, erst am Ende), logs/<job>.sec (Wanduhr), logs/lane-<bahn>.pid/.job.
HERE=$(cd "$(dirname "$0")" && pwd)
R=$(cd "$HERE/../../../.." && pwd)
lane=$1 job=$2 script=$3
shift 3
L=$R/logs
mkdir -p "$L"
cd "$R" || exit 1
rm -f "$L/$job.rc" "$L/$job.sec"
echo $$ > "$L/lane-$lane.pid"
echo "$job" > "$L/lane-$lane.job"
start=$(date +%s)
echo "# $job gestartet $(date '+%F %T'), Skript $script $*" > "$L/$job.log"
# Source fingerprint excludes this Linux orchestration directory.
echo "# Stand: eh_gen $(sha256sum scripts/recomp/eh_gen.py | cut -c1-10), rt/cpu.h $(sha256sum scripts/recomp/rt/cpu.h | cut -c1-10), Baum $(find scripts/recomp -type f -not -path '*/linux/*' | sort | xargs sha256sum | sha256sum | cut -c1-10)" >> "$L/$job.log"
bash "$HERE/$script" "$@" >> "$L/$job.log" 2>&1
rc=$?
echo $(( $(date +%s) - start )) > "$L/$job.sec"
echo "# $job beendet $(date '+%F %T'), Code $rc, $(( $(date +%s) - start )) s" >> "$L/$job.log"
rm -f "$L/lane-$lane.pid"
echo $rc > "$L/$job.rc"
