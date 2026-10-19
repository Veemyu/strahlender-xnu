#!/bin/bash
# Holt nur Logs und Zahlen vom Ryzen (keine erzeugten C-Dateien, Objekte oder Bibliotheken) nach work/recomp/ryzen/ (gitignoriert).
# Aufruf: fetch.sh [status|holen|log <job> [zeilen]|stop <bahn>]
#   status        belegte Bahnen, letzte Jobs mit Code/Dauer, Last und freier RAM
#   holen         logs/*.log|stats|times|rc|sec → work/recomp/ryzen/logs/ (Standard)
#   log <job>     Ende eines Logs anzeigen (Standard 40 Zeilen)
#   stop <bahn>   laufenden Job der Bahn (a|b) abbrechen (SIGTERM an dessen Prozessgruppe)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cmd=${1:-holen}
rz_require
case "$cmd" in
  status)
    rz_ssh "cd ~/$RZ_DIR/logs 2>/dev/null || exit 0
      for l in a b; do
        if [ -f lane-\$l.pid ] && kill -0 \$(cat lane-\$l.pid) 2>/dev/null; then echo \"Bahn \$l: belegt durch '\$(cat lane-\$l.job)' (PID \$(cat lane-\$l.pid))\"; else echo \"Bahn \$l: frei\"; fi
      done
      for f in \$(ls -t *.rc 2>/dev/null | head -12); do j=\${f%.rc}; echo \"\$j: Code \$(cat \$f), \$(cat \$j.sec 2>/dev/null) s\"; done
      echo \"Last: \$(cut -d' ' -f1-3 /proc/loadavg), frei: \$(awk '/MemAvailable/ {printf \"%d MB\", \$2/1024}' /proc/meminfo)\""
    ;;
  holen)
    mkdir -p "$RZ_LOCAL_OUT/logs"
    rsync -a --max-size=3m --include='*/' --include='*.log' --include='*.stats' --include='*.times' --include='*.rc' --include='*.sec' --exclude='*' \
      "$RZ_HOST:$RZ_DIR/logs/" "$RZ_LOCAL_OUT/logs/" || rz_die "Logs konnten nicht geholt werden."
    rz_info "Logs und Zahlen nach $RZ_LOCAL_OUT/logs/ kopiert:"
    ls -1 "$RZ_LOCAL_OUT/logs" | head -60
    ;;
  log)
    [ -n "${2:-}" ] || rz_die "Aufruf: fetch.sh log <job> [zeilen]"
    [[ "$2" =~ ^[A-Za-z0-9_.-]+$ ]] || rz_die "Ungültiger Jobname '$2'."
    rz_ssh "tail -n ${3:-40} ~/$RZ_DIR/logs/$2.log" || rz_die "Kein Log '$2' auf dem Ryzen."
    ;;
  stop)
    lane=${2:-}; [[ "$lane" =~ ^[ab]$ ]] || rz_die "Aufruf: fetch.sh stop a|b"
    rz_ssh "p=\$(cat ~/$RZ_DIR/logs/lane-$lane.pid 2>/dev/null); [ -n \"\$p\" ] && kill -0 \$p 2>/dev/null && { pkill -TERM -g \$(ps -o pgid= \$p | tr -d ' ') ; echo Abbruch gesendet; } || echo 'Bahn $lane ist frei.'"
    ;;
  *) rz_die "Unbekannter Befehl '$cmd' (status | holen | log <job> | stop <bahn>).";;
esac
