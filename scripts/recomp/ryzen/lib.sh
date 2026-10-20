#!/bin/bash
# Gemeinsame Funktionen der Mac-Seite der Ryzen-Farm (docs/recomp-ryzen.md). Wird von sync.sh, build.sh, run_probe.sh,
# fetch.sh per `source` geladen. Zugriff auf den Ryzen nur per ssh; lange Jobs laufen entkoppelt (setsid + nohup) mit
# Logdatei und Statusdateien (.pid, .rc, .sec) unter ~/$RZ_DIR/logs. Zwei "Bahnen" (a: Erzeugen/Bauen, b: Proben)
# verhindern, dass sich zwei schwere Jobs überschneiden.

# --- Einstellungen (per Umgebungsvariable überschreibbar) ---
RZ_DIR=${RZ_DIR:-xnu-recomp}        # Arbeitsordner relativ zu $HOME auf dem Ryzen; außerhalb wird nichts angelegt
RZ_LANE_A=${RZ_LANE_A:-a}           # Bahn für Erzeugen/Bauen
RZ_LANE_B=${RZ_LANE_B:-b}           # Bahn für Proben/Tests
RZ_TIMEOUT=${RZ_TIMEOUT:-5400}      # längste Wartezeit (s) beim Mitlesen eines Jobs
RZ_POLL=${RZ_POLL:-5}               # Abfrageintervall (s)

RZ_REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
# Host (ssh-Alias) nur aus Umgebung oder work/local.env (gitignoriert); nie im Repo. Nur die Zeile RZ_HOST=..., Wert wird nicht ausgegeben.
if [ -z "${RZ_HOST:-}" ] && [ -f "$RZ_REPO/work/local.env" ]; then
  RZ_HOST=$(sed -n 's/^RZ_HOST=//p' "$RZ_REPO/work/local.env" | tail -n 1)
fi
[ -n "${RZ_HOST:-}" ] || { echo "FEHLER: RZ_HOST fehlt. RZ_HOST in work/local.env setzen (Datei ist gitignoriert) oder als Umgebungsvariable." >&2; exit 2; }
RZ_LOCAL_OUT="$RZ_REPO/work/recomp/ryzen"   # lokale Ablage (gitignoriert): Manifest, geholte Logs und Zahlen

rz_die() { echo "FEHLER: $*" >&2; exit 1; }
rz_info() { echo "[ryzen] $*"; }

rz_ssh() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$RZ_HOST" "$@"; }

# Erreichbarkeit prüfen und den Arbeitsordner anlegen (idempotent).
rz_require() {
  command -v ssh >/dev/null || rz_die "ssh fehlt auf diesem Rechner."
  command -v rsync >/dev/null || rz_die "rsync fehlt auf diesem Rechner."
  rz_ssh true 2>/dev/null || rz_die "Der Ryzen ist über den ssh-Alias '$RZ_HOST' nicht erreichbar (BatchMode, Key-Auth). Rechner eingeschaltet? Alias in ~/.ssh/config vorhanden? Test: ssh $RZ_HOST true"
  rz_ssh "mkdir -p ~/$RZ_DIR/logs" || rz_die "Arbeitsordner ~/$RZ_DIR auf dem Ryzen konnte nicht angelegt werden."
}

# rz_dispatch <bahn> <job> <remote-skript> [argumente...]
# Startet scripts/recomp/ryzen/remote/<skript> entkoppelt auf dem Ryzen; Ausgabe nach logs/<job>.log, Rückgabewert nach logs/<job>.rc.
rz_dispatch() {
  local lane=$1 job=$2; shift 2
  local ok='^[A-Za-z0-9_./=:,+ -]+$'
  [[ "$job $*" =~ $ok ]] || rz_die "Unzulässige Zeichen in Job-Name oder Argumenten: '$job $*'"
  if rz_ssh "f=~/$RZ_DIR/logs/lane-$lane.pid; [ -f \$f ] && kill -0 \$(cat \$f) 2>/dev/null"; then
    local cur; cur=$(rz_ssh "cat ~/$RZ_DIR/logs/lane-$lane.job 2>/dev/null")
    rz_die "Die Bahn '$lane' ist noch belegt (Job '${cur:-?}'). Warten (fetch.sh status) oder abbrechen: fetch.sh stop $lane"
  fi
  rz_ssh "cd ~/$RZ_DIR && rm -f logs/$job.rc && { setsid nohup bash scripts/recomp/ryzen/remote/job.sh $lane $job $* > /dev/null 2>&1 < /dev/null & }" \
    || rz_die "Job konnte auf dem Ryzen nicht gestartet werden."
  rz_info "Job '$job' (Bahn $lane) gestartet; Log: ~/$RZ_DIR/logs/$job.log"
}

# rz_wait <job>: wartet bis logs/<job>.rc existiert, zeigt die jeweils letzte neue Logzeile, gibt den Rückgabewert zurück.
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
  rz_die "Zeitüberschreitung ($RZ_TIMEOUT s) beim Warten auf Job '$job'. Er läuft weiter; Stand: fetch.sh status"
}

# rz_run <bahn> <job> <remote-skript> [argumente...]: starten, warten (außer RZ_DETACH=1), Ende des Logs zeigen.
rz_run() {
  local lane=$1 job=$2; shift 2
  rz_require
  rz_dispatch "$lane" "$job" "$@"
  if [ "${RZ_DETACH:-0}" = 1 ]; then
    rz_info "Nicht auf das Ende gewartet (RZ_DETACH=1). Stand: scripts/recomp/ryzen/fetch.sh status"
    return 0
  fi
  local rc=0
  rz_wait "$job" || rc=$?
  rz_ssh "tail -n ${RZ_TAIL:-25} ~/$RZ_DIR/logs/$job.log"
  if [ "$rc" -eq 0 ]; then rz_info "Job '$job' erfolgreich."; else echo "FEHLER: Job '$job' endete mit Code $rc (vollständiges Log: fetch.sh log $job)." >&2; fi
  return "$rc"
}
