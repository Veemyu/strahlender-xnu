#!/bin/bash
# Führt eine Probe/einen Test auf dem Ryzen aus (Bahn b), Log: ~/xnu-recomp/logs/probe-<test>.log.
# Aufruf: run_probe.sh <eh|eh-real|rebase32|gc|bench|boot|boot-las|bdsp|alle> [--detach]   (alle = ohne bdsp)
# Voraussetzungen: sync.sh gelaufen (bdsp: sync.sh --mit-rt-bdsp); für boot/boot-las/bdsp zusätzlich ein fertiger Build (build.sh).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
test_name=${1:-}
case "$test_name" in
  eh|eh-real|rebase32|gc|bench|boot|boot-las|bdsp|alle) ;;
  *) rz_die "Aufruf: run_probe.sh <eh|eh-real|rebase32|gc|bench|boot|boot-las|bdsp|alle> [--detach]";;
esac
[ "${2:-}" = "--detach" ] && RZ_DETACH=1
rz_require
rz_ssh "test -f ~/$RZ_DIR/work/exefs/sdk -a -f ~/$RZ_DIR/scripts/recomp/ryzen/remote/probe.sh" || rz_die "Eingaben/Skripte fehlen auf dem Ryzen. Erst sync.sh ausführen."
case "$test_name" in
  boot|boot-las|bdsp|alle)
    rz_ssh "ls ~/$RZ_DIR/work/recomp/obj4-c/*.o >/dev/null 2>&1" || rz_die "Kein fertiger Build auf dem Ryzen (work/recomp/obj4-c). Erst build.sh ausführen." ;;
esac
RZ_TAIL=${RZ_TAIL:-40} rz_run "$RZ_LANE_B" "probe-$test_name" probe.sh "$test_name"
