#!/bin/bash
# Shared functions for the Mac side of the Linux host farm (docs/recomp-linux.md). Loaded via `source` by sync.sh, build.sh, run_probe.sh,
# fetch.sh. Access to the Linux host is only via ssh; long jobs run detached (setsid + nohup) with
# log file and status files (.pid, .rc, .sec) under ~/$RZ_DIR/logs. Two "lanes" (a: generate/build, b: probes)
# prevent two heavy jobs from overlapping.

# --- Settings (overridable via environment variables) ---
RZ_DIR=${RZ_DIR:-xnu-recomp}        # work folder relative to $HOME on the Linux host; nothing is created outside it
RZ_LANE_A=${RZ_LANE_A:-a}           # lane for generate/build
RZ_LANE_B=${RZ_LANE_B:-b}           # lane for probes/tests
RZ_TIMEOUT=${RZ_TIMEOUT:-5400}      # maximum wait (s) when following a job
RZ_POLL=${RZ_POLL:-5}               # poll interval (s)

RZ_REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
# Host (ssh alias) only from the environment or work/local.env (gitignored); never in the repo. Only the RZ_HOST=... line is read, the value is not printed.
if [ -z "${RZ_HOST:-}" ] && [ -f "$RZ_REPO/work/local.env" ]; then
  RZ_HOST=$(sed -n 's/^RZ_HOST=//p' "$RZ_REPO/work/local.env" | tail -n 1)
fi
[ -n "${RZ_HOST:-}" ] || { echo "ERROR: RZ_HOST is missing. Set RZ_HOST in work/local.env (file is gitignored) or as an environment variable." >&2; exit 2; }
RZ_LOCAL_OUT="$RZ_REPO/work/recomp/linux"   # local storage (gitignored): manifest, fetched logs and numbers

rz_die() { echo "ERROR: $*" >&2; exit 1; }
rz_info() { echo "[linux] $*"; }

rz_ssh() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$RZ_HOST" "$@"; }

# Check reachability and create the work folder (idempotent).
rz_require() {
  command -v ssh >/dev/null || rz_die "ssh is missing on this machine."
  command -v rsync >/dev/null || rz_die "rsync is missing on this machine."
  rz_ssh true 2>/dev/null || rz_die "The Linux host is not reachable via the ssh alias '$RZ_HOST' (BatchMode, key auth). Is the machine switched on? Is the alias in ~/.ssh/config? Test: ssh $RZ_HOST true"
  rz_ssh "mkdir -p ~/$RZ_DIR/logs" || rz_die "Could not create work folder ~/$RZ_DIR on the Linux host."
}

# rz_dispatch <bahn> <job> <remote-skript> [argumente...]
# Starts scripts/recomp/linux/host/<script> detached on the configured Linux test host.
rz_dispatch() {
  local lane=$1 job=$2; shift 2
  local ok='^[A-Za-z0-9_./=:,+ -]+$'
  [[ "$job $*" =~ $ok ]] || rz_die "Invalid characters in job name or arguments: '$job $*'"
  if rz_ssh "f=~/$RZ_DIR/logs/lane-$lane.pid; [ -f \$f ] && kill -0 \$(cat \$f) 2>/dev/null"; then
    local cur; cur=$(rz_ssh "cat ~/$RZ_DIR/logs/lane-$lane.job 2>/dev/null")
    rz_die "Lane '$lane' is still busy (job '${cur:-?}'). Wait (fetch.sh status) or abort: fetch.sh stop $lane"
  fi
  rz_ssh "cd ~/$RZ_DIR && rm -f logs/$job.rc && { setsid nohup bash scripts/recomp/linux/host/job.sh $lane $job $* > /dev/null 2>&1 < /dev/null & }" \
    || rz_die "Job could not be started on the Linux host."
  rz_info "Job '$job' (lane $lane) started; log: ~/$RZ_DIR/logs/$job.log"
}

# rz_wait <job>: waits until logs/<job>.rc exists, shows the latest new log line each time, returns the exit code.
rz_wait() {
  local job=$1 waited=0 rc="" last="" now=""
  sleep 2
  while [ "$waited" -lt "$RZ_TIMEOUT" ]; do
    rc=$(rz_ssh "cat ~/$RZ_DIR/logs/$job.rc 2>/dev/null" || true)
    [ -n "$rc" ] && return "$rc"
    now=$(rz_ssh "tail -n 1 ~/$RZ_DIR/logs/$job.log 2>/dev/null | cut -c1-160" || true)
    if [ -n "$now" ] && [ "$now" != "$last" ]; then echo "  … $now"; last=$now; fi
    sleep "$RZ_POLL"; waited=$((waited + RZ_POLL))
  done
  rz_die "Timeout ($RZ_TIMEOUT s) while waiting for job '$job'. It keeps running; status: fetch.sh status"
}

# rz_run <bahn> <job> <remote-skript> [argumente...]: start, wait (unless RZ_DETACH=1), show the end of the log.
rz_run() {
  local lane=$1 job=$2; shift 2
  rz_require
  rz_dispatch "$lane" "$job" "$@"
  if [ "${RZ_DETACH:-0}" = 1 ]; then
    rz_info "Not waiting for completion (RZ_DETACH=1). Check with scripts/recomp/linux/fetch.sh status"
    return 0
  fi
  local rc=0
  rz_wait "$job" || rc=$?
  rz_ssh "tail -n ${RZ_TAIL:-25} ~/$RZ_DIR/logs/$job.log"
  if [ "$rc" -eq 0 ]; then rz_info "Job '$job' succeeded."; else echo "ERROR: Job '$job' ended with code $rc (full log: fetch.sh log $job)." >&2; fi
  return "$rc"
}
