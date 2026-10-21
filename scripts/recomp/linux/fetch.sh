#!/bin/bash
# Fetches only logs and numbers from the Linux host (no generated C files, objects or libraries) into work/recomp/linux/ (gitignored).
# Usage: fetch.sh [status|holen|log <job> [zeilen]|stop <bahn>]
#   status        busy lanes, latest jobs with code/duration, load and free RAM
#   holen         logs/*.log|stats|times|rc|sec → work/recomp/linux/logs/ (default)
#   log <job>     show the end of a log (default 40 lines)
#   stop <bahn>   abort the running job of the lane (a|b) (SIGTERM to its process group)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cmd=${1:-holen}
rz_require
case "$cmd" in
  status)
    rz_ssh "cd ~/$RZ_DIR/logs 2>/dev/null || exit 0
      for l in a b; do
        if [ -f lane-\$l.pid ] && kill -0 \$(cat lane-\$l.pid) 2>/dev/null; then echo \"Lane \$l: busy with '\$(cat lane-\$l.job)' (PID \$(cat lane-\$l.pid))\"; else echo \"Lane \$l: free\"; fi
      done
      for f in \$(ls -t *.rc 2>/dev/null | head -12); do j=\${f%.rc}; echo \"\$j: Code \$(cat \$f), \$(cat \$j.sec 2>/dev/null) s\"; done
      echo \"Load: \$(cut -d' ' -f1-3 /proc/loadavg), free: \$(awk '/MemAvailable/ {printf \"%d MB\", \$2/1024}' /proc/meminfo)\""
    ;;
  holen)
    mkdir -p "$RZ_LOCAL_OUT/logs"
    rsync -a --max-size=3m --include='*/' --include='*.log' --include='*.stats' --include='*.times' --include='*.rc' --include='*.sec' --exclude='*' \
      "$RZ_HOST:$RZ_DIR/logs/" "$RZ_LOCAL_OUT/logs/" || rz_die "Could not fetch logs."
    rz_info "Logs and numbers copied to $RZ_LOCAL_OUT/logs/:"
    ls -1 "$RZ_LOCAL_OUT/logs" | head -60
    ;;
  log)
    [ -n "${2:-}" ] || rz_die "Usage: fetch.sh log <job> [zeilen]"
    [[ "$2" =~ ^[A-Za-z0-9_.-]+$ ]] || rz_die "Invalid job name '$2'."
    rz_ssh "tail -n ${3:-40} ~/$RZ_DIR/logs/$2.log" || rz_die "No log '$2' on the Linux host."
    ;;
  stop)
    lane=${2:-}; [[ "$lane" =~ ^[ab]$ ]] || rz_die "Usage: fetch.sh stop a|b"
    rz_ssh "p=\$(cat ~/$RZ_DIR/logs/lane-$lane.pid 2>/dev/null); [ -n \"\$p\" ] && kill -0 \$p 2>/dev/null && { pkill -TERM -g \$(ps -o pgid= \$p | tr -d ' ') ; echo Abort sent; } || echo 'Lane $lane is free.'"
    ;;
  *) rz_die "Unknown command '$cmd' (status | holen | log <job> | stop <bahn>).";;
esac
