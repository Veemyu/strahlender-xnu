#!/bin/bash
# Runs a probe/test on the Linux host (lane b), log: ~/xnu-recomp/logs/probe-<test>.log.
# Usage: run_probe.sh <eh|eh-real|rebase32|gc|bench|boot|boot-las|bdsp|alle> [--detach]   (alle = all except bdsp)
# Prerequisites: sync.sh has run (bdsp: sync.sh --mit-rt-bdsp); for boot/boot-las/bdsp also a finished build (build.sh).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
test_name=${1:-}
case "$test_name" in
  eh|eh-real|rebase32|gc|bench|boot|boot-las|bdsp|alle) ;;
  *) rz_die "Usage: run_probe.sh <eh|eh-real|rebase32|gc|bench|boot|boot-las|bdsp|alle> [--detach]";;
esac
[ "${2:-}" = "--detach" ] && RZ_DETACH=1
rz_require
rz_ssh "test -f ~/$RZ_DIR/work/exefs/sdk -a -f ~/$RZ_DIR/scripts/recomp/linux/host/probe.sh" || rz_die "Inputs or scripts are missing on the Linux test host. Run sync.sh first."
case "$test_name" in
  boot|boot-las|bdsp|alle)
    rz_ssh "ls ~/$RZ_DIR/work/recomp/obj4-c/*.o >/dev/null 2>&1" || rz_die "No finished build on the Linux host (work/recomp/obj4-c). Run build.sh first." ;;
esac
RZ_TAIL=${RZ_TAIL:-40} rz_run "$RZ_LANE_B" "probe-$test_name" probe.sh "$test_name"
