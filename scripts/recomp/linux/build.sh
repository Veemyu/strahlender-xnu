#!/bin/bash
# Generates (LAS lifter, c mode) and compiles the four modules on the Linux host (lane a), log: ~/xnu-recomp/logs/build.log.
# Usage: build.sh [--neu] [--nur-gen] [--nur-compile] [--sync] [--detach]
#   --neu          discard all objects (full rebuild); default: incremental (only changed chunks)
#   --tag=NAME     comparison run in its own object folder obj4-c-NAME; --schwelle=BYTES: -O0 threshold for single-function files (default 300000)
#   --jobs=N       parallel compilers (default 10)
#   --inkrementell measures rebuilds after small changes to a copy of the finished build (job 'incr')
#   --las-runtime  builds the Linux path of the LAS runtime (platform/linux.c, core, services) without graphics and reports missing packages
#   --sync         run sync.sh --ohne-setup first
#   --detach       do not wait for the end (status: fetch.sh status)
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
rz_ssh "test -f ~/$RZ_DIR/work/exefs/main -a -f ~/$RZ_DIR/scripts/recomp/eh_gen.py" || rz_die "Inputs are missing on the Linux host. Run sync.sh first."
RZ_TAIL=${RZ_TAIL:-30} rz_run "$RZ_LANE_A" "$JOB" "$SCRIPT" ${ARGS[@]+"${ARGS[@]}"}
